from __future__ import annotations

from collections import Counter

from speakquest.challenges import load_catalogue
from speakquest.contracts import FLAW_CODES
from speakquest.tokens import tokenize_script
from speakquest_eval.synth import plan_challenge, surface_words


def test_surface_words_mirror_script_tokens() -> None:
    for entry in load_catalogue():
        words = surface_words(entry.script)
        info = tokenize_script(entry.script)
        assert sum(w.n_tokens for w in words) == len(info.tokens)
        for w in words:
            for k in range(w.n_tokens):
                assert info.tokens[w.first_token + k].phrase == w.phrase


def test_plans_are_deterministic_and_cover_every_code_in_both_splits() -> None:
    by_split: dict[str, Counter[str]] = {"dev": Counter(), "heldout": Counter()}
    for entry in load_catalogue():
        plans = plan_challenge(entry)
        again = plan_challenge(entry)
        assert [(p.clip_id, [(f.code, f.a, f.b) for f in p.flaws]) for p in plans] == [
            (p.clip_id, [(f.code, f.a, f.b) for f in p.flaws]) for p in again
        ]
        roles = Counter(p.role for p in plans)
        assert roles == {"reference": 1, "clean": 2, "flawed": 4}
        for plan in plans:
            phrases = [f.phrase for f in plan.flaws]
            assert len(phrases) == len(set(phrases)), "two flaws share a phrase"
            by_split[plan.split].update(f.code for f in plan.flaws)
    for split, counts in by_split.items():
        missing = set(FLAW_CODES) - set(counts)
        assert not missing, f"{split} split lacks {missing}"
