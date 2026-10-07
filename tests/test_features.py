from __future__ import annotations

import numpy as np
import pytest

from speakquest.contracts import Pause, WordMeasure
from speakquest.features import _longest_run, articulation_time, build_tracks, robust_sd
from speakquest.rubric import load_rubric
from tests.audio_helpers import silence, tone

CFG = load_rubric().features


def _w(i: int, start: float, end: float) -> WordMeasure:
    return WordMeasure(
        index=i, text="w", norm="w", start=start, end=end, kind="match", script_index=i, syllables=1
    )


def test_longest_run() -> None:
    assert _longest_run(np.array([0, 1, 1, 0, 1, 1, 1, 0], dtype=bool)) == (4, 3)
    assert _longest_run(np.array([0, 0], dtype=bool)) == (0, 0)
    assert _longest_run(np.array([1, 1], dtype=bool)) == (0, 2)


def test_robust_sd_ignores_octave_errors() -> None:
    rng = np.random.default_rng(0)
    values = rng.normal(0, 2, 400)
    spiked = np.concatenate([values, np.full(8, 12.0)])
    assert robust_sd(spiked) == pytest.approx(robust_sd(values), rel=0.15)
    assert robust_sd(np.array([1.0])) == 0.0


def test_articulation_time_subtracts_pauses_and_insertions() -> None:
    words = [_w(0, 0.0, 0.5), _w(1, 1.5, 2.0)]
    pauses = [Pause(start=0.5, end=1.2, ms=700, before_word=1)]
    filler = WordMeasure(
        index=9, text="um", norm="um", start=1.2, end=1.5, kind="filler", syllables=1
    )
    assert articulation_time(words, pauses) == pytest.approx(1.3)
    assert articulation_time(words, pauses, [filler]) == pytest.approx(1.0)
    assert articulation_time([], pauses) == 0.0


@pytest.mark.slow
def test_tracks_mark_silence_and_voicing() -> None:
    sig = np.concatenate([silence(0.5), tone(1.0, f0=200), silence(0.5)])
    tracks = build_tracks(sig, 16000, CFG)
    assert tracks.silent[:20].all() and not tracks.silent[30:70].any()
    voiced = tracks.voiced_in(0.6, 1.4)
    assert np.median(voiced) == pytest.approx(200, rel=0.03)
    assert tracks.voiced_in(0.0, 0.4).size == 0
