"""Grounded coaching: ask Bedrock, validate, retry once, else template.

The model sees only the findings JSON and the script (no audio). Its answer
is checked by :mod:`speakquest_explain.validator`; one corrective retry is
allowed, after which the deterministic template text is used. The model
never produces scores, findings, evidence or timestamps.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from speakquest.contracts import Coaching, Finding
from speakquest.logs import get_logger, log_event
from speakquest_explain.template import template_items
from speakquest_explain.validator import ordered, validate

log = get_logger("speakquest.explain")

# A small, fast model (system design §6). Amazon Nova 2 Lite is the default:
# on this project's account the Anthropic models require a use-case form that
# has not been submitted, and Nova 2 Lite gave the most accurate notes of the
# models that were reachable (docs/DECISIONS.md). Override with
# SPEAKQUEST_BEDROCK_MODEL_ID / var.bedrock_model_id.
DEFAULT_MODEL_ID = "us.amazon.nova-2-lite-v1:0"

SYSTEM_PROMPT = """You are a voice director giving notes on one recorded take of a script.

You receive measured findings as JSON. Each finding has an id, a flaw code, the script
words it covers and numeric evidence. Write one note per finding.

Rules — an automatic checker rejects any answer that breaks them:
1. Return only JSON: {"items":[{"finding_id":"f1","headline":"...","why":"...","drill":"..."}]}
   with exactly one item per finding, using the given ids.
2. Use digits only for numbers copied from that finding's evidence (you may round them to
   fewer decimals) or quoted from the script. Never compute new numbers, percentages or
   conversions. Write any other quantity in words ("three times").
3. Never mention times or timestamps (no "at 4.2 seconds", no "0:12"). The interface shows
   where each finding is.
4. Voice: direct, specific, second person, like a director's margin note. No praise, no
   emoji, no "great job". Headline ≤ 15 words naming the words affected; "why" is one or two
   sentences on why it matters to a listener; "drill" is one concrete exercise.

Flaw codes: RUSH = too fast (rate_ratio > 1 means faster than the reference; tell them to
take more time), DRAG = too slow (rate_ratio < 1; tell them to move it along),
HESITATE long pause (pause_ms vs reference_pause_ms), MONO flat pitch (semitone SD vs
reference), FADE trailing off (drop_db below the speaker's average), SKIP skipped words,
FILLER filler, repeat or extra word."""


class ModelClient(Protocol):
    model_id: str

    def complete(self, system: str, user: str) -> str: ...


class PermanentModelError(Exception):
    """Retrying cannot help (no model access, bad credentials, bad request)."""


@dataclass
class BedrockClient:
    model_id: str
    region: str | None = None
    max_tokens: int = 1500
    timeout_s: int = 25
    _client: Any = None

    def _bedrock(self) -> Any:
        if self._client is None:
            import boto3  # noqa: PLC0415
            from botocore.config import Config  # noqa: PLC0415

            self._client = boto3.client(
                "bedrock-runtime",
                region_name=self.region or os.environ.get("AWS_REGION", "us-east-1"),
                config=Config(
                    read_timeout=self.timeout_s,
                    connect_timeout=5,
                    retries={"max_attempts": 2, "mode": "standard"},
                ),
            )
        return self._client

    def complete(self, system: str, user: str) -> str:
        """One Converse call: works for any Bedrock text model (Claude, Nova, …)."""
        from botocore.exceptions import ClientError  # noqa: PLC0415

        try:
            resp = self._bedrock().converse(
                modelId=self.model_id,
                system=[{"text": system}],
                messages=[{"role": "user", "content": [{"text": user}]}],
                inferenceConfig={"maxTokens": self.max_tokens, "temperature": 0.2},
            )
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in (
                "AccessDeniedException",
                "ValidationException",
                "ResourceNotFoundException",
                "UnrecognizedClientException",
            ):
                raise PermanentModelError(f"{code}: {exc}") from exc
            raise
        blocks = resp.get("output", {}).get("message", {}).get("content", [])
        return "".join(str(b.get("text", "")) for b in blocks)


def _user_prompt(findings: Sequence[Finding], script: str) -> str:
    compact = [
        {
            "id": f.id,
            "code": f.code,
            "words": f.words,
            "evidence": f.evidence,
            "severity": f.severity,
        }
        for f in findings
    ]
    return (
        f"Script:\n{script}\n\nFindings:\n{json.dumps(compact, ensure_ascii=False)}\n\n"
        "Return the JSON now."
    )


def coach(findings: Sequence[Finding], script: str, client: ModelClient | None) -> Coaching:
    findings = list(findings)
    if not findings:
        return Coaching(source="template", model_id=None, items=[], attempts=0)
    rejections: list[str] = []
    attempts = 0
    if client is not None:
        user = _user_prompt(findings, script)
        for attempt in (1, 2):
            attempts = attempt
            started = time.monotonic()
            try:
                raw = client.complete(SYSTEM_PROMPT, user)
            except PermanentModelError as exc:
                rejections.append(f"model unavailable: {exc}"[:300])
                log_event(log, "explain.model_unavailable", error=str(exc)[:300])
                break
            except Exception as exc:  # any transport failure falls back
                rejections.append(f"model call failed: {exc.__class__.__name__}: {exc}"[:300])
                log_event(log, "explain.model_error", attempt=attempt, error=str(exc)[:300])
                continue
            verdict = validate(raw, findings, script)
            log_event(
                log,
                "explain.validated",
                attempt=attempt,
                ok=verdict.ok,
                errors=verdict.errors[:5],
                ms=round((time.monotonic() - started) * 1000),
            )
            if verdict.ok and verdict.output is not None:
                return Coaching(
                    source="bedrock",
                    model_id=client.model_id,
                    items=ordered(verdict.output.items, findings),
                    attempts=attempt,
                    rejections=rejections,
                )
            rejections.extend(verdict.errors[:10])
            user = (
                f"{_user_prompt(findings, script)}\n\nYour previous answer was rejected:\n- "
                + "\n- ".join(verdict.errors[:10])
                + "\nFix every problem and return the JSON only."
            )
    return Coaching(
        source="template",
        model_id=client.model_id if client else None,
        items=template_items(findings),
        attempts=attempts,
        rejections=rejections,
    )


def client_from_env() -> ModelClient | None:
    if os.environ.get("SPEAKQUEST_BEDROCK", "1") == "0":
        return None
    return BedrockClient(model_id=os.environ.get("SPEAKQUEST_BEDROCK_MODEL_ID", DEFAULT_MODEL_ID))
