from __future__ import annotations

import json
import os

import pytest

from speakquest.contracts import Finding
from speakquest_explain.coach import DEFAULT_MODEL_ID, BedrockClient, PermanentModelError, coach
from speakquest_explain.template import template_items
from speakquest_explain.validator import extract_json, validate

SCRIPT = "We ship the final build before the deadline. Try it free for 30 days."


def F(fid: str, code: str, evidence: dict, words: list[str] | None = None) -> Finding:
    dims = {
        "RUSH": "pace",
        "DRAG": "pace",
        "HESITATE": "pauses",
        "MONO": "pitch",
        "FADE": "volume",
        "SKIP": "accuracy",
        "FILLER": "accuracy",
    }
    return Finding(
        id=fid,
        code=code,
        dimension=dims[code],
        start=1.0,
        end=2.0,
        words=words if words is not None else ["before", "the", "deadline"],
        evidence=evidence,
        severity=2,
        rubric_version="1.0.0",
    )


FINDINGS = [
    F("f1", "RUSH", {"rate_ratio": 1.42, "syllables_per_s": 6.1, "reference_syllables_per_s": 4.3}),
    F("f2", "HESITATE", {"pause_ms": 970, "reference_pause_ms": 140}, ["build", "before"]),
]


def item(fid: str, headline: str, why: str = "It matters.", drill: str = "Read it again.") -> dict:
    return {"finding_id": fid, "headline": headline, "why": why, "drill": drill}


def good() -> str:
    return json.dumps(
        {
            "items": [
                item("f1", "You rushed 'before the deadline' — 1.4× the reference pace."),
                item("f2", "You stalled 970 ms before 'before'.", "The reference pauses 140 ms."),
            ]
        }
    )


def test_valid_output_passes_and_rounding_is_allowed() -> None:
    v = validate(good(), FINDINGS, SCRIPT)
    assert v.ok, v.errors


def test_code_fences_and_prose_are_tolerated() -> None:
    assert extract_json('Sure!\n```json\n{"items": []}\n```') == {"items": []}
    assert extract_json('Here: {"items": []} done') == {"items": []}


@pytest.mark.parametrize(
    ("payload", "fragment"),
    [
        ("not json at all", "not valid JSON"),
        (json.dumps({"notes": []}), "schema"),
        (
            json.dumps({"items": [item("f1", "x"), item("f9", "y"), item("f2", "z")]}),
            "unknown finding_id 'f9'",
        ),
        (json.dumps({"items": [item("f1", "x")]}), "missing items for findings: f2"),
        (
            json.dumps({"items": [item("f1", "x"), item("f1", "y"), item("f2", "z")]}),
            "appears 2 times",
        ),
        (
            json.dumps({"items": [item("f1", "You were 42% too fast."), item("f2", "ok")]}),
            "number 42",
        ),
        (
            json.dumps({"items": [item("f1", "x", "Pace was 1.9× too quick."), item("f2", "ok")]}),
            "number 1.9",
        ),
        (json.dumps({"items": [item("f1", "At 0:12 you rushed."), item("f2", "ok")]}), "timestamp"),
        (
            json.dumps({"items": [item("f1", "Rushed at 4.2 seconds."), item("f2", "ok")]}),
            "timestamp",
        ),
        (
            json.dumps(
                {
                    "items": [
                        item("f1", "x"),
                        item("f2", "Paused 140 ms like the ref; drill 3 reps."),
                    ]
                }
            ),
            "number 3",
        ),
    ],
)
def test_rejections(payload: str, fragment: str) -> None:
    v = validate(payload, FINDINGS, SCRIPT)
    assert not v.ok
    assert any(fragment in e for e in v.errors), v.errors


def test_advice_must_match_the_finding_direction() -> None:
    findings = [F("f1", "DRAG", {"rate_ratio": 0.6}), F("f2", "RUSH", {"rate_ratio": 1.5})]
    payload = json.dumps(
        {
            "items": [
                item("f1", "Slow down on 'the deadline'."),
                item("f2", "ok", drill="Speed it up a little."),
            ]
        }
    )
    errors = validate(payload, findings, SCRIPT).errors
    assert any("dragged to slow down" in e for e in errors)
    assert any("rushed to speed up" in e for e in errors)
    fine = json.dumps(
        {
            "items": [
                item("f1", "Move 'the deadline' along."),
                item("f2", "Slow down on 'the deadline'."),
            ]
        }
    )
    assert validate(fine, findings, SCRIPT).ok


def test_numbers_from_another_finding_are_not_allowed() -> None:
    payload = json.dumps({"items": [item("f1", "You paused 970 ms."), item("f2", "ok")]})
    assert not validate(payload, FINDINGS, SCRIPT).ok


def test_quoting_script_numbers_is_allowed() -> None:
    payload = json.dumps(
        {"items": [item("f1", "Don't rush 'free for 30 days'."), item("f2", "ok")]}
    )
    assert validate(payload, FINDINGS, SCRIPT).ok


def test_template_covers_every_code_and_passes_the_validator() -> None:
    findings = [
        *FINDINGS,
        F(
            "f3",
            "DRAG",
            {"rate_ratio": 0.62, "syllables_per_s": 3.0, "reference_syllables_per_s": 4.8},
        ),
        F("f4", "MONO", {"pitch_sd_st": 0.8, "reference_pitch_sd_st": 3.1, "ratio": 0.26}),
        F("f5", "MONO", {"ratio": 0.2, "scope": "whole take"}, []),
        F("f6", "FADE", {"drop_db": 9.4, "reference_drop_db": 1.1}),
        F("f7", "SKIP", {"skipped_words": 2}, ["final", "build"]),
        F("f8", "FILLER", {"count": 1, "kind": "filler"}, ["um"]),
        F("f9", "FILLER", {"vocalization_ms": 420, "kind": "vocalization"}, []),
        F("f10", "FILLER", {"count": 1, "kind": "repeat"}, ["the"]),
        F("f11", "RUSH", {"rate_ratio": 1.5, "scope": "whole take"}, []),
    ]
    items = template_items(findings)
    assert [i.finding_id for i in items] == [f.id for f in findings]
    v = validate({"items": [i.model_dump() for i in items]}, findings, SCRIPT)
    assert v.ok, v.errors
    assert "1.42× the reference pace" in items[0].headline
    assert "970 ms" in items[1].headline


class Scripted:
    model_id = "fake-model"

    def __init__(self, *responses: object):
        self.responses = list(responses)
        self.calls: list[str] = []

    def complete(self, system: str, user: str) -> str:
        self.calls.append(user)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return str(r)


def test_coach_accepts_first_valid_answer() -> None:
    c = coach(FINDINGS, SCRIPT, Scripted(good()))
    assert c.source == "bedrock" and c.attempts == 1 and c.model_id == "fake-model"
    assert [i.finding_id for i in c.items] == ["f1", "f2"]


def test_coach_retries_once_with_feedback_then_succeeds() -> None:
    bad = json.dumps({"items": [item("f1", "You were 42% fast."), item("f2", "ok")]})
    client = Scripted(bad, good())
    c = coach(FINDINGS, SCRIPT, client)
    assert c.source == "bedrock" and c.attempts == 2
    assert "previous answer was rejected" in client.calls[1]
    assert any("42" in r for r in c.rejections)


def test_coach_falls_back_to_template_after_two_failures() -> None:
    c = coach(FINDINGS, SCRIPT, Scripted("nope", "still nope"))
    assert c.source == "template" and c.attempts == 2
    assert len(c.items) == 2 and len(c.rejections) == 2


def test_coach_does_not_retry_permanent_errors() -> None:
    client = Scripted(PermanentModelError("AccessDeniedException: no access"), good())
    c = coach(FINDINGS, SCRIPT, client)
    assert c.source == "template" and c.attempts == 1 and len(client.calls) == 1
    assert "model unavailable" in c.rejections[0]


def test_coach_survives_transport_errors() -> None:
    c = coach(FINDINGS, SCRIPT, Scripted(TimeoutError("read timeout"), good()))
    assert c.source == "bedrock" and c.attempts == 2


def test_no_findings_means_no_model_call() -> None:
    client = Scripted()
    c = coach([], SCRIPT, client)
    assert c.items == [] and c.attempts == 0 and client.calls == []


def test_no_client_uses_template() -> None:
    c = coach(FINDINGS, SCRIPT, None)
    assert c.source == "template" and c.model_id is None


@pytest.mark.live_aws
def test_live_bedrock_output_is_grounded() -> None:
    client = BedrockClient(model_id=os.environ.get("SPEAKQUEST_BEDROCK_MODEL_ID", DEFAULT_MODEL_ID))
    c = coach(FINDINGS, SCRIPT, client)
    assert c.source == "bedrock", c.rejections
    assert validate({"items": [i.model_dump() for i in c.items]}, FINDINGS, SCRIPT).ok
