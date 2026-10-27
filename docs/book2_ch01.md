# HP2 ch. 1: NL→EN→NL drill from one audio pass (2026-10-24)

No book text in this file. Numbers are observed unless marked *(assumed)*.

## Goal

A NL→EN→NL drill of book 2, chapter 1, in the format of the HP1 ch. 1 drill v3. Per unit: NL clip,
1 s gap, EN clip, 1 s gap, NL clip, 1 s gap. Two constraints from the user:

- **Least effort.** The audio is analysed once. After that the drill is planned and cut from the
  indexes, with no re-transcription of cut clips and no listening gate before delivery.
- **Text match unknown.** The book-2 audiobooks may not follow the EPUB text on Drive. That is checked
  from the same pass.

## Why this works without a second look at the audio (HP1 evidence, `docs/flow_v2.md`)

- **Index cuts equal the verified cuts** to the millisecond.
- **Index risk rules flag** 100 % of the EN and ~85 % of the NL clip defects that re-transcription found.
  The NL ones they miss are narrator words added right before a sentence, which whisper did not hear
  either (2 of 13 NL edge defects in drill v3).
- **The drill plans around risky boundaries.** It merges a unit with its neighbour when either:
  - a cut would go through speech (no pause ≥ 120 ms in both languages), or
  - an edge word at the cut has a CTC score < 0.3.

## Flow (commands)

```bash
bash scripts/restore_state.sh ch01                       # HP1 state (regression) + HP1 inputs
uv run python -m batkol.sources fetch b2ch01            # resolve book-2 globs, download audio + EPUBs
uv run python -m batkol.drill ch01 --no-risk-merge --no-render --compare ~/work/ch01/units.json   # regression
uv run python -m batkol.edition ch01 nl                 # HP1 baseline match figures (seconds; optional)
uv run python -m batkol.analyze b2ch01 nl --slice 60    # timing
uv run python -m batkol.analyze b2ch01 nl               # whisper + emissions, then stops for the text check
uv run python -m batkol.edition b2ch01 nl               # decision book | reconcile | stop
uv run python -m batkol.analyze b2ch01 nl               # alignment, gap pass, index
uv run python -m batkol.analyze b2ch01 en               # whisper, emissions, alignment, gap pass; stops for the text
uv run python -m batkol.edition b2ch01 en
uv run python -m batkol.analyze b2ch01 en               # book match, index
uv run python -m batkol.drill b2ch01                    # ~/work/b2ch01/drill/hp2_ch01.{mp3,tsv}, _report.md
rclone copy ~/work/b2ch01/drill gdrive:batkol-out/poc/b2ch01/ --include "*.{mp3,tsv,md}"
rclone copy ~/work/b2ch01 gdrive:batkol-out/poc/b2ch01/ --include "edition_*.md"
bash scripts/backup_state.sh
```

Each `analyze` run is resumable: whisper is cached per 5-min window, and every other stage per file.
Run the full passes as harness-tracked background tasks.

## Rules

### Sources (`batkol/sources.py`)

- Book-2 paths are rclone globs. They were written before the files could be seen, because the Drive
  token had expired.
- Audio must match exactly one file. The EPUB globs may match several editions; all of them become
  candidates for the text check.
- `fetch` records the resolved paths in `~/work/b2ch01/sources.json`. If a glob matches 0 or 2+ audio
  files, fix the glob.

### Text check (`batkol/edition.py`)

- **Inputs.** The whisper transcript (from the pass), diffed against chapter 1 of every candidate EPUB.
  The existing chapter text also counts as a candidate, and it is never overwritten.
- **Measures.** Share of book tokens: ok, fuzzy (spelling), differs, unheard. Spoken tokens not in the
  book: added. Runs of ≥ 4 tokens where audio and text part ways.
- **Decision.** The candidate with the most ok tokens is chosen:
  - `book`: ok + fuzzy ≥ 85 %. The text is force-aligned as is.
    - The runs go into `edition_nl.json`.
    - `drill` merges every NL boundary within 0.5 s of a run (`nl_text_run`), so no cut lands where
      the book's word timings are unreliable.
  - `reconcile`: NL with ok + fuzzy < 85 %. `analyze` refuses to align. A reconciliation step (align
    the spoken words in the runs) is not written, and is only needed if HP2 ends up here.
  - `stop`: ok < 70 % for every candidate, so the wrong file or chapter.
  - EN is always `book` unless `stop`. The EN index is built from what the cast said, and the text only
    maps it to sentences.
- **Why runs need no reconciliation** (observed on the TTS fixture). One sentence was reworded in the
  narration ("de bakker gaf hem er drie" spoken as "toen gaf de vriendelijke bakker hem zomaar drie").
  - Book-first alignment re-synced on the matching words around the run, so the unit clip held the whole
    spoken sentence. Only the TSV text differs from what is heard.
  - The planned rule (runs ≤ 1 per 1000 tokens, else reconcile) would have stopped on this harmless case.
    It was replaced before any HP2 data was seen.
- **Report.** `edition_<lang>.md` holds book text, so it goes to Drive only, never to git.

### Drill (`batkol/drill.py`)

- **Units.** The LaBSE sentence groups (`pairs.json`, computed once).
  - An NL sentence without an EN partner joins the previous unit, so every NL sentence is drilled.
  - An EN sentence without an NL partner is left out, unless a merge puts it inside an EN clip.
- **Cuts.**
  - NL: one cut at the longest pause between units, so a narrator addition joins a side.
  - EN: cuts at the first and the last pause, so credits and cast additions between units are left out.
- **Merges.** With no pause in either language. With risk merge (on by default) also when an edge
  word scores < 0.3, or an NL cut lies in an edition run. Merging stops at 45 s of Dutch speech; beyond that, a forced cut goes inside speech and is
  flagged.
- **Report.**
  - units, and merges by reason;
  - joined NL sentences and left-out EN sentences;
  - NL word coverage (target 100 %) and cuts inside speech (target 0);
  - units with index risks, with their MP3 timestamps (optional spot-check).
- **Output.** `~/work/<chapter>/drill/`. The verified HP1 `~/work/ch01/units.json` is never overwritten.

## Regression gate (HP1, no listening)

`drill ch01 --no-risk-merge` against the verified drill v3 should give the same sentence groups, except
where an NL-only sentence now joins a unit (v3 skipped those). Cut times should agree within 20 ms on
≥ 95 % of cuts. Expected sources of difference:
- narrator additions are now inside the unit;
- the index takes its silence threshold at the gap midpoint, where v3 took it at the word edge.

An unexplained difference must be fixed before HP2.

## Status

### Done (this session, code only: Drive was unreachable)

- `sources.py`, `analyze.py`, `edition.py`, `drill.py`.
- `index.build`, `pipeline.SRC` and `restore_state.sh` now take their paths from the registry.
- `chapter.chapter1`: heading forms "Hoofdstuk een", "1 + title on the same line" and "— CHAPTER ONE —"
  are accepted. Bare digits are not, since OCR editions contain page numbers.
- Tests on synthetic and TTS-made fixtures (scratch only, no book material); results below.

### Observed in fixture tests (scratch only)

- **Synthetic index** (noise-burst "words", real `index.boundaries`):
  - merge on no pause, risk merge, and the merge cap with a flagged in-speech cut all work as specified;
  - NL-only sentences join a unit, EN-only sentences are excluded, EN credits are excluded;
  - an EN-only sentence between merged units is reported as inside the clip, not as left out;
  - compare mode reproduces a build at 0 ms.
- **`sources.fetch`** on a mock folder tree: the globs resolve nested book-2 folders, case-insensitive.
  Note: an unanchored rclone glob with a `/` inside matches nothing; a leading `**` is needed.
- **Full chain on a TTS fixture** (own 11-sentence text, Piper NL `nathalie` + EN `alan`; EN with
  "credits" before the heading): `analyze` → `edition` → `analyze` → `drill` ran end to end.
  - The edition check found the one reworded sentence (ok 97.6 %).
  - The EN credits were left out of unit 0.
  - NL coverage 100 %, 0 cuts in speech.
  - Merges came from Piper's short sentence pauses (5 NL, 3 EN), plus 1 text-run merge.
- **First Dutch TTS voice tried** (`nl_NL-mls`): garbled ("eposite"). Whisper heard 36 of 85 words, and
  the edition check correctly said `stop`.
- **Timing on this machine** (4 vCPU), 20 s slice: whisper rtf 0.55, emissions rtf 0.20, model load
  14 s. HP1 measured 0.26 and 0.155 on longer audio. Re-time with `--slice 60` on HP2 before the full
  pass.

### Run on HP2 (2026-10-24, observed)

- **Inputs.**
  - NL: per-chapter opus, as HP1 (18.7 min).
  - EN: only one whole-book m4b on Drive (1 GB, AAC stereo, chapter marks).
    `sources.fetch` downloads it to `~/work/in/raw/` and cuts the chapter by its chapter-mark title
    (`cut` in the registry; titles use a non-breaking space), ±0.5 s → `en_b2ch01.opus` (17.5 min).
  - EPUBs: 1 NL, 2 EN (Full Cast `Books/` copy and the copy in the NL folder). `chapter1` read all
    three headings without regex changes.
- **Regression (HP1, `--no-risk-merge --no-render`).** 239 of 239 units with the same sentence groups;
  95.3 % of 956 cuts within 20 ms (gate ≥ 95 %: pass). Every cut off by > 0.2 s is EN, and nearly all
  widen the clip (start earlier, end later): the EN rule now cuts at the outer pauses. NL max |Δ| 0.1 s.
- **Timing (4 vCPU).** 60 s slice: whisper rtf 0.33, emissions rtf 0.25, model load 86 s (incl. the
  1.2 GB MMS_FA download). Full passes: NL whisper + emissions ~10 min, NL align + gap pass ~3 min,
  EN ~9 min, drill with render 2.5 min.
- **Text check.**
  - NL: ok 95.8 %, match 98.1 %, 1 run, 9 intro tokens (spoken credits) → `book`.
  - EN: ok 96.4 %, match 96.9 %, 2 runs → `book` (en_b2_a; en_b2_b within 0.1 pt).
- **Indexes.** NL 2750 words (316 pause boundaries), EN 2520 words (474 pause boundaries).
- **Drill** (`gdrive:batkol-out/poc/b2ch01/hp2_ch01.{mp3,tsv}`, report, edition reports): 56.4 min,
  121 units from 173 sentence groups. Merges: nl_no_pause ×30, en_no_pause ×12, en_edge_score ×13,
  nl_edge_score ×1. NL coverage 100 %. No unpaired sentences. 11 units with index risks.
  - The one `cut_in_speech` flag is unit 0's EN start: the first word sits at the file edge, so the
    index has no pause before it. Clip starts at 0.565 s, speech at ~0.7 s, with only the title-music
    tail (≈ -34 dB) before it. Not a clipped word.
  - Seven units flag `nl_start_word_added` (narrator word before the sentence): the HP1 defect type the
    rules catch. Not listened to.

### Not yet observed

- Listening check of the HP2 drill.
- Whether `chapter1` still extracts HP1 ch. 1 identically after the regex change. Check this by
  diffing against `~/work/text/en_a.ch01.txt` (the NL text is repaired, so it cannot be diffed).
- Compute for HP2 *(assumed from HP1 rates)*: ~15 min NL, ~12 min EN, ~2 min drill render.
  Model downloads took ~4 min here: whisper turbo, MMS_FA 1.2 GB, LaBSE.
