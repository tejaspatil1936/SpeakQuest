"""AWS Lambda entry points.

| Function                 | Package   | Handler                                  |
|--------------------------|-----------|------------------------------------------|
| ``speakquest-<env>-api``     | zip   | ``speakquest_api.lambdas.api_handler``     |
| ``speakquest-<env>-worker``  | image | ``speakquest_api.lambdas.worker_handler``  |
| ``speakquest-<env>-explain`` | zip   | ``speakquest_api.lambdas.explain_handler`` |
| ``speakquest-<env>-persist`` | zip   | ``speakquest_api.lambdas.persist_handler`` |

Clients are built once per container (cold start) from environment
variables. The worker steps are imported lazily so the zip functions never
import numpy.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from speakquest.errors import AnalysisError
from speakquest.storage import S3Storage
from speakquest_api.config import settings
from speakquest_api.handlers import Deps, StepFunctionsStarter, dispatch
from speakquest_api.http import Request
from speakquest_api.repository import DynamoRepository
from speakquest_api.steps import StepDeps, explain_step, fail_step, persist_step


@lru_cache(maxsize=1)
def _api_deps() -> Deps:
    cfg = settings()
    cfg.require_aws()
    return Deps(
        settings=cfg,
        storage=S3Storage(cfg.bucket, region=cfg.region),
        repo=DynamoRepository(cfg.table, region=cfg.region),
        workflow=StepFunctionsStarter(cfg.state_machine_arn, region=cfg.region),
    )


@lru_cache(maxsize=2)
def _step_deps(with_model: bool = False) -> StepDeps:
    cfg = settings()
    cfg.require_aws()
    model = None
    if with_model:
        from speakquest_explain.coach import client_from_env  # noqa: PLC0415

        model = client_from_env()
    return StepDeps(
        storage=S3Storage(cfg.bucket, region=cfg.region),
        repo=DynamoRepository(cfg.table, region=cfg.region),
        model=model,
    )


def api_handler(event: dict[str, Any], _context: Any = None) -> dict[str, Any]:
    return dispatch(Request.from_event(event), _api_deps())


def worker_handler(event: dict[str, Any], _context: Any = None) -> dict[str, Any]:
    from speakquest_api import worker_steps  # noqa: PLC0415 - numpy lives in the image only

    step = event.get("step")
    state = event.get("state", event)
    if step == "normalize":
        return worker_steps.normalize_step(state, _step_deps())
    if step == "analyze":
        return worker_steps.analyze_step(state, _step_deps())
    raise AnalysisError("INTERNAL", f"unknown worker step {step!r}")


def explain_handler(event: dict[str, Any], _context: Any = None) -> dict[str, Any]:
    return explain_step(event.get("state", event), _step_deps(with_model=True))


def persist_handler(event: dict[str, Any], _context: Any = None) -> dict[str, Any]:
    state = event.get("state", event)
    if event.get("step") == "fail":
        return fail_step(state, _step_deps())
    return persist_step(state, _step_deps())
