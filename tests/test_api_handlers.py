from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from moto import mock_aws

from speakquest.storage import S3Storage
from speakquest_api.config import Settings
from speakquest_api.handlers import Deps, dispatch
from speakquest_api.http import Request
from speakquest_api.repository import ChallengeRecord, DynamoRepository
from tests.test_repository import make_table

SID = "0b5a3a1c-8f9e-4c2d-9a7b-1234567890ab"
OTHER = "1c6b4b2d-9a0f-4d3e-8b8c-234567890abc"


class Recorder:
    def __init__(self, fail: bool = False):
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail = fail

    def start(self, analysis_id: str, payload: dict[str, Any]) -> str:
        if self.fail:
            raise RuntimeError("states unavailable")
        self.calls.append((analysis_id, payload))
        return f"arn:aws:states:::execution:x:{analysis_id}"


@pytest.fixture
def deps() -> Iterator[Deps]:
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="sq-test")
        make_table()
        repo = DynamoRepository("speakquest-test", region="us-east-1")
        repo.put_challenge(
            ChallengeRecord(
                id="deadline",
                title="The Deadline",
                script="We ship the final build.",
                difficulty=1,
                flaw_targets=["RUSH"],
                cue="Steady.",
                reference_ready=True,
                reference_audio_key="references/deadline/audio.wav",
                reference_features_key="references/deadline/features.json",
                reference_duration_s=5.2,
            )
        )
        repo.put_challenge(
            ChallengeRecord(
                id="unready", title="U", script="a b c", difficulty=2, flaw_targets=[], cue="c"
            )
        )
        ids = iter(f"{i:08d}-0000-4000-8000-000000000000" for i in range(1, 100))
        yield Deps(
            settings=Settings(bucket="sq-test", table="speakquest-test"),
            storage=S3Storage("sq-test", region="us-east-1"),
            repo=repo,
            workflow=Recorder(),
            new_id=lambda: next(ids),
        )


def call(
    deps: Deps,
    method: str,
    path: str,
    body: Any = None,
    sid: str | None = SID,
    raw: bytes | None = None,
) -> tuple[int, dict[str, Any]]:
    headers = {"content-type": "application/json"}
    if sid:
        headers["X-Session-Id"] = sid
    req = Request(
        method=method,
        path=path,
        headers={k.lower(): v for k, v in headers.items()},
        body=raw if raw is not None else (json.dumps(body).encode() if body else b""),
    )
    resp = dispatch(req, deps)
    return resp["statusCode"], json.loads(resp["body"]) if resp["body"] else {}


def upload(deps: Deps, size: int = 2048) -> str:
    status, body = call(
        deps,
        "POST",
        "/uploads",
        {"challengeId": "deadline", "contentType": "audio/webm;codecs=opus", "bytes": size},
    )
    assert status == 201, body
    deps.storage.put_bytes(body["key"], b"x" * size, "audio/webm")
    return str(body["key"])


def test_challenges_list_with_reference_urls(deps: Deps) -> None:
    status, body = call(deps, "GET", "/challenges")
    assert status == 200
    ready = next(c for c in body["challenges"] if c["id"] == "deadline")
    assert ready["reference_ready"] and "X-Amz-Signature" in ready["reference_audio_url"]
    unready = next(c for c in body["challenges"] if c["id"] == "unready")
    assert unready["reference_audio_url"] is None


def test_session_header_is_required_and_validated(deps: Deps) -> None:
    assert call(deps, "GET", "/me/progress", sid=None)[1]["error"]["code"] == "SESSION_REQUIRED"
    assert call(deps, "GET", "/me/progress", sid="not-a-uuid")[0] == 400


def test_create_upload_presigns_a_locked_put(deps: Deps) -> None:
    status, body = call(
        deps,
        "POST",
        "/uploads",
        {"challengeId": "deadline", "contentType": "audio/mp4", "bytes": 4096},
    )
    assert status == 201
    assert body["key"] == f"uploads/{SID}/00000001-0000-4000-8000-000000000000.m4a"
    assert body["headers"] == {"Content-Type": "audio/mp4"} and body["method"] == "PUT"
    signed = body["uploadUrl"].lower().split("x-amz-signedheaders=")[1].split("&")[0]
    assert "content-length" in signed and "content-type" in signed


@pytest.mark.parametrize(
    ("payload", "status", "code"),
    [
        ({"challengeId": "deadline", "contentType": "video/mp4", "bytes": 10}, 422, "VALIDATION"),
        (
            {"challengeId": "deadline", "contentType": "audio/webm", "bytes": 11 * 1024 * 1024},
            413,
            "AUDIO_TOO_LARGE",
        ),
        (
            {"challengeId": "nope", "contentType": "audio/webm", "bytes": 10},
            404,
            "CHALLENGE_NOT_FOUND",
        ),
        (
            {"challengeId": "unready", "contentType": "audio/webm", "bytes": 10},
            409,
            "REFERENCE_NOT_READY",
        ),
        ({"challengeId": "deadline", "contentType": "audio/webm"}, 422, "VALIDATION"),
    ],
)
def test_create_upload_rejections(
    deps: Deps, payload: dict[str, Any], status: int, code: str
) -> None:
    got, body = call(deps, "POST", "/uploads", payload)
    assert (got, body["error"]["code"]) == (status, code)


def test_bad_json_and_unknown_routes(deps: Deps) -> None:
    assert call(deps, "POST", "/uploads", raw=b"{nope")[1]["error"]["code"] == "BAD_JSON"
    assert call(deps, "GET", "/nowhere")[0] == 404
    assert call(deps, "DELETE", "/challenges")[0] == 405


def test_analysis_lifecycle(deps: Deps) -> None:
    key = upload(deps)
    status, body = call(
        deps, "POST", "/analyses", {"challengeId": "deadline", "key": key, "durationS": 4.2}
    )
    assert status == 202
    aid = body["analysisId"]
    assert aid == "00000001-0000-4000-8000-000000000000"
    rec: Recorder = deps.workflow  # type: ignore[assignment]
    assert rec.calls[0][1] | {"takeSk": None} == {
        "analysisId": aid,
        "sessionId": SID,
        "challengeId": "deadline",
        "uploadKey": key,
        "language": "en-US",
        "referenceFeaturesKey": "references/deadline/features.json",
        "takeSk": None,
    }
    # Retried POST is idempotent: same id, no second execution.
    assert call(deps, "POST", "/analyses", {"challengeId": "deadline", "key": key})[0] == 202
    assert len(rec.calls) == 1

    status, body = call(deps, "GET", f"/analyses/{aid}")
    assert status == 200 and body["status"] == "QUEUED" and body["stage"] == "QUEUED"
    assert call(deps, "GET", f"/analyses/{aid}", sid=OTHER)[0] == 404
    assert call(deps, "GET", f"/analyses/{aid}/result")[1]["error"]["code"] == "NOT_READY"

    deps.repo.update_analysis(
        aid,
        status="DONE",
        stage="DONE",
        keys={"upload": key, "result": f"results/{aid}/result.json"},
        summary={
            "scores": {
                "pace": 90,
                "pauses": 100,
                "pitch": 100,
                "volume": 100,
                "accuracy": 100,
                "overall": 98,
            },
            "findingCount": 1,
            "codes": ["RUSH"],
        },
    )
    status, body = call(deps, "GET", f"/analyses/{aid}")
    assert body["status"] == "DONE" and body["summary"]["scores"]["overall"] == 98
    status, body = call(deps, "GET", f"/analyses/{aid}/result")
    assert status == 200
    assert f"results/{aid}/result.json" in body["resultUrl"]
    assert key.split("/")[-1] in body["audioUrl"]
    assert "references/deadline/audio.wav" in body["referenceAudioUrl"]

    status, body = call(deps, "GET", "/me/progress")
    assert status == 200 and body["xp"] == 0 and body["level"]["name"] == "Rehearsal"
    assert [t["analysisId"] for t in body["takes"]] == [aid]


def test_create_analysis_guards(deps: Deps) -> None:
    foreign = f"uploads/{OTHER}/00000009-0000-4000-8000-000000000000.webm"
    assert (
        call(deps, "POST", "/analyses", {"challengeId": "deadline", "key": foreign})[1]["error"][
            "code"
        ]
        == "FORBIDDEN_KEY"
    )
    missing = f"uploads/{SID}/00000009-0000-4000-8000-000000000000.webm"
    assert (
        call(deps, "POST", "/analyses", {"challengeId": "deadline", "key": missing})[1]["error"][
            "code"
        ]
        == "UPLOAD_MISSING"
    )
    for _ in range(3):
        assert (
            call(deps, "POST", "/analyses", {"challengeId": "deadline", "key": upload(deps)})[0]
            == 202
        )
    status, body = call(deps, "POST", "/analyses", {"challengeId": "deadline", "key": upload(deps)})
    assert (status, body["error"]["code"]) == (429, "TOO_MANY_ACTIVE")


def test_workflow_start_failure_marks_the_take_failed(deps: Deps) -> None:
    deps.workflow = Recorder(fail=True)
    key = upload(deps)
    status, body = call(deps, "POST", "/analyses", {"challengeId": "deadline", "key": key})
    assert (status, body["error"]["code"]) == (503, "WORKFLOW_UNAVAILABLE")
    aid = key.split("/")[-1].split(".")[0]
    status, body = call(deps, "GET", f"/analyses/{aid}")
    assert body["status"] == "FAILED" and body["error"]["code"] == "INTERNAL"
