"""Checks against a real, Terraform-deployed bucket (opt-in).

    SPEAKQUEST_LIVE_AWS=1 SPEAKQUEST_LIVE_BUCKET=<bucket> pytest tests/test_live_s3.py

Exercises what the browser and the API rely on: presigned PUTs locked to a
content type and length, presigned GETs, CORS for the allowed origin only,
TLS-only access, no public reads, SSE-S3 and the lifecycle rules.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request
import uuid

import boto3
import pytest

from speakquest.storage import S3Storage

pytestmark = pytest.mark.live_aws
BUCKET = os.environ.get("SPEAKQUEST_LIVE_BUCKET", "")
REGION = os.environ.get("AWS_REGION", "us-east-1")


@pytest.fixture(scope="module")
def storage() -> S3Storage:
    if not BUCKET:
        pytest.skip("SPEAKQUEST_LIVE_BUCKET not set")
    return S3Storage(BUCKET, region=REGION)


def _req(
    url: str, method: str = "GET", data: bytes | None = None, headers: dict[str, str] | None = None
) -> tuple[int, dict[str, str], bytes]:
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()


def test_presigned_put_is_locked_to_type_and_length(storage: S3Storage) -> None:
    key = f"uploads/{uuid.uuid4()}/{uuid.uuid4()}.webm"
    body = b"\x1aE\xdf\xa3" + os.urandom(2000)
    url = storage.presign_put(key, "audio/webm", 300, content_length=len(body))
    assert _req(url, "PUT", body, {"Content-Type": "audio/mp4"})[0] == 403
    assert _req(url, "PUT", body[:1000], {"Content-Type": "audio/webm"})[0] == 403
    assert _req(url, "PUT", body, {"Content-Type": "audio/webm"})[0] == 200
    assert storage.size(key) == len(body)
    status, _, got = _req(storage.presign_get(key, 60))
    assert status == 200 and got == body
    head = boto3.client("s3", region_name=REGION).head_object(Bucket=BUCKET, Key=key)
    assert head["ServerSideEncryption"] == "AES256"


def test_no_public_or_plain_http_access(storage: S3Storage) -> None:
    key = f"results/{uuid.uuid4()}/result.json"
    storage.put_bytes(key, b"{}", "application/json")
    assert _req(f"https://{BUCKET}.s3.{REGION}.amazonaws.com/{key}")[0] == 403
    insecure = storage.presign_get(key, 60).replace("https://", "http://", 1)
    assert _req(insecure)[0] == 403


def test_cors_allows_only_configured_origins(storage: S3Storage) -> None:
    url = f"https://{BUCKET}.s3.{REGION}.amazonaws.com/uploads/x.webm"
    pre = {"Access-Control-Request-Method": "PUT", "Access-Control-Request-Headers": "content-type"}
    status, headers, _ = _req(url, "OPTIONS", headers={"Origin": "http://localhost:5173", **pre})
    assert status == 200 and headers["access-control-allow-origin"] == "http://localhost:5173"
    assert _req(url, "OPTIONS", headers={"Origin": "https://evil.example", **pre})[0] == 403


def test_lifecycle_rules_match_the_design(storage: S3Storage) -> None:
    rules = boto3.client("s3", region_name=REGION).get_bucket_lifecycle_configuration(
        Bucket=BUCKET
    )["Rules"]
    days = {r["Filter"].get("Prefix"): r["Expiration"]["Days"] for r in rules if "Expiration" in r}
    assert days == {"uploads/": 7, "work/": 1, "transcripts/": 7, "results/": 14}
    block = boto3.client("s3", region_name=REGION).get_public_access_block(Bucket=BUCKET)
    assert all(block["PublicAccessBlockConfiguration"].values())
