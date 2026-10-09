"""The same contract against DynamoDB (moto) and SQLite."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from speakquest.contracts import Badge, Scores
from speakquest_api.repository import (
    AnalysisRecord,
    ChallengeRecord,
    ConflictError,
    DynamoRepository,
    ItemRepository,
    ProfileRecord,
    SqliteRepository,
    TakeRecord,
    take_sort_key,
)


def make_table() -> None:
    boto3.client("dynamodb", region_name="us-east-1").create_table(
        TableName="speakquest-test",
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
    )


@pytest.fixture(params=["sqlite", "dynamo"])
def repo(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[ItemRepository]:
    if request.param == "sqlite":
        yield SqliteRepository(tmp_path / "db.sqlite")
        return
    with mock_aws():
        make_table()
        yield DynamoRepository("speakquest-test", region="us-east-1")


def _analysis(aid: str = "a1") -> AnalysisRecord:
    return AnalysisRecord(
        analysis_id=aid,
        session_id="s1",
        challenge_id="deadline",
        status="QUEUED",
        stage="QUEUED",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        take_sk=take_sort_key("2026-01-01T00:00:00Z", aid),
        keys={"upload": "uploads/s1/a1.webm"},
        duration_s=4.5,
        ttl=1700000000,
    )


def test_challenges_round_trip_in_order(repo: ItemRepository) -> None:
    for i, cid in enumerate(["zeta", "alpha"]):
        repo.put_challenge(
            ChallengeRecord(
                id=cid,
                title=cid,
                script="x y z",
                difficulty=1,
                flaw_targets=["RUSH"],
                cue="c",
                order=i,
                reference_duration_s=3.25,
            )
        )
    assert [c.id for c in repo.list_challenges()] == ["zeta", "alpha"]
    got = repo.get_challenge("alpha")
    assert got is not None and got.reference_duration_s == 3.25
    assert repo.get_challenge("nope") is None


def test_analysis_create_is_idempotent_and_updates_merge(repo: ItemRepository) -> None:
    repo.create_analysis(_analysis())
    with pytest.raises(ConflictError):
        repo.create_analysis(_analysis())
    repo.update_analysis(
        "a1",
        status="RUNNING",
        stage="ANALYZE",
        keys={"upload": "uploads/s1/a1.webm", "result": "results/a1/result.json"},
    )
    rec = repo.get_analysis("a1")
    assert rec is not None
    assert (rec.status, rec.stage, rec.duration_s) == ("RUNNING", "ANALYZE", 4.5)
    assert rec.keys["result"] == "results/a1/result.json"
    assert rec.updated_at >= rec.created_at
    repo.update_analysis(
        "a1", status="FAILED", error={"code": "AUDIO_SILENT", "stage": "NORMALIZE"}
    )
    rec = repo.get_analysis("a1")
    assert rec is not None and rec.error == {"code": "AUDIO_SILENT", "stage": "NORMALIZE"}
    assert repo.get_analysis("missing") is None


def test_takes_newest_first_and_profile(repo: ItemRepository) -> None:
    for i in range(3):
        ts = f"2026-10-15T00:00:0{i}Z"
        repo.put_take(
            "s1",
            TakeRecord(
                sk=take_sort_key(ts, f"a{i}"),
                analysis_id=f"a{i}",
                challenge_id="deadline",
                created_at=ts,
                status="QUEUED",
            ),
        )
    repo.update_take(
        "s1",
        take_sort_key("2026-10-15T00:00:01Z", "a1"),
        status="DONE",
        scores=Scores(pace=90, pauses=100, pitch=100, volume=100, accuracy=95, overall=97),
        codes=["RUSH"],
    )
    takes = repo.list_takes("s1")
    assert [t.analysis_id for t in takes] == ["a2", "a1", "a0"]
    assert takes[1].scores is not None and takes[1].scores.pace == 90
    assert takes[1].codes == ["RUSH"]
    assert [t.analysis_id for t in repo.list_takes("s1", limit=2)] == ["a2", "a1"]
    assert repo.list_takes("other") == []
    assert repo.get_profile("s1") is None
    repo.put_profile(
        "s1",
        ProfileRecord(
            xp=12,
            badges=[Badge(id="FIRST_TAKE", label="First take", awarded_at="t")],
            counted=["a1"],
        ),
    )
    prof = repo.get_profile("s1")
    assert prof is not None and prof.xp == 12 and prof.badges[0].id == "FIRST_TAKE"
