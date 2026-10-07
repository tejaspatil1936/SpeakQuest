from __future__ import annotations

from speakquest.diff import align, classify_insertions, coverage

FILLERS = frozenset({"um", "uh"})


def _ops(script: str, spoken: str) -> list[tuple[str, int | None, int | None]]:
    return [
        (o.op, o.script_index, o.take_index) for o in align(script.split(), spoken.split(), FILLERS)
    ]


def test_identical_sequences_match_one_to_one() -> None:
    assert _ops("before the deadline", "before the deadline") == [
        ("match", 0, 0),
        ("match", 1, 1),
        ("match", 2, 2),
    ]


def test_skipped_word_is_a_deletion() -> None:
    assert _ops("we ship before the deadline", "we ship the deadline") == [
        ("match", 0, 0),
        ("match", 1, 1),
        ("del", 2, None),
        ("match", 3, 2),
        ("match", 4, 3),
    ]


def test_filler_is_an_insertion_not_a_substitution() -> None:
    # Even next to a skip, "um" must not stand in for the skipped word.
    assert _ops("a b c", "a um c") == [
        ("match", 0, 0),
        ("ins", None, 1),
        ("del", 1, None),
        ("match", 2, 2),
    ]


def test_near_miss_aligns_as_substitution() -> None:
    assert _ops("the deadline is close", "the deadlines is close")[1] == ("sub", 1, 1)


def test_repetition_and_filler_classification() -> None:
    script = "before the deadline we ship".split()
    spoken = "before the the deadline um we ship banana".split()
    ops = align(script, spoken, FILLERS)
    kinds = classify_insertions(ops, script, spoken, FILLERS)
    # The traceback keeps the later "the" as the match, so the first is the repeat.
    assert kinds == {1: "repeat", 4: "filler", 7: "insert"}


def test_coverage_counts_matches_and_subs() -> None:
    script = "one two three four".split()
    assert coverage(align(script, "one two three four".split()), 4) == 1.0
    assert coverage(align(script, "one four".split()), 4) == 0.5
    assert coverage([], 0) == 0.0


def test_empty_inputs() -> None:
    assert _ops("a b", "") == [("del", 0, None), ("del", 1, None)]
    assert align([], ["um"], FILLERS)[0].op == "ins"


def test_alignment_is_deterministic() -> None:
    script = "the quick brown fox jumps over the lazy dog".split()
    spoken = "the the quick um fox jumps over lazy dog dog".split()
    first = align(script, spoken, FILLERS)
    for _ in range(5):
        assert align(script, spoken, FILLERS) == first
