"""Detection metrics (system design §5.5).

* A predicted finding matches a labelled flaw of the same code when their
  timestamp IoU ≥ 0.5; matching is one-to-one, greedy by IoU.
* SKIP labels are points in time (the words are absent), so both sides of a
  SKIP comparison are padded to a minimum width before computing IoU.
* False-positive rate is findings per minute on clean-vs-clean pairs.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from statistics import median

from speakquest.contracts import FLAW_CODES

IOU_THRESHOLD = 0.5
MIN_WIDTH_S = {"SKIP": 0.3}


@dataclass(frozen=True)
class Interval:
    code: str
    start: float
    end: float


def _padded(iv: Interval) -> tuple[float, float]:
    width = MIN_WIDTH_S.get(iv.code, 0.0)
    if iv.end - iv.start >= width:
        return iv.start, iv.end
    centre = (iv.start + iv.end) / 2
    return centre - width / 2, centre + width / 2


def iou(a: Interval, b: Interval) -> float:
    a0, a1 = _padded(a)
    b0, b1 = _padded(b)
    inter = max(0.0, min(a1, b1) - max(a0, b0))
    union = max(a1, b1) - min(a0, b0)
    return inter / union if union > 0 else 0.0


@dataclass
class ClipMatch:
    tp: list[tuple[Interval, Interval, float]] = field(default_factory=list)
    fp: list[Interval] = field(default_factory=list)
    fn: list[Interval] = field(default_factory=list)


def match(
    predicted: Sequence[Interval], labelled: Sequence[Interval], threshold: float = IOU_THRESHOLD
) -> ClipMatch:
    pairs = sorted(
        (
            (iou(p, g), i, j)
            for i, p in enumerate(predicted)
            for j, g in enumerate(labelled)
            if p.code == g.code
        ),
        key=lambda x: (-x[0], x[1], x[2]),
    )
    used_p: set[int] = set()
    used_g: set[int] = set()
    result = ClipMatch()
    for score, i, j in pairs:
        if score < threshold or i in used_p or j in used_g:
            continue
        used_p.add(i)
        used_g.add(j)
        result.tp.append((predicted[i], labelled[j], score))
    result.fp = [p for i, p in enumerate(predicted) if i not in used_p]
    result.fn = [g for j, g in enumerate(labelled) if j not in used_g]
    return result


@dataclass
class CodeStats:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    ious: list[float] = field(default_factory=list)

    @property
    def precision(self) -> float | None:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else None

    @property
    def recall(self) -> float | None:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else None

    def to_dict(self) -> dict[str, float | int | None]:
        return {
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "precision": None if self.precision is None else round(self.precision, 3),
            "recall": None if self.recall is None else round(self.recall, 3),
            "mean_iou": round(sum(self.ious) / len(self.ious), 3) if self.ious else None,
        }


def aggregate(matches: Iterable[ClipMatch]) -> dict[str, CodeStats]:
    stats: dict[str, CodeStats] = {code: CodeStats() for code in FLAW_CODES}
    for m in matches:
        for p, _g, score in m.tp:
            stats[p.code].tp += 1
            stats[p.code].ious.append(score)
        for p in m.fp:
            stats[p.code].fp += 1
        for g in m.fn:
            stats[g.code].fn += 1
    return stats


def micro(stats: dict[str, CodeStats]) -> CodeStats:
    total = CodeStats()
    for s in stats.values():
        total.tp += s.tp
        total.fp += s.fp
        total.fn += s.fn
        total.ious += s.ious
    return total


def fp_per_minute(findings_on_clean: int, clean_seconds: float) -> float | None:
    return findings_on_clean / (clean_seconds / 60) if clean_seconds > 0 else None


def summarize_errors(errors_ms: Sequence[float]) -> dict[str, float | int | None]:
    if not errors_ms:
        return {"n": 0, "median_ms": None, "p90_ms": None, "mean_ms": None}
    ordered = sorted(errors_ms)
    p90 = ordered[min(len(ordered) - 1, round(0.9 * (len(ordered) - 1)))]
    return {
        "n": len(ordered),
        "median_ms": round(median(ordered), 1),
        "p90_ms": round(p90, 1),
        "mean_ms": round(sum(ordered) / len(ordered), 1),
    }
