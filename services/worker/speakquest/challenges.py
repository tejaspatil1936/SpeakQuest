"""Challenge catalogue loading (``data/scripts/challenges.yaml``)."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

from speakquest.contracts import Challenge, FlawCode

_REPO_CATALOGUE = Path(__file__).resolve().parents[3] / "data" / "scripts" / "challenges.yaml"


class CatalogueEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    difficulty: Literal[1, 2, 3]
    split: Literal["dev", "heldout"]
    flaw_targets: list[FlawCode]
    cue: str
    script: str
    language: str = "en-US"

    def to_challenge(
        self,
        *,
        reference_duration_s: float | None = None,
        reference_audio_url: str | None = None,
        reference_ready: bool = False,
    ) -> Challenge:
        return Challenge(
            id=self.id,
            title=self.title,
            script=self.script,
            difficulty=self.difficulty,
            flaw_targets=self.flaw_targets,
            language=self.language,
            cue=self.cue,
            reference_duration_s=reference_duration_s,
            reference_audio_url=reference_audio_url,
            reference_ready=reference_ready,
        )


def catalogue_path(path: str | Path | None = None) -> Path:
    return Path(path or os.environ.get("SPEAKQUEST_CATALOGUE") or _REPO_CATALOGUE)


@lru_cache(maxsize=4)
def _load(path: str) -> tuple[CatalogueEntry, ...]:
    data = yaml.safe_load(Path(path).read_text())
    entries = tuple(CatalogueEntry.model_validate(e) for e in data["challenges"])
    ids = [e.id for e in entries]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate challenge ids in catalogue")
    return entries


def load_catalogue(path: str | Path | None = None) -> tuple[CatalogueEntry, ...]:
    return _load(str(catalogue_path(path)))


def get_entry(challenge_id: str, path: str | Path | None = None) -> CatalogueEntry | None:
    return next((e for e in load_catalogue(path) if e.id == challenge_id), None)
