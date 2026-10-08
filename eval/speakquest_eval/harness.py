"""Run the real analysis pipeline over the labelled dataset and score it.

Each clip goes through exactly what production does — ffmpeg
normalisation, an aligner, the script diff, features, rules — and the
findings are compared with the annotation intervals. Nothing is mocked:
if the aligner mishears a word, that error shows up in the numbers.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from speakquest.challenges import load_catalogue
from speakquest.contracts import AnalysisResult, TakeAnalysis, Transcript
from speakquest.errors import AnalysisError
from speakquest.normalize import load_wav, normalize
from speakquest.pipeline import analyze_samples, prepare
from speakquest.rubric import Rubric, load_rubric
from speakquest.timing import get_aligner
from speakquest_eval.metrics import (
    ClipMatch,
    Interval,
    aggregate,
    fp_per_minute,
    match,
    micro,
    summarize_errors,
)


@dataclass(frozen=True)
class Paths:
    audio: Path
    annotations: Path
    cache: Path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def normalized(clip_wav: Path, paths: Paths, rubric: Rubric) -> Path:
    out = paths.cache / "wav16" / f"{clip_wav.stem}.wav"
    if not out.exists() or out.stat().st_mtime < clip_wav.stat().st_mtime:
        normalize(clip_wav, out, rubric.audio)
    return out


def transcript_for(wav16: Path, aligner_name: str, paths: Paths) -> Transcript:
    key = f"{wav16.stem}.{aligner_name.replace(':', '_')}.{_sha(wav16)}.json"
    cached = paths.cache / "transcripts" / key
    if cached.exists():
        return Transcript.model_validate_json(cached.read_text())
    transcript = get_aligner(aligner_name).transcribe(wav16, "en-US")
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(transcript.model_dump_json())
    return transcript


def _boundary_errors(
    result_words: Sequence[Any], boundaries: Sequence[dict[str, Any]]
) -> list[float]:
    by_token = {w.script_index: w for w in result_words if w.script_index is not None}
    errs: list[float] = []
    for b in boundaries:
        w = by_token.get(b["token"])
        if w is None:
            continue
        t = w.start if b["edge"] == "start" else w.end
        errs.append(abs(t - b["time"]) * 1000)
    return errs


def evaluate(
    split: str, aligner_name: str, paths: Paths, rubric: Rubric | None = None
) -> dict[str, Any]:
    rubric = rubric or load_rubric()
    started = time.time()
    matches: list[ClipMatch] = []
    clips: list[dict[str, Any]] = []
    clean_findings, clean_seconds = 0, 0.0
    clean_codes: dict[str, int] = {}
    boundary_errors: list[float] = []
    failures: list[dict[str, str]] = []

    for entry in load_catalogue():
        if split not in ("all", entry.split):
            continue
        annotations = sorted(paths.annotations.glob(f"{entry.id}__*.json"))
        if not annotations:
            continue
        ref_ann = paths.annotations / f"{entry.id}__reference.json"
        ref_wav = normalized(paths.audio / f"{entry.id}__reference.wav", paths, rubric)
        ref_tr = transcript_for(ref_wav, aligner_name, paths)
        samples, sr = load_wav(ref_wav)
        reference: TakeAnalysis = prepare(samples, sr, ref_tr, entry.script, rubric).analysis
        boundary_errors += _boundary_errors(
            reference.words, json.loads(ref_ann.read_text())["boundaries"]
        )

        for ann_path in annotations:
            ann = json.loads(ann_path.read_text())
            if ann["role"] == "reference":
                continue
            wav16 = normalized(paths.audio / f"{ann['clip_id']}.wav", paths, rubric)
            transcript = transcript_for(wav16, aligner_name, paths)
            samples, sr = load_wav(wav16)
            try:
                result: AnalysisResult = analyze_samples(
                    analysis_id=ann["clip_id"],
                    challenge_id=entry.id,
                    samples=samples,
                    sr=sr,
                    transcript=transcript,
                    script_text=entry.script,
                    reference=reference,
                    rubric=rubric,
                    created_at="1970-01-01T00:00:00Z",
                )
            except AnalysisError as exc:
                failures.append({"clip_id": ann["clip_id"], "code": exc.code})
                labelled = [Interval(f["code"], f["start"], f["end"]) for f in ann["flaws"]]
                matches.append(ClipMatch(fn=labelled))
                continue
            predicted = [Interval(f.code, f.start, f.end) for f in result.findings]
            labelled = [Interval(f["code"], f["start"], f["end"]) for f in ann["flaws"]]
            m = match(predicted, labelled)
            boundary_errors += _boundary_errors(result.take.words, ann["boundaries"])
            if ann["role"] == "clean":
                clean_findings += len(predicted)
                clean_seconds += ann["duration_s"]
                for p in predicted:
                    clean_codes[p.code] = clean_codes.get(p.code, 0) + 1
            else:
                matches.append(m)
            clips.append(
                {
                    "clip_id": ann["clip_id"],
                    "role": ann["role"],
                    "voice": ann["voice"],
                    "labels": [f"{g.code}@{g.start:.2f}-{g.end:.2f}" for g in labelled],
                    "found": [f"{f.code}@{f.start:.2f}-{f.end:.2f}" for f in result.findings],
                    "tp": len(m.tp),
                    "fp": len(m.fp),
                    "fn": len(m.fn),
                    "overall": result.scores.overall,
                }
            )

    stats = aggregate(matches)
    return {
        "split": split,
        "aligner": aligner_name,
        "rubric_version": rubric.version,
        "rubric_digest": rubric.digest,
        "iou_threshold": 0.5,
        "n_flawed_clips": len(matches),
        "n_clean_clips": sum(1 for c in clips if c["role"] == "clean"),
        "per_code": {code: s.to_dict() for code, s in stats.items()},
        "micro": micro(stats).to_dict(),
        "clean_minutes": round(clean_seconds / 60, 2),
        "clean_findings": clean_findings,
        "clean_findings_by_code": dict(sorted(clean_codes.items())),
        "fp_per_minute": None
        if (r := fp_per_minute(clean_findings, clean_seconds)) is None
        else round(r, 2),
        "boundary_error": summarize_errors(boundary_errors),
        "failures": failures,
        "clips": clips,
        "runtime_s": round(time.time() - started, 1),
    }


def _fmt(v: float | int | None) -> str:
    return "–" if v is None else f"{v:.2f}" if isinstance(v, float) else str(v)


def to_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# Evaluation — split `{report['split']}`, aligner `{report['aligner']}`",
        "",
        f"Rubric {report['rubric_version']} (digest `{report['rubric_digest']}`), "
        f"match = same code and IoU ≥ {report['iou_threshold']}. "
        f"{report['n_flawed_clips']} flawed clips, {report['n_clean_clips']} clean clips "
        f"({report['clean_minutes']} min).",
        "",
        "| Code | TP | FP | FN | Precision | Recall | Mean IoU |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for code, s in report["per_code"].items():
        lines.append(
            f"| {code} | {s['tp']} | {s['fp']} | {s['fn']} | {_fmt(s['precision'])} | "
            f"{_fmt(s['recall'])} | {_fmt(s['mean_iou'])} |"
        )
    m = report["micro"]
    lines += [
        f"| **all** | {m['tp']} | {m['fp']} | {m['fn']} | {_fmt(m['precision'])} | "
        f"{_fmt(m['recall'])} | {_fmt(m['mean_iou'])} |",
        "",
        f"**False positives on clean-vs-clean pairs:** {report['clean_findings']} findings in "
        f"{report['clean_minutes']} min = **{_fmt(report['fp_per_minute'])} per minute** "
        f"(target < 1). By code: {report['clean_findings_by_code'] or 'none'}.",
        "",
        f"**Aligner boundary error** at known word edges: median "
        f"{_fmt(report['boundary_error']['median_ms'])} ms, p90 "
        f"{_fmt(report['boundary_error']['p90_ms'])} ms (n={report['boundary_error']['n']}).",
        "",
    ]
    if report["failures"]:
        lines += [
            "**Clips that failed analysis:** "
            + ", ".join(f"{f['clip_id']} ({f['code']})" for f in report["failures"]),
            "",
        ]
    lines += [
        "<details><summary>Per-clip detail</summary>",
        "",
        "| Clip | Labels | Found | TP/FP/FN |",
        "|---|---|---|---|",
    ]
    for c in report["clips"]:
        lines.append(
            f"| {c['clip_id']} | {' '.join(c['labels']) or '–'} | "
            f"{' '.join(c['found']) or '–'} | {c['tp']}/{c['fp']}/{c['fn']} |"
        )
    lines += ["", "</details>", ""]
    return "\n".join(lines)
