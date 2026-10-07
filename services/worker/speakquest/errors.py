"""Error codes surfaced to the user when an analysis cannot complete.

Every failure that reaches DynamoDB carries one of these codes plus the
workflow stage, so the playback screen can say *why* a take failed instead of
showing a generic error. ``retryable`` tells the UI whether re-uploading the
same take could succeed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class ErrorSpec:
    message: str
    retryable: bool


ERRORS: Final[dict[str, ErrorSpec]] = {
    # Input / audio validation (Normalize stage)
    "AUDIO_MISSING": ErrorSpec("The upload never arrived. Record the take again.", True),
    "AUDIO_UNSUPPORTED": ErrorSpec("That file is not an audio format we can read.", False),
    "AUDIO_CORRUPT": ErrorSpec("The recording is damaged and could not be decoded.", True),
    "AUDIO_TOO_SHORT": ErrorSpec("The take is too short to analyse. Read the whole script.", True),
    "AUDIO_TOO_LONG": ErrorSpec("Takes are capped at 3 minutes.", True),
    "AUDIO_TOO_LARGE": ErrorSpec("Uploads are capped at 10 MB.", True),
    "AUDIO_SILENT": ErrorSpec("The recording is silent. Check your microphone.", True),
    "AUDIO_TOO_QUIET": ErrorSpec("The recording is too quiet to measure. Move closer.", True),
    # Transcription
    "TRANSCRIBE_FAILED": ErrorSpec("Speech recognition failed for this take.", True),
    "TRANSCRIBE_TIMEOUT": ErrorSpec("Speech recognition took too long.", True),
    "NO_SPEECH": ErrorSpec("No words were recognised in the take.", True),
    # Analysis
    "SCRIPT_MISMATCH": ErrorSpec("The take does not match the script on the cue card.", True),
    "REFERENCE_MISSING": ErrorSpec("This challenge has no analysed reference yet.", False),
    # Infrastructure
    "TIMEOUT": ErrorSpec("The analysis ran out of time.", True),
    "INTERNAL": ErrorSpec("Something went wrong on our side.", True),
}


class AnalysisError(Exception):
    """A failure with a stable, user-facing code."""

    def __init__(self, code: str, detail: str | None = None, *, stage: str | None = None):
        if code not in ERRORS:
            raise ValueError(f"unknown error code {code!r}")
        self.code = code
        self.stage = stage
        self.detail = detail
        super().__init__(f"{code}: {detail or ERRORS[code].message}")

    @property
    def message(self) -> str:
        return ERRORS[self.code].message

    @property
    def retryable(self) -> bool:
        return ERRORS[self.code].retryable

    def to_dict(self) -> dict[str, str | bool | None]:
        return {
            "code": self.code,
            "message": self.message,
            "detail": self.detail,
            "stage": self.stage,
            "retryable": self.retryable,
        }
