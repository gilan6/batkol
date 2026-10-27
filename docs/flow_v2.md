# Flow v2: one analysis pass, then planning and cutting (2026-10-17)

No book text in this file. Numbers are observed in this session unless marked *(assumed)*.

## 1. Why the flow changed

The user's point: sound files should be analysed once, with everything needed logged.
After that, all work is planning and cutting. The data agrees.

### Cost: per-clip re-checks vs one pass

| Work | Whisper / alignment compute |
|---|---|
| Re-transcribing cut clips (ch. 1 drill v1: 313 units × 2; v3: 151 units; lesson bank: 65 clips) | ≈ 64 min |
| One full pass, EN ch. 1: transcript 6.1 min, CTC emissions + alignment 4.9 min, gap pass 6.6 min (unbatched) | ≈ 18 min |
| One full pass, NL ch. 1: emissions 5.3 min, alignment 1 s, transcript 8.4 min, gap pass 2.6 min (398 gaps in 28 batched windows) | ≈ 16 min |
| Index build from the cached pass | 3–5 s per source |
| Lesson build from the indexes (plan + cut + render, no ASR) | ~20 s |

Whisper's cost is **per 30 s window**, not per second of audio, so a 1 s clip costs as much
as 30 s of speech. The per-clip checks averaged ~7 s per unit for that reason. Batching gaps
into 28 s windows made the gap pass about 15× faster (28 windows instead of ~380 calls).

### Does the index alone predict what clip re-transcription found?

`batkol/validate_index.py` takes every historical clip, reads from the index which words lie
inside the cut, adds the index's signal risks, and compares with what whisper heard on that clip.

| Clip set | Edges with a defect found by re-transcription | Flagged by the index | Clean edges also flagged |
|---|---|---|---|
| EN ch. 1 drill v1 (313 units) | 7 | **7 (100 %)** | 20.8 % |
| EN ch. 1 drill v3 (239 units) | 2 | **2 (100 %)** | 8.8 % |
| NL ch. 1 drill v1 | 19 | 16 (84 %) → see §4 | 30.6 % |
| NL ch. 1 drill v3 | 13 | 11 (85 %) → see §4 | 10.8 % |

The index rules that predict defects:
1. Token diff: words of the expected text vs the index words inside the cut. This catches
   leaked neighbour words and narrator additions.
2. A cut edge not in a real pause (≥ 0.12 s quiet).
3. An edge word with CTC alignment score < 0.3. These are overlapping, whispered or emotional
   lines; it caught every English miss of rules 1–2 ("the Potters" 0.01, "frightened" 0.00,
   "oh" 0.01, "Muggles" 0.04).
4. Unindexed sound inside a clip margin.

The v1 vs v3 difference in false flags shows that better cut rules mostly *avoid* risky edges.
In flow v2 the planner avoids them up front, so flags rarely reach a build.

**Index cuts reproduce the verified cuts exactly:** the 10 lesson-1 clips shared by both
builds are identical to the millisecond.

### Where re-transcription found things the old pass did not log

All of these are gaps in the old pass, now closed inside the pass:
- **No Dutch transcript**, so narrator additions ("en", "ja", "nee", a repeated "Lily en
  James") were invisible. *Fixed:* the NL transcript is diffed against the book (4,493 ok,
  71 spelling, 109 differs, 31 unheard, 42 added before the gap pass).
- **Long-form whisper drops short words** ("Shoo!", "Nee,", "Ja,"). *Fixed:* a batched gap
  re-transcription for both languages. Only confidently aligned results become words;
  157 of 159 English gap tokens were hallucinations ("thank you", "i'll see you next time")
  and stay out of the word list.
- **No measure of how cleanly a boundary can be cut inside speech.** *Fixed:* per-boundary
  `depth_db` and onset cut. The 3 leaked buildup onsets sit at the shallowest dips (−7.5,
  −5.5 dB) or after a ≤ 3-letter word (−21.1 dB).

Listening stays necessary for one thing: whether a cut inside speech *sounds* clean.
A transcript cannot measure that.

## 2. Flow v2

```
audio + book text ──► INDEX (once per source; cached, resumable)
                        whisper transcript (long-form) + batched gap pass
                        CTC alignment (MMS_FA, 120 s windows)
                        diff vs book: ok | fuzzy | differs | unheard | added | omitted
                        energy pause map: per boundary pause, cut_end, cut_start,
                        onset cut, depth_db; unindexed sound
                     ──► PLAN (text + index only)
                        NL↔EN sentence pairing (LaBSE + DP, n:m), pause chunks,
                        items as BOOK-TOKEN ranges, backward buildup (risky onsets
                        filtered), recombination, recall schedule
                     ──► CUT + RENDER (index lookups + ffmpeg, no ASR)
                        gate: a cut landing in speech is dropped;
                        "needs ear" clips go to one listening list
                     ──► QA (measures, never re-analyses)
                        listening verdicts (gate future builds) +
                        sampled re-transcription (measures the index),
                        both in the span bank, keyed by word span
```

### Index file `~/work/index/<key>.json`

| Key | Content |
|---|---|
| `words[]` | `tok, s, e, score, sent, book_i, status` (+`gap`, `heard`) |
| `bounds[k]` | Before word k: `gap, pause, kind (pause\|short\|none), cut_end, cut_start, onset, onset_db, depth_db, speech_in_gap, thr` |
| `omitted[]` | Book tokens never spoken (EN cast drift: 91 in ch. 1) |
| `unindexed[]` | Speech-energy regions with no word |
| `meta` | `gap_tokens_dropped` (EN hallucinations kept for audit) |

Keys: `nl_ch01`, `en_ch01`, `pims_L01`.

### Identities that survive reprocessing

- **Lesson items** are book-token ranges (`batkol/lessons/lesson01.json`).
- **Clip verdicts** are keyed by `span_id` = (source, first word start, last word end,
  onset/pause), not by cut times. A cut-rule change keeps the verdict.

## 3. Status (end of session 2026-10-17)

### Done and pushed

`index.py`, `validate_index.py`, `lesson.py` (index-only), span bank in `clipbank.py`,
`CLAUDE.md`, `scripts/restore_state.sh`.

### Data on Drive

- `gdrive:batkol-out/state/`: indexes, stage caches (alignment, ASR, emissions, gap passes),
  repaired text, clip banks, lesson data.
- `gdrive:batkol-out/poc/`:
  - ch. 1 NL→EN→NL drill v3 (MP3 / TSV / report);
  - lesson 1 v1 (ASR-checked) in `lesson01/`;
  - lesson 1 v2 (index-only) in `lesson01_v2/`, with its listening list.

### Legacy

`pipeline.py` (ch. 1 drill builder) still runs its own energy cuts and per-clip
verification. Its stage caches feed the indexes. Porting it is next-step 2.

### Stopped after two failed fixes: Dutch additions right before a sentence

Per the working rule, work on this symptom stopped after the second failed fix.

**Symptom.** The narrator sometimes adds a short word directly before a sentence ("Nee, het
had…", "Ja, inderdaad…"). It is missing from the index, so 3 historical NL edges stay
unpredicted (v1 units 59 and 119, v3 unit 52).

**Fix 1:** diff the NL long-form transcript against the book. It found 42 additions but not these.

**Fix 2:** batched gap re-transcription. It found 7 more ("ja" ×2, "en en", the narrator's
repeated "Lily en James"), but whisper returned empty text for the target gaps.

**Ruled out:**
- *Gap selection:* the target gaps were selected and transcribed (in `ch01/nl_gapfill.jsonl`).
- *The score filter:* there was no text to filter.

**Observed:** whisper heard these words only on a clip that also held the following sentence.

**Cheapest next test:** transcribe gap + first 1–2 s of the following words, then remove the
known book words. Try the 3 known gaps first.

**Impact:** text fidelity only. The clip audio is complete and starts with the spoken word.

The CTC score filter (≥ 0.5) does separate real gap words from hallucinations:

| Kept | Rejected |
|---|---|
| "ja" 0.99 | "Dank u wel." 0.000–0.001 |
| "Lily en James" 0.75–0.88 | "MUZIEK" 0.05 |
| | "uh, um, what are" ≤ 0.06 |

### Long clauses and full coverage (lesson 3)

- **Every NL word belongs to a drilled item.** Each lesson report lists `uncovered` book ranges of the
  units reached so far; after lesson 3 there are none.
- **Splitting.** Items over 12 words or 4.5 s of speech (cut margins excluded) are split into parts at
  clause boundaries. A cut inside speech must pass `ok_cut`, the same calibrated rule as `risky_onset`.
  - Each part is drilled cue → say → narrator → repeat (twice), then recalled at 25 s and 2 min.
  - The whole clause is built up from the part boundaries, then recalled repeat-only at 2 and 10 min.
- **Cues.** The audiobook English is preferred, including inner cuts inside speech when they pass
  `ok_cut`. Otherwise the cue is a literal gloss read by Piper (written per part in the lesson spec).
- **Backfill and re-splits.** Text skipped earlier enters the next lesson as a backfill item
  (lesson 3: X1). Long items taught whole are reviewed as their parts (`resplit` in the spec).
- **Long material without a safe split** (H) and long sentence drills are recalled repeat-only.
- **Lessons 4 and 5: done.** Lesson 4 covers units 9–12 (30.9 min; `tolerance_min` 2.5 lets unit 12, the end
  of the paragraph, in). Lesson 5 covers units 13–17 (27.6 min).
- **Lesson 6 continues at U18 (unit 18).** Items U18–U24 are already specified in
  `batkol/lessons/lesson05.json`.
- Clause items inside one sentence are separated by cuts inside speech, so they are **parts** of a long
  item; only parts may have planned in-speech cuts.
- Narrator additions at an item's edge, with no pause between, are included in the item (`Sources.nl_range`).

## 4. Open items and next steps (priority order)

1. **User listening.**
   - **Lesson 1 list: done, all 11 pass** (recorded in the span bank, `list=lesson01`).
     - The 8 in-speech buildup onsets that `risky_onset` accepted passed 8/8 by ear. So far
       the rule lets no bad cut through. Nothing shows yet whether it is too strict, since
       rejected onsets are never heard.
     - The 3 heading clips flagged only for low edge-word scores (0.003–0.11, right after the
       intro music) all passed. That is 3/3 false alarms here, while the same rule caught all
       5 English score-only defects in the history. Keep the rule and gather more verdicts.
   - **Lesson 2 list: 18 clips pending.**
   - Record verdicts with
     `python -m batkol.clipbank verdict2 ~/work/bank/spans.jsonl <span_id> pass|fail`.
   - Refit `lesson.risky_onset` once a list contains failures. It is fitted on 26 cuts
     (3 leaks) plus 8 passes by ear.
2. **Port the ch. 1 NL→EN→NL drill to the index:** units from pairs + `Index.span`;
   merge-on-no-pause becomes a lookup. Delete per-clip verification from `pipeline.py`.
3. **Lesson 2: done** (`batkol/lessons/lesson02.json`, `gdrive:batkol-out/poc/lesson02/`).
   - 28.5 min: 8 new items F–M, 7 reviews from lesson 1 (warm-up + ~10 min later),
     recombinations S3, S5, L+M; no TTS; 18 clips on its listening list.
   - Learner state (`batkol/learner.py`, `~/work/learner/state.json`) records what each lesson
     taught or reviewed. Due dates are derived from it, *assuming one lesson per day*.
   - **Lesson 3 continues at item N**, then O–W (already defined in the lesson02 spec), and
     reviews F–M plus their drills.
4. **New chapters:** run the index pass per chapter (~16–18 min per language per chapter
   at current rates; the EN gap pass should be batched too, ~1 min).
5. **Batch `clipbank.qa_sample`** like the gap pass (it currently calls whisper per clip).
6. **NL `unindexed` regions (232)** are mostly word tails and breaths around peaky CTC
   spans, so they are not useful for NL yet. Tune (e.g. require a pause-bounded island) or
   ignore for NL.
7. **Ambiguous case** "'Een wat?'": the index puts "een" inside the clip, while whisper on
   the 0.6 s clip heard only "wat". Settle by ear.

## 5. Observed vs assumed

- **Observed:** every timing, count and recall figure above. Index cut times equal the
  verified cut times. The gap pass speed-up from batching.
- **Assumed / not yet observed:**
  - that listening confirms the 9 onset cuts and 3 low-score clips on the v2 list;
  - that the provisional onset rule generalises beyond its 26 samples;
  - per-chapter costs for chapters 2–17 (projected from chapter 1).
