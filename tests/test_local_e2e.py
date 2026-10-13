"""Full HTTP flow against the local runtime with real audio and a real aligner.

Skipped unless the synthetic dataset and the Vosk model exist
(`make models dataset`).
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from speakquest_api.config import Settings
from speakquest_api.local.server import build, make_handler
from speakquest_api.seed import seed

pytestmark = [pytest.mark.slow, pytest.mark.asr]
ROOT = Path(__file__).resolve().parents[1]
AUDIO = ROOT / "data" / "audio"
VOSK = ROOT / ".models" / "vosk" / "vosk-model-small-en-us-0.15"
SID = "0b5a3a1c-8f9e-4c2d-9a7b-1234567890ab"
ORIGIN = "http://localhost:5173"


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    if not (AUDIO / "deadline__reference.wav").exists() or not VOSK.exists():
        pytest.skip("dataset or vosk model missing (make models dataset)")
    base = tmp_path_factory.mktemp("local")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)  # type: ignore[arg-type]
    port = httpd.server_address[1]
    cfg = Settings(
        backend="local",
        local_dir=str(base),
        local_base_url=f"http://127.0.0.1:{port}",
        local_aligner="vosk",
    )
    deps, workflow, storage = build(cfg, model=None)
    assert seed(storage, deps.repo, workflow.aligner, AUDIO, only=["deadline"]) == ["deadline"]
    httpd.RequestHandlerClass = make_handler(deps, storage)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()
    workflow.shutdown()


def http(
    method: str,
    url: str,
    body: Any = None,
    headers: dict[str, str] | None = None,
    raw: bytes | None = None,
) -> tuple[int, dict[str, str], bytes]:
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    hdrs = {"x-session-id": SID, "origin": ORIGIN, **(headers or {})}
    if body is not None:
        hdrs["content-type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as err:
        return err.code, dict(err.headers), err.read()


def test_record_upload_analyse_and_read_back(server: str) -> None:
    status, headers, body = http("GET", f"{server}/challenges")
    assert status == 200 and headers["access-control-allow-origin"] == ORIGIN
    challenge = json.loads(body)["challenges"][0]
    assert challenge["id"] == "deadline" and challenge["reference_ready"]
    assert http("GET", challenge["reference_audio_url"])[0] == 200

    take = (AUDIO / "deadline__flawed-2.wav").read_bytes()
    status, _, body = http(
        "POST",
        f"{server}/uploads",
        {"challengeId": "deadline", "contentType": "audio/wav", "bytes": len(take)},
    )
    assert status == 201
    up = json.loads(body)
    # Browsers preflight the cross-origin PUT; it must be allowed.
    status, headers, _ = http("OPTIONS", up["uploadUrl"], headers={
        "access-control-request-method": "PUT",
        "access-control-request-headers": "content-type"})
    assert status == 204 and "PUT" in headers["access-control-allow-methods"]
    # A PUT that doesn't match the signed type is refused, like S3 would.
    assert http("PUT", up["uploadUrl"], raw=take, headers={"content-type": "audio/webm"})[0] == 403
    assert http("PUT", up["uploadUrl"], raw=take, headers=up["headers"])[0] == 200

    status, _, body = http(
        "POST", f"{server}/analyses", {"challengeId": "deadline", "key": up["key"]}
    )
    assert status == 202
    aid = json.loads(body)["analysisId"]
    seen = set()
    deadline = time.time() + 120
    while time.time() < deadline:
        state = json.loads(http("GET", f"{server}/analyses/{aid}")[2])
        seen.add(state["stage"])
        if state["status"] in ("DONE", "FAILED"):
            break
        time.sleep(0.3)
    assert state["status"] == "DONE", state
    assert state["summary"]["findingCount"] >= 1

    status, _, body = http("GET", f"{server}/analyses/{aid}/result")
    links = json.loads(body)
    result = json.loads(http("GET", links["resultUrl"])[2])
    assert result["analysis_id"] == aid and result["coaching"]["source"] == "template"
    assert result["versions"]["aligner"].startswith("vosk:")
    labels = json.loads((ROOT / "data/annotations/deadline__flawed-2.json").read_text())["flaws"]
    assert {f["code"] for f in labels} <= {f["code"] for f in result["findings"]}
    assert http("GET", links["audioUrl"])[2] == take

    progress = json.loads(http("GET", f"{server}/me/progress")[2])
    assert progress["xp"] > 0 and progress["takes"][0]["status"] == "DONE"
    assert {b["id"] for b in progress["badges"]} >= {"FIRST_TAKE"}


def test_corrupt_upload_fails_with_a_reason(server: str) -> None:
    junk = b"\x00\x01not audio" * 200
    up = json.loads(
        http(
            "POST",
            f"{server}/uploads",
            {"challengeId": "deadline", "contentType": "audio/webm", "bytes": len(junk)},
        )[2]
    )
    assert http("PUT", up["uploadUrl"], raw=junk, headers=up["headers"])[0] == 200
    aid = json.loads(
        http("POST", f"{server}/analyses", {"challengeId": "deadline", "key": up["key"]})[2]
    )["analysisId"]
    for _ in range(100):
        state = json.loads(http("GET", f"{server}/analyses/{aid}")[2])
        if state["status"] in ("DONE", "FAILED"):
            break
        time.sleep(0.2)
    assert state["status"] == "FAILED"
    assert state["error"]["code"] in ("AUDIO_UNSUPPORTED", "AUDIO_CORRUPT")
    assert state["error"]["stage"] == "NORMALIZE"
