"""Versioned rubric: loading, severity banding and deterministic scoring.

The rubric YAML is the only place thresholds and penalty weights live. The
scorer is pure arithmetic over findings, so the same findings and rubric
version always produce the same scores (system design §5.4).
"""

from __future__ import annotations

import hashlib
import os
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from speakquest.contracts import (
    DIMENSIONS,
    FLAW_CODES,
    Dimension,
    Finding,
    FlawCode,
    Penalty,
    Scores,
)

_REPO_RUBRIC = Path(__file__).resolve().parents[3] / "rubric" / "v1.yaml"


class FeatureConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rate_window_words: int = Field(ge=1)
    global_rate_normalization: tuple[float, float]
    min_pause_ms: int = Field(ge=0)
    frame_ms: int = Field(ge=5, le=100)
    silence_rel_db: float = Field(lt=0)
    pitch_floor_hz: float = Field(gt=0)
    pitch_ceiling_hz: float = Field(gt=0)
    vocalization_min_ms: int = Field(ge=0)
    vocalization_max_ms: int = Field(ge=0)
    vocalization_min_voiced_ratio: float = Field(ge=0, le=1)


class AudioLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min_duration_s: float
    max_duration_s: float
    max_bytes: int
    silent_peak_dbfs: float
    quiet_mean_dbfs: float
    sample_rate: int
    min_script_coverage: float = Field(ge=0, le=1)


class Rubric(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    features: FeatureConfig
    rules: dict[FlawCode, dict[str, Any]]
    dimensions: dict[FlawCode, Dimension]
    penalties: dict[FlawCode, dict[int, float]]
    overall_weights: dict[Dimension, float]
    audio: AudioLimits
    digest: str = ""

    @model_validator(mode="after")
    def _complete(self) -> Rubric:
        for name, table in (
            ("rules", self.rules),
            ("dimensions", self.dimensions),
            ("penalties", self.penalties),
        ):
            missing = set(FLAW_CODES) - set(table)
            if missing:
                raise ValueError(f"rubric {name} missing codes: {sorted(missing)}")
        for code, severities in self.penalties.items():
            if set(severities) != {1, 2, 3}:
                raise ValueError(f"penalties for {code} must define severities 1, 2 and 3")
        if set(self.overall_weights) != set(DIMENSIONS):
            raise ValueError("overall_weights must cover every dimension")
        if sum(self.overall_weights.values()) <= 0:
            raise ValueError("overall_weights must sum to a positive number")
        for code, rule in self.rules.items():
            bands = rule.get("severity_bands")
            if not isinstance(bands, list) or len(bands) != 3:
                raise ValueError(f"rule {code} needs exactly three severity_bands")
        return self

    def rule(self, code: FlawCode) -> dict[str, Any]:
        return self.rules[code]

    def severity(
        self, code: FlawCode, magnitude: float, direction: Literal["above", "below"] = "above"
    ) -> int:
        """Map a measured magnitude onto severity 1–3 using the rule's bands.

        ``above``: magnitude ≥ band[i] → severity i+1 (bigger is worse).
        ``below``: magnitude ≤ band[i] → severity i+1 (smaller is worse).
        The first band is the detection threshold, so any finding is at least 1.
        """
        bands = [float(b) for b in self.rules[code]["severity_bands"]]
        level = 1
        for i, band in enumerate(bands):
            hit = magnitude >= band if direction == "above" else magnitude <= band
            if hit:
                level = i + 1
        return level


def resolve_rubric_path(path: str | Path | None = None) -> Path:
    candidate = Path(path or os.environ.get("SPEAKQUEST_RUBRIC") or _REPO_RUBRIC)
    if not candidate.is_file():
        raise FileNotFoundError(f"rubric not found at {candidate}")
    return candidate


@lru_cache(maxsize=8)
def _load_cached(path: str) -> Rubric:
    raw = Path(path).read_bytes()
    data = yaml.safe_load(raw)
    rubric = Rubric.model_validate(data)
    rubric.digest = hashlib.sha256(raw).hexdigest()[:12]
    return rubric


def load_rubric(path: str | Path | None = None) -> Rubric:
    return _load_cached(str(resolve_rubric_path(path)))


def _round_half_up(value: float) -> int:
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def score(findings: list[Finding], rubric: Rubric) -> tuple[Scores, list[Penalty]]:
    """Score = 100 − Σ severity-weighted penalties per dimension, floored at 0."""
    deductions: dict[Dimension, float] = dict.fromkeys(DIMENSIONS, 0.0)
    penalties: list[Penalty] = []
    for finding in sorted(findings, key=lambda f: (f.start, f.id)):
        dimension = rubric.dimensions[finding.code]
        points = float(rubric.penalties[finding.code][finding.severity])
        deductions[dimension] += points
        penalties.append(Penalty(finding_id=finding.id, dimension=dimension, points=points))

    per_dim = {d: max(0, _round_half_up(100 - deductions[d])) for d in DIMENSIONS}
    total_weight = sum(rubric.overall_weights.values())
    weighted = sum(per_dim[d] * rubric.overall_weights[d] for d in DIMENSIONS) / total_weight
    return Scores(**per_dim, overall=_round_half_up(weighted)), penalties
