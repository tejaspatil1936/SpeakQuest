"""Static checks that tie the Terraform and the Python code together."""

from __future__ import annotations

import importlib
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INFRA = ROOT / "infra"
ASL = INFRA / "modules" / "workflow" / "definition.asl.json"


def _asl() -> dict:
    text = ASL.read_text().replace("${max_polls}", "40")
    for var in ("worker_arn", "explain_arn", "persist_arn", "bucket", "name_prefix"):
        text = text.replace("${" + var + "}", f"<{var}>")
    assert "${" not in text, "unsubstituted template variable in the ASL"
    return json.loads(text)


def test_state_machine_is_well_formed() -> None:
    asl = _asl()
    states = asl["States"]
    targets = {asl["StartAt"]}
    for name, st in states.items():
        for key in ("Next", "Default"):
            if key in st:
                targets.add(st[key])
        targets |= {c["Next"] for c in st.get("Choices", [])}
        targets |= {c["Next"] for c in st.get("Catch", [])}
        if st["Type"] == "Task" and name != "MarkFailed":
            assert st.get("Catch"), f"{name} has no Catch"
            assert any("States.ALL" in c["ErrorEquals"] for c in st["Catch"]), name
    assert targets <= set(states), targets - set(states)
    assert set(states) - targets == set(), f"unreachable: {set(states) - targets}"
    # The design's order and polling budget.
    order = ["Normalize", "StartTranscribe", "InitPoll", "WaitTranscribe", "CheckTranscribe"]
    assert [asl["StartAt"], *[states[s]["Next"] for s in order[:-1]]] == order
    assert states["WaitTranscribe"]["Seconds"] == 5
    poll_rule = states["TranscribeDone?"]["Choices"][2]
    assert poll_rule["NumericGreaterThanEquals"] == 40
    # Explain failures continue to Persist; everything else goes to MarkFailed.
    assert states["Explain"]["Catch"][0]["Next"] == "Persist"
    for name in ("Normalize", "StartTranscribe", "CheckTranscribe", "Analyze", "Persist"):
        assert states[name]["Catch"][0]["Next"] == "MarkFailed"


def test_lambda_payload_steps_match_handlers() -> None:
    states = _asl()["States"]
    steps = {
        s["Parameters"]["Payload"].get("step")
        for s in states.values()
        if s.get("Resource") == "arn:aws:states:::lambda:invoke"
    }
    assert steps == {"normalize", "analyze", None, "persist", "fail"}


def test_terraform_handlers_resolve_to_python_functions() -> None:
    handlers = set()
    for tf in INFRA.rglob("*.tf"):
        handlers |= set(re.findall(r'handler\s*=\s*"([\w.]+)"', tf.read_text()))
    dockerfile = (ROOT / "services/worker/Dockerfile").read_text()
    handlers |= set(re.findall(r'CMD \["([\w.]+)"\]', dockerfile))
    assert len(handlers) == 4
    for dotted in handlers:
        module, func = dotted.rsplit(".", 1)
        assert callable(getattr(importlib.import_module(module), func)), dotted


@pytest.mark.parametrize("module", ["api", "worker", "workflow"])
def test_every_function_has_a_terraform_log_group(module: str) -> None:
    text = (INFRA / "modules" / module / "main.tf").read_text()
    functions = len(re.findall(r'resource "aws_lambda_function"', text))
    lambda_groups = len(re.findall(r'name\s+=\s+"/aws/lambda/', text))
    assert functions == lambda_groups
    assert "retention_in_days = var.log_retention_days" in text
    assert text.count("depends_on") >= functions


def test_destroy_is_never_blocked_by_data() -> None:
    mods = INFRA / "modules"
    assert "force_destroy = true" in (mods / "storage/main.tf").read_text()
    assert "force_delete         = true" in (mods / "registry/main.tf").read_text()
    assert "deletion_protection_enabled = false" in (mods / "data/main.tf").read_text()
    everything = "\n".join(p.read_text() for p in INFRA.rglob("*.tf"))
    for forbidden in (
        "aws_kms_key",
        "aws_secretsmanager",
        "aws_nat_gateway",
        "aws_eip",
        "aws_db_instance",
        "aws_opensearch",
        "aws_bedrock_model_invocation",
    ):
        assert forbidden not in everything, forbidden


def test_verify_zero_checks_every_log_group_prefix() -> None:
    script = (ROOT / "scripts" / "verify-zero.sh").read_text()
    everything = "\n".join(p.read_text() for p in INFRA.rglob("*.tf"))
    for prefix in set(re.findall(r'name\s+=\s+"(/aws/[a-z]+(?:/[a-z]+)?)/', everything)):
        assert prefix in script, f"verify-zero.sh does not check {prefix}"
