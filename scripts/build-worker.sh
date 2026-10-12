#!/usr/bin/env bash
# Build the worker Lambda image. Usage: scripts/build-worker.sh [image:tag]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE="${1:-speakquest-worker:local}"
mkdir -p "$ROOT/build"
# Worker dependencies with hashes, from the lockfile (no dev tools, no boto3:
# the Lambda base image provides it).
uv export --frozen --no-dev --extra worker --no-emit-project --format requirements-txt \
  --project "$ROOT" > "$ROOT/build/worker-requirements.txt"
docker build --platform linux/amd64 -f "$ROOT/services/worker/Dockerfile" -t "$IMAGE" "$ROOT"
docker image inspect "$IMAGE" --format 'image {{.Id}} size {{.Size}}' \
  | awk '{printf "%s %s size %.0f MB\n", $1, substr($2,1,19), $4/1048576}'
