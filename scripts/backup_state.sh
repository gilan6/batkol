#!/usr/bin/env bash
# Save every costly byproduct of ~/work to Drive (user-approved target), so no
# audio pass, model pass or verdict is ever recomputed or lost with the container.
# Not saved (cheap or available elsewhere): 16 kHz decode caches (~20 s each), inputs
# (gdrive:batkol), outputs (gdrive:batkol-out/HP, 50l), logs, models (re-downloaded from HF).
set -euo pipefail
cd "$HOME/work"
rclone copy . gdrive:batkol-out/state/ \
  --include "index/**" --include "bank/**" --include "learner/**" --include "text/**" \
  --include "{ch,b?ch}*/*.json" --include "{ch,b?ch}*/*.jsonl" --include "{ch,b?ch}*/*.npy" --include "{ch,b?ch}*/*.npz" --include "{ch,b?ch}*/*.md" \
  --include "{ch,b?ch}*/drill/*.json" --include "{ch,b?ch}*/drill/*.md" \
  --include "ch*/v1/**" --include "pims*/**" --include "lesson*/*.json" 2>&1 | grep -v NOTICE || true
rclone size gdrive:batkol-out/state/ 2>&1 | grep -v NOTICE
