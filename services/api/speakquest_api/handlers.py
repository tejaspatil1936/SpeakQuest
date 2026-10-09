"""The six public endpoints (system design §3).

Handlers are plain functions of (request, dependencies) so the Lambda entry
point and the local server share them unchanged.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, cast, get_args

from speakquest.contracts import (
    CONTENT_TYPE_EXTENSIONS,
    AnalysisResultResponse,
    AnalysisStatusResponse,
    AnalysisSummary,
    Challenge,
    ChallengeList,
    CreateAnalysisRequest,
    CreateAnalysisResponse,
    CreateUploadRequest,
    CreateUploadResponse,
    ErrorInfo,
    ProgressResponse,
    Scores,
    Stage,
    TakeSummary,
    base_content_type,
)
from speakquest.logs import get_logger, log_event
from speakquest.storage import Storage
from speakquest_api.config import Settings
from speakquest_api.progress import level_for
from speakquest_api.repository import (
    AnalysisRecord,
    ChallengeRecord,
    ConflictError,
    ItemRepository,
    TakeRecord,
    take_sort_key,
)

from .http import ApiError, Request, response

log = get_logger("speakquest.api")


class WorkflowStarter(Protocol):
    def start(self, analysis_id: str, payload: dict[str, Any]) -> str: ...


class StepFunctionsStarter:
    def __init__(self, state_machine_arn: str, region: str | None = None, client: Any = None):
        import boto3  # noqa: PLC0415

        self.arn = state_machine_arn
        self.client = client or boto3.client("stepfunctions", region_name=region)

    def start(self, analysis_id: str, payload: dict[str, Any]) -> str:
        resp = self.client.start_execution(
            stateMachineArn=self.arn, name=analysis_id, input=json.dumps(payload)
        )
        return str(resp["executionArn"])


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


@dataclass
class Deps:
    settings: Settings
    storage: Storage
    repo: ItemRepository
    workflow: WorkflowStarter
    clock: Callable[[], float] = time.time
    new_id: Callable[[], str] = field(default=lambda: str(uuid.uuid4()))


# --------------------------------------------------------------------------- helpers


def _challenge_or_404(deps: Deps, challenge_id: str) -> ChallengeRecord:
    rec = deps.repo.get_challenge(challenge_id)
    if rec is None:
        raise ApiError(404, "CHALLENGE_NOT_FOUND", f"No challenge called '{challenge_id}'.")
    if not rec.reference_ready or not rec.reference_features_key:
        raise ApiError(
            409, "REFERENCE_NOT_READY", "This challenge's reference take has not been analysed yet."
        )
    return rec


def _analysis_or_404(deps: Deps, req: Request) -> AnalysisRecord:
    aid = req.path_params.get("id", "")
    rec = deps.repo.get_analysis(aid) if re.fullmatch(r"[0-9a-f-]{36}", aid) else None
    # Another browser's analysis is indistinguishable from a missing one.
    if rec is None or rec.session_id != req.session_id:
        raise ApiError(404, "ANALYSIS_NOT_FOUND", "No such take for this browser.")
    return rec


def _to_challenge(rec: ChallengeRecord, deps: Deps) -> Challenge:
    url = (
        deps.storage.presign_get(rec.reference_audio_key, deps.settings.result_url_ttl_s)
        if rec.reference_ready and rec.reference_audio_key
        else None
    )
    return Challenge(
        id=rec.id,
        title=rec.title,
        script=rec.script,
        difficulty=rec.difficulty,  # type: ignore[arg-type]
        flaw_targets=rec.flaw_targets,
        language=rec.language,
        cue=rec.cue,
        reference_duration_s=rec.reference_duration_s,
        reference_audio_url=url,
        reference_ready=rec.reference_ready,
    )


# --------------------------------------------------------------------------- endpoints


def list_challenges(req: Request, deps: Deps) -> dict[str, Any]:
    challenges = [_to_challenge(r, deps) for r in deps.repo.list_challenges()]
    return response(200, ChallengeList(challenges=challenges))


def create_upload(req: Request, deps: Deps) -> dict[str, Any]:
    sid = req.session_id
    body = req.json_as(CreateUploadRequest)
    _challenge_or_404(deps, body.challengeId)
    if body.bytes > deps.settings.max_upload_bytes:
        raise ApiError(
            413,
            "AUDIO_TOO_LARGE",
            f"Uploads are capped at {deps.settings.max_upload_bytes // 1048576} MB.",
        )
    analysis_id = deps.new_id()
    ext = CONTENT_TYPE_EXTENSIONS[base_content_type(body.contentType)]
    key = f"uploads/{sid}/{analysis_id}.{ext}"
    ttl = deps.settings.upload_url_ttl_s
    url = deps.storage.presign_put(key, body.contentType, ttl, content_length=body.bytes)
    log_event(
        log,
        "upload.presigned",
        session=sid[:8],
        analysis_id=analysis_id,
        bytes=body.bytes,
        content_type=body.contentType,
    )
    return response(
        201,
        CreateUploadResponse(
            uploadUrl=url, key=key, headers={"Content-Type": body.contentType}, expiresIn=ttl
        ),
    )


_KEY = re.compile(
    r"^uploads/(?P<sid>[0-9a-f-]{36})/(?P<aid>[0-9a-f-]{36})\.(?P<ext>[a-z0-9]{2,4})$"
)


def create_analysis(req: Request, deps: Deps) -> dict[str, Any]:
    sid = req.session_id
    body = req.json_as(CreateAnalysisRequest)
    m = _KEY.match(body.key)
    if not m or m["sid"] != sid or m["ext"] not in CONTENT_TYPE_EXTENSIONS.values():
        raise ApiError(403, "FORBIDDEN_KEY", "That upload key does not belong to this browser.")
    analysis_id = m["aid"]
    challenge = _challenge_or_404(deps, body.challengeId)

    existing = deps.repo.get_analysis(analysis_id)
    if existing is not None:
        if existing.session_id != sid:
            raise ApiError(409, "CONFLICT", "That analysis already exists.")
        return response(202, CreateAnalysisResponse(analysisId=analysis_id))

    size = deps.storage.size(body.key)
    if size is None:
        raise ApiError(409, "UPLOAD_MISSING", "The upload has not arrived yet. Retry the upload.")
    if size > deps.settings.max_upload_bytes:
        raise ApiError(413, "AUDIO_TOO_LARGE", "Uploads are capped at 10 MB.")

    now = deps.clock()
    recent = [
        t
        for t in deps.repo.list_takes(sid, limit=20)
        if t.status in ("QUEUED", "RUNNING") and t.created_at >= _iso(now - 900)
    ]
    if len(recent) >= deps.settings.max_active_analyses:
        raise ApiError(
            429, "TOO_MANY_ACTIVE", "You already have takes being analysed. Wait for one to finish."
        )

    created = _iso(now)
    take_sk = take_sort_key(created, analysis_id)
    record = AnalysisRecord(
        analysis_id=analysis_id,
        session_id=sid,
        challenge_id=challenge.id,
        status="QUEUED",
        stage="QUEUED",
        created_at=created,
        updated_at=created,
        take_sk=take_sk,
        keys={"upload": body.key},
        duration_s=body.durationS,
        ttl=int(now) + deps.settings.analysis_ttl_days * 86400,
    )
    try:
        deps.repo.create_analysis(record)
    except ConflictError:
        return response(202, CreateAnalysisResponse(analysisId=analysis_id))
    deps.repo.put_take(
        sid,
        TakeRecord(
            sk=take_sk,
            analysis_id=analysis_id,
            challenge_id=challenge.id,
            created_at=created,
            status="QUEUED",
            duration_s=body.durationS,
        ),
    )
    payload = {
        "analysisId": analysis_id,
        "sessionId": sid,
        "challengeId": challenge.id,
        "uploadKey": body.key,
        "language": challenge.language or deps.settings.transcribe_language,
        "referenceFeaturesKey": challenge.reference_features_key,
        "takeSk": take_sk,
    }
    try:
        deps.workflow.start(analysis_id, payload)
    except Exception as exc:
        log.exception("workflow.start_failed", extra={"analysis_id": analysis_id})
        deps.repo.update_analysis(
            analysis_id,
            status="FAILED",
            stage="QUEUED",
            error={
                "code": "INTERNAL",
                "stage": "QUEUED",
                "message": "The analysis could not be started.",
            },
        )
        deps.repo.update_take(sid, take_sk, status="FAILED")
        raise ApiError(
            503, "WORKFLOW_UNAVAILABLE", "The analysis could not be started. Try again shortly."
        ) from exc
    log_event(log, "analysis.started", analysis_id=analysis_id, challenge=challenge.id)
    return response(202, CreateAnalysisResponse(analysisId=analysis_id))


def get_analysis(req: Request, deps: Deps) -> dict[str, Any]:
    rec = _analysis_or_404(deps, req)
    summary = None
    if rec.status == "DONE" and rec.summary:
        summary = AnalysisSummary.model_validate(rec.summary)
    error = None
    if rec.status == "FAILED" and rec.error:
        error = ErrorInfo(
            code=str(rec.error.get("code", "INTERNAL")),
            message=str(rec.error.get("message", "The analysis failed.")),
            stage=rec.error.get("stage"),
        )
    stage = cast(Stage, rec.stage if rec.stage in get_args(Stage) else "QUEUED")
    return response(
        200,
        AnalysisStatusResponse(
            analysisId=rec.analysis_id,
            challengeId=rec.challenge_id,
            status=rec.status,
            stage=stage,
            createdAt=rec.created_at,
            updatedAt=rec.updated_at,
            summary=summary,
            error=error,
        ),
    )


def get_result(req: Request, deps: Deps) -> dict[str, Any]:
    rec = _analysis_or_404(deps, req)
    if rec.status != "DONE" or "result" not in rec.keys:
        raise ApiError(409, "NOT_READY", "This take has not finished analysing.")
    ttl = deps.settings.result_url_ttl_s
    challenge = deps.repo.get_challenge(rec.challenge_id)
    ref_url = (
        deps.storage.presign_get(challenge.reference_audio_key, ttl)
        if challenge and challenge.reference_audio_key
        else None
    )
    return response(
        200,
        AnalysisResultResponse(
            resultUrl=deps.storage.presign_get(rec.keys["result"], ttl),
            audioUrl=deps.storage.presign_get(rec.keys["upload"], ttl),
            referenceAudioUrl=ref_url,
            expiresIn=ttl,
        ),
    )


def get_progress(req: Request, deps: Deps) -> dict[str, Any]:
    sid = req.session_id
    profile = deps.repo.get_profile(sid)
    xp = profile.xp if profile else 0
    takes = [
        TakeSummary(
            analysisId=t.analysis_id,
            challengeId=t.challenge_id,
            createdAt=t.created_at,
            status=t.status,
            durationS=t.duration_s,
            scores=Scores.model_validate(t.scores) if t.scores else None,
            codes=t.codes,
        )
        for t in deps.repo.list_takes(sid, limit=50)
    ]
    return response(
        200,
        ProgressResponse(
            xp=xp, level=level_for(xp), badges=profile.badges if profile else [], takes=takes
        ),
    )


# --------------------------------------------------------------------------- routing

_ROUTES: list[tuple[str, re.Pattern[str], Callable[[Request, Deps], dict[str, Any]]]] = [
    ("GET", re.compile(r"^/challenges/?$"), list_challenges),
    ("POST", re.compile(r"^/uploads/?$"), create_upload),
    ("POST", re.compile(r"^/analyses/?$"), create_analysis),
    ("GET", re.compile(r"^/analyses/(?P<id>[^/]+)/result/?$"), get_result),
    ("GET", re.compile(r"^/analyses/(?P<id>[^/]+)/?$"), get_analysis),
    ("GET", re.compile(r"^/me/progress/?$"), get_progress),
]


def dispatch(req: Request, deps: Deps) -> dict[str, Any]:
    from .http import error_response  # noqa: PLC0415

    try:
        for method, pattern, handler in _ROUTES:
            m = pattern.match(req.path)
            if m and req.method == method:
                req.path_params = {**m.groupdict(), **req.path_params}
                return handler(req, deps)
        if any(p.match(req.path) for _, p, _ in _ROUTES):
            raise ApiError(405, "METHOD_NOT_ALLOWED", f"{req.method} is not allowed here.")
        raise ApiError(404, "NOT_FOUND", "No such endpoint.")
    except ApiError as err:
        if err.status >= 500:
            log_event(log, "api.error", code=err.code, path=req.path)
        return error_response(err)
    except Exception:
        log.exception("api.unhandled", extra={"path": req.path})
        return error_response(ApiError(500, "INTERNAL", "Something went wrong on our side."))
