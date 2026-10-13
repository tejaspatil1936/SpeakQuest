"""``speakquest-cloud``: operator commands against a deployed environment.

    speakquest-cloud seed [--aligner transcribe|vosk]   # used by `make seed`

Bucket, table and region come from ``terraform output -json`` (or flags),
so nothing is hard-coded. AWS credentials come from the usual SDK chain.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from speakquest.storage import S3Storage
from speakquest.timing import Aligner, TranscribeJobAligner, get_aligner
from speakquest_api.repository import DynamoRepository
from speakquest_api.seed import seed

ROOT = Path(__file__).resolve().parents[3]


def terraform_outputs(infra: Path) -> dict[str, str]:
    raw = subprocess.run(
        ["terraform", f"-chdir={infra}", "output", "-json"],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    ).stdout
    return {k: v["value"] for k, v in json.loads(raw).items() if v.get("value") is not None}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="speakquest-cloud")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sd = sub.add_parser("seed", help="upload and pre-analyse reference takes")
    sd.add_argument("--aligner", default="transcribe", choices=["transcribe", "vosk", "whisper"])
    sd.add_argument("--audio-dir", default=str(ROOT / "data" / "audio"))
    sd.add_argument("--only", nargs="*", default=[])
    sd.add_argument("--bucket")
    sd.add_argument("--table")
    sd.add_argument("--region")
    sd.add_argument("--infra", default=str(ROOT / "infra"))
    args = parser.parse_args(argv)

    outputs = (
        {} if (args.bucket and args.table and args.region) else terraform_outputs(Path(args.infra))
    )
    bucket = args.bucket or outputs["bucket_name"]
    table = args.table or outputs["table_name"]
    region = args.region or outputs.get("region", "us-east-1")
    storage = S3Storage(bucket, region=region)
    repo = DynamoRepository(table, region=region)
    aligner: Aligner = (
        TranscribeJobAligner(bucket, job_prefix=table, region=region)
        if args.aligner == "transcribe"
        else get_aligner(args.aligner)
    )
    done = seed(storage, repo, aligner, Path(args.audio_dir), args.only)
    print(f"seeded {len(done)} challenges into {bucket} / {table}: {', '.join(done)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
