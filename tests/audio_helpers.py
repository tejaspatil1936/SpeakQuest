"""Deterministic synthetic audio for tests (no recordings in the repo)."""

from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import numpy as np


def tone(
    seconds: float,
    sr: int = 16000,
    f0: float = 140.0,
    amp: float = 0.3,
    vibrato_st: float = 0.0,
    seed: int = 0,
) -> np.ndarray:
    """A voiced-speech stand-in: harmonic stack with optional pitch movement."""
    n = int(seconds * sr)
    t = np.arange(n) / sr
    f = f0 * 2 ** ((vibrato_st * np.sin(2 * np.pi * 1.5 * t)) / 12)
    phase = 2 * np.pi * np.cumsum(f) / sr
    sig = sum((0.6**k) * np.sin((k + 1) * phase) for k in range(5))
    rng = np.random.default_rng(seed)
    sig = sig / np.max(np.abs(sig)) * amp + rng.normal(0, 1e-4, n)
    return sig.astype(np.float32)


def silence(seconds: float, sr: int = 16000) -> np.ndarray:
    return np.zeros(int(seconds * sr), dtype=np.float32)


def write_wav(path: Path, samples: np.ndarray, sr: int = 16000) -> Path:
    pcm = np.clip(samples, -1, 1)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes((pcm * 32767).astype("<i2").tobytes())
    return path


def transcode(src: Path, dst: Path, *args: str) -> Path:
    subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(src), *args, str(dst)],
        check=True,
        timeout=60,
    )
    return dst
