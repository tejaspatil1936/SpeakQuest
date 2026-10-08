from __future__ import annotations

from speakquest.challenges import get_entry, load_catalogue
from speakquest.tokens import tokenize_script


def test_catalogue_is_valid_and_split() -> None:
    entries = load_catalogue()
    assert 6 <= len(entries) <= 10
    splits = {e.split for e in entries}
    assert splits == {"dev", "heldout"}
    assert sum(e.split == "heldout" for e in entries) >= 3
    for e in entries:
        challenge = e.to_challenge()
        assert challenge.id == e.id
        info = tokenize_script(e.script)
        assert 15 <= len(info.tokens) <= 60
        assert info.phrase_count >= 2


def test_numbers_in_scripts_are_spelled_out() -> None:
    entry = get_entry("station-ident")
    assert entry is not None
    norms = [t.norm for t in tokenize_script(entry.script).tokens]
    assert "ninety" in norms and "point" in norms
    assert get_entry("nope") is None
