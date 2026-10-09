"""Air time, levels and stamps (system design §10.5).

XP is *air time*: seconds of takes that were successfully analysed. Levels
are named after the road to a show. Badges are typographic stamps awarded
by deterministic rules over the session's takes.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from speakquest.contracts import Badge, Level

LEVELS: tuple[tuple[str, int], ...] = (
    ("Rehearsal", 0),
    ("Read-through", 120),
    ("Dress", 360),
    ("Opening night", 900),
    ("Headliner", 1800),
)

STAMPS: dict[str, str] = {
    "FIRST_TAKE": "First take",
    "CLEAN_TAKE": "Clean take",
    "FIXED_IT": "Fixed it",
    "STEADY": "Steady",
    "THIRD_TAKE": "Third take",
    "FULL_HOUSE": "Full house",
}


def level_for(xp_s: int) -> Level:
    index = 0
    for i, (_name, floor) in enumerate(LEVELS):
        if xp_s >= floor:
            index = i
    name, floor = LEVELS[index]
    nxt = LEVELS[index + 1] if index + 1 < len(LEVELS) else None
    return Level(
        index=index,
        name=name,
        floor_s=floor,
        next_name=nxt[0] if nxt else None,
        next_at_s=nxt[1] if nxt else None,
    )


@dataclass(frozen=True)
class DoneTake:
    analysis_id: str
    challenge_id: str
    created_at: str
    duration_s: float
    codes: tuple[str, ...]
    pace: int
    pauses: int


def new_stamps(
    take: DoneTake,
    earlier: Sequence[DoneTake],
    have: set[str],
    challenge_ids: Sequence[str],
    when: str,
) -> list[Badge]:
    """Stamps earned by ``take`` given the session's earlier finished takes."""
    earned: list[str] = []
    same = [t for t in earlier if t.challenge_id == take.challenge_id]
    if not earlier:
        earned.append("FIRST_TAKE")
    if not take.codes:
        earned.append("CLEAN_TAKE")
    if same:
        previous = max(same, key=lambda t: t.created_at)
        if previous.codes and set(previous.codes) - set(take.codes):
            earned.append("FIXED_IT")
    if take.pace == 100 and take.pauses == 100:
        earned.append("STEADY")
    if len(same) + 1 >= 3:
        earned.append("THIRD_TAKE")
    done = {t.challenge_id for t in earlier} | {take.challenge_id}
    if challenge_ids and set(challenge_ids) <= done:
        earned.append("FULL_HOUSE")
    return [
        Badge(id=b, label=STAMPS[b], awarded_at=when, analysis_id=take.analysis_id)
        for b in earned
        if b not in have
    ]
