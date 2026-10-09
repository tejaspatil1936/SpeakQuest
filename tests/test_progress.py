from __future__ import annotations

from speakquest_api.progress import DoneTake, level_for, new_stamps


def T(
    aid: str,
    cid: str = "deadline",
    codes: tuple[str, ...] = ("RUSH",),
    ts: str = "t1",
    pace: int = 90,
    pauses: int = 100,
) -> DoneTake:
    return DoneTake(
        analysis_id=aid,
        challenge_id=cid,
        created_at=ts,
        duration_s=10,
        codes=codes,
        pace=pace,
        pauses=pauses,
    )


def test_levels() -> None:
    assert level_for(0).name == "Rehearsal" and level_for(0).next_at_s == 120
    assert level_for(119).name == "Rehearsal"
    assert level_for(120).name == "Read-through"
    assert level_for(5000).name == "Headliner" and level_for(5000).next_name is None


def test_first_take_and_clean_take() -> None:
    ids = [b.id for b in new_stamps(T("a1", codes=()), [], set(), ["deadline", "toast"], "now")]
    assert ids == ["FIRST_TAKE", "CLEAN_TAKE"]


def test_fixed_it_third_take_and_steady() -> None:
    earlier = [T("a1", codes=("RUSH", "FADE"), ts="t1"), T("a2", codes=("RUSH", "FADE"), ts="t2")]
    take = T("a3", codes=("FADE",), ts="t3", pace=100, pauses=100)
    ids = [b.id for b in new_stamps(take, earlier, {"FIRST_TAKE"}, ["deadline", "x"], "now")]
    assert ids == ["FIXED_IT", "STEADY", "THIRD_TAKE"]


def test_full_house_and_no_duplicates() -> None:
    earlier = [T("a1", cid="deadline")]
    take = T("a2", cid="toast")
    assert [
        b.id for b in new_stamps(take, earlier, {"FIRST_TAKE"}, ["deadline", "toast"], "now")
    ] == ["FULL_HOUSE"]
    assert (
        new_stamps(take, earlier, {"FIRST_TAKE", "FULL_HOUSE"}, ["deadline", "toast"], "now") == []
    )
