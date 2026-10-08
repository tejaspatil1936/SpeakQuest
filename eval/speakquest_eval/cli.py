"""``speakquest-eval``: generate the dataset, run the evaluation, write reports."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _paths(args: argparse.Namespace) -> tuple[Path, Path, Path]:
    return Path(args.audio), Path(args.annotations), Path(args.cache)


def cmd_generate(args: argparse.Namespace) -> int:
    from speakquest_eval.synth import generate  # noqa: PLC0415 - needs the fixtures extra

    audio, annotations, _ = _paths(args)
    rows = generate(audio, annotations, Path(args.models) / "piper", only=args.only or ())
    if not args.only:
        manifest = ROOT / "data" / "manifest.csv"
        with manifest.open("w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        print(f"wrote {manifest}")
    print(f"generated {len(rows)} clips into {audio}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    from speakquest_eval.harness import Paths, evaluate, to_markdown  # noqa: PLC0415

    audio, annotations, cache = _paths(args)
    report = evaluate(args.split, args.aligner, Paths(audio, annotations, cache))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stem = f"{args.aligner.replace(':', '_')}-{args.split}"
    (out / f"{stem}.json").write_text(json.dumps(report, indent=2) + "\n")
    (out / f"{stem}.md").write_text(to_markdown(report))
    m = report["micro"]
    print(
        f"{stem}: precision={m['precision']} recall={m['recall']} "
        f"fp/min={report['fp_per_minute']} boundary_median_ms="
        f"{report['boundary_error']['median_ms']} -> {out / stem}.md"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="speakquest-eval")
    parser.add_argument("--audio", default=str(ROOT / "data" / "audio"))
    parser.add_argument("--annotations", default=str(ROOT / "data" / "annotations"))
    parser.add_argument("--cache", default=str(ROOT / "data" / "generated"))
    parser.add_argument("--models", default=str(ROOT / ".models"))
    sub = parser.add_subparsers(dest="cmd", required=True)
    gen = sub.add_parser("generate", help="synthesise clips and annotations")
    gen.add_argument("--only", nargs="*", help="challenge ids")
    gen.set_defaults(fn=cmd_generate)
    run = sub.add_parser("run", help="evaluate detection on a split")
    run.add_argument("--split", choices=["dev", "heldout", "all"], default="heldout")
    run.add_argument("--aligner", default="vosk")
    run.add_argument("--out", default=str(ROOT / "eval" / "reports"))
    run.set_defaults(fn=cmd_run)
    args = parser.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    sys.exit(main())
