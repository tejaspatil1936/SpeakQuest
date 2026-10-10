"""Workflow steps end to end on local adapters (same code the Lambdas run)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from speakquest.contracts import AnalysisResult
from speakquest.pipeline import prepare
from speakquest.rubric import load_rubric
from speakquest.storage import LocalStorage, get_json, put_json
from speakquest_api.repository import (
    AnalysisRecord,
    ChallengeRecord,
    SqliteRepository,
    TakeRecord,
    take_sort_key,
)
from speakquest_api.steps import StepDeps, error_code, explain_step, fail_step, persist_step
from speakquest_api.worker_steps import analyze_step, normalize_step, transcript_key
from tests.audio_helpers import write_wav
from tests.synth import SCRIPT, SR, reference_words, render, with_changes

pytestmark = pytest.mark.slow
SID = "0b5a3a1c-8f9e-4c2d-9a7b-1234567890ab"


def _setup(tmp_path: Path, aid: str, take_words: Any) -> tuple[StepDeps, dict[str, Any]]:
    storage = LocalStorage(tmp_path / "bucket", "http://localhost:8787", b"k")
    repo = SqliteRepository(tmp_path / "db.sqlite")
    samples, transcript = render(reference_words())
    reference = prepare(samples, SR, transcript, SCRIPT, load_rubric()).analysis
    put_json(storage, "references/deadline/features.json", reference.model_dump(mode="json"))
    repo.put_challenge(
        ChallengeRecord(
            id="deadline",
            title="T",
            script=SCRIPT,
            difficulty=1,
            flaw_targets=["RUSH"],
            cue="c",
            reference_ready=True,
            reference_features_key="references/deadline/features.json",
        )
    )
    take_samples, take_transcript = render(take_words)
    wav = write_wav(tmp_path / "take.wav", take_samples, SR)
    upload_key = f"uploads/{SID}/{aid}.wav"
    storage.upload(wav, upload_key)
    # The transcription states would write this; tests supply the aligner output.
    put_json(storage, transcript_key(aid), take_transcript.model_dump(mode="json"))
    created = "2026-10-15T00:00:00Z"
    sk = take_sort_key(created, aid)
    repo.create_analysis(
        AnalysisRecord(
            analysis_id=aid,
            session_id=SID,
            challenge_id="deadline",
            status="QUEUED",
            stage="QUEUED",
            created_at=created,
            updated_at=created,
            take_sk=sk,
            keys={"upload": upload_key},
        )
    )
    repo.put_take(
        SID,
        TakeRecord(
            sk=sk, analysis_id=aid, challenge_id="deadline", created_at=created, status="QUEUED"
        ),
    )
    state = {
        "analysisId": aid,
        "sessionId": SID,
        "challengeId": "deadline",
        "uploadKey": upload_key,
        "language": "en-US",
        "takeSk": sk,
        "referenceFeaturesKey": "references/deadline/features.json",
    }
    return StepDeps(storage=storage, repo=repo, model=None), state


def test_full_step_sequence_persists_result_and_progress(tmp_path: Path) -> None:
    aid = "11111111-0000-4000-8000-000000000000"
    words = with_changes(reference_words(rate=0.92, f_scale=1.45, amp=0.2), [5], gap=1.1)
    deps, state = _setup(tmp_path, aid, words)
    state["normalize"] = normalize_step(state, deps)
    assert deps.repo.get_analysis(aid).stage == "TRANSCRIBE"  # type: ignore[union-attr]
    state["analyze"] = analyze_step(state, deps)
    assert state["analyze"]["findingCount"] == 1
    state["explain"] = explain_step(state, deps)
    assert state["explain"]["source"] == "template"
    out = persist_step(state, deps)

    result = AnalysisResult.model_validate(get_json(deps.storage, out["resultKey"]))
    assert [f.code for f in result.findings] == ["HESITATE"]
    assert result.coaching is not None and result.coaching.items[0].finding_id == "f1"
    rec = deps.repo.get_analysis(aid)
    assert rec is not None and (rec.status, rec.stage) == ("DONE", "DONE")
    assert rec.summary is not None and rec.summary["codes"] == ["HESITATE"]
    take = deps.repo.list_takes(SID)[0]
    assert take.status == "DONE" and take.scores is not None and take.codes == ["HESITATE"]
    profile = deps.repo.get_profile(SID)
    assert profile is not None and profile.xp == round(result.take.duration_s)
    assert {b.id for b in profile.badges} == {"FIRST_TAKE", "FULL_HOUSE"}

    # Persist retried by Step Functions must not double-count air time.
    persist_step(state, deps)
    assert deps.repo.get_profile(SID).xp == profile.xp  # type: ignore[union-attr]


def test_persist_falls_back_to_template_when_explain_never_ran(tmp_path: Path) -> None:
    aid = "22222222-0000-4000-8000-000000000000"
    words = with_changes(reference_words(rate=0.92, f_scale=1.45, amp=0.2), [6, 7], amp=0.035)
    deps, state = _setup(tmp_path, aid, words)
    normalize_step(state, deps)
    analyze_step(state, deps)
    persist_step(state, deps)
    result = AnalysisResult.model_validate(get_json(deps.storage, f"results/{aid}/result.json"))
    assert result.coaching is not None and result.coaching.source == "template"
    assert "explain step failed" in result.coaching.rejections[0]


def test_silent_upload_fails_with_code_and_stage(tmp_path: Path) -> None:
    import numpy as np

    aid = "33333333-0000-4000-8000-000000000000"
    deps, state = _setup(tmp_path, aid, reference_words())
    write_wav(tmp_path / "silent.wav", np.zeros(SR * 3, dtype=np.float32), SR)
    deps.storage.upload(tmp_path / "silent.wav", state["uploadKey"])
    from speakquest.errors import AnalysisError

    with pytest.raises(AnalysisError) as exc:
        normalize_step(state, deps)
    # What Step Functions hands the Catch target for a Python Lambda error:
    state["error"] = {
        "Error": "AnalysisError",
        "Cause": json.dumps({"errorMessage": str(exc.value), "errorType": "AnalysisError"}),
    }
    assert fail_step(state, deps) == {"code": "AUDIO_SILENT", "stage": "NORMALIZE"}
    rec = deps.repo.get_analysis(aid)
    assert rec is not None and rec.status == "FAILED"
    assert rec.error is not None and rec.error["retryable"] is True
    assert deps.repo.list_takes(SID)[0].status == "FAILED"


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (
            {"Error": "AnalysisError", "Cause": json.dumps({"errorMessage": "NO_SPEECH: x"})},
            "NO_SPEECH",
        ),
        ({"Error": "TRANSCRIBE_TIMEOUT", "Cause": "40 polls"}, "TRANSCRIBE_TIMEOUT"),
        ({"Error": "States.Timeout", "Cause": ""}, "TIMEOUT"),
        ({"Error": "Lambda.Unknown", "Cause": "Task timed out after 300.00 seconds"}, "TIMEOUT"),
        ({"Error": "Lambda.ServiceException", "Cause": "boom"}, "INTERNAL"),
        (None, "INTERNAL"),
    ],
)
def test_error_code_mapping(error: dict[str, Any] | None, code: str) -> None:
    assert error_code(error)[0] == code


def test_zip_lambdas_do_not_import_numpy() -> None:
    probe = (
        "import sys, speakquest_api.lambdas, speakquest_api.steps; "
        "print('numpy' in sys.modules, 'scipy' in sys.modules)"
    )
    out = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True, timeout=60
    )
    assert out.stdout.strip() == "False False"
