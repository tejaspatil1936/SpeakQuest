from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from speakquest.contracts import Finding
from speakquest.rubric import Rubric, load_rubric, score


def _finding(fid: str, code: str, severity: int, start: float = 0.0) -> Finding:
    dims = {
        "RUSH": "pace",
        "DRAG": "pace",
        "HESITATE": "pauses",
        "MONO": "pitch",
        "FADE": "volume",
        "SKIP": "accuracy",
        "FILLER": "accuracy",
    }
    return Finding(
        id=fid,
        code=code,
        dimension=dims[code],
        start=start,
        end=start + 1,
        words=["w"],
        evidence={},
        severity=severity,
        rubric_version="1.0.0",
    )


def test_v1_loads_and_matches_design_thresholds() -> None:
    r = load_rubric()
    assert r.version == "1.0.0"
    assert r.rule("RUSH")["rate_ratio_above"] == 1.35
    assert r.rule("DRAG")["rate_ratio_below"] == 0.70
    assert r.rule("HESITATE")["pause_ms_above"] == 600
    assert r.rule("HESITATE")["reference_pause_ms_below"] == 250
    # Tuned on the dev split from the design's initial 0.50 (see rubric comment).
    assert r.rule("MONO")["sd_ratio_below"] == 0.40
    assert r.rule("FADE")["db_below_mean"] == 6.0
    assert r.audio.max_bytes == 10 * 1024 * 1024
    assert r.audio.max_duration_s == 180
    assert len(r.digest) == 12


def test_clean_take_scores_full_marks() -> None:
    scores, penalties = score([], load_rubric())
    assert scores.model_dump() == {
        "pace": 100,
        "pauses": 100,
        "pitch": 100,
        "volume": 100,
        "accuracy": 100,
        "overall": 100,
    }
    assert penalties == []


def test_penalties_hit_the_mapped_dimension_only() -> None:
    r = load_rubric()
    scores, penalties = score([_finding("f1", "HESITATE", 2), _finding("f2", "FILLER", 1)], r)
    assert scores.pauses == 100 - r.penalties["HESITATE"][2]
    assert scores.accuracy == 100 - r.penalties["FILLER"][1]
    assert scores.pace == scores.pitch == scores.volume == 100
    assert [p.finding_id for p in penalties] == ["f1", "f2"]


def test_dimension_floor_is_zero() -> None:
    findings = [_finding(f"f{i}", "SKIP", 3, start=i) for i in range(1, 10)]
    scores, _ = score(findings, load_rubric())
    assert scores.accuracy == 0
    assert scores.overall == 80


def test_scoring_is_order_independent_and_repeatable() -> None:
    r = load_rubric()
    fs = [
        _finding("f1", "RUSH", 1, 3.0),
        _finding("f2", "MONO", 3, 1.0),
        _finding("f3", "FADE", 2, 2.0),
    ]
    a = score(fs, r)
    b = score(list(reversed(fs)), r)
    assert a == b
    assert a[0].overall == round((92 + 100 + 72 + 85 + 100) / 5)


@pytest.mark.parametrize(
    ("code", "value", "direction", "expected"),
    [
        ("RUSH", 1.36, "above", 1),
        ("RUSH", 1.7, "above", 2),
        ("RUSH", 2.4, "above", 3),
        ("DRAG", 0.69, "below", 1),
        ("DRAG", 0.5, "below", 2),
        ("DRAG", 0.3, "below", 3),
        ("HESITATE", 700, "above", 1),
        ("HESITATE", 1200, "above", 2),
        ("HESITATE", 2500, "above", 3),
        ("SKIP", 1, "above", 1),
        ("SKIP", 5, "above", 3),
    ],
)
def test_severity_bands(code: str, value: float, direction: str, expected: int) -> None:
    assert load_rubric().severity(code, value, direction) == expected


def test_incomplete_rubric_is_rejected(tmp_path: Path, repo_root: Path) -> None:
    data = yaml.safe_load((repo_root / "rubric" / "v1.yaml").read_text())
    del data["penalties"]["MONO"]
    with pytest.raises(ValidationError, match="missing codes"):
        Rubric.model_validate(data)
    data = yaml.safe_load((repo_root / "rubric" / "v1.yaml").read_text())
    data["penalties"]["MONO"] = {1: 1, 2: 2}
    with pytest.raises(ValidationError, match="severities"):
        Rubric.model_validate(data)
