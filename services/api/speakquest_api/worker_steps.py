"""Workflow steps that need the audio stack (worker container image).

* ``normalize_step`` — ffmpeg → 16 kHz mono WAV in ``work/`` with sanity checks
* ``analyze_step``   — transcript + reference → findings, scores (no coaching)
* ``transcribe_local_step`` — local stand-in for the Transcribe states
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from speakquest.contracts import TakeAnalysis, Transcript
from speakquest.errors import AnalysisError
from speakquest.logs import get_logger, log_event
from speakquest.normalize import normalize
from speakquest.pipeline import analyze_take
from speakquest.rubric import load_rubric
from speakquest.storage import StorageMissingError, get_json, put_json
from speakquest.timing import Aligner, parse_transcribe_json
from speakquest_api.repository import now_iso
from speakquest_api.steps import StepDeps, analysis_key, mark

log = get_logger("speakquest.worker")


def normalized_key(analysis_id: str) -> str:
    return f"work/{analysis_id}/normalized.wav"


def transcript_key(analysis_id: str) -> str:
    return f"transcripts/{analysis_id}.json"


def normalize_step(state: dict[str, Any], deps: StepDeps) -> dict[str, Any]:
    aid = state["analysisId"]
    mark(deps, state, "NORMALIZE")
    rubric = load_rubric()
    with tempfile.TemporaryDirectory(prefix="sq-") as tmp:
        src = Path(tmp) / Path(state["uploadKey"]).name
        try:
            deps.storage.download(state["uploadKey"], src)
        except StorageMissingError as exc:
            raise AnalysisError("AUDIO_MISSING", stage="NORMALIZE") from exc
        audio = normalize(src, Path(tmp) / "normalized.wav", rubric.audio)
        deps.storage.upload(audio.path, normalized_key(aid), "audio/wav")
    deps.repo.update_analysis(aid, stage="TRANSCRIBE", duration_s=round(audio.duration_s, 2))
    log_event(
        log,
        "normalize.done",
        analysis_id=aid,
        **{k: v for k, v in audio.to_dict().items() if k != "path"},
    )
    return {
        "normalizedKey": normalized_key(aid),
        "durationS": round(audio.duration_s, 3),
        "speechDbfs": round(audio.speech_dbfs, 1),
    }


def transcribe_local_step(
    state: dict[str, Any], deps: StepDeps, aligner: Aligner
) -> dict[str, Any]:
    aid = state["analysisId"]
    mark(deps, state, "TRANSCRIBE")
    with tempfile.TemporaryDirectory(prefix="sq-") as tmp:
        wav = deps.storage.download(normalized_key(aid), Path(tmp) / "n.wav")
        transcript = aligner.transcribe(wav, state.get("language", "en-US"))
    put_json(deps.storage, transcript_key(aid), transcript.model_dump(mode="json"))
    return {"transcriptKey": transcript_key(aid), "words": len(transcript.words)}


def load_transcript(raw: dict[str, Any], language: str) -> Transcript:
    """Accept Amazon Transcribe output or our own Transcript JSON."""
    if "results" in raw:
        return parse_transcribe_json(raw, language)
    return Transcript.model_validate(raw)


def analyze_step(state: dict[str, Any], deps: StepDeps) -> dict[str, Any]:
    aid = state["analysisId"]
    mark(deps, state, "ANALYZE")
    challenge = deps.repo.get_challenge(state["challengeId"])
    if challenge is None or not state.get("referenceFeaturesKey"):
        raise AnalysisError("REFERENCE_MISSING", stage="ANALYZE")
    try:
        reference = TakeAnalysis.model_validate(
            get_json(deps.storage, state["referenceFeaturesKey"])
        )
    except StorageMissingError as exc:
        raise AnalysisError("REFERENCE_MISSING", stage="ANALYZE") from exc
    try:
        raw = get_json(deps.storage, state.get("transcriptKey") or transcript_key(aid))
    except StorageMissingError as exc:
        raise AnalysisError("TRANSCRIBE_FAILED", "transcript missing", stage="TRANSCRIBE") from exc
    except json.JSONDecodeError as exc:
        raise AnalysisError(
            "TRANSCRIBE_FAILED", "transcript unreadable", stage="TRANSCRIBE"
        ) from exc
    transcript = load_transcript(raw, state.get("language", "en-US"))
    with tempfile.TemporaryDirectory(prefix="sq-") as tmp:
        wav = deps.storage.download(normalized_key(aid), Path(tmp) / "n.wav")
        result = analyze_take(
            analysis_id=aid,
            challenge_id=challenge.id,
            wav=wav,
            transcript=transcript,
            script_text=challenge.script,
            reference=reference,
            rubric=load_rubric(),
            created_at=now_iso(),
        )
    put_json(deps.storage, analysis_key(aid), result.model_dump(mode="json"))
    log_event(
        log,
        "analyze.done",
        analysis_id=aid,
        findings=len(result.findings),
        overall=result.scores.overall,
        aligner=transcript.aligner,
    )
    return {"analysisKey": analysis_key(aid), "findingCount": len(result.findings)}
