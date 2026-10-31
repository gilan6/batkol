# HP2 ch. 2: NL→EN→NL drill, leveled (2026-10-31)

No book text in this file. Numbers are observed unless marked *(assumed)*.

## Goal

Book 2, chapter 2, in the format of chapter 1 (`docs/book2_ch01.md`): per unit, NL clip, 1 s gap, EN
clip, 1 s gap, NL clip, 1 s gap. The user's verdict on the chapter 1 drill: good.

It is the first chapter delivered with the cross-source leveling made while preparing the public
repo's README examples (`batkol/build.py`, 2026-10-27). The drill renderer already called it, so no
new leveling code was needed; the chapter 1 MP3 on Drive is the 2026-10-24 build, from before it.

## What changed for chapter 2

- **Chapter text.** `chapter.chapter_paras(path, n)` replaces `chapter1`. It cuts from chapter n's
  heading to chapter n+1's (a digit, or the NL/EN number word from `num2words`), skipping the table of
  contents as before. Chapter 1 comes out identical to the old code on all six EPUBs. A book's last
  chapter is not supported yet: it has no next heading.
- **Chapter number.** A chapter id ends in `ch<number>` (`sources.number`: b2ch02 → 2), so
  `batkol.edition` cuts the right chapter. `sources_local.py` builds the book-2 entries with one helper.
- **Threads.** `BATKOL_THREADS` (default 4) sets the CPU threads of whisper and the CTC model.
- **Shorter steps.** `analyze --asr-only` stops after whisper, so a ~21-min chapter runs as two steps
  of at most ~16 min on the laptop instead of one of ~25.
- **Progress.** Live bars (seconds of audio, ETA) for the whisper long-form pass (per decoded 30 s
  chunk), the emissions and the gap passes, plus one line per finished whisper window. Each chapter
  logs to `~/work/logs/<chapter>.log`; watch it with `tail -f`.

## Run (laptop, `BATKOL_THREADS=6`)

- **Inputs.** NL: per-chapter opus, 21.0 min. EN: cut from the whole-book m4b at its chapter-2 mark
  (20.6 min). EPUBs as chapter 1 (1 NL, 2 EN).
- **Slice (60 s of NL).** Whisper rtf 0.78, emissions rtf 0.37, models loaded in 52 s. With 4 threads
  the laptop measured 0.85 and 0.46 (`docs/local_plan.md` §4).
- **NL whisper.** 14.3 min wall for 21.0 min of audio (model load included), 3090 words.
- **NL text check.** ok 95.6 %, match 97.6 %, 0 runs, no spoken intro or outro → `book` (nl_b2_a).
- **NL emissions, alignment, gap pass, index.** 14 min wall: emissions 9.6 min (rtf 0.45, slower than
  the slice), alignment 1 s, gap pass 230 gaps in 16 windows (1 word kept). The alignment runs from the
  heading at 0.2 s to the last word at 1258 s of 1261 s; median CTC score 0.98, 2.8 % of words < 0.3
  (ch. 1: 1.4 %).
- **NL index.** 3096 words (ok 2939, fuzzy 60, differs 59, unheard 16, added 22), 363 pause boundaries.
- **EN whisper.** 12.2 min wall for 20.6 min of audio, 2827 words.
- **EN text check.** ok 96.8 %, match 97.0 % (both EN EPUBs alike) → `book` (en_b2_a). One run where
  the cast rewords 4 book tokens as 1; five where it leaves out 4–6 book tokens.
- **EN emissions, alignment, gap pass, match, index.** 13 min wall: emissions 8.8 min, alignment 1 s,
  gap pass 4.3 min (95 gaps in 9 windows, 2 words kept), match and index seconds.
- **EN index.** 2833 words (ok 2809, fuzzy 6, differs 15, added 3), 76 book tokens omitted by the cast,
  573 pause boundaries.
- **Total.** About 60 min of compute from fetch to drill, in steps of at most 14.3 min.

## Drill

`gdrive:batkol-out/HP/book2/hp2_ch02.mp3`; the TSV, the report and both edition reports are in
`gdrive:batkol-out/HP/meta/book2/b2ch02/`.

- 65.6 min, 136 units from 237 sentence groups (built in 5 min, LaBSE pairing included). Merges:
  nl_no_pause ×39, en_no_pause ×31, en_edge_score ×33, nl_edge_score ×17.
- NL word coverage 100 %. Cuts inside speech: 0 (ch. 1: 1, at the file edge). No unpaired sentences.
- 15 units with index risks, not listened to: NL start word added ×5 or differs ×5, NL end word
  differs ×2, NL start word unheard ×1, EN end word differs ×1, and unit 0 (low edge scores at the
  heading, which starts at the file edge). Three of the start flags are stammered words, which the text
  writes with a hyphen.

## Levels (measured in the output MP3s)

Each utterance is cut from the MP3 by its TSV times and measured with ffmpeg ebur128; the band is the
target ±3 dB plus 0.5 dB of measuring slack.

| file | whole file | NL median (p10–p90) | EN median (p10–p90) | NL − EN | NL outside band |
|---|---|---|---|---|---|
| ch. 1 on Drive, 2026-10-24 | −22.0 LUFS | −24.4 (−28.5 to −20.7) | −20.9 (−21.5 to −18.5) | −3.5 dB | 83 % |
| ch. 1 rebuilt 2026-10-27, `~/work` only | −18.6 LUFS | −19.5 (−21.5 to −15.8) | −19.0 (−19.7 to −16.7) | −0.5 dB | 5 % |
| ch. 2, 2026-10-31 | −18.5 LUFS | −19.2 (−21.5 to −15.5) | −18.6 (−19.7 to −16.9) | −0.6 dB | 6 % |

- Gains: NL +5.0 dB, EN +0.1 dB. The old peak cap would have allowed NL about +0.6 dB, as in ch. 1.
- Peaks: −0.7 dBFS in the decoded MP3. The limiter holds −1 dBFS before encoding; MP3 adds a few
  tenths of a dB of overshoot, still under 0 dBFS.

## Not yet observed

- A listening check of ch. 2.
- The ch. 1 MP3 on Drive is still the unleveled 2026-10-24 build. The leveled rebuild is in
  `~/work/b2ch01/drill/`; replacing the Drive copy is the user's call.
