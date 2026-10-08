from __future__ import annotations

import pytest

from speakquest_eval.metrics import (
    Interval,
    aggregate,
    fp_per_minute,
    iou,
    match,
    micro,
    summarize_errors,
)


def test_iou_basic_and_disjoint() -> None:
    assert iou(Interval("RUSH", 0, 2), Interval("RUSH", 1, 3)) == pytest.approx(1 / 3)
    assert iou(Interval("RUSH", 0, 1), Interval("RUSH", 2, 3)) == 0.0
    assert iou(Interval("RUSH", 0, 1), Interval("RUSH", 0, 1)) == 1.0


def test_skip_points_are_padded() -> None:
    label = Interval("SKIP", 2.00, 2.02)
    assert iou(Interval("SKIP", 2.01, 2.01), label) == pytest.approx(1.0)
    assert iou(Interval("SKIP", 2.10, 2.12), label) == pytest.approx(0.2 / 0.4)
    assert iou(Interval("SKIP", 2.5, 2.5), label) == 0.0


def test_matching_is_one_to_one_and_code_aware() -> None:
    labels = [Interval("RUSH", 1, 3), Interval("FADE", 5, 6)]
    preds = [Interval("RUSH", 1.1, 3), Interval("RUSH", 1, 2.9), Interval("MONO", 5, 6)]
    m = match(preds, labels)
    assert len(m.tp) == 1 and m.tp[0][0] == preds[0]
    assert m.fp == [preds[1], preds[2]]
    assert m.fn == [labels[1]]


def test_iou_threshold_applies() -> None:
    m = match([Interval("DRAG", 0, 1)], [Interval("DRAG", 0.6, 1.6)])
    assert not m.tp and len(m.fp) == 1 and len(m.fn) == 1


def test_aggregate_precision_recall() -> None:
    m1 = match([Interval("RUSH", 0, 1)], [Interval("RUSH", 0, 1)])
    m2 = match([Interval("RUSH", 5, 6)], [Interval("RUSH", 9, 10)])
    stats = aggregate([m1, m2])
    assert stats["RUSH"].precision == 0.5 and stats["RUSH"].recall == 0.5
    assert stats["MONO"].precision is None
    assert micro(stats).tp == 1
    assert stats["RUSH"].to_dict()["mean_iou"] == 1.0


def test_fp_rate_and_error_summary() -> None:
    assert fp_per_minute(3, 120) == 1.5
    assert fp_per_minute(0, 0) is None
    s = summarize_errors([10, 20, 30, 40, 100])
    assert s["median_ms"] == 30 and s["n"] == 5 and s["p90_ms"] == 100
    assert summarize_errors([])["median_ms"] is None
