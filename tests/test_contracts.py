from __future__ import annotations

import subprocess
import sys

import pytest
from pydantic import ValidationError

from speakquest import contracts as c
from speakquest.errors import ERRORS, AnalysisError


def test_timed_word_rejects_reversed_span() -> None:
    with pytest.raises(ValidationError):
        c.TimedWord(text="hi", start=1.0, end=0.5)


def test_finding_id_pattern_and_severity_bounds() -> None:
    base = dict(
        code="RUSH",
        dimension="pace",
        start=1.0,
        end=2.0,
        words=["a"],
        evidence={},
        rubric_version="1.0.0",
    )
    c.Finding(id="f1", severity=1, **base)
    with pytest.raises(ValidationError):
        c.Finding(id="x1", severity=1, **base)
    with pytest.raises(ValidationError):
        c.Finding(id="f1", severity=4, **base)


@pytest.mark.parametrize("ctype", ["audio/webm;codecs=opus", "audio/mp4", "AUDIO/WAV"])
def test_upload_request_accepts_recorder_types(ctype: str) -> None:
    c.CreateUploadRequest(challengeId="deadline", contentType=ctype, bytes=1024)


@pytest.mark.parametrize("ctype", ["video/mp4", "text/plain", "application/octet-stream"])
def test_upload_request_rejects_non_audio(ctype: str) -> None:
    with pytest.raises(ValidationError):
        c.CreateUploadRequest(challengeId="deadline", contentType=ctype, bytes=1024)


def test_upload_request_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        c.CreateUploadRequest.model_validate(
            {"challengeId": "deadline", "contentType": "audio/webm", "bytes": 1, "admin": True}
        )


def test_every_content_type_has_extension() -> None:
    assert set(c.ALLOWED_CONTENT_TYPES) == set(c.CONTENT_TYPE_EXTENSIONS)


def test_analysis_error_carries_code_and_stage() -> None:
    err = AnalysisError("AUDIO_SILENT", "peak -90 dBFS", stage="NORMALIZE")
    assert err.code == "AUDIO_SILENT"
    assert err.to_dict()["stage"] == "NORMALIZE"
    assert err.retryable is True
    assert all(spec.message.endswith(".") for spec in ERRORS.values())


def test_unknown_error_code_is_a_programming_error() -> None:
    with pytest.raises(ValueError):
        AnalysisError("NOPE")


def test_committed_json_schema_is_current(repo_root) -> None:
    proc = subprocess.run(
        [sys.executable, str(repo_root / "scripts" / "export_schemas.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
