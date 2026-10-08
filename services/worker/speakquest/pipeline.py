"""End-to-end analysis of one take against its challenge reference.

Pure function of (normalised audio, transcript, script, reference, rubric):
no AWS calls, no clocks except the ``created_at`` stamp the caller passes in.
The Lambda handlers and the local runner both call into here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from speakquest.contracts import AnalysisResult, TakeAnalysis, Transcript, Versions
from speakquest.diff import align, classify_insertions, coverage
from speakquest.errors import AnalysisError
from speakquest.features import build_tracks, compare_rates, measure
from speakquest.findings import detect
from speakquest.normalize import FloatArray, load_wav
from speakquest.rubric import Rubric, score
from speakquest.timing import SpokenToken, spoken_tokens
from speakquest.tokens import tokenize_script


def worker_digest() -> str:
    return os.environ.get("SPEAKQUEST_IMAGE_DIGEST", "local")


@dataclass(frozen=True)
class Prepared:
    tokens: list[SpokenToken]
    analysis: TakeAnalysis
    ops: list
    confidences: dict[int, float]


def _fillers(rubric: Rubric) -> frozenset[str]:
    return frozenset(str(w) for w in rubric.rule("FILLER")["filler_words"])


def prepare(
    samples: FloatArray,
    sr: int,
    transcript: Transcript,
    script_text: str,
    rubric: Rubric,
    *,
    require_coverage: bool = True,
) -> Prepared:
    script = tokenize_script(script_text)
    tokens = spoken_tokens(transcript)
    if not tokens:
        raise AnalysisError("NO_SPEECH", stage="ANALYZE")
    fillers = _fillers(rubric)
    script_norms = [t.norm for t in script.tokens]
    spoken_norms = [t.norm for t in tokens]
    ops = align(script_norms, spoken_norms, fillers)
    cov = coverage(ops, script_norms, spoken_norms)
    if require_coverage and cov < rubric.audio.min_script_coverage:
        raise AnalysisError(
            "SCRIPT_MISMATCH", f"only {cov:.0%} of the script was recognised", stage="ANALYZE"
        )
    inserts = classify_insertions(ops, script_norms, spoken_norms, fillers)
    tracks = build_tracks(samples, sr, rubric.features)
    analysis = measure(samples, sr, tokens, ops, inserts, script, rubric.features, tracks)
    confidences = {i: t.confidence for i, t in enumerate(tokens) if t.confidence is not None}
    return Prepared(tokens=tokens, analysis=analysis, ops=ops, confidences=confidences)


def analyze_reference(
    wav: Path, transcript: Transcript, script_text: str, rubric: Rubric
) -> TakeAnalysis:
    """Measure a challenge's reference recording once, at seed time."""
    samples, sr = load_wav(wav)
    return prepare(samples, sr, transcript, script_text, rubric).analysis


def analyze_take(
    *,
    analysis_id: str,
    challenge_id: str,
    wav: Path,
    transcript: Transcript,
    script_text: str,
    reference: TakeAnalysis,
    rubric: Rubric,
    created_at: str,
) -> AnalysisResult:
    samples, sr = load_wav(wav)
    return analyze_samples(
        analysis_id=analysis_id,
        challenge_id=challenge_id,
        samples=samples,
        sr=sr,
        transcript=transcript,
        script_text=script_text,
        reference=reference,
        rubric=rubric,
        created_at=created_at,
    )


def analyze_samples(
    *,
    analysis_id: str,
    challenge_id: str,
    samples: FloatArray,
    sr: int,
    transcript: Transcript,
    script_text: str,
    reference: TakeAnalysis,
    rubric: Rubric,
    created_at: str,
) -> AnalysisResult:
    if not reference.words:
        raise AnalysisError("REFERENCE_MISSING", stage="ANALYZE")
    script = tokenize_script(script_text)
    prepared = prepare(samples, sr, transcript, script_text, rubric)
    take = compare_rates(prepared.analysis, reference, rubric.features)
    findings, take = detect(take, reference, script, prepared.ops, rubric, prepared.confidences)
    scores, penalties = score(findings, rubric)

    warnings: list[str] = []
    if take.rate_ratio_global is None:
        warnings.append("No words were matched in both recordings; pace was not compared.")
    if take.pitch_median_hz is None:
        warnings.append("No voiced speech was detected; pitch was not measured.")

    return AnalysisResult(
        analysis_id=analysis_id,
        challenge_id=challenge_id,
        created_at=created_at,
        versions=Versions(
            rubric_version=rubric.version,
            worker_image_digest=worker_digest(),
            transcribe_language=transcript.language,
            aligner=transcript.aligner,
        ),
        script=script,
        take=take,
        reference=reference,
        alignment=prepared.ops,
        findings=findings,
        penalties=penalties,
        scores=scores,
        warnings=warnings,
    )
