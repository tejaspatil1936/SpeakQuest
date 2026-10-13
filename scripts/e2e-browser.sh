#!/usr/bin/env bash
# Real-browser end-to-end run against the local backend (make e2e).
#
# Builds a fake-microphone WAV (4.5 s lead-in + a synthetic flawed take),
# seeds a throwaway local backend, starts it, builds the web app against it
# and drives headless Chrome through record → upload → analysis → playback.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$ROOT/build/e2e"
CLIP="${CLIP:-deadline__flawed-2}"
PORT="${PORT:-8787}"
rm -rf "$WORK" && mkdir -p "$WORK"

ffmpeg -loglevel error -y -f lavfi -t 4.5 -i anullsrc=r=48000:cl=mono \
  -i "$ROOT/data/audio/$CLIP.wav" -f lavfi -t 2 -i anullsrc=r=48000:cl=mono \
  -filter_complex "[1:a]aresample=48000,aformat=channel_layouts=mono[t];[0:a][t][2:a]concat=n=3:v=0:a=1" \
  -c:a pcm_s16le "$WORK/mic.wav"
seconds="$(python3 -c "import json;print(round(json.load(open('$ROOT/data/annotations/$CLIP.json'))['duration_s']+4.5))")"
codes="$(python3 -c "import json;print(','.join(f['code'] for f in json.load(open('$ROOT/data/annotations/$CLIP.json'))['flaws']))")"
challenge="${CLIP%%__*}"

export SPEAKQUEST_LOCAL_DIR="$WORK/local" SPEAKQUEST_MODEL_DIR="$ROOT/.models"
export SPEAKQUEST_ALLOWED_ORIGINS="http://127.0.0.1:4174" SPEAKQUEST_LOCAL_BASE_URL="http://127.0.0.1:$PORT"
"$ROOT/.venv/bin/python" -m speakquest_api.local.server seed --only "$challenge" >/dev/null
"$ROOT/scripts/with-aws-env.sh" "$ROOT/.venv/bin/python" -m speakquest_api.local.server serve \
  --port "$PORT" > "$WORK/server.log" 2>&1 &
server=$!
trap 'kill $server 2>/dev/null || true' EXIT
for _ in $(seq 50); do curl -sf "http://127.0.0.1:$PORT/healthz" >/dev/null && break; sleep 0.2; done

(cd "$ROOT/web" && VITE_API_URL="http://127.0.0.1:$PORT" VITE_DEMO=0 npm run build >/dev/null)
cd "$ROOT/web"
API_URL="http://127.0.0.1:$PORT" MIC_WAV="$WORK/mic.wav" TAKE_SECONDS="$seconds" \
  CHALLENGE="$challenge" EXPECT_CODES="$codes" node scripts/e2e-local.mjs
