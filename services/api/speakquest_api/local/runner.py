"""In-process stand-in for the Step Functions state machine.

Runs the same step functions in the same order with the same failure
semantics as ``infra/modules/workflow/definition.asl.json``:

    Normalize → Transcribe → Analyze → Explain (failure tolerated) → Persist
    any other failure → Fail (status FAILED + code + stage)

The only substitution is transcription: a local aligner replaces the
StartTranscriptionJob/GetTranscriptionJob polling states.
"""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from speakquest.errors import AnalysisError
from speakquest.logs import get_logger, log_event
from speakquest.timing import Aligner
from speakquest_api.steps import StepDeps, explain_step, fail_step, persist_step

log = get_logger("speakquest.local")


def _as_sfn_error(exc: BaseException) -> dict[str, str]:
    """Shape an exception the way Step Functions hands it to a Catch."""
    if isinstance(exc, AnalysisError):
        return {
            "Error": "AnalysisError",
            "Cause": json.dumps({"errorMessage": str(exc), "errorType": "AnalysisError"}),
        }
    return {
        "Error": exc.__class__.__name__,
        "Cause": json.dumps({"errorMessage": str(exc)[:500], "errorType": exc.__class__.__name__}),
    }


def run_workflow(state: dict[str, Any], deps: StepDeps, aligner: Aligner) -> dict[str, Any]:
    from speakquest_api import worker_steps  # noqa: PLC0415 - audio stack

    started = time.monotonic()
    try:
        state["normalize"] = worker_steps.normalize_step(state, deps)
        state["transcribe"] = worker_steps.transcribe_local_step(state, deps, aligner)
        state["transcriptKey"] = state["transcribe"]["transcriptKey"]
        state["analyze"] = worker_steps.analyze_step(state, deps)
        try:
            state["explain"] = explain_step(state, deps)
        except Exception as exc:  # the design tolerates Explain failures
            log.exception("local.explain_failed", extra={"analysis_id": state["analysisId"]})
            state["explainError"] = _as_sfn_error(exc)
        state["persist"] = persist_step(state, deps)
    except Exception as exc:  # every other failure goes to the Fail step
        state["error"] = _as_sfn_error(exc)
        try:
            state["failed"] = fail_step(state, deps)
        except Exception:
            log.exception("local.fail_step_failed", extra={"analysis_id": state["analysisId"]})
    log_event(
        log,
        "local.workflow_done",
        analysis_id=state["analysisId"],
        ok="persist" in state,
        ms=round((time.monotonic() - started) * 1000),
    )
    return state


class LocalWorkflow:
    """WorkflowStarter that queues executions on a small thread pool.

    One worker by default: the audio stack is memory-hungry and a laptop
    running the whole system should not analyse several takes at once.
    """

    def __init__(self, deps: StepDeps, aligner: Aligner, workers: int = 1):
        self.deps = deps
        self.aligner = aligner
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="sq-workflow")
        self.futures: dict[str, Future[dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def start(self, analysis_id: str, payload: dict[str, Any]) -> str:
        with self._lock:
            if analysis_id not in self.futures:
                self.futures[analysis_id] = self.pool.submit(
                    run_workflow, dict(payload), self.deps, self.aligner
                )
        return f"local:{analysis_id}"

    def wait(self, analysis_id: str, timeout: float = 120) -> dict[str, Any]:
        return self.futures[analysis_id].result(timeout=timeout)

    def shutdown(self) -> None:
        self.pool.shutdown(wait=False, cancel_futures=True)
