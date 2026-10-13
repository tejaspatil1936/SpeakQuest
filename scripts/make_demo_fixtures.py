"""Produce demo fixtures for the web app from the synthetic dataset.

Runs the real pipeline (ffmpeg → aligner → analysis) on a few generated
clips and writes, under web/public/fixtures/:

* ``<clip>.result.json`` — genuine AnalysisResult documents
* ``<clip>.ogg`` / reference ``.ogg`` — Opus-compressed synthetic speech
* ``index.json`` — what the demo adapter lists

These are clearly labelled fixtures (synthetic TTS voices), used only by the
web app's demo mode; production results come from the API.

Usage: python scripts/make_demo_fixtures.py [--aligner vosk]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

from speakquest.challenges import get_entry, load_catalogue
from speakquest.normalize import load_wav
from speakquest.pipeline import analyze_samples, prepare
from speakquest.rubric import load_rubric
from speakquest_eval.harness import Paths, normalized, transcript_for
from speakquest_explain.coach import client_from_env, coach

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "public" / "fixtures"
CLIPS = [
    ("deadline", "deadline__flawed-2"),
    ("deadline", "deadline__flawed-4"),
    ("gallery-four", "gallery-four__flawed-1"),
    ("the-toast", "the-toast__flawed-2"),
    ("weather-desk", "weather-desk__clean-ryan"),
]


def opus(src: Path, dst: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(src),
            "-ac",
            "1",
            "-c:a",
            "libopus",
            "-b:a",
            "24k",
            str(dst),
        ],
        check=True,
        timeout=60,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--aligner", default="vosk")
    args = parser.parse_args()
    rubric = load_rubric()
    # Real coaching when AWS credentials are present (run through
    # scripts/with-aws-env.sh); otherwise the deterministic template.
    model = client_from_env() if os.environ.get("AWS_ACCESS_KEY_ID") else None
    paths = Paths(
        ROOT / "data" / "audio", ROOT / "data" / "annotations", ROOT / "data" / "generated"
    )
    OUT.mkdir(parents=True, exist_ok=True)
    index = []
    for challenge_id, clip in CLIPS:
        entry = get_entry(challenge_id)
        assert entry is not None
        ref_wav = normalized(paths.audio / f"{challenge_id}__reference.wav", paths, rubric)
        samples, sr = load_wav(ref_wav)
        reference = prepare(
            samples, sr, transcript_for(ref_wav, args.aligner, paths), entry.script, rubric
        ).analysis
        wav = normalized(paths.audio / f"{clip}.wav", paths, rubric)
        samples, sr = load_wav(wav)
        result = analyze_samples(
            analysis_id=f"demo-{clip.replace('__', '-')}",
            challenge_id=challenge_id,
            samples=samples,
            sr=sr,
            transcript=transcript_for(wav, args.aligner, paths),
            script_text=entry.script,
            reference=reference,
            rubric=rubric,
            created_at="2026-10-15T09:00:00Z",
        )
        coaching = coach(result.findings, entry.script, model)
        result = result.model_copy(
            update={
                "coaching": coaching,
                "versions": result.versions.model_copy(update={"model_id": coaching.model_id}),
            }
        )
        (OUT / f"{result.analysis_id}.result.json").write_text(result.model_dump_json(indent=1))
        opus(paths.audio / f"{clip}.wav", OUT / f"{result.analysis_id}.ogg")
        opus(paths.audio / f"{challenge_id}__reference.wav", OUT / f"{challenge_id}.reference.ogg")
        index.append(
            {
                "analysisId": result.analysis_id,
                "challengeId": challenge_id,
                "clip": clip,
                "overall": result.scores.overall,
                "codes": [f.code for f in result.findings],
            }
        )
        print(clip, result.scores.overall, [f.code for f in result.findings], coaching.source)
    (OUT / "index.json").write_text(json.dumps({"fixtures": index}, indent=2) + "\n")
    challenges = []
    for entry in load_catalogue():
        ref = OUT / f"{entry.id}.reference.ogg"
        if not ref.exists():
            opus(paths.audio / f"{entry.id}__reference.wav", ref)
        ann = json.loads((paths.annotations / f"{entry.id}__reference.json").read_text())
        challenges.append(
            entry.to_challenge(
                reference_duration_s=ann["duration_s"],
                reference_audio_url=f"/fixtures/{entry.id}.reference.ogg",
                reference_ready=True,
            ).model_dump()
        )
    (OUT / "challenges.json").write_text(json.dumps({"challenges": challenges}, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
