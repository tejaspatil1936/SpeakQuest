"""Seed challenges and pre-analyse their reference takes (``make seed``).

For every catalogue entry: normalise the reference recording, time its words
with the chosen aligner, measure it once (``features.json``), upload
``references/<id>/audio.wav | words.json | features.json`` and write the
challenge item with ``reference_ready``. Runs against S3/DynamoDB or the
local adapters — the code is the same.
"""

from __future__ import annotations

import tempfile
from collections.abc import Sequence
from pathlib import Path

from speakquest.challenges import load_catalogue
from speakquest.logs import get_logger, log_event
from speakquest.normalize import normalize
from speakquest.pipeline import analyze_reference
from speakquest.rubric import load_rubric
from speakquest.storage import Storage, put_json
from speakquest.timing import Aligner
from speakquest_api.repository import ChallengeRecord, ItemRepository

log = get_logger("speakquest.seed")


def reference_audio_path(audio_dir: Path, challenge_id: str) -> Path:
    return audio_dir / f"{challenge_id}__reference.wav"


def seed(
    storage: Storage,
    repo: ItemRepository,
    aligner: Aligner,
    audio_dir: Path,
    only: Sequence[str] = (),
) -> list[str]:
    rubric = load_rubric()
    seeded: list[str] = []
    for order, entry in enumerate(load_catalogue()):
        if only and entry.id not in only:
            continue
        src = reference_audio_path(audio_dir, entry.id)
        if not src.exists():
            raise FileNotFoundError(
                f"{src} missing — generate references with `make dataset` or supply recordings"
            )
        prefix = f"references/{entry.id}"
        with tempfile.TemporaryDirectory(prefix="sq-seed-") as tmp:
            audio = normalize(src, Path(tmp) / "audio.wav", rubric.audio)
            storage.upload(audio.path, f"{prefix}/audio.wav", "audio/wav")
            transcript = aligner.transcribe(audio.path, entry.language)
            features = analyze_reference(audio.path, transcript, entry.script, rubric)
        put_json(storage, f"{prefix}/words.json", transcript.model_dump(mode="json"))
        put_json(storage, f"{prefix}/features.json", features.model_dump(mode="json"))
        repo.put_challenge(
            ChallengeRecord(
                id=entry.id,
                title=entry.title,
                script=entry.script,
                difficulty=entry.difficulty,
                flaw_targets=entry.flaw_targets,
                cue=entry.cue,
                language=entry.language,
                reference_audio_key=f"{prefix}/audio.wav",
                reference_features_key=f"{prefix}/features.json",
                reference_duration_s=round(audio.duration_s, 2),
                reference_ready=True,
                order=order,
            )
        )
        log_event(
            log,
            "seed.reference",
            challenge=entry.id,
            words=len(transcript.words),
            aligner=transcript.aligner,
            duration_s=round(audio.duration_s, 2),
        )
        seeded.append(entry.id)
    return seeded
