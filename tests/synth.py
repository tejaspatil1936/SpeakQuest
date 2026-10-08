"""Build synthetic 'recordings' with exact word timings for rule tests.

Each word is a harmonic tone (a voiced-speech stand-in) whose duration,
level and pitch glide are set explicitly, so every flaw can be injected
with a known magnitude at a known place.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from speakquest.contracts import TimedWord, Transcript
from speakquest.tokens import syllables, tokenize_script

SR = 16000
SCRIPT = (
    "We ship the final build before the deadline, "
    "then we rest for a while and celebrate the launch together."
)


@dataclass(frozen=True)
class W:
    text: str
    dur: float
    gap: float = 0.04  # silence *before* the word
    amp: float = 0.3
    f0: float = 150.0
    f1: float | None = None
    transcribe: bool = True  # False: audible but missing from the transcript


def _tone(dur: float, f0: float, f1: float, amp: float) -> np.ndarray:
    n = int(dur * SR)
    f = np.linspace(f0, f1, n)
    phase = 2 * np.pi * np.cumsum(f) / SR
    sig = sum((0.55**k) * np.sin((k + 1) * phase) for k in range(6))
    env = np.ones(n)
    ramp = min(int(0.015 * SR), n // 4)
    if ramp:
        env[:ramp] = np.linspace(0, 1, ramp)
        env[-ramp:] = np.linspace(1, 0, ramp)
    return (sig / np.max(np.abs(sig)) * amp * env).astype(np.float32)


def render(
    words: list[W], lead: float = 0.4, tail: float = 0.4, language: str = "en-US"
) -> tuple[np.ndarray, Transcript]:
    rng = np.random.default_rng(7)
    parts = [np.zeros(int(lead * SR), dtype=np.float32)]
    t = lead
    timed: list[TimedWord] = []
    for i, w in enumerate(words):
        gap = 0.0 if i == 0 else w.gap
        parts.append(np.zeros(int(gap * SR), dtype=np.float32))
        t += int(gap * SR) / SR
        tone = _tone(w.dur, w.f0, w.f1 if w.f1 is not None else w.f0, w.amp)
        parts.append(tone)
        if w.transcribe:
            timed.append(
                TimedWord(
                    text=w.text,
                    start=round(t, 3),
                    end=round(t + len(tone) / SR, 3),
                    confidence=0.99,
                )
            )
        t += len(tone) / SR
    parts.append(np.zeros(int(tail * SR), dtype=np.float32))
    samples = np.concatenate(parts)
    samples = samples + rng.normal(0, 3e-4, samples.size).astype(np.float32)
    return samples, Transcript(aligner="synthetic", language=language, words=timed)


def reference_words(rate: float = 1.0, f_scale: float = 1.0, amp: float = 0.3) -> list[W]:
    """A clean, expressive reading: rising-falling contour inside each phrase."""
    info = tokenize_script(SCRIPT)
    out: list[W] = []
    by_phrase: dict[int, int] = {}
    for tok in info.tokens:
        pos = by_phrase.get(tok.phrase, 0)
        by_phrase[tok.phrase] = pos + 1
        # Zig-zag contour: ~ +/- 4 semitones around the speaker's centre.
        base = 150 * f_scale * 2 ** ((4 if pos % 2 == 0 else -3) / 12 - pos * 0.15 / 12)
        first_in_phrase = pos == 0 and tok.phrase > 0
        out.append(
            W(
                text=tok.norm,
                dur=round(0.19 * syllables(tok.norm) / rate, 3),
                gap=0.42 if first_in_phrase else 0.04,
                amp=amp,
                f0=base,
                f1=base * 1.04,
            )
        )
    return out


def with_changes(words: list[W], idx: range | list[int], **changes: float | bool) -> list[W]:
    s = set(idx)
    return [replace(w, **changes) if i in s else w for i, w in enumerate(words)]  # type: ignore[arg-type]
