"""Run the worker container image as Lambda against a moto S3/DynamoDB.

    python scripts/smoke_worker_image.py [image]

Starts moto_server, seeds a challenge with a reference measured on the
host, uploads a synthetic-voice take and its transcript (standing in for
Amazon Transcribe's output), then invokes the image's Lambda handler through
the Runtime Interface Emulator for the Normalize and Analyze states. Proves
the image's ffmpeg, parselmouth and handler wiring work on Amazon Linux.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import boto3

from speakquest.challenges import get_entry
from speakquest.normalize import load_wav
from speakquest.pipeline import prepare
from speakquest.rubric import load_rubric
from speakquest_api.repository import (
    AnalysisRecord,
    ChallengeRecord,
    DynamoRepository,
    TakeRecord,
    take_sort_key,
)
from speakquest_eval.harness import Paths, normalized, transcript_for

ROOT = Path(__file__).resolve().parents[1]
IMAGE = sys.argv[1] if len(sys.argv) > 1 else "speakquest-worker:local"
SID = "0b5a3a1c-8f9e-4c2d-9a7b-1234567890ab"
AID = "5e0e5e0e-0000-4000-8000-000000000001"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def wait_http(url: str, timeout: float = 30) -> None:
    end = time.time() + timeout
    while time.time() < end:
        try:
            urllib.request.urlopen(url, timeout=2)
            return
        except Exception:
            time.sleep(0.3)
    raise RuntimeError(f"{url} did not come up")


def invoke(port: int, event: dict) -> dict:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/2015-03-31/functions/function/invocations",
        data=json.dumps(event).encode(),
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read())


def main() -> int:
    moto_port, rie_port = free_port(), free_port()
    env = {
        **os.environ,
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_DEFAULT_REGION": "us-east-1",
        "AWS_REGION": "us-east-1",
        "AWS_ENDPOINT_URL": f"http://127.0.0.1:{moto_port}",
    }
    os.environ.update(
        {
            k: env[k]
            for k in (
                "AWS_ACCESS_KEY_ID",
                "AWS_SECRET_ACCESS_KEY",
                "AWS_DEFAULT_REGION",
                "AWS_REGION",
                "AWS_ENDPOINT_URL",
            )
        }
    )
    moto = subprocess.Popen(
        [sys.executable, "-m", "moto.server", "-p", str(moto_port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    container = None
    try:
        wait_http(f"http://127.0.0.1:{moto_port}/moto-api/")
        s3 = boto3.client("s3")
        s3.create_bucket(Bucket="speakquest-smoke")
        boto3.client("dynamodb").create_table(
            TableName="speakquest-smoke",
            BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
        )
        rubric = load_rubric()
        paths = Paths(ROOT / "data/audio", ROOT / "data/annotations", ROOT / "data/generated")
        entry = get_entry("deadline")
        assert entry is not None
        ref_wav = normalized(paths.audio / "deadline__reference.wav", paths, rubric)
        samples, sr = load_wav(ref_wav)
        reference = prepare(
            samples, sr, transcript_for(ref_wav, "vosk", paths), entry.script, rubric
        ).analysis
        s3.put_object(
            Bucket="speakquest-smoke",
            Key="references/deadline/features.json",
            Body=reference.model_dump_json().encode(),
        )
        repo = DynamoRepository("speakquest-smoke")
        repo.put_challenge(
            ChallengeRecord(
                id="deadline",
                title=entry.title,
                script=entry.script,
                difficulty=1,
                flaw_targets=entry.flaw_targets,
                cue=entry.cue,
                reference_ready=True,
                reference_features_key="references/deadline/features.json",
            )
        )
        clip = "deadline__flawed-2"
        upload_key = f"uploads/{SID}/{AID}.wav"
        s3.upload_file(str(paths.audio / f"{clip}.wav"), "speakquest-smoke", upload_key)
        take_wav = normalized(paths.audio / f"{clip}.wav", paths, rubric)
        s3.put_object(
            Bucket="speakquest-smoke",
            Key=f"transcripts/{AID}.json",
            Body=transcript_for(take_wav, "vosk", paths).model_dump_json().encode(),
        )
        sk = take_sort_key("2026-10-15T00:00:00Z", AID)
        repo.create_analysis(
            AnalysisRecord(
                analysis_id=AID,
                session_id=SID,
                challenge_id="deadline",
                status="QUEUED",
                stage="QUEUED",
                created_at="2026-10-15T00:00:00Z",
                updated_at="2026-10-15T00:00:00Z",
                take_sk=sk,
                keys={"upload": upload_key},
            )
        )
        repo.put_take(
            SID,
            TakeRecord(
                sk=sk,
                analysis_id=AID,
                challenge_id="deadline",
                created_at="2026-10-15T00:00:00Z",
                status="QUEUED",
            ),
        )

        container = subprocess.Popen(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "host",
                "-e",
                f"AWS_LAMBDA_RUNTIME_API_PORT={rie_port}",
                "-e",
                "AWS_ACCESS_KEY_ID=testing",
                "-e",
                "AWS_SECRET_ACCESS_KEY=testing",
                "-e",
                "AWS_REGION=us-east-1",
                "-e",
                f"AWS_ENDPOINT_URL={env['AWS_ENDPOINT_URL']}",
                "-e",
                "SPEAKQUEST_BUCKET=speakquest-smoke",
                "-e",
                "SPEAKQUEST_TABLE=speakquest-smoke",
                "-e",
                "SPEAKQUEST_IMAGE_DIGEST=local-smoke",
                "--entrypoint",
                "/usr/local/bin/aws-lambda-rie",
                IMAGE,
                "--runtime-interface-emulator-address",
                f"127.0.0.1:{rie_port}",
                "/var/lang/bin/python3.12",
                "-m",
                "awslambdaric",
                "speakquest_api.lambdas.worker_handler",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        time.sleep(3)
        state = {
            "analysisId": AID,
            "sessionId": SID,
            "challengeId": "deadline",
            "uploadKey": upload_key,
            "language": "en-US",
            "takeSk": sk,
            "referenceFeaturesKey": "references/deadline/features.json",
        }
        t = time.time()
        out = invoke(rie_port, {"step": "normalize", "state": state})
        print("normalize:", out, f"{time.time() - t:.1f}s")
        assert out.get("normalizedKey") == f"work/{AID}/normalized.wav", out
        state["normalize"] = out
        t = time.time()
        out = invoke(rie_port, {"step": "analyze", "state": state})
        print("analyze:", out, f"{time.time() - t:.1f}s")
        assert out.get("findingCount", 0) >= 1, out
        result = json.loads(
            s3.get_object(Bucket="speakquest-smoke", Key=f"results/{AID}/analysis.json")[
                "Body"
            ].read()
        )
        print(
            "findings:",
            [f["code"] for f in result["findings"]],
            "digest:",
            result["versions"]["worker_image_digest"],
        )
        assert result["versions"]["worker_image_digest"] == "local-smoke"
        rec = repo.get_analysis(AID)
        assert rec is not None and rec.stage == "ANALYZE"
        bad = invoke(rie_port, {"step": "nope", "state": state})
        assert bad.get("errorType") == "AnalysisError", bad
        print("worker image smoke test: PASS")
        return 0
    finally:
        if container:
            container.terminate()
            container.wait(timeout=20)
        moto.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
