"""Persistence for the single-table design (system design §7).

| pk                  | sk                         | item                         |
|---------------------|----------------------------|------------------------------|
| ``SESSION#<uuid>``  | ``PROFILE``                | air time, stamps             |
| ``SESSION#<uuid>``  | ``TAKE#<ts>#<analysisId>`` | one take's summary           |
| ``ANALYSIS#<id>``   | ``META``                   | status, stage, keys, error   |
| ``CATALOGUE``       | ``CHALLENGE#<id>``         | script, reference keys       |

Challenges live under one ``CATALOGUE`` partition (the design lists
``CHALLENGE#<id>``/``META``) so ``GET /challenges`` is a single Query
instead of a table Scan.

:class:`DynamoRepository` is used in AWS; :class:`SqliteRepository` stores
the same items in one SQLite table for local runs. Both share the
item-level logic in :class:`ItemRepository`.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from abc import ABC, abstractmethod
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from speakquest.contracts import AnalysisStatus, Badge, FlawCode, Scores


class ConflictError(Exception):
    pass


class _Rec(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ChallengeRecord(_Rec):
    id: str
    title: str
    script: str
    difficulty: int
    flaw_targets: list[FlawCode]
    cue: str
    language: str = "en-US"
    reference_audio_key: str | None = None
    reference_features_key: str | None = None
    reference_duration_s: float | None = None
    reference_ready: bool = False
    order: int = 0


class AnalysisRecord(_Rec):
    analysis_id: str
    session_id: str
    challenge_id: str
    status: AnalysisStatus
    stage: str
    created_at: str
    updated_at: str
    take_sk: str
    keys: dict[str, str] = Field(default_factory=dict)
    error: dict[str, Any] | None = None
    summary: dict[str, Any] | None = None
    duration_s: float | None = None
    ttl: int | None = None


class TakeRecord(_Rec):
    sk: str
    analysis_id: str
    challenge_id: str
    created_at: str
    status: AnalysisStatus
    duration_s: float | None = None
    scores: Scores | None = None
    codes: list[FlawCode] = Field(default_factory=list)


class ProfileRecord(_Rec):
    xp: int = 0
    badges: list[Badge] = Field(default_factory=list)
    counted: list[str] = Field(default_factory=list)  # analysis ids already credited
    created_at: str = ""
    updated_at: str = ""


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def take_sort_key(created_at: str, analysis_id: str) -> str:
    return f"TAKE#{created_at}#{analysis_id}"


class ItemRepository(ABC):
    """Typed operations on top of four storage primitives."""

    @abstractmethod
    def _get(self, pk: str, sk: str) -> dict[str, Any] | None: ...

    @abstractmethod
    def _put(self, pk: str, sk: str, item: dict[str, Any], *, if_absent: bool = False) -> None: ...

    @abstractmethod
    def _update(self, pk: str, sk: str, fields: dict[str, Any]) -> None: ...

    @abstractmethod
    def _query(
        self, pk: str, prefix: str, *, newest_first: bool = False, limit: int | None = None
    ) -> list[dict[str, Any]]: ...

    # challenges ---------------------------------------------------------
    def put_challenge(self, rec: ChallengeRecord) -> None:
        self._put("CATALOGUE", f"CHALLENGE#{rec.id}", rec.model_dump(mode="json"))

    def get_challenge(self, challenge_id: str) -> ChallengeRecord | None:
        item = self._get("CATALOGUE", f"CHALLENGE#{challenge_id}")
        return ChallengeRecord.model_validate(item) if item else None

    def list_challenges(self) -> list[ChallengeRecord]:
        recs = [ChallengeRecord.model_validate(i) for i in self._query("CATALOGUE", "CHALLENGE#")]
        return sorted(recs, key=lambda r: (r.order, r.id))

    # analyses -----------------------------------------------------------
    def create_analysis(self, rec: AnalysisRecord) -> None:
        self._put(
            f"ANALYSIS#{rec.analysis_id}", "META", rec.model_dump(mode="json"), if_absent=True
        )

    def get_analysis(self, analysis_id: str) -> AnalysisRecord | None:
        item = self._get(f"ANALYSIS#{analysis_id}", "META")
        return AnalysisRecord.model_validate(item) if item else None

    def update_analysis(self, analysis_id: str, **fields: Any) -> None:
        fields.setdefault("updated_at", now_iso())
        self._update(f"ANALYSIS#{analysis_id}", "META", _jsonable(fields))

    # session ------------------------------------------------------------
    def put_take(self, session_id: str, take: TakeRecord) -> None:
        self._put(f"SESSION#{session_id}", take.sk, take.model_dump(mode="json"))

    def update_take(self, session_id: str, sk: str, **fields: Any) -> None:
        self._update(f"SESSION#{session_id}", sk, _jsonable(fields))

    def list_takes(self, session_id: str, limit: int = 50) -> list[TakeRecord]:
        items = self._query(f"SESSION#{session_id}", "TAKE#", newest_first=True, limit=limit)
        return [TakeRecord.model_validate(i) for i in items]

    def get_profile(self, session_id: str) -> ProfileRecord | None:
        item = self._get(f"SESSION#{session_id}", "PROFILE")
        return ProfileRecord.model_validate(item) if item else None

    def put_profile(self, session_id: str, profile: ProfileRecord) -> None:
        self._put(f"SESSION#{session_id}", "PROFILE", profile.model_dump(mode="json"))


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    return value


# --------------------------------------------------------------------------- DynamoDB


def _to_dynamo(value: Any) -> Any:
    return json.loads(json.dumps(value), parse_float=Decimal)


def _from_dynamo(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: _from_dynamo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_from_dynamo(v) for v in value]
    return value


class DynamoRepository(ItemRepository):
    def __init__(self, table_name: str, region: str | None = None, resource: Any | None = None):
        import boto3  # noqa: PLC0415

        self.table = (resource or boto3.resource("dynamodb", region_name=region)).Table(table_name)

    def _get(self, pk: str, sk: str) -> dict[str, Any] | None:
        item = self.table.get_item(Key={"pk": pk, "sk": sk}, ConsistentRead=True).get("Item")
        return _strip(_from_dynamo(item)) if item else None

    def _put(self, pk: str, sk: str, item: dict[str, Any], *, if_absent: bool = False) -> None:
        from botocore.exceptions import ClientError  # noqa: PLC0415

        kwargs: dict[str, Any] = {"Item": _to_dynamo({**item, "pk": pk, "sk": sk})}
        if if_absent:
            kwargs["ConditionExpression"] = "attribute_not_exists(pk)"
        try:
            self.table.put_item(**kwargs)
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ConflictError(f"{pk}/{sk} exists") from exc
            raise

    def _update(self, pk: str, sk: str, fields: dict[str, Any]) -> None:
        if not fields:
            return
        names = {f"#f{i}": k for i, k in enumerate(fields)}
        values = {f":v{i}": _to_dynamo(v) for i, v in enumerate(fields.values())}
        expr = "SET " + ", ".join(f"#f{i} = :v{i}" for i in range(len(fields)))
        self.table.update_item(
            Key={"pk": pk, "sk": sk},
            UpdateExpression=expr,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )

    def _query(
        self, pk: str, prefix: str, *, newest_first: bool = False, limit: int | None = None
    ) -> list[dict[str, Any]]:
        from boto3.dynamodb.conditions import Key  # noqa: PLC0415

        kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with(prefix),
            "ScanIndexForward": not newest_first,
        }
        out: list[dict[str, Any]] = []
        while True:
            if limit is not None:
                kwargs["Limit"] = limit - len(out)
            page = self.table.query(**kwargs)
            out += [_strip(_from_dynamo(i)) for i in page.get("Items", [])]
            if "LastEvaluatedKey" not in page or (limit is not None and len(out) >= limit):
                return out
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def _strip(item: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in item.items() if k not in ("pk", "sk")} | (
        {"sk": item["sk"]} if str(item.get("sk", "")).startswith("TAKE#") else {}
    )


# --------------------------------------------------------------------------- SQLite


class SqliteRepository(ItemRepository):
    """The same items in one SQLite table — for local development only."""

    def __init__(self, path: Path | str):
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS items (pk TEXT, sk TEXT, data TEXT, PRIMARY KEY (pk, sk))"
        )
        self._db.commit()

    def _get(self, pk: str, sk: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute(
                "SELECT data FROM items WHERE pk=? AND sk=?", (pk, sk)
            ).fetchone()
        return _strip({**json.loads(row[0]), "sk": sk}) if row else None

    def _put(self, pk: str, sk: str, item: dict[str, Any], *, if_absent: bool = False) -> None:
        with self._lock:
            if (
                if_absent
                and self._db.execute("SELECT 1 FROM items WHERE pk=? AND sk=?", (pk, sk)).fetchone()
            ):
                raise ConflictError(f"{pk}/{sk} exists")
            self._db.execute(
                "INSERT OR REPLACE INTO items VALUES (?, ?, ?)",
                (pk, sk, json.dumps(_jsonable(item))),
            )
            self._db.commit()

    def _update(self, pk: str, sk: str, fields: dict[str, Any]) -> None:
        with self._lock:
            row = self._db.execute(
                "SELECT data FROM items WHERE pk=? AND sk=?", (pk, sk)
            ).fetchone()
            data = json.loads(row[0]) if row else {}
            data.update(fields)
            self._db.execute(
                "INSERT OR REPLACE INTO items VALUES (?, ?, ?)", (pk, sk, json.dumps(data))
            )
            self._db.commit()

    def _query(
        self, pk: str, prefix: str, *, newest_first: bool = False, limit: int | None = None
    ) -> list[dict[str, Any]]:
        order = "DESC" if newest_first else "ASC"
        sql = f"SELECT sk, data FROM items WHERE pk=? AND sk LIKE ? ORDER BY sk {order}"
        params: tuple[Any, ...] = (pk, prefix.replace("%", r"\%") + "%")
        if limit is not None:
            sql += " LIMIT ?"
            params += (limit,)
        with self._lock:
            rows = self._db.execute(sql, params).fetchall()
        return [_strip({**json.loads(data), "sk": sk}) for sk, data in rows]
