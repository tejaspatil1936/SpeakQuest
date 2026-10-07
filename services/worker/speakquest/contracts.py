"""Data contracts shared by the worker, the API and the frontend.

These Pydantic models are the single source of truth. ``make contracts``
exports them as JSON Schema into ``contracts/`` and the web app derives its
Zod validators from that output, so a field renamed here fails the frontend
type-check instead of failing silently at runtime.

Naming: API envelopes use camelCase (they are request/response bodies the
browser builds by hand); the persisted analysis document uses snake_case,
matching the finding shape in the system design.

This module must not import numpy/scipy — it ships inside the API Lambda zip.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION: Literal["1"] = "1"

FlawCode = Literal["RUSH", "DRAG", "HESITATE", "MONO", "FADE", "SKIP", "FILLER"]
FLAW_CODES: tuple[FlawCode, ...] = ("RUSH", "DRAG", "HESITATE", "MONO", "FADE", "SKIP", "FILLER")

Dimension = Literal["pace", "pauses", "pitch", "volume", "accuracy"]
DIMENSIONS: tuple[Dimension, ...] = ("pace", "pauses", "pitch", "volume", "accuracy")

AnalysisStatus = Literal["QUEUED", "RUNNING", "DONE", "FAILED"]
Stage = Literal["QUEUED", "NORMALIZE", "TRANSCRIBE", "ANALYZE", "EXPLAIN", "PERSIST", "DONE"]

AlignOpKind = Literal["match", "sub", "ins", "del"]
WordKind = Literal["match", "sub", "filler", "repeat", "insert"]

Seconds = Annotated[float, Field(ge=0)]
EvidenceValue = float | int | str


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False)


# --------------------------------------------------------------------------- ASR


class TimedWord(_Model):
    """One recognised word with its time span, as produced by any aligner."""

    text: str
    start: Seconds
    end: Seconds
    confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def _ordered(self) -> TimedWord:
        if self.end < self.start:
            raise ValueError(f"word '{self.text}' ends before it starts")
        return self


class Transcript(_Model):
    """Aligner-independent transcript: the pipeline never sees vendor JSON."""

    aligner: str
    language: str
    words: list[TimedWord]


# --------------------------------------------------------------------------- script


class ScriptToken(_Model):
    index: int = Field(ge=0)
    norm: str
    display: str
    phrase: int = Field(ge=0)


class ScriptInfo(_Model):
    text: str
    tokens: list[ScriptToken]
    phrase_count: int = Field(ge=0)


class AlignOp(_Model):
    op: AlignOpKind
    script_index: int | None = None
    take_index: int | None = None


# --------------------------------------------------------------------------- measurements


class WordMeasure(_Model):
    """Per-word measurements; the kinetic transcript is rendered from these."""

    index: int = Field(ge=0)
    text: str
    norm: str
    start: Seconds
    end: Seconds
    kind: WordKind
    script_index: int | None = None
    syllables: int = Field(ge=0)
    rate_ratio: float | None = Field(
        default=None, description="Local speech rate / reference rate, after global normalisation"
    )
    loudness_db: float | None = Field(default=None, description="dB relative to speaker mean")
    pitch_st: float | None = Field(default=None, description="Semitones from speaker median F0")
    pause_before_ms: int = Field(default=0, ge=0)
    finding_ids: list[str] = Field(default_factory=list)


class Pause(_Model):
    start: Seconds
    end: Seconds
    ms: int = Field(ge=0)
    before_word: int = Field(ge=0, description="Index of the word that follows the pause")


class Vocalization(_Model):
    """Voiced sound inside a gap that the aligner did not transcribe (likely 'um')."""

    start: Seconds
    end: Seconds
    ms: int = Field(ge=0)


class PhraseStat(_Model):
    phrase: int = Field(ge=0)
    start: Seconds
    end: Seconds
    pitch_sd_st: float | None = None
    voiced_frames: int = Field(default=0, ge=0)


class TakeAnalysis(_Model):
    duration_s: Seconds
    words: list[WordMeasure]
    pauses: list[Pause]
    phrases: list[PhraseStat]
    vocalizations: list[Vocalization] = Field(default_factory=list)
    syllables_per_s: float = Field(ge=0)
    rate_ratio_global: float | None = Field(
        default=None, description="This take's global rate divided by the reference's"
    )
    pitch_median_hz: float | None = None
    loudness_mean_db: float | None = Field(default=None, description="Absolute dBFS mean")


# --------------------------------------------------------------------------- findings & scores


class Finding(_Model):
    id: str = Field(pattern=r"^f\d+$")
    code: FlawCode
    dimension: Dimension
    start: Seconds
    end: Seconds
    words: list[str]
    evidence: dict[str, EvidenceValue]
    severity: int = Field(ge=1, le=3)
    rubric_version: str
    script_span: tuple[int, int] | None = None

    @model_validator(mode="after")
    def _ordered(self) -> Finding:
        if self.end < self.start:
            raise ValueError(f"finding {self.id} ends before it starts")
        return self


class Scores(_Model):
    pace: int = Field(ge=0, le=100)
    pauses: int = Field(ge=0, le=100)
    pitch: int = Field(ge=0, le=100)
    volume: int = Field(ge=0, le=100)
    accuracy: int = Field(ge=0, le=100)
    overall: int = Field(ge=0, le=100)


class Penalty(_Model):
    finding_id: str
    dimension: Dimension
    points: float = Field(ge=0)


# --------------------------------------------------------------------------- coaching


class CoachingItem(_Model):
    finding_id: str
    headline: str = Field(min_length=1, max_length=160)
    why: str = Field(min_length=1, max_length=600)
    drill: str = Field(min_length=1, max_length=600)


class CoachingOutput(_Model):
    """The exact shape the language model must return (system design §6)."""

    items: list[CoachingItem]


class Coaching(_Model):
    source: Literal["bedrock", "template"]
    model_id: str | None = None
    items: list[CoachingItem]
    attempts: int = Field(ge=0)
    rejections: list[str] = Field(
        default_factory=list, description="Validator messages from rejected model outputs"
    )


# --------------------------------------------------------------------------- result document


class Versions(_Model):
    rubric_version: str
    worker_image_digest: str
    transcribe_language: str
    aligner: str
    model_id: str | None = None


class AnalysisResult(_Model):
    """``results/<analysisId>/result.json`` — everything the playback screen renders."""

    schema_version: Literal["1"] = SCHEMA_VERSION
    analysis_id: str
    challenge_id: str
    created_at: str
    versions: Versions
    script: ScriptInfo
    take: TakeAnalysis
    reference: TakeAnalysis
    alignment: list[AlignOp]
    findings: list[Finding]
    penalties: list[Penalty]
    scores: Scores
    coaching: Coaching | None = None
    warnings: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- API envelopes


class Challenge(_Model):
    id: str = Field(pattern=r"^[a-z0-9-]{3,48}$")
    title: str
    script: str
    difficulty: Literal[1, 2, 3]
    flaw_targets: list[FlawCode]
    language: str = "en-US"
    cue: str = Field(description="One-line director's note shown on the cue card")
    reference_duration_s: float | None = None
    reference_audio_url: str | None = None
    reference_ready: bool = False


class ChallengeList(_Model):
    challenges: list[Challenge]


ALLOWED_CONTENT_TYPES: tuple[str, ...] = (
    "audio/webm",
    "audio/ogg",
    "audio/mp4",
    "audio/mpeg",
    "audio/wav",
    "audio/x-wav",
)
CONTENT_TYPE_EXTENSIONS: dict[str, str] = {
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/mp4": "m4a",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
}


def base_content_type(content_type: str) -> str:
    """``audio/webm;codecs=opus`` → ``audio/webm``."""
    return content_type.split(";", 1)[0].strip().lower()


class CreateUploadRequest(_Model):
    challengeId: str = Field(pattern=r"^[a-z0-9-]{3,48}$")  # noqa: N815 - wire format
    contentType: str  # noqa: N815
    bytes: int = Field(gt=0)

    @field_validator("contentType")
    @classmethod
    def _content_type(cls, v: str) -> str:
        if base_content_type(v) not in ALLOWED_CONTENT_TYPES:
            raise ValueError(f"unsupported content type '{v}'")
        return v


class CreateUploadResponse(_Model):
    uploadUrl: str  # noqa: N815
    key: str
    method: Literal["PUT"] = "PUT"
    headers: dict[str, str]
    expiresIn: int  # noqa: N815


class CreateAnalysisRequest(_Model):
    challengeId: str = Field(pattern=r"^[a-z0-9-]{3,48}$")  # noqa: N815
    key: str = Field(min_length=1, max_length=256)
    durationS: float | None = Field(default=None, ge=0)  # noqa: N815 - client-side hint only


class CreateAnalysisResponse(_Model):
    analysisId: str  # noqa: N815


class ErrorInfo(_Model):
    code: str
    message: str
    stage: str | None = None


class AnalysisSummary(_Model):
    scores: Scores
    findingCount: int  # noqa: N815
    codes: list[FlawCode]


class AnalysisStatusResponse(_Model):
    analysisId: str  # noqa: N815
    challengeId: str  # noqa: N815
    status: AnalysisStatus
    stage: Stage
    createdAt: str  # noqa: N815
    updatedAt: str  # noqa: N815
    summary: AnalysisSummary | None = None
    error: ErrorInfo | None = None


class AnalysisResultResponse(_Model):
    resultUrl: str  # noqa: N815
    audioUrl: str  # noqa: N815
    referenceAudioUrl: str | None = None  # noqa: N815
    expiresIn: int  # noqa: N815


class Level(_Model):
    index: int = Field(ge=0)
    name: str
    floor_s: int = Field(ge=0)
    next_name: str | None = None
    next_at_s: int | None = None


class Badge(_Model):
    id: str
    label: str
    awarded_at: str
    analysis_id: str | None = None


class TakeSummary(_Model):
    analysisId: str  # noqa: N815
    challengeId: str  # noqa: N815
    createdAt: str  # noqa: N815
    status: AnalysisStatus
    durationS: float | None = None  # noqa: N815
    scores: Scores | None = None
    codes: list[FlawCode] = Field(default_factory=list)


class ProgressResponse(_Model):
    xp: int = Field(ge=0, description="Air time in seconds of successfully analysed takes")
    level: Level
    badges: list[Badge]
    takes: list[TakeSummary]


class ErrorResponse(_Model):
    error: ErrorInfo
