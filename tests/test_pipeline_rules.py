"""Each flaw rule fires on its injected flaw and nowhere else."""

from __future__ import annotations

from dataclasses import replace

import pytest

from speakquest.contracts import AnalysisResult, TakeAnalysis
from speakquest.errors import AnalysisError
from speakquest.pipeline import analyze_samples, prepare
from speakquest.rubric import load_rubric
from tests.synth import SCRIPT, SR, W, reference_words, render, with_changes

pytestmark = pytest.mark.slow
RUBRIC = load_rubric()


@pytest.fixture(scope="module")
def reference() -> TakeAnalysis:
    samples, transcript = render(reference_words())
    return prepare(samples, SR, transcript, SCRIPT, RUBRIC).analysis


def run(words: list[W], reference: TakeAnalysis) -> AnalysisResult:
    samples, transcript = render(words)
    return analyze_samples(
        analysis_id="a1",
        challenge_id="deadline",
        samples=samples,
        sr=SR,
        transcript=transcript,
        script_text=SCRIPT,
        reference=reference,
        rubric=RUBRIC,
        created_at="2026-10-15T00:00:00Z",
    )


def codes(result: AnalysisResult) -> list[str]:
    return [f.code for f in result.findings]


def participant() -> list[W]:
    """A second, different 'speaker': 8 % slower, higher voice, quieter."""
    return reference_words(rate=0.92, f_scale=1.45, amp=0.2)


def test_reference_measures_sanely(reference: TakeAnalysis) -> None:
    assert len(reference.words) == 19
    assert all(w.kind == "match" for w in reference.words)
    assert len(reference.phrases) == 2
    assert all((p.pitch_sd_st or 0) > 2 for p in reference.phrases)
    # The phrase break is a real pause; word boundaries inside phrases are not.
    assert [p.before_word for p in reference.pauses] == [8]
    assert 380 <= reference.pauses[0].ms <= 460


def test_clean_second_speaker_has_no_findings(reference: TakeAnalysis) -> None:
    result = run(participant(), reference)
    assert codes(result) == []
    assert result.scores.overall == 100
    assert result.take.rate_ratio_global == pytest.approx(0.92, abs=0.03)
    # Normalised per-word ratios hover around 1.
    ratios = [w.rate_ratio for w in result.take.words if w.rate_ratio is not None]
    assert ratios and all(0.85 < r < 1.15 for r in ratios)


def test_rush(reference: TakeAnalysis) -> None:
    words = participant()
    words = [replace(w, dur=w.dur * 0.5) if 3 <= i <= 7 else w for i, w in enumerate(words)]
    result = run(words, reference)
    assert codes(result) == ["RUSH"]
    f = result.findings[0]
    assert f.evidence["rate_ratio"] > 1.35
    assert f.script_span is not None and 2 <= f.script_span[0] <= 4 and 6 <= f.script_span[1] <= 8
    assert result.scores.pace < 100 and result.scores.pauses == 100


def test_drag(reference: TakeAnalysis) -> None:
    words = participant()
    words = [replace(w, dur=w.dur * 1.9) if 10 <= i <= 14 else w for i, w in enumerate(words)]
    result = run(words, reference)
    assert codes(result) == ["DRAG"]
    assert result.findings[0].evidence["rate_ratio"] < 0.7


def test_whole_take_rush_is_reported_once(reference: TakeAnalysis) -> None:
    words = [replace(w, dur=w.dur * 0.55, gap=w.gap * 0.55) for w in participant()]
    result = run(words, reference)
    whole = [f for f in result.findings if f.evidence.get("scope") == "whole take"]
    assert len(whole) == 1 and whole[0].code == "RUSH"


def test_hesitation(reference: TakeAnalysis) -> None:
    words = with_changes(participant(), [5], gap=1.1)
    result = run(words, reference)
    assert codes(result) == ["HESITATE"]
    f = result.findings[0]
    assert 1000 <= f.evidence["pause_ms"] <= 1200
    assert f.evidence["reference_pause_ms"] == 0
    assert f.words == ["build", "before"]
    assert f.severity == 2


def test_long_pause_at_a_phrase_break_is_not_a_hesitation(reference: TakeAnalysis) -> None:
    words = with_changes(participant(), [8], gap=0.9)
    assert codes(run(words, reference)) == []


def test_monotone(reference: TakeAnalysis) -> None:
    words = participant()
    words = [replace(w, f0=200.0, f1=200.0) if i >= 8 else w for i, w in enumerate(words)]
    result = run(words, reference)
    assert codes(result) == ["MONO"]
    f = result.findings[0]
    assert f.evidence["ratio"] < 0.2 and f.severity == 3
    assert f.script_span == (8, 18)


def test_fade(reference: TakeAnalysis) -> None:
    words = with_changes(participant(), [6, 7], amp=0.035)
    result = run(words, reference)
    assert codes(result) == ["FADE"]
    f = result.findings[0]
    assert f.words == ["the", "deadline"]
    assert f.evidence["drop_db"] >= 10


def test_skip(reference: TakeAnalysis) -> None:
    words = [w for i, w in enumerate(participant()) if i not in (3, 4)]
    result = run(words, reference)
    assert codes(result) == ["SKIP"]
    f = result.findings[0]
    assert f.words == ["final", "build"]
    assert f.evidence["skipped_words"] == 2
    assert result.scores.accuracy == 100 - RUBRIC.penalties["SKIP"][2]


def test_filler_word_and_repeat(reference: TakeAnalysis) -> None:
    words = participant()
    words = [*words[:5], W(text="um", dur=0.35, gap=0.08, f0=210), *words[5:]]
    words = [*words[:13], replace(words[13], gap=0.05), *words[13:]]  # repeat "a"
    result = run(words, reference)
    fillers = [f for f in result.findings if f.code == "FILLER"]
    assert [f.evidence["kind"] for f in fillers] == ["filler", "repeat"]
    assert fillers[0].words == ["um"]


def test_untranscribed_vocalisation_becomes_filler(reference: TakeAnalysis) -> None:
    words = participant()
    words = [
        *words[:5],
        W(text="um", dur=0.4, gap=0.15, f0=210, transcribe=False),
        replace(words[5], gap=0.15),
        *words[6:],
    ]
    result = run(words, reference)
    assert codes(result) == ["FILLER"]
    assert result.findings[0].evidence["kind"] == "vocalization"
    assert 350 <= result.findings[0].evidence["vocalization_ms"] <= 450


def test_combined_flaws_get_ordered_ids_and_attached_words(reference: TakeAnalysis) -> None:
    words = with_changes(participant(), [6, 7], amp=0.035)
    words = with_changes(words, [12], gap=1.0)
    words = [w for i, w in enumerate(words) if i != 16]
    result = run(words, reference)
    assert codes(result) == ["FADE", "HESITATE", "SKIP"]
    assert [f.id for f in result.findings] == ["f1", "f2", "f3"]
    tagged = {fid for w in result.take.words for fid in w.finding_ids}
    assert {"f1", "f2"} <= tagged


def test_identical_inputs_give_identical_results(reference: TakeAnalysis) -> None:
    words = with_changes(participant(), [6, 7], amp=0.035)
    a = run(words, reference).model_dump_json()
    b = run(words, reference).model_dump_json()
    assert a == b


def test_wrong_script_is_rejected(reference: TakeAnalysis) -> None:
    words = [W(text=t, dur=0.3) for t in "completely different words were read aloud here".split()]
    with pytest.raises(AnalysisError) as e:
        run(words, reference)
    assert e.value.code == "SCRIPT_MISMATCH"


def test_empty_transcript_is_no_speech(reference: TakeAnalysis) -> None:
    words = [W(text="x", dur=1.0, transcribe=False)]
    with pytest.raises(AnalysisError) as e:
        run(words, reference)
    assert e.value.code == "NO_SPEECH"
