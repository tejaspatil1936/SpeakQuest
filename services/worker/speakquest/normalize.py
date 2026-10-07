"""Audio intake: probe, convert to 16 kHz mono WAV, sanity-check.

This is the ``Normalize`` workflow state. Browsers upload webm/opus
(Chrome, Firefox) or mp4/aac (Safari); everything downstream sees one
format. The original upload is never modified.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt

from speakquest.errors import AnalysisError
from speakquest.rubric import AudioLimits

FloatArray = npt.NDArray[np.float32]

FFMPEG_TIMEOUT_S = 90
_DB_FLOOR = -120.0


def _binary(name: str) -> str:
    override = os.environ.get(f"SPEAKQUEST_{name.upper()}")
    if override:
        return override
    for candidate in (f"/opt/bin/{name}", shutil.which(name)):
        if candidate and Path(candidate).exists():
            return candidate
    raise AnalysisError("INTERNAL", f"{name} binary not found", stage="NORMALIZE")


@dataclass(frozen=True)
class ProbeInfo:
    format_name: str
    codec: str
    channels: int
    sample_rate: int
    duration_s: float | None


@dataclass(frozen=True)
class NormalizedAudio:
    path: Path
    sample_rate: int
    duration_s: float
    peak_dbfs: float
    speech_dbfs: float
    clipped_ratio: float

    def to_dict(self) -> dict[str, float | int | str]:
        return {
            "path": str(self.path),
            "sample_rate": self.sample_rate,
            "duration_s": round(self.duration_s, 3),
            "peak_dbfs": round(self.peak_dbfs, 2),
            "speech_dbfs": round(self.speech_dbfs, 2),
            "clipped_ratio": round(self.clipped_ratio, 5),
        }


def probe(path: Path) -> ProbeInfo:
    if not path.is_file() or path.stat().st_size == 0:
        raise AnalysisError("AUDIO_MISSING", f"{path.name} is missing or empty", stage="NORMALIZE")
    cmd = [
        _binary("ffprobe"),
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=FFMPEG_TIMEOUT_S, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise AnalysisError("AUDIO_CORRUPT", "ffprobe timed out", stage="NORMALIZE") from exc
    if proc.returncode != 0:
        raise AnalysisError(
            "AUDIO_UNSUPPORTED", proc.stderr.strip()[:300] or "ffprobe failed", stage="NORMALIZE"
        )
    info = json.loads(proc.stdout or "{}")
    audio = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
    if not audio:
        raise AnalysisError("AUDIO_UNSUPPORTED", "no audio stream", stage="NORMALIZE")
    stream = audio[0]
    raw_duration = stream.get("duration") or info.get("format", {}).get("duration")
    try:
        duration = float(raw_duration) if raw_duration not in (None, "N/A") else None
    except ValueError:
        duration = None
    return ProbeInfo(
        format_name=str(info.get("format", {}).get("format_name", "")),
        codec=str(stream.get("codec_name", "")),
        channels=int(stream.get("channels") or 0),
        sample_rate=int(stream.get("sample_rate") or 0),
        duration_s=duration,
    )


def load_wav(path: Path) -> tuple[FloatArray, int]:
    """Read a 16-bit PCM mono WAV into float32 samples in [-1, 1]."""
    with wave.open(str(path), "rb") as wf:
        if wf.getsampwidth() != 2:
            raise AnalysisError("AUDIO_UNSUPPORTED", "expected 16-bit PCM", stage="NORMALIZE")
        sr = wf.getframerate()
        channels = wf.getnchannels()
        raw = wf.readframes(wf.getnframes())
    pcm = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        pcm = pcm.reshape(-1, channels).mean(axis=1).astype(np.float32)
    return pcm, sr


def dbfs(value: float) -> float:
    return 20.0 * math.log10(value) if value > 0 else _DB_FLOOR


def frame_rms(samples: FloatArray, sr: int, frame_ms: int) -> FloatArray:
    """Non-overlapping RMS frames; the last partial frame is dropped."""
    hop = max(1, int(sr * frame_ms / 1000))
    n = len(samples) // hop
    if n == 0:
        return np.zeros(0, dtype=np.float32)
    frames = samples[: n * hop].reshape(n, hop).astype(np.float64)
    return np.sqrt(np.mean(frames * frames, axis=1)).astype(np.float32)


def speech_level_dbfs(samples: FloatArray, sr: int, frame_ms: int = 20) -> float:
    """Mean level of the loudest 30 % of frames — a robust 'how loud is the voice'."""
    rms = frame_rms(samples, sr, frame_ms)
    if rms.size == 0:
        return _DB_FLOOR
    top = np.sort(rms)[int(rms.size * 0.7) :]
    return dbfs(float(np.sqrt(np.mean(top.astype(np.float64) ** 2))))


def convert(src: Path, dst: Path, sample_rate: int) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        _binary("ffmpeg"),
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(src),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-sample_fmt",
        "s16",
        "-f",
        "wav",
        str(dst),
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=FFMPEG_TIMEOUT_S, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise AnalysisError("AUDIO_CORRUPT", "ffmpeg timed out", stage="NORMALIZE") from exc
    if proc.returncode != 0 or not dst.is_file():
        raise AnalysisError(
            "AUDIO_CORRUPT", proc.stderr.strip()[:300] or "ffmpeg failed", stage="NORMALIZE"
        )


def normalize(src: Path, dst: Path, limits: AudioLimits) -> NormalizedAudio:
    """Validate an upload and write the canonical 16 kHz mono WAV to ``dst``."""
    size = src.stat().st_size if src.is_file() else 0
    if size > limits.max_bytes:
        raise AnalysisError("AUDIO_TOO_LARGE", f"{size} bytes", stage="NORMALIZE")
    info = probe(src)
    # Container durations can be missing (MediaRecorder webm) or wrong, so this
    # is only a cheap early reject; the decoded length below is authoritative.
    if info.duration_s is not None and info.duration_s > limits.max_duration_s * 1.05:
        raise AnalysisError("AUDIO_TOO_LONG", f"{info.duration_s:.1f}s", stage="NORMALIZE")

    convert(src, dst, limits.sample_rate)
    samples, sr = load_wav(dst)
    duration = len(samples) / sr if sr else 0.0
    if duration < limits.min_duration_s:
        raise AnalysisError("AUDIO_TOO_SHORT", f"{duration:.2f}s", stage="NORMALIZE")
    if duration > limits.max_duration_s:
        raise AnalysisError("AUDIO_TOO_LONG", f"{duration:.1f}s", stage="NORMALIZE")

    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    peak_db = dbfs(peak)
    if peak_db < limits.silent_peak_dbfs:
        raise AnalysisError("AUDIO_SILENT", f"peak {peak_db:.1f} dBFS", stage="NORMALIZE")
    speech_db = speech_level_dbfs(samples, sr)
    if speech_db < limits.quiet_mean_dbfs:
        raise AnalysisError(
            "AUDIO_TOO_QUIET", f"speech level {speech_db:.1f} dBFS", stage="NORMALIZE"
        )
    clipped = float(np.mean(np.abs(samples) >= 0.999)) if samples.size else 0.0
    return NormalizedAudio(
        path=dst,
        sample_rate=sr,
        duration_s=duration,
        peak_dbfs=peak_db,
        speech_dbfs=speech_db,
        clipped_ratio=clipped,
    )
