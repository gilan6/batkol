# HP2 ch. 3 and 4: NL→EN→NL drills (2026-11-02)

No book text in this file. Numbers are observed unless marked *(assumed)*.

## Goal

Book 2, chapters 3 and 4, in the format of chapters 1 and 2 (`docs/book2_ch01.md`,
`docs/book2_ch02.md`): per unit, NL clip, 1 s gap, EN clip, 1 s gap, NL clip, 1 s gap, with the
cross-source leveling of `batkol/build.py`. Chapter 3 first, then chapter 4.

## What changed

- **Longer chapters, same step limit.** Chapter 4 is 39.4 min of NL. On the laptop that took 25 min
  of whisper, then 16 min of emissions plus 8 min of alignment and gap pass, so either half of the
  pass in one run would reach or pass 25 min. `analyze` now takes:
  - `--stop-after asr|emissions`: end the run after that stage (`--stop-after asr` replaces
    `--asr-only`);
  - `--asr-minutes M`: whisper starts no new 5-min window after M minutes; the run stops with a
    `[stop]` line and a rerun continues from the cached windows.
- **Runs from a snapshot of HEAD** (`~/work/code/batkol-<sha>`, the parallel-session rule), so another
  session's uncommitted edits can't reach a long run. Chapter 3's NL whisper ran on `708ff56`, under
  `timeout 23m`, before the flags existed; every later step ran on `26c57c2`.
- **Registry.** `b2ch03` and `b2ch04` are two more `hp2(...)` lines in `sources_local.py`.
- **Memory in the render.** The first chapter-4 drill was killed by the OOM killer (7.2 GB resident of
  WSL's 7.5 GB). Limiting the whole mix in one piece needs ~4.9x the mix in temporaries (measured on
  10- and 30-min mixes), and chapter 4's mix is 123 min, 1.3 GB as float32; chapter 3's 93 min had
  just fit. `build.limited` now limits the mix in 60 s blocks, each with more than the filters' reach
  of samples on both sides, and `encode_mp3` streams the blocks to ffmpeg (`4ded078`). Output is
  unchanged: same PCM and MP3 bytes on a test mix with peaks on every block boundary.

## Chapter 3 (laptop, `BATKOL_THREADS=6`)

- **Inputs.** NL: per-chapter opus, 29.8 min. EN: cut from the whole-book m4b at its chapter-3 mark,
  27.6 min. The three EPUBs give the chapter cleanly (NL and EN end on the same sentence).
- **Slice (60 s of NL).** Whisper rtf 0.80, emissions rtf 0.42, models loaded in 60 s.
- **NL whisper.** 18.9 min wall for 29.8 min of audio, 4787 words (the 23-min cap was not reached).
- **NL text check.** ok 94.9 %, match 97.5 %, no spoken intro or outro → `book` (nl_b2_a). 7 runs of
  2–5 book tokens where the narration words it differently (ch. 1: 1, ch. 2: 0); `drill` merges any NL
  cut within 0.5 s of one.
- **NL emissions, alignment, gap pass, index.** 17 min wall: emissions 12.2 min, alignment 1 s, gap
  pass 293 gaps in 21 windows (3 words kept). Alignment from the heading at 0.2 s to the last word at
  1784.9 s of 1788.4 s; median CTC score 0.98, 1.4 % of words < 0.3.
- **NL index.** 4741 words (ok 4454, fuzzy 124, differs 102, added 46, unheard 15), 565 pause boundaries.
- **EN whisper.** 15.5 min wall for 27.6 min of audio, 4367 words.
- **EN text check.** ok 95.5 %, match 95.9 % (both EN EPUBs alike) → `book` (en_b2_a). The cast leaves
  out 143 book tokens; 8 runs: five left-out stretches of 4–8 tokens, three rewordings.
- **EN emissions, alignment, gap pass, match, index.** 14 min wall: emissions 11.3 min, alignment 1 s,
  gap pass 2.1 min (52 gaps in 5 windows, 0 words kept).
- **EN index.** 4367 words (ok 4307, fuzzy 21, differs 35, added 4), 158 book tokens omitted by the
  cast, 1492 pause boundaries (34 % of boundaries; ch. 2: 20 %).
- **Drill.** `gdrive:batkol-out/HP/book2/hp2_ch03.mp3`; TSV and reports in `HP/meta/book2/b2ch03/`.
  - 92.7 min, 214 units from 323 sentence groups (6 min). Merges: nl_no_pause ×43, en_no_pause ×26,
    en_edge_score ×34, nl_edge_score ×14, nl_text_run ×7.
  - NL word coverage 100 %. Cuts inside speech: 0. 27 units with index risks, not listened to.
  - Two NL sentences (two short interjections) play with no EN after them: the cast never speaks their EN
    lines (whisper heard nothing in the 3 s there but one 0.4 s sound, and the index lists all their
    book words as omitted). So `drill` joined the NL to the previous unit and left the EN out, as
    designed; the report lists them under "no EN audio found".
- **Levels.** Whole file −18.7 LUFS, peak −0.9 dBFS. NL median −19.7 LUFS (p10 −21.5, p90 −16.0),
  EN −18.4 (−19.8, −16.7): NL − EN −1.3 dB (ch. 2: −0.6). Gains NL +5.0 dB, EN −0.5 dB. The source gain
  matches the whole source's integrated loudness, which loud lines raise, so a lively narration's
  typical line ends up a little under the target.

## Chapter 4 (laptop, `BATKOL_THREADS=6`)

- **Inputs.** NL: per-chapter opus, 39.4 min. EN: cut from the m4b at its chapter-4 mark, 37.2 min.
- **Slice (60 s of NL).** Whisper rtf 0.80, emissions rtf 0.37, models loaded in 25 s; projected
  whisper 31 min.
- **NL whisper.** Two runs with `--asr-minutes 15`: windows 1–5 in 16 min wall (the cap stopped it),
  6–8 in 9 min. 6143 words.
- **NL text check.** ok 93.4 %, match 96.9 % → `book` (nl_b2_a). 14 runs (ch. 3: 7). One is a whole
  sentence of 16 book tokens the narrator does not read: whisper's words run on with only a 0.92 s
  pause where ~5 s of speech would be.
- **NL emissions** (`--stop-after emissions`): 15.9 min. **Alignment, gap pass, index:** 8 min wall
  (411 gaps in 29 windows, 2 words kept). Alignment from 0.2 s to 2359.7 s of 2363.0 s; median CTC score
  0.98, 1.9 % of words < 0.3. The skipped sentence's 16 tokens are squeezed into 572.0–574.2 s with
  scores near 0. They pull the previous sentence's last three words 0.3–0.9 s early (low scores);
  from the next sentence's second word on, timings agree with whisper again (score ≥ 0.97).
- **NL index.** 6102 words (ok 5659, fuzzy 210, differs 139, unheard 50, added 44), 703 pause boundaries.
- **EN whisper.** Two runs with `--asr-minutes 15`: windows 1–6 in 17 min wall, 7–8 in 4 min. 5680 words.
- **EN text check.** ok 96.1 %, match 96.9 % (both EN EPUBs alike) → `book` (en_b2_a); 12 runs.
- **EN emissions, alignment, gap pass, match, index** in one run: 19 min wall (emissions 15.1 min,
  gap pass 3.8 min: 65 gaps in 6 windows, 2 words kept).
- **EN index.** 5683 words (ok 5558, fuzzy 39, differs 81, added 5), 119 book tokens omitted by the
  cast, 1084 pause boundaries.
- **Drill.** `gdrive:batkol-out/HP/book2/hp2_ch04.mp3`; TSV and reports in `HP/meta/book2/b2ch04/`.
  - 123.1 min, 266 units from 388 sentence groups (2 min on `4ded078`; the first try ran out of memory,
    see above). Merges: nl_no_pause ×59, en_no_pause ×29, en_edge_score ×30, nl_edge_score ×9,
    nl_text_run ×9. No unpaired sentences.
  - NL word coverage 100 %. Cuts inside speech: 1, the last unit's EN end at the file edge: the last word
    ends at 2227.38 s (score 0.999) and the clip 0.95 s later, in sound 17.5 dB under speech (the
    chapter's closing music), because the index looks at most 1 s past the last word. No word is cut.
  - The sentence the narrator skips lies inside unit 76 (NL sentences 112–115, merged: no pause), so no
    cut falls where its squeezed tokens are.
  - 46 units with index risks, not listened to (NL start word added ×17 the most common).
- **Levels.** Whole file −18.6 LUFS, peak −0.8 dBFS. NL median −19.6 LUFS (p10 −21.5, p90 −15.8),
  EN −18.7 (−19.5, −16.5): NL − EN −0.9 dB. Gains NL +5.0 dB, EN +0.2 dB.

## Summary

| | NL audio | MP3 | units | cuts in speech | risks | NL − EN | whole file |
|---|---|---|---|---|---|---|---|
| ch. 2 | 21.0 min | 65.6 min | 136 | 0 | 15 | −0.6 dB | −18.5 LUFS |
| ch. 3 | 29.8 min | 92.7 min | 214 | 0 | 27 | −1.3 dB | −18.7 LUFS |
| ch. 4 | 39.4 min | 123.1 min | 266 | 1 (file edge) | 46 | −0.9 dB | −18.6 LUFS |

Compute on the laptop: chapter 3 about 75 min from fetch to drill, chapter 4 about 95 min (in steps
of at most 19 min).

## Not yet observed

- A listening check of chapters 3 and 4.
- Whether the NL−EN gap of up to 1.3 dB is audible. If it is, the per-source gain could aim the median
  utterance at the target instead of the integrated loudness (`build.match_loudness`; it is shared
  with the lessons).
