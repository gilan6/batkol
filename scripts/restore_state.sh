#!/usr/bin/env bash
# Restore the working state of a new session. Data never lives in git:
#   inputs  gdrive:batkol/        (read-only: audiobooks, EPUBs, Pimsleur)
#   state   gdrive:batkol-out/state/  (indexes, stage caches, clip bank, repaired text, lesson data)
#   outputs gdrive:batkol-out/HP/, 50l/  (audio for listening; sidecars and reports in */meta/)
# Usage: bash scripts/restore_state.sh [chapter ...]   (chapter ids from batkol/sources_local.py; default ch01)
set -euo pipefail
W="$HOME/work"
mkdir -p "$W/in/pims" "$W/cache" "$W/tts" "$W/logs"
cd "$(dirname "$0")/.."

echo "[1/4] python env"
uv sync -q

echo "[2/4] state from Drive"
rclone copy gdrive:batkol-out/state/ "$W/" 2>&1 | grep -v NOTICE || true

echo "[3/4] chapter inputs (audio + EPUBs, paths from batkol/sources_local.py) + Pimsleur Lesson 01"
for ch in "${@:-ch01}"; do
  uv run python -m batkol.sources fetch "$ch"
done
[ -f "$W/in/pims/Lesson01.mp3" ] || rclone copyto "gdrive:$(uv run python -c 'from batkol.sources import PIMS_L01; print(PIMS_L01)')" "$W/in/pims/Lesson01.mp3" 2>&1 | grep -v NOTICE || true

echo "[4/4] English TTS voice (Piper, free; fallback only)"
for f in en_GB-alan-medium.onnx en_GB-alan-medium.onnx.json; do
  [ -f "$W/tts/$f" ] || curl -sSL -o "$W/tts/$f" "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium/$f"
done
ls "$W/index" 2>/dev/null && echo "restored. 16 kHz audio caches rebuild on first use (~20 s each)."
