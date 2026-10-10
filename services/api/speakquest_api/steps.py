"""Workflow steps that run in zip Lambdas: Explain, Persist and Fail.

Each step receives the whole Step Functions state (the execution input plus
earlier results under ``normalize``/``analyze``/``explain``) and talks to
storage and the repository through injected adapters, so the local runner
calls exactly these functions. No numpy here: this module ships in the zip.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from speakquest.contracts import AnalysisResult, Coaching
from speakquest.errors import ERRORS
from speakquest.logs import get_logger, log_event
from speakquest.storage import Storage, StorageMissingError, get_json, put_json
from speakquest_api.progress import DoneTake, new_stamps
from speakquest_api.repository import ItemRepository, ProfileRecord, now_iso
from speakquest_explain.coach import ModelClient, coach
from speakquest_explain.template import template_items

log = get_logger("speakquest.steps")


@dataclass
class StepDeps:
    storage: Storage
    repo: ItemRepository
    model: ModelClient | None = None


def analysis_key(analysis_id: str) -> str:
    return f"results/{analysis_id}/analysis.json"


def coaching_key(analysis_id: str) -> str:
    return f"results/{analysis_id}/coaching.json"


def result_key(analysis_id: str) -> str:
    return f"results/{analysis_id}/result.json"


def mark(deps: StepDeps, state: dict[str, Any], stage: str, status: str = "RUNNING") -> None:
    deps.repo.update_analysis(state["analysisId"], status=status, stage=stage)
    if status != "DONE":
        deps.repo.update_take(state["sessionId"], state["takeSk"], status=status)


# --------------------------------------------------------------------------- Explain


def explain_step(state: dict[str, Any], deps: StepDeps) -> dict[str, Any]:
    aid = state["analysisId"]
    mark(deps, state, "EXPLAIN")
    analysis = AnalysisResult.model_validate(get_json(deps.storage, analysis_key(aid)))
    coaching = coach(analysis.findings, analysis.script.text, deps.model)
    put_json(deps.storage, coaching_key(aid), coaching.model_dump(mode="json"))
    log_event(
        log,
        "explain.done",
        analysis_id=aid,
        source=coaching.source,
        attempts=coaching.attempts,
        items=len(coaching.items),
    )
    return {"coachingKey": coaching_key(aid), "source": coaching.source}


# --------------------------------------------------------------------------- Persist


def persist_step(
    state: dict[str, Any], deps: StepDeps, challenge_ids: list[str] | None = None
) -> dict[str, Any]:
    aid, sid = state["analysisId"], state["sessionId"]
    mark(deps, state, "PERSIST")
    analysis = AnalysisResult.model_validate(get_json(deps.storage, analysis_key(aid)))
    try:
        coaching = Coaching.model_validate(get_json(deps.storage, coaching_key(aid)))
    except StorageMissingError:
        # The Explain step crashed outright; the design's fallback still applies.
        coaching = Coaching(
            source="template",
            items=template_items(analysis.findings),
            attempts=0,
            rejections=["explain step failed; template used"],
        )
    result = analysis.model_copy(
        update={
            "coaching": coaching,
            "versions": analysis.versions.model_copy(update={"model_id": coaching.model_id}),
        }
    )
    put_json(deps.storage, result_key(aid), result.model_dump(mode="json"))

    codes = list(dict.fromkeys(f.code for f in result.findings))
    summary = {
        "scores": result.scores.model_dump(),
        "findingCount": len(result.findings),
        "codes": codes,
    }
    record = deps.repo.get_analysis(aid)
    keys = {**(record.keys if record else {}), "result": result_key(aid)}
    duration = round(result.take.duration_s, 2)
    deps.repo.update_take(
        sid, state["takeSk"], status="DONE", scores=result.scores, codes=codes, duration_s=duration
    )

    profile = deps.repo.get_profile(sid) or ProfileRecord(created_at=now_iso())
    if aid not in profile.counted:
        earlier = [
            DoneTake(
                analysis_id=t.analysis_id,
                challenge_id=t.challenge_id,
                created_at=t.created_at,
                duration_s=t.duration_s or 0.0,
                codes=tuple(t.codes),
                pace=t.scores.pace,
                pauses=t.scores.pauses,
            )
            for t in deps.repo.list_takes(sid, limit=200)
            if t.status == "DONE" and t.scores is not None and t.analysis_id != aid
        ]
        this = DoneTake(
            analysis_id=aid,
            challenge_id=result.challenge_id,
            created_at=result.created_at,
            duration_s=duration,
            codes=tuple(codes),
            pace=result.scores.pace,
            pauses=result.scores.pauses,
        )
        stamps = new_stamps(
            this,
            earlier,
            {b.id for b in profile.badges},
            challenge_ids
            if challenge_ids is not None
            else [c.id for c in deps.repo.list_challenges()],
            now_iso(),
        )
        profile = profile.model_copy(
            update={
                "xp": profile.xp + round(duration),
                "badges": [*profile.badges, *stamps],
                "counted": [*profile.counted, aid][-500:],
                "updated_at": now_iso(),
            }
        )
        deps.repo.put_profile(sid, profile)
    deps.repo.update_analysis(
        aid, status="DONE", stage="DONE", keys=keys, summary=summary, duration_s=duration
    )
    log_event(
        log,
        "persist.done",
        analysis_id=aid,
        findings=len(result.findings),
        overall=result.scores.overall,
    )
    return {"resultKey": result_key(aid)}


# --------------------------------------------------------------------------- Fail


def error_code(error: dict[str, Any] | None) -> tuple[str, str]:
    """Map a Step Functions ``{Error, Cause}`` (or a local exception dict) to a code."""
    if not error:
        return "INTERNAL", ""
    name = str(error.get("Error", ""))
    cause_raw = error.get("Cause", "")
    detail = ""
    message = cause_raw
    try:
        cause = json.loads(cause_raw) if isinstance(cause_raw, str) and cause_raw else {}
        if isinstance(cause, dict):
            message = cause.get("errorMessage", cause_raw)
    except json.JSONDecodeError:
        pass
    message = str(message or "")
    head = message.split(":", 1)[0].strip()
    if head in ERRORS:
        detail = message.split(":", 1)[1].strip() if ":" in message else ""
        return head, detail[:300]
    if name in ERRORS:
        return name, message[:300]
    if (
        name in ("States.Timeout", "Sandbox.Timedout", "Lambda.Timeout")
        or "Task timed out" in message
    ):
        return "TIMEOUT", message[:300]
    return "INTERNAL", f"{name}: {message}"[:300]


def fail_step(state: dict[str, Any], deps: StepDeps) -> dict[str, Any]:
    aid = state["analysisId"]
    code, detail = error_code(state.get("error"))
    record = deps.repo.get_analysis(aid)
    stage = record.stage if record else "QUEUED"
    deps.repo.update_analysis(
        aid,
        status="FAILED",
        error={
            "code": code,
            "message": ERRORS[code].message,
            "stage": stage,
            "detail": detail,
            "retryable": ERRORS[code].retryable,
        },
    )
    deps.repo.update_take(state["sessionId"], state["takeSk"], status="FAILED")
    log_event(log, "analysis.failed", analysis_id=aid, code=code, stage=stage, detail=detail)
    return {"code": code, "stage": stage}
