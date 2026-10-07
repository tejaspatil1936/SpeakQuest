from __future__ import annotations

import pytest

from speakquest.tokens import cardinal, normalize_word, normalize_words, syllables, tokenize_script


@pytest.mark.parametrize(
    ("n", "words"),
    [
        (0, "zero"),
        (7, "seven"),
        (13, "thirteen"),
        (40, "forty"),
        (42, "forty two"),
        (100, "one hundred"),
        (305, "three hundred five"),
        (1204, "one thousand two hundred four"),
        (2_500_000, "two million five hundred thousand"),
    ],
)
def test_cardinal(n: int, words: str) -> None:
    assert " ".join(cardinal(n)) == words


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Deadline,", ["deadline"]),
        ("don't", ["dont"]),
        ("well-known", ["well", "known"]),
        ("2026", ["twenty", "twenty", "six"]),
        ("1999", ["nineteen", "ninety", "nine"]),
        ("2005", ["two", "thousand", "five"]),
        ("1905", ["nineteen", "oh", "five"]),
        ("1990s", ["nineteen", "nineties"]),
        ("3rd", ["third"]),
        ("21st", ["twenty", "first"]),
        ("12th", ["twelfth"]),
        ("40%", ["forty", "percent"]),
        ("$5", ["five", "dollars"]),
        ("$1", ["one", "dollar"]),
        ("3.5", ["three", "point", "five"]),
        ("10,000", ["ten", "thousand"]),
        ("café", ["cafe"]),
        ("—", []),
    ],
)
def test_normalize_word(raw: str, expected: list[str]) -> None:
    assert normalize_word(raw) == expected


def test_script_and_asr_meet_in_same_vocabulary() -> None:
    assert normalize_words("Meet me at 3 p.m.") == normalize_words("meet me at three P M")


def test_tokenize_script_phrases_and_display() -> None:
    info = tokenize_script("Before the deadline, we ship. In 2026 we grow!")
    norms = [t.norm for t in info.tokens]
    assert norms == [
        "before",
        "the",
        "deadline",
        "we",
        "ship",
        "in",
        "twenty",
        "twenty",
        "six",
        "we",
        "grow",
    ]
    assert [t.phrase for t in info.tokens] == [0, 0, 0, 1, 1, 2, 2, 2, 2, 2, 2]
    assert info.phrase_count == 3
    assert info.tokens[2].display == "deadline"
    assert {t.display for t in info.tokens if t.norm == "twenty"} == {"2026"}
    assert [t.index for t in info.tokens] == list(range(len(info.tokens)))


def test_tokenize_keeps_decimals_and_thousands_in_one_phrase() -> None:
    info = tokenize_script("Costs rose 3.5 percent to $1,000 overall.")
    assert info.phrase_count == 1


def test_line_breaks_and_dashes_split_phrases() -> None:
    info = tokenize_script("Line one\nLine two - and three")
    assert info.phrase_count == 3


@pytest.mark.parametrize(
    ("word", "count"),
    [
        ("the", 1),
        ("deadline", 2),
        ("before", 2),
        ("beautiful", 3),
        ("table", 2),
        ("started", 2),
        ("jumped", 1),
        ("rhythm", 1),
        ("", 0),
        ("a", 1),
    ],
)
def test_syllables(word: str, count: int) -> None:
    assert syllables(word) == count
