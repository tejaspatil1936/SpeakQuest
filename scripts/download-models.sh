#!/usr/bin/env bash
# Download the local models into .models/ (gitignored):
#   - Vosk small English model (local word timestamps, ~40 MB)
#   - three Piper voices (synthetic dataset, ~190 MB)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODELS="$ROOT/.models"
VOSK="vosk-model-small-en-us-0.15"
VOSK_SHA256="30f26242c4eb449f948e42cb302dd7a686cb29a3423a8367f99ff41780942498"

mkdir -p "$MODELS/vosk" "$MODELS/piper"
if [[ ! -d "$MODELS/vosk/$VOSK" ]]; then
  tmp="$(mktemp -d)"
  curl -fsSL --retry 3 -o "$tmp/$VOSK.zip" "https://alphacephei.com/vosk/models/$VOSK.zip"
  echo "$VOSK_SHA256  $tmp/$VOSK.zip" | sha256sum -c -
  unzip -q "$tmp/$VOSK.zip" -d "$MODELS/vosk"
  rm -rf "$tmp"
fi
"$ROOT/.venv/bin/python" -m piper.download_voices --download-dir "$MODELS/piper" \
  en_US-lessac-medium en_US-ryan-medium en_US-amy-medium
echo "models ready in $MODELS"
