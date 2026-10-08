"""Align the spoken words to the script (Needleman–Wunsch).

Forced alignment breaks exactly where flaws happen (skips, repeats,
fillers), so the system design times the speech with an ASR and then diffs
the recognised words against the script:

* insertions → fillers or repetitions (``FILLER``)
* deletions  → skipped words (``SKIP``)
* matches and substitutions → positions used for prosody comparison

Costs are integers scaled by 10 so the dynamic programme is exact and the
traceback is deterministic.
"""

from __future__ import annotations

from collections.abc import Sequence
from difflib import SequenceMatcher
from typing import Literal

from speakquest.contracts import AlignOp, AlignOpKind

GAP = 10
MATCH = 0
NEAR = 6  # "deadlines" for "deadline": same word, recogniser slip
SUB = 12  # a different word: cheaper than ins+del so misreads stay aligned
FILLER_SUB = 25  # never let "um" stand in for a script word

InsertKind = Literal["filler", "repeat", "insert"]


def _similar(a: str, b: str) -> bool:
    if min(len(a), len(b)) < 3:
        return False
    return SequenceMatcher(None, a, b, autojunk=False).ratio() >= 0.75


def _sub_cost(script: str, spoken: str, fillers: frozenset[str]) -> int:
    if script == spoken:
        return MATCH
    if spoken in fillers:
        return FILLER_SUB
    if _similar(script, spoken):
        return NEAR
    return SUB


def align(
    script: Sequence[str], spoken: Sequence[str], fillers: frozenset[str] = frozenset()
) -> list[AlignOp]:
    """Globally align normalised script tokens to normalised spoken tokens."""
    n, m = len(script), len(spoken)
    cost = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        cost[i][0] = i * GAP
    for j in range(1, m + 1):
        cost[0][j] = j * GAP
    for i in range(1, n + 1):
        row, prev = cost[i], cost[i - 1]
        s = script[i - 1]
        for j in range(1, m + 1):
            row[j] = min(
                prev[j - 1] + _sub_cost(s, spoken[j - 1], fillers),
                prev[j] + GAP,  # script token not spoken
                row[j - 1] + GAP,  # spoken token not in script
            )

    ops: list[AlignOp] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0:
            c = _sub_cost(script[i - 1], spoken[j - 1], fillers)
            if cost[i][j] == cost[i - 1][j - 1] + c:
                kind: AlignOpKind = "match" if c == MATCH else "sub"
                ops.append(AlignOp(op=kind, script_index=i - 1, take_index=j - 1))
                i, j = i - 1, j - 1
                continue
        if i > 0 and cost[i][j] == cost[i - 1][j] + GAP:
            ops.append(AlignOp(op="del", script_index=i - 1))
            i -= 1
            continue
        ops.append(AlignOp(op="ins", take_index=j - 1))
        j -= 1
    ops.reverse()
    return ops


def coverage(ops: Sequence[AlignOp], script: Sequence[str], spoken: Sequence[str]) -> float:
    """Fraction of script tokens the speaker actually said.

    Exact matches and near-misses count; arbitrary substitutions do not, or
    reading a different text of the same length would look like full coverage.
    """
    if not script:
        return 0.0
    hits = 0
    for op in ops:
        if op.script_index is None or op.take_index is None:
            continue
        a, b = script[op.script_index], spoken[op.take_index]
        if op.op == "match" or (op.op == "sub" and _similar(a, b)):
            hits += 1
    return hits / len(script)


def classify_insertions(
    ops: Sequence[AlignOp], script: Sequence[str], spoken: Sequence[str], fillers: frozenset[str]
) -> dict[int, InsertKind]:
    """Label every inserted spoken token as a filler, a repetition or other."""
    kinds: dict[int, InsertKind] = {}
    last_script: int | None = None
    next_script: list[int | None] = [None] * len(ops)
    upcoming: int | None = None
    for k in range(len(ops) - 1, -1, -1):
        next_script[k] = upcoming
        if ops[k].script_index is not None and ops[k].op != "del":
            upcoming = ops[k].script_index

    for k, op in enumerate(ops):
        if op.op == "ins" and op.take_index is not None:
            word = spoken[op.take_index]
            neighbours = {spoken[op.take_index - 1]} if op.take_index > 0 else set()
            if last_script is not None:
                neighbours.add(script[last_script])
            nxt = next_script[k]
            if nxt is not None:
                neighbours.add(script[nxt])
            if word in fillers:
                kinds[op.take_index] = "filler"
            elif word in neighbours:
                kinds[op.take_index] = "repeat"
            else:
                kinds[op.take_index] = "insert"
        elif op.script_index is not None and op.op != "del":
            last_script = op.script_index
    return kinds
