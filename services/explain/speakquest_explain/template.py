"""Deterministic coaching text: the fallback when the model can't be used.

Written in the director's voice the design asks for (§10.6): direct,
specific, second person, one drill per finding, no praise padding. Every
number comes straight from the finding's evidence, so this text passes the
same validator the model's output must pass.
"""

from __future__ import annotations

from collections.abc import Callable

from speakquest.contracts import CoachingItem, Finding


def _quote(f: Finding, limit: int = 6) -> str:
    if not f.words:
        return "that stretch"
    words = f.words if len(f.words) <= limit else [*f.words[: limit - 1], "…"]
    return "'" + " ".join(words) + "'"


def _num(f: Finding, key: str) -> str:
    v = f.evidence.get(key)
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def _rush(f: Finding) -> CoachingItem:
    whole = f.evidence.get("scope") == "whole take"
    target = "the whole take" if whole else _quote(f)
    return CoachingItem(
        finding_id=f.id,
        headline=f"You rushed {target} — {_num(f, 'rate_ratio')}× the reference pace.",
        why="Speed hides the words that carry the meaning; the listener drops them first.",
        drill=f"Read {target} at half speed three times, then once at the reference pace, "
        "landing every stressed syllable.",
    )


def _drag(f: Finding) -> CoachingItem:
    whole = f.evidence.get("scope") == "whole take"
    target = "the whole take" if whole else _quote(f)
    return CoachingItem(
        finding_id=f.id,
        headline=f"You dragged {target} — {_num(f, 'rate_ratio')}× the reference pace.",
        why="Stretched words sound unsure and let the sentence lose its shape.",
        drill=f"Mark the one word in {target} that matters most and move through the rest "
        "to reach it.",
    )


def _hesitate(f: Finding) -> CoachingItem:
    before, after = [*f.words, "", ""][:2]
    return CoachingItem(
        finding_id=f.id,
        headline=f"You stalled for {_num(f, 'pause_ms')} ms between '{before}' and '{after}'.",
        why=f"The reference pauses {_num(f, 'reference_pause_ms')} ms there. A gap that long "
        "mid-thought reads as a lost line.",
        drill=f"Say '{before} {after}' as one breath group five times, then read the "
        "sentence through without stopping.",
    )


def _mono(f: Finding) -> CoachingItem:
    whole = f.evidence.get("scope") == "whole take"
    target = "the whole take" if whole else _quote(f)
    detail = (
        f"Your pitch moved {_num(f, 'pitch_sd_st')} semitones here; the reference moved "
        f"{_num(f, 'reference_pitch_sd_st')}."
        if "pitch_sd_st" in f.evidence
        else f"Your pitch movement was {_num(f, 'ratio')} of the reference's."
    )
    return CoachingItem(
        finding_id=f.id,
        headline=f"{target[0].upper() + target[1:]} came out flat.",
        why=f"{detail} Without movement the listener can't hear which word matters.",
        drill="Pick the key word, lift it, and let the line fall after it. Exaggerate twice, "
        "then pull back to natural.",
    )


def _fade(f: Finding) -> CoachingItem:
    return CoachingItem(
        finding_id=f.id,
        headline=f"You faded on {_quote(f)} — {_num(f, 'drop_db')} dB under your average.",
        why=f"The reference drops {_num(f, 'reference_drop_db')} dB there. The end of a line "
        "is where the point lands; it has to reach the back row.",
        drill="Breathe before the line, aim the last word at a spot across the room, and keep "
        "your volume until the final consonant.",
    )


def _skip(f: Finding) -> CoachingItem:
    return CoachingItem(
        finding_id=f.id,
        headline=f"You skipped {_quote(f)}.",
        why="Dropped words change what the script says; small words often carry the logic.",
        drill="Read the sentence slowly with your finger under each word, then at full pace.",
    )


def _filler(f: Finding) -> CoachingItem:
    kind = str(f.evidence.get("kind", ""))
    if kind == "vocalization":
        headline = f"You filled a gap with a {_num(f, 'vocalization_ms')} ms 'um'."
    elif "repeat" in kind:
        headline = f"You repeated {_quote(f)}."
    else:
        headline = f"You added {_quote(f)}, which isn't in the script."
    return CoachingItem(
        finding_id=f.id,
        headline=headline,
        why="Fillers tell the listener you're searching. Silence sounds more certain.",
        drill="Read the line again and replace the filler with a closed-mouth pause.",
    )


_BUILDERS: dict[str, Callable[[Finding], CoachingItem]] = {
    "RUSH": _rush,
    "DRAG": _drag,
    "HESITATE": _hesitate,
    "MONO": _mono,
    "FADE": _fade,
    "SKIP": _skip,
    "FILLER": _filler,
}


def template_items(findings: list[Finding]) -> list[CoachingItem]:
    return [_BUILDERS[f.code](f) for f in findings]
