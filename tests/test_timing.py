from __future__ import annotations

import json
from pathlib import Path

import pytest

from speakquest.contracts import TimedWord, Transcript
from speakquest.errors import AnalysisError
from speakquest.timing import (
    TranscribeFileAligner,
    WordsFileAligner,
    get_aligner,
    parse_transcribe_json,
    spoken_tokens,
)

FIXTURE = Path(__file__).parent / "fixtures" / "transcribe_sample.json"


def test_parse_transcribe_drops_punctuation_and_keeps_fillers() -> None:
    t = parse_transcribe_json(json.loads(FIXTURE.read_text()))
    assert [w.text for w in t.words] == ["Before", "the", "um", "deadline", "in", "2026"]
    assert t.words[2].start == 0.90
    assert t.words[2].confidence == pytest.approx(0.87)
    assert t.aligner == "amazon-transcribe"


def test_failed_or_malformed_transcribe_documents() -> None:
    with pytest.raises(AnalysisError) as e:
        parse_transcribe_json({"status": "FAILED", "results": {}})
    assert e.value.code == "TRANSCRIBE_FAILED"
    with pytest.raises(AnalysisError):
        parse_transcribe_json({"results": None})


def test_spoken_tokens_expand_numbers_evenly() -> None:
    toks = spoken_tokens(parse_transcribe_json(json.loads(FIXTURE.read_text())))
    assert [t.norm for t in toks][-3:] == ["twenty", "twenty", "six"]
    assert toks[-3].start == 2.05 and toks[-1].end == 2.95
    assert toks[-2].start == pytest.approx(2.35)
    assert {t.source_word for t in toks[-3:]} == {5}


def test_spoken_tokens_clamp_overlaps() -> None:
    t = Transcript(
        aligner="x",
        language="en-US",
        words=[
            TimedWord(text="a", start=0.0, end=0.5),
            TimedWord(text="b", start=0.4, end=0.8),
        ],
    )
    toks = spoken_tokens(t)
    assert toks[1].start == 0.5


def test_file_aligners_round_trip(tmp_path: Path) -> None:
    t = TranscribeFileAligner(FIXTURE).transcribe(Path("unused.wav"), "en-US")
    words = tmp_path / "words.json"
    words.write_text(t.model_dump_json())
    assert WordsFileAligner(words).transcribe(Path("x"), "en-US") == t
    assert get_aligner("words-file", words_path=words).name == "words-file"
    with pytest.raises(ValueError):
        get_aligner("nope")
