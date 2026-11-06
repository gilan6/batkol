# Batkol

The interleaved audiobook was called "drill" (`batkol/drill.py`, `~/work/<chapter>/drill/`) until 2026-11-05.

Pimsleur-style Dutch pronunciation drills cut from Harry Potter audiobooks (book 1; book 2 started).
- Dutch: one narrator, Jan Meng.
- English: Audible full cast.
- Instruction phrases ("frames"): Pimsleur Dutch I.

## Privacy (this repo is public)

- Anything about the user, their machine or accounts goes in `private/`, never in a tracked file.
  `private/` is git-ignored here and tracked only in a private repo. Files are copied from this repo
  to the private one, never back.
- Git hooks block personal data in commits and pushes. Enable them once per clone:
  `git config core.hooksPath scripts/hooks`. Never bypass them: fix the hit or ask the user.
- Rewriting public history needs the user's OK.

Private notes, where present: @private/CLAUDE.md

## Where it runs

The user's laptop: Windows 11 + WSL2 Ubuntu, x86_64, 16 GB RAM, no GPU. Everything runs on CPU.
Setup, verification and open decisions: `docs/local_plan.md`.
- The repo (`~/batkol`) and `~/work` live in the WSL filesystem, never under `/mnt` (slow).
- `~/work` persists between sessions. Seed it once from Drive (`docs/local_plan.md` §4):
  ```bash
  bash scripts/restore_state.sh [chapter ...]   # ~/work from gdrive:batkol-out/state + inputs from gdrive:batkol
                                                # (chapter ids in batkol/sources_local.py; default ch01)
  ```
  After that, don't restore per session: it would only re-copy what is already there.
- Drive: `gdrive:` is an rclone remote for Google Drive. It is slow: never a working directory; inputs are
  copied to `~/work` first. Write only inside `gdrive:batkol-out/`; `gdrive:batkol/` is read-only input.
  Never delete anything on Drive.
- WSL stops when Windows sleeps. Before a long run, ask the user to keep the laptop plugged in and awake.
- Cloud sessions are retired: their proxy blocks `download-r2.pytorch.org` (CPU torch wheels) and 50languages.com.

## Where things live

| What | Where | In git? |
|---|---|---|
| Code, docs, lesson specs (book-token ranges, no text) | this repo | yes |
| Inputs: audiobooks, EPUBs, Pimsleur | `gdrive:batkol/` (read-only); paths in `batkol/sources_local.py` (git-ignored; template `sources_local.example.py`) | never |
| State: indexes, stage caches, clip bank, repaired text | `~/work` (laptop), backed up to `gdrive:batkol-out/state/` | never |
| Audio for listening (audio files only) | `gdrive:batkol-out/HP/{lessons,book1,book2}/`, `gdrive:batkol-out/50l/lessons/` | never |
| Their metadata: sidecar JSON, TSV, reports, READMEs | `gdrive:batkol-out/HP/meta/` and `50l/meta/`, one folder per lesson or chapter | never |

- **No book text, audio or transcripts in git.** Write to Drive only inside `gdrive:batkol-out/`.
- Put outputs on Drive with `bash scripts/publish.sh AUDIO_DIR META_DIR FILE...`: audio files go to
  AUDIO_DIR, every other file to META_DIR, so the audio folders never hold anything else.
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
   one lesson per day assumed). The interleaved audiobook (`batkol/interleaved.py`) plays each unit
   NL slowed to 0.8× with the pitch kept (`build.atempo`), then EN, then NL at normal speed.
   Levels (`batkol/build.py`): every source to -18 LUFS; an utterance more than 3 dB off is pulled
   back (by at most 6 dB); a -1 dBFS look-ahead limiter on the final mix.
4. **QA:** listening verdicts (gate builds) and sampled re-transcription (measures the
   index, never gates), both in `~/work/bank/spans.jsonl` (`batkol/clipbank.py`).

## Commands

```bash
# A new chapter's interleaved audiobook (docs/book2_ch01.md, _ch02.md, _ch03_04.md): one audio pass per source,
# then cutting only. Register it in batkol/sources_local.py; the id's ch<number> picks the EPUB chapter.
# Laptop: BATKOL_THREADS=6, and each run appended to ~/work/logs/<chapter>.log (live bars: tail -f).
uv run python -m batkol.sources fetch b2ch02            # resolve Drive paths, download audio + EPUBs
uv run python -m batkol.analyze b2ch02 nl --slice 60    # time a slice first (working rule)
uv run python -m batkol.analyze b2ch02 nl --stop-after asr   # whisper (~14 min for a 21-min chapter)
uv run python -m batkol.edition b2ch02 nl               # audiobook vs EPUB(s): picks the text, decides book|reconcile|stop
uv run python -m batkol.analyze b2ch02 nl               # emissions + alignment + gap pass + index (same for en)
# Longer chapters, so no run passes 25 min: --asr-minutes 15 (rerun until whisper is done), then
# --stop-after emissions, then the plain run (alignment, gap pass, index).
uv run python -m batkol.interleaved b2ch02              # leveled MP3/TSV/report from the indexes (~5 min, no ASR)
# Per unit: NL at 0.8x (pitch kept), 1 s, EN, 1 s, NL, 1 s. --speeds 1,1,1 plays all three at normal speed
# (first NL, EN, second NL; each 0.5-2; docs/interleaved_speed.md).
bash scripts/publish.sh HP/book2 HP/meta/book2/b2ch02 ~/work/b2ch02/interleaved/*.{mp3,tsv,md} ~/work/b2ch02/edition_*.md
uv run python -m batkol.index nl_ch01 en_ch01 pims_L01                 # (re)build indexes from caches (seconds)
uv run python -m batkol.lesson view 7 12                                # pause chunks + book ranges for item selection
# batkol/lessons/ch01_plan.json: DRAFT items for all of ch. 1 (A-W hand-picked; u012.* automatic and
# unreviewed). Review a lesson's share before using it (batkol/plan.py; LaBSE vectors cached on Drive).
uv run python -m batkol.lesson batkol/lessons/lesson03.json ~/work/lesson03  # build a lesson (records learner state)
bash scripts/publish.sh HP/lessons HP/meta/lessons/lesson03 ~/work/lesson03/*  # after writing its README.md there
# Long items (> 12 words / 4.5 s speech) need "parts" in the spec: book ranges cut where ok_cut allows,
# each with "en_book" (audiobook cue) and/or "gloss" (Piper). Report field "uncovered" must stay empty.
uv run python -m batkol.validate_index all                             # index vs re-transcription history
uv run python -m batkol.clipbank qa ~/work/lesson01/lesson01.json ~/work/bank/spans.jsonl 10
uv run python -m batkol.clipbank verdict2 ~/work/bank/spans.jsonl <span_id> pass|fail [note]
```
- Legacy, pre-index: `batkol/pipeline.py` built the HP1 ch. 1 interleaved audiobook (v3, re-transcription
  verified) and its stage caches, which the HP1 indexes read. New chapters use `analyze` + `interleaved`;
  per-clip verification is not part of the flow any more.

## Working rules (from the user)

- Plan first. Time a 1-minute slice before any full run.
- Keep every long step ≤ 25 min and resumable. Run it as a harness-tracked background
  task, never a hand-rolled `pgrep` watcher.
- Report observed vs assumed separately; never claim an unobserved result.
- If the same fix fails twice on the same symptom: stop and report what fails, what is
  ruled out, and the cheapest next test.
- No Dutch TTS. English TTS (Piper, free, offline) only as a fallback. No paid APIs.
- Lessons: prepare lesson n only. Have everything lesson n+1 needs from lesson n ready (where it starts,
  what building n found), but write no specs or checks for it.
- Push back when you disagree; stick to the ground truth.
