"""API Gateway HTTP API (payload v2) request/response helpers."""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
MAX_BODY_BYTES = 16 * 1024


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


@dataclass
class Request:
    method: str
    path: str
    headers: dict[str, str]
    path_params: dict[str, str] = field(default_factory=dict)
    query: dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    source_ip: str = ""

    @classmethod
    def from_event(cls, event: dict[str, Any]) -> Request:
        ctx = event.get("requestContext", {})
        http = ctx.get("http", {})
        raw = event.get("body") or ""
        body = base64.b64decode(raw) if event.get("isBase64Encoded") else raw.encode()
        return cls(
            method=str(http.get("method", "GET")).upper(),
            path=str(event.get("rawPath") or http.get("path") or "/"),
            headers={k.lower(): v for k, v in (event.get("headers") or {}).items()},
            path_params=dict(event.get("pathParameters") or {}),
            query=dict(event.get("queryStringParameters") or {}),
            body=body,
            source_ip=str(http.get("sourceIp", "")),
        )

    @property
    def session_id(self) -> str:
        sid = self.headers.get("x-session-id", "").strip().lower()
        if not _UUID.match(sid):
            raise ApiError(
                400,
                "SESSION_REQUIRED",
                "Send a UUID in the x-session-id header to identify this browser.",
            )
        return sid

    def json_as[M: BaseModel](self, model: type[M]) -> M:
        if len(self.body) > MAX_BODY_BYTES:
            raise ApiError(413, "PAYLOAD_TOO_LARGE", "Request body is too large.")
        try:
            data = json.loads(self.body or b"{}")
        except json.JSONDecodeError as exc:
            raise ApiError(400, "BAD_JSON", "Request body is not valid JSON.") from exc
        try:
            return model.model_validate(data)
        except ValidationError as exc:
            first = exc.errors()[0]
            loc = ".".join(str(p) for p in first["loc"]) or "body"
            raise ApiError(422, "VALIDATION", f"{loc}: {first['msg']}") from exc


def cors_headers(origin: str | None, allowed: tuple[str, ...]) -> dict[str, str]:
    """Only used by the local server; in AWS the HTTP API's CORS config applies."""
    if not origin or origin.rstrip("/") not in allowed:
        return {}
    return {
        "access-control-allow-origin": origin,
        "access-control-allow-methods": "GET,POST,PUT,OPTIONS",
        "access-control-allow-headers": "content-type,x-session-id",
        "access-control-max-age": "600",
        "vary": "origin",
    }


def response(
    status: int,
    body: BaseModel | dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    payload = body.model_dump(mode="json") if isinstance(body, BaseModel) else body
    return {
        "statusCode": status,
        "headers": {
            "content-type": "application/json",
            "cache-control": "no-store",
            **(headers or {}),
        },
        "body": "" if payload is None else json.dumps(payload, separators=(",", ":")),
    }


def error_response(err: ApiError) -> dict[str, Any]:
    return response(err.status, {"error": {"code": err.code, "message": err.message}})
