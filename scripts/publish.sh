#!/usr/bin/env bash
# Put outputs for listening on Drive. Audio folders hold audio files only: each audio file goes to
# AUDIO_DIR, every other file (sidecar JSON, TSV, reports, README) to META_DIR, both under
# gdrive:batkol-out/ (the only place we write on Drive).
#   bash scripts/publish.sh HP/lessons HP/meta/lessons/lesson08 ~/work/lesson08/*
#   bash scripts/publish.sh HP/book2 HP/meta/book2/b2ch02 ~/work/b2ch02/drill/*.{mp3,tsv,md} ~/work/b2ch02/edition_*.md
#   bash scripts/publish.sh 50l/lessons 50l/meta/fl002 ~/work/fl002/*
set -euo pipefail
[ $# -ge 3 ] || { sed -n 2,7p "$0"; exit 2; }
audio=$1 meta=$2
shift 2
for f in "$@"; do
  [ -f "$f" ] || { echo "skipped (not a file): $f" >&2; continue; }
  case "${f,,}" in
    *.mp3|*.m4a|*.opus|*.ogg|*.wav|*.flac) dest=$audio ;;
    *) dest=$meta ;;
  esac
  rclone copyto "$f" "gdrive:batkol-out/$dest/$(basename "$f")" --log-level ERROR
  echo "$dest/$(basename "$f")"
done
