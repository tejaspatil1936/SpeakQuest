"""Lambda entry points with API Gateway v2 events, against moto."""

from __future__ import annotations

import json
from collections.abc import Iterator

import boto3
import pytest
from moto import mock_aws

from speakquest_api import config, lambdas
from speakquest_api.repository import ChallengeRecord, DynamoRepository
from tests.test_repository import make_table

SID = "0b5a3a1c-8f9e-4c2d-9a7b-1234567890ab"


@pytest.fixture
def aws_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("SPEAKQUEST_BUCKET", "sq-test")
    monkeypatch.setenv("SPEAKQUEST_TABLE", "speakquest-test")
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="sq-test")
        make_table()
        sfn = boto3.client("stepfunctions", region_name="us-east-1")
        role = "arn:aws:iam::123456789012:role/sfn"
        arn = sfn.create_state_machine(
            name="speakquest-test-analysis",
            roleArn=role,
            definition=json.dumps({"StartAt": "P", "States": {"P": {"Type": "Pass", "End": True}}}),
        )["stateMachineArn"]
        monkeypatch.setenv("SPEAKQUEST_STATE_MACHINE_ARN", arn)
        DynamoRepository("speakquest-test").put_challenge(
            ChallengeRecord(
                id="deadline",
                title="T",
                script="a b c",
                difficulty=1,
                flaw_targets=[],
                cue="c",
                reference_ready=True,
                reference_features_key="references/deadline/features.json",
                reference_audio_key="references/deadline/audio.wav",
            )
        )
        config.settings.cache_clear()
        lambdas._api_deps.cache_clear()
        lambdas._step_deps.cache_clear()
        yield
        config.settings.cache_clear()
        lambdas._api_deps.cache_clear()
        lambdas._step_deps.cache_clear()


def event(method: str, path: str, body: dict | None = None) -> dict:
    return {
        "version": "2.0",
        "routeKey": f"{method} {path}",
        "rawPath": path,
        "headers": {"x-session-id": SID, "content-type": "application/json"},
        "requestContext": {"http": {"method": method, "path": path, "sourceIp": "1.2.3.4"}},
        "body": json.dumps(body) if body else None,
        "isBase64Encoded": False,
    }


def test_api_handler_starts_a_real_state_machine_execution(aws_env: None) -> None:
    resp = lambdas.api_handler(event("GET", "/challenges"))
    assert resp["statusCode"] == 200
    up = json.loads(
        lambdas.api_handler(
            event(
                "POST",
                "/uploads",
                {"challengeId": "deadline", "contentType": "audio/webm", "bytes": 10},
            )
        )["body"]
    )
    boto3.client("s3").put_object(Bucket="sq-test", Key=up["key"], Body=b"0123456789")
    resp = lambdas.api_handler(
        event("POST", "/analyses", {"challengeId": "deadline", "key": up["key"]})
    )
    assert resp["statusCode"] == 202, resp["body"]
    aid = json.loads(resp["body"])["analysisId"]
    sfn = boto3.client("stepfunctions")
    execs = sfn.list_executions(stateMachineArn=lambdas.settings().state_machine_arn)["executions"]
    assert [e["name"] for e in execs] == [aid]
    payload = json.loads(sfn.describe_execution(executionArn=execs[0]["executionArn"])["input"])
    assert payload["uploadKey"] == up["key"]


def test_persist_handler_fail_branch(aws_env: None) -> None:
    from speakquest_api.repository import AnalysisRecord, TakeRecord

    repo = DynamoRepository("speakquest-test")
    aid = "44444444-0000-4000-8000-000000000000"
    repo.create_analysis(
        AnalysisRecord(
            analysis_id=aid,
            session_id=SID,
            challenge_id="deadline",
            status="RUNNING",
            stage="TRANSCRIBE",
            created_at="t",
            updated_at="t",
            take_sk="TAKE#t#a",
        )
    )
    repo.put_take(
        SID,
        TakeRecord(
            sk="TAKE#t#a",
            analysis_id=aid,
            challenge_id="deadline",
            created_at="t",
            status="RUNNING",
        ),
    )
    out = lambdas.persist_handler(
        {
            "step": "fail",
            "state": {
                "analysisId": aid,
                "sessionId": SID,
                "takeSk": "TAKE#t#a",
                "error": {"Error": "TRANSCRIBE_TIMEOUT", "Cause": "40 polls"},
            },
        }
    )
    assert out == {"code": "TRANSCRIBE_TIMEOUT", "stage": "TRANSCRIBE"}
    assert repo.get_analysis(aid).status == "FAILED"  # type: ignore[union-attr]
