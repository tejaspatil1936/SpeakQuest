#!/usr/bin/env bash
# Build the zip-Lambda bundle (api, explain, persist) into build/lambda/.
# Terraform's archive_file zips the directory. Dependencies are resolved for
# the Lambda runtime (Python 3.12, manylinux x86_64), not for this machine.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/build/lambda"

rm -rf "$OUT"
mkdir -p "$OUT"

# Pin to the versions in uv.lock so the Lambda runs what the tests ran.
uv export --frozen --no-hashes --no-dev --no-emit-project --format requirements-txt \
  --project "$ROOT" > "$ROOT/build/lambda-requirements.txt"
grep -E '^(pydantic|pydantic-core|annotated-types|typing-extensions|typing-inspection|pyyaml)==' \
  "$ROOT/build/lambda-requirements.txt" > "$ROOT/build/lambda-requirements.min.txt"

uv pip install --quiet --target "$OUT" --python-version 3.12 \
  --python-platform x86_64-manylinux2014 --only-binary :all: \
  -r "$ROOT/build/lambda-requirements.min.txt"

cp -r "$ROOT/services/worker/speakquest" "$ROOT/services/api/speakquest_api" \
  "$ROOT/services/explain/speakquest_explain" "$OUT/"
# The local runtime never runs in Lambda.
rm -rf "$OUT/speakquest_api/local"
find "$OUT" -name '__pycache__' -type d -prune -exec rm -rf {} +

du -sh "$OUT" | awk '{print "lambda bundle: " $1}'
