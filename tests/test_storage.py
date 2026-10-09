from __future__ import annotations

import time
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

import boto3
import pytest
from moto import mock_aws

from speakquest.storage import LocalStorage, S3Storage, StorageMissingError, get_json, put_json


def _query(url: str) -> dict[str, str]:
    return dict(parse_qsl(urlparse(url).query))


def test_local_round_trip_and_missing(tmp_path: Path) -> None:
    st = LocalStorage(tmp_path / "bucket", "http://localhost:8787", b"secret")
    put_json(st, "results/a/result.json", {"ok": True})
    assert get_json(st, "results/a/result.json") == {"ok": True}
    assert st.size("results/a/result.json") == len(b'{"ok":true}')
    with pytest.raises(StorageMissingError):
        st.get_bytes("results/none.json")
    with pytest.raises(ValueError):
        st.path("../escape")


def test_local_presigned_urls_enforce_method_type_and_expiry(tmp_path: Path) -> None:
    st = LocalStorage(tmp_path, "http://localhost:8787/", b"secret")
    url = st.presign_put("uploads/s/a.webm", "audio/webm", 300)
    assert url.startswith("http://localhost:8787/_storage/uploads/s/a.webm?")
    q = _query(url)
    assert st.verify("PUT", "uploads/s/a.webm", q, "audio/webm")
    assert not st.verify("PUT", "uploads/s/a.webm", q, "audio/mp4")
    assert not st.verify("PUT", "uploads/s/b.webm", q, "audio/webm")
    assert not st.verify("GET", "uploads/s/a.webm", q)
    tampered = {**q, "e": str(int(q["e"]) + 100)}
    assert not st.verify("PUT", "uploads/s/a.webm", tampered, "audio/webm")
    expired = st.presign_get("results/x.json", -1)
    assert not st.verify("GET", "results/x.json", _query(expired))
    assert st.verify("GET", "results/x.json", _query(st.presign_get("results/x.json", 60)))
    assert int(q["e"]) <= time.time() + 301


@mock_aws
def test_s3_adapter_against_moto(tmp_path: Path) -> None:
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="speakquest-test")
    st = S3Storage("speakquest-test", region="us-east-1")
    st.put_bytes("results/a/result.json", b"{}", "application/json")
    assert st.exists("results/a/result.json")
    assert st.size("nope") is None
    with pytest.raises(StorageMissingError):
        st.get_bytes("nope")
    src = tmp_path / "f.bin"
    src.write_bytes(b"abc")
    st.upload(src, "work/a/f.bin")
    assert st.download("work/a/f.bin", tmp_path / "out.bin").read_bytes() == b"abc"
    with pytest.raises(StorageMissingError):
        st.download("work/none", tmp_path / "x")
    put_url = st.presign_put("uploads/s/a.webm", "audio/webm", 300)
    assert "X-Amz-Signature" in put_url and "content-type" in put_url.lower()
    assert "X-Amz-Expires=600" in st.presign_get("results/a/result.json", 600)
