"""Export the Pydantic contracts as JSON Schema for the frontend.

Usage: python scripts/export_schemas.py [--check]

``--check`` exits non-zero when the committed schema is stale (used in CI).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import TypeAdapter

from speakquest import contracts as c

OUT = Path(__file__).resolve().parents[1] / "contracts" / "schema.json"

EXPORTED = {
    "AnalysisResult": c.AnalysisResult,
    "Challenge": c.Challenge,
    "ChallengeList": c.ChallengeList,
    "CreateUploadRequest": c.CreateUploadRequest,
    "CreateUploadResponse": c.CreateUploadResponse,
    "CreateAnalysisRequest": c.CreateAnalysisRequest,
    "CreateAnalysisResponse": c.CreateAnalysisResponse,
    "AnalysisStatusResponse": c.AnalysisStatusResponse,
    "AnalysisResultResponse": c.AnalysisResultResponse,
    "ProgressResponse": c.ProgressResponse,
    "ErrorResponse": c.ErrorResponse,
}


def build() -> str:
    defs: dict[str, object] = {}
    roots: dict[str, object] = {}
    for name, model in EXPORTED.items():
        schema = TypeAdapter(model).json_schema(ref_template="#/$defs/{model}")
        defs.update(schema.pop("$defs", {}))
        defs[name] = schema
        roots[name] = {"$ref": f"#/$defs/{name}"}
    doc = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://speakquest.dev/contracts/schema.json",
        "title": "SpeakQuest contracts",
        "description": "Generated from services/worker/speakquest/contracts.py. Do not edit.",
        "x-schema-version": c.SCHEMA_VERSION,
        "properties": roots,
        "$defs": dict(sorted(defs.items())),
    }
    return json.dumps(doc, indent=2, sort_keys=False) + "\n"


def main() -> int:
    text = build()
    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text() != text:
            print(f"{OUT} is stale; run `make contracts`", file=sys.stderr)
            return 1
        print("contracts up to date")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text)
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
