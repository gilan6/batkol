# Batkol

Formerly `hp-dutch-drills`: package `hpdrill`, Drive folders `hp-nl` and `hp-nl-out` (renamed 2026-10-27).
Older logs, reports and Drive output files may still name the old paths.

Pimsleur-style Dutch pronunciation drills cut from Harry Potter audiobooks (book 1; book 2 started).
- Dutch: one narrator, Jan Meng.
- English: Audible full cast.
- Instruction phrases ("frames"): Pimsleur Dutch I.

The user knows almost all the words. The goal is pronunciation through many
repetitions of natural speech, with English cues that make them translate first.

## Where it runs

The user's laptop: Windows 11 + WSL2 Ubuntu, x86_64, 16 GB RAM, no GPU. Everything runs on CPU.
Setup, verification and open decisions: `docs/local_plan.md`.
- The repo (`~/batkol`) and `~/work` live in the WSL filesystem, never under `/mnt/c` or `/mnt/g` (slow).
- `~/work` persists between sessions. Seed it once from Drive (`docs/local_plan.md` §4):
  ```bash
  bash scripts/restore_state.sh [chapter ...]   # ~/work from gdrive:batkol-out/state + inputs from gdrive:batkol
                                                # (chapter ids in batkol/sources_local.py; default ch01)
  ```
  After that, don't restore per session: it would only re-copy what is already there.
- Drive: Google Drive for desktop mounts it on Windows as `G:`; WSL mounts that at `/mnt/g` (`/etc/fstab`).
  `gdrive:` is an rclone alias remote for `/mnt/g/My Drive`, so code and scripts keep using `gdrive:`. No OAuth token.
  - `gdrive:` empty or missing: Drive for desktop is not running, or `/mnt/g` is not mounted
    (`sudo mount -t drvfs G: /mnt/g -o uid=1000,gid=1000`).
  - `/mnt/g` is slow and streams from Drive: never a working directory. Inputs are copied to `~/work` first.
  - Nothing enforces read-only any more (the old token did). Write only inside `gdrive:batkol-out/`;
    `gdrive:batkol/` is read-only input. Never delete anything on G:.
- WSL stops when Windows sleeps. Before a long run, ask the user to keep the laptop plugged in and awake.
- Cloud sessions are retired: their proxy blocks `download-r2.pytorch.org` (CPU torch wheels) and 50languages.com.

## Where things live

| What | Where | In git? |
|---|---|---|
| Code, docs, lesson specs (book-token ranges, no text) | this repo | yes |
| Inputs: audiobooks, EPUBs, Pimsleur | `gdrive:batkol/` (read-only); paths in `batkol/sources_local.py` (git-ignored; template `sources_local.example.py`) | never |
| State: indexes, stage caches, clip bank, repaired text | `~/work` (laptop), backed up to `gdrive:batkol-out/state/` | never |
| Outputs for listening: MP3, TSV, reports | `gdrive:batkol-out/poc/` | never |

- **No book text, audio or transcripts in git.** Write to Drive only inside `gdrive:batkol-out/`.
- After any costly step (audio pass, model pass, lesson build, verdicts), run `bash scripts/backup_state.sh`.
  It saves every costly byproduct to `gdrive:batkol-out/state/` (a user-approved target). The laptop
  disk is the only live copy, so this is the off-site backup. Never recompute what is already in `~/work`.

## Flow v2: one analysis pass per source, then only planning and cutting

See `docs/flow_v2.md` for the reasons, with data, and the status.

1. **Index** (`batkol/index.py`), once per audio file:
   - whisper transcript plus CTC (MMS_FA) alignment;
   - diff against the book;
   - energy pause map → `~/work/index/<key>.json`.

   It records words (timings, scores, status vs the book), boundaries (pause, cut points,
   onset cut) and unindexed sound.
2. **Plan:** pairing (LaBSE), chunks, items as book-token ranges, schedule.
   Pure computation on indexes; no ASR.
3. **Cut and render:** index lookups plus ffmpeg (`batkol/lesson.py`). Lessons continue in chapter
   order. Reviews come from the learner state (`batkol/learner.py`, `~/work/learner/state.json`;
   one lesson per day assumed).
4. **QA:** listening verdicts (gate builds) and sampled re-transcription (measures the
   index, never gates), both in `~/work/bank/spans.jsonl` (`batkol/clipbank.py`).

## Commands

```bash
# A new chapter, NL -> EN -> NL drill (docs/book2_ch01.md): one audio pass per source, then cutting only
uv run python -m batkol.sources fetch b2ch01            # resolve Drive globs, download audio + EPUBs
uv run python -m batkol.analyze b2ch01 nl --slice 60    # time a slice first (working rule)
uv run python -m batkol.analyze b2ch01 nl               # whisper + emissions; stops for the text check
uv run python -m batkol.edition b2ch01 nl               # audiobook vs EPUB(s): picks the text, decides book|reconcile|stop
uv run python -m batkol.analyze b2ch01 nl               # alignment + gap pass + index (same for en)
uv run python -m batkol.drill b2ch01                    # drill MP3/TSV/report from the indexes (~1 min, no ASR)
uv run python -m batkol.index nl_ch01 en_ch01 pims_L01                 # (re)build indexes from caches (seconds)
uv run python -m batkol.lesson view 7 12                                # pause chunks + book ranges for item selection
# batkol/lessons/ch01_plan.json: DRAFT items for all of ch. 1 (A-W hand-picked; u012.* automatic and
# unreviewed). Review a lesson's share before using it (batkol/plan.py; LaBSE vectors cached on Drive).
uv run python -m batkol.lesson batkol/lessons/lesson03.json ~/work/lesson03  # build a lesson (records learner state)
# Long items (> 12 words / 4.5 s speech) need "parts" in the spec: book ranges cut where ok_cut allows,
# each with "en_book" (audiobook cue) and/or "gloss" (Piper). Report field "uncovered" must stay empty.
uv run python -m batkol.validate_index all                             # index vs re-transcription history
uv run python -m batkol.clipbank qa ~/work/lesson01/lesson01.json ~/work/bank/spans.jsonl 10
uv run python -m batkol.clipbank verdict2 ~/work/bank/spans.jsonl <span_id> pass|fail [note]
```
- Legacy, pre-index: `batkol/pipeline.py` built the HP1 ch. 1 NL→EN→NL drill (v3, re-transcription
  verified) and its stage caches, which the HP1 indexes read. New chapters use `analyze` + `drill`;
  per-clip verification is not part of the flow any more.

## Working rules (from the user)

- Plan first. Time a 1-minute slice before any full run.
- Keep every long step ≤ 25 min and resumable. Run it as a harness-tracked background
  task, never a hand-rolled `pgrep` watcher.
- Report observed vs assumed separately; never claim an unobserved result.
- If the same fix fails twice on the same symptom: stop and report what fails, what is
  ruled out, and the cheapest next test.
- No Dutch TTS. English TTS (Piper, free, offline) only as a fallback. No paid APIs.
- Push back when you disagree; stick to the ground truth.
