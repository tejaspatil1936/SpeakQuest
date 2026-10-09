"""Grounding validator for model-written coaching (system design §6).

The language model may phrase things; it may not invent facts. An output is
accepted only if:

* it parses as ``{"items": [{"finding_id", "headline", "why", "drill"}]}``;
* every ``finding_id`` exists in the input, and each finding is covered
  exactly once;
* every number in the text appears in *that* finding's evidence (compared at
  the precision the text uses, so 1.42 may be written 1.4) or in the script
  itself (quoting "30 days" is not inventing data);
* no timestamps appear — the UI renders times from the findings.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from pydantic import ValidationError

from speakquest.contracts import CoachingItem, CoachingOutput, Finding

_NUMBER = re.compile(r"(?<![\w.])-?\d+(?:[.,]\d+)*(?![\w])|(?<![\w.])-?\d+(?:\.\d+)?(?=[x×%])")
_TIMESTAMP = re.compile(
    r"\b\d{1,2}:\d{2}(?::\d{2})?\b"  # 0:12, 1:02:03
    r"|\b(?:at|around|near|from|until|by)\s+(?:the\s+)?\d+(?:\.\d+)?\s*(?:s|sec|secs|seconds?)\b"
    r"|\b\d+(?:\.\d+)?\s*(?:s|sec|secs|seconds?)\s+(?:in|into|mark)\b"
    r"|\btimestamp",
    re.IGNORECASE,
)


# Advice that contradicts the finding's direction (telling a speaker who
# dragged to slow down) is as wrong as an invented number.
_CONTRADICTIONS: dict[str, tuple[re.Pattern[str], str]] = {
    "DRAG": (
        re.compile(r"\bslow(?:ing)?\s+(?:it\s+|things\s+)?down\b", re.IGNORECASE),
        "tells a speaker who dragged to slow down",
    ),
    "RUSH": (
        re.compile(r"\bspeed(?:ing)?\s+(?:it\s+|things\s+)?up\b", re.IGNORECASE),
        "tells a speaker who rushed to speed up",
    ),
}


@dataclass(frozen=True)
class Verdict:
    output: CoachingOutput | None
    errors: list[str]

    @property
    def ok(self) -> bool:
        return self.output is not None and not self.errors


def extract_json(text: str) -> object:
    """Parse a JSON object, tolerating code fences or prose around it."""
    stripped = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", stripped, re.DOTALL)
    if fence:
        stripped = fence.group(1)
    else:
        first, last = stripped.find("{"), stripped.rfind("}")
        if first != -1 and last > first:
            stripped = stripped[first : last + 1]
    return json.loads(stripped)


def _decimals(token: str) -> int:
    return len(token.split(".", 1)[1]) if "." in token else 0


def _numbers_in(text: str) -> list[str]:
    out: list[str] = []
    for m in _NUMBER.finditer(text):
        token = m.group(0)
        # "1,000" is a thousands separator; "3,5" is two numbers in a list.
        if re.fullmatch(r"-?\d{1,3}(?:,\d{3})+", token):
            token = token.replace(",", "")
        out.extend(t for t in token.split(",") if t)
    return out


def _evidence_numbers(values: Iterable[object]) -> list[Decimal]:
    nums: list[Decimal] = []
    for v in values:
        if isinstance(v, bool):
            continue
        if isinstance(v, int | float):
            nums.append(Decimal(str(v)))
        elif isinstance(v, str):
            for tok in _numbers_in(v):
                try:
                    nums.append(Decimal(tok))
                except InvalidOperation:
                    continue
    return nums


def _grounded(token: str, allowed: Sequence[Decimal]) -> bool:
    try:
        value = Decimal(token)
    except InvalidOperation:
        return False
    places = Decimal(1).scaleb(-_decimals(token))
    for a in allowed:
        if a == value:
            return True
        if a.quantize(places, rounding=ROUND_HALF_UP) == value:
            return True
    return False


def validate(raw: str | object, findings: Sequence[Finding], script: str) -> Verdict:
    errors: list[str] = []
    try:
        data = extract_json(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, ValueError) as exc:
        return Verdict(None, [f"output is not valid JSON ({exc.__class__.__name__})"])
    try:
        output = CoachingOutput.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first["loc"])
        return Verdict(None, [f"output does not match the schema at '{loc}': {first['msg']}"])

    by_id = {f.id: f for f in findings}
    seen: dict[str, int] = {}
    script_numbers = _evidence_numbers([script])
    for item in output.items:
        if item.finding_id not in by_id:
            errors.append(f"unknown finding_id '{item.finding_id}'")
            continue
        seen[item.finding_id] = seen.get(item.finding_id, 0) + 1
        finding = by_id[item.finding_id]
        allowed = _evidence_numbers(finding.evidence.values()) + script_numbers
        contradiction = _CONTRADICTIONS.get(finding.code)
        for field in ("headline", "why", "drill"):
            text = getattr(item, field)
            if contradiction and contradiction[0].search(text):
                errors.append(f"{item.finding_id}.{field} {contradiction[1]}")
            if _TIMESTAMP.search(text):
                errors.append(f"{item.finding_id}.{field} contains a timestamp")
            for token in _numbers_in(text):
                if not _grounded(token, allowed):
                    errors.append(
                        f"{item.finding_id}.{field} uses the number {token}, which is not in "
                        "that finding's evidence"
                    )
    for fid, count in seen.items():
        if count > 1:
            errors.append(f"finding_id '{fid}' appears {count} times")
    missing = [f.id for f in findings if f.id not in seen]
    if missing:
        errors.append(f"missing items for findings: {', '.join(missing)}")
    return Verdict(output if not errors else None, errors)


def ordered(items: Sequence[CoachingItem], findings: Sequence[Finding]) -> list[CoachingItem]:
    rank = {f.id: i for i, f in enumerate(findings)}
    return sorted(items, key=lambda it: rank.get(it.finding_id, len(rank)))
