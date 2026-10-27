# Pimsleur-style Dutch drills: proof-of-concept plan (v2, 2026-10-17)

Supersedes the "Status 2026-10-15" plan where marked. No book text in this file.

## 1. PoC goal

One lesson (~15 min) from one passage of HP1 ch. 1 that runs every mechanism of the
program end to end. Output on Drive in `gdrive:batkol-out/poc/lesson01/`: MP3 plus a
sidecar JSON listing the source of every utterance.

Done when all of these hold:
- **Mechanisms:** passage played at the start and again at the end; anticipation;
  backward buildup; in-lesson recall at 5 s, 25 s, 2 min and 10 min; at least 2
  recombination drills; Pimsleur English instruction frames ("frames").
- **Audio sources:** coverage gate reported per category. Dutch targets are 100 %
  human recordings. Overall human-recorded seconds ≥ 90 %.
- **Cut quality:**
  - Every clip used is re-transcribed and shows 0 edge defects.
  - The user listens to about 20 backward-buildup cuts and passes them before the
    full render.
- **Runtime:** ≤ 1.5 h of compute in this environment. Every step ≤ 25 min and
  resumable.

## 2. Established facts (observed 2026-10-17)

### Inputs (P0 resolved)

All on Drive, all DRM-free files.

| Input | Fact |
|---|---|
| NL ebook | 2 EPUB editions. The audio follows the Harmonie 2000 edition ("Duffelings"). Its text was repaired: encoding bug, 33 dashes restored, 6 OCR fixes. |
| EN ebook | UK *Philosopher's Stone*. Two copies, chapter 1 identical. |
| NL audiobook | One narrator (Jan Meng). One Opus file per chapter (17). Chapter 1 is 35.0 min. |
| EN audiobook | Audible / Pottermore full cast. One Opus file per chapter. Chapter 1 is 32.8 min, with about 75 s of credits before the text. |
| Pimsleur Dutch I | 30 lessons (~29 min each, MP3 96 kbps), 20 readings, booklet PDF, user guide. About 15 h in total. |

### Environment

This Claude Code cloud session.
- **Machine:** 4 vCPU, 16 GB, no GPU. Started from the phone.
- **Reachable:** PyPI, Hugging Face, GitHub, `dl.fbaipublicfiles.com`, Google APIs.
- **Blocked:** `download-r2.pytorch.org` (torch is installed from PyPI instead).
- Drive is accessed through rclone.
- §8 of the old plan (Colab) is not needed for the PoC.

### Built and verified (repo `batkol/`, NL→EN→NL ch. 1 drill)

- EPUB text extraction and repair; sentence splitting.
- NL forced alignment: torchaudio MMS_FA in 120 s windows.
- EN: whisper large-v3-turbo transcript → MMS_FA alignment of that transcript →
  match to the book text, plus re-transcription of gaps whisper skipped.
- NL↔EN sentence pairing (n:m): LaBSE + dynamic programming.
- Pause map from audio energy; cut snapping; merging of units with no pause between them.
- Loudness matching; assembly; re-transcription check of every clip; cached,
  resumable stages.

### Measured

| What | Value |
|---|---|
| Chapter 1 compute | ~25 min |
| Verification | ~7 s per unit |
| whisper turbo | 0.26 × realtime |
| MMS emissions | 0.155 × realtime |
| NL narrator pause map | 49 % of sentences have an internal pause ≥ 150 ms. Pause-bounded chunks: median 7 words; 44 % are 2–6 words. |
| Sentence boundaries without a pause ≥ 120 ms | 16 % NL, 9 % EN (fast dialogue, overlapping voices) |

EN full cast:
- Constant background bed at about −34 dB, no true silence. Whether it is music or
  ambience is not identified.
- Speech tags such as "said Dumbledore" are dropped.
- Whisper's long-form transcription skips short exclamations.

NL narrator: adds small words that are not in the EPUB ("en", "ja") and changes word
order in places.

### Rules learned

1. Cut only inside measured pauses ≥ 120 ms. Where there is none, merge the units;
   never cut through speech.
2. Run CTC forced alignment in windows. One pass over more than 2³¹ cells (frames ×
   states) segfaults torchaudio.
3. Re-transcribe speech-bearing gaps left by the long-form transcript.
4. Re-transcription checks catch edge words, not missing content. Keep a human listening gate.
5. Avoid gated models (pyannote needs a Hugging Face token). For Pimsleur, use
   language ID per pause-bounded segment instead of diarization.
6. Run long jobs as harness-tracked background tasks: time-boxed, with cached stages.
   No hand-rolled `pgrep` watchers (one matched its own command line).

## 3. PoC steps

Estimates are projected from measured rates. "Gate" means stop and report before
continuing.

| Step | Work | Est. | Output / check |
|---|---|---|---|
| L0 | Resources: spaCy `nl_core_news_md`, Piper TTS voices nl/en (Hugging Face), wordfreq; Pimsleur Lessons 01–02. Time a 1-min slice of each new model. | 10 min | Each loads. A proxy 403 is reported, not worked around. |
| L1 | Pimsleur frames: split Lessons 01–02 at pauses → whisper language ID per segment → transcribe EN and NL segments. Group recurring English frames ("Listen and repeat", "How do you say …", "Say …", "Do you remember …"). Keep the cleanest take of each frame and the Dutch citation clips. | 20 min | Frame catalogue JSON plus a sample MP3 for the user. |
| L2 | Passage and items: spaCy lemmas and part-of-speech tags; chunk candidates from the pause map. Known words = lemmas of the Dutch turns in Pimsleur L01–02 plus the wordfreq top-N (a stand-in; see §4). LLM step in this session, using indices only and never copying text: pick 10–12 target chunks, backward-buildup split points, the matching English audiobook span with an equivalence yes/no, and glosses where no faithful span exists. | 10 min | `passage_items.json` |
| L3 | Clip bank: NL chunks (pause cuts), backward-buildup suffixes (onset at the word start, snapped to the energy minimum within ±50 ms, preferring a stop or fricative onset, 10 ms fade-in), EN cues from the audiobook span, Pimsleur NL citation forms where the vocabulary overlaps, Piper TTS on misses. | 10 min | **Gate:** about 20 buildup onset cuts as one MP3; the user passes them before L5. |
| L4 | Recombination: "found sentences" are other sentences in the Dutch book that contain a target lemma, are ≤ 8 words, and have every other lemma known or already drilled; prefer quoted dialogue. Search ch. 1 first; if fewer than 2 are found, align ch. 2 (~6 min). Concatenation joins whole chunks at pauses only, rejecting joins with a large F0 / energy / MFCC jump (librosa). | 10–15 min | Recombination list |
| L5 | Scheduler (code): items × [5 s, 25 s, 2 min, 10 min] placed greedily. Lesson order: passage → introduce items (anticipation + backward buildup) → interleaved recalls → recombination → passage. Due dates persisted for the later steps (1 h … 2 y). | 5 min | `schedule.json` |
| L6 | Coverage gate: TTS seconds ÷ total per category (frames, EN cues, NL targets, buildup, recombination). | 1 min | **Gate:** stop if NL targets are not 100 % human. |
| L7 | Render MP3 + sidecar; re-transcribe every distinct clip used; upload. | 10 min | `lesson01.mp3`, `lesson01.json`, report |

Total: about 1.5 h of compute plus two listening gates.

## 4. Decisions (recommended option first)

1. **Dutch item with no human audio:** drop it and report (PoC) / Dutch TTS.
2. **Passage:** ch. 1 opening paragraphs (already aligned, verified, cuts clean) /
   a dialogue-rich passage (more present tense, more pause-less boundaries).
3. **Known-word list:**
   - Pimsleur L01–02 transcripts + wordfreq stand-in (PoC);
   - full-course transcription: ~15 h audio ≈ 4 h CPU, which needs splitting into
     ≤ 25 min runs; second pass.
4. **TTS engine:** Piper (offline, no key, average quality; reachability not yet
   verified) / Google Cloud TTS (API reachable, needs a key).
5. **PoC lesson length:** ~15 min / 30 min.

## 5. Risks to test first

- **Buildup onsets cut inside speech:** about half of all chunk boundaries have no
  pause. This is untested and decides whether backward buildup can use narrator
  audio → L3 gate.
- **EN cue clips:** background bed, overlapping voices, dropped words. Demucs is
  still undecided; decide by listening to the L3 cue clips.
- **Pimsleur language ID:** the narrator mixes Dutch words into English frames.
  English-only segments are frame candidates; Dutch citations come from
  Dutch-only segments.
- **Found-sentence yield in ch. 1 alone is unknown;** ch. 2 alignment is the fallback.

## 6. Decisions taken (2026-10-17)

- **No Dutch TTS:** every Dutch utterance is narrator audio. An item with no clean cut is dropped. English TTS (Piper, free) is a fallback only.
- **Pimsleur:** only Lesson 01 is processed (~30 min of audio), for the English instruction phrases. No full-course transcription.
- **Passages** follow chapter order; each lesson continues where the previous one stopped.
- **Goal is pronunciation.** The learner knows almost all words, so there is no vocabulary selection. Items are 2–6-word pause chunks plus backward buildup, with many repetitions of natural speech.
- **English cue first** (anticipation: translate, then hear the narrator, then repeat). No slowed versions.
- **Lesson 1 is 15 min;** 30 min next.

## 7. Clip bank: verify each sound bite once, then build (`batkol/clipbank.py`)

Sound bites are reused many times: a Dutch target plays about 6 times in one lesson, and again in later lessons. So verification belongs to the bite, not to the final product.

- **Identity.** A clip id is a hash of the source and the cut: source, start, end, fade-in. A changed cut gets a new id, so it is checked fresh.
- **Checks, once per id:**
  - signal: energy at each cut relative to the local silence threshold;
  - re-transcription: lost or leaked words at the clip edges, compared with the clip's expected tokens.
- **Status:**
  - `pass`;
  - `review`: the cut is inside speech (buildup onsets), or the edges differ beyond a fuzzy match; needs a listening verdict;
  - `fail`: a missing or extra edge word, or a cut ≥ 3 dB over the silence threshold.
- **Log.** `~/work/bank/clips.jsonl` is append-only; the latest record per id wins. Human verdicts are appended with `by=user` and override the automatic status:
  `python -m batkol.clipbank verdict <log> <clip_id> pass|fail [note]`
- **Builders** request clips, the bank answers from the log or verifies new ones, and only usable clips enter the schedule. On failure:
  - Dutch target → drop the item;
  - English cue → Piper TTS;
  - buildup piece → drop the piece;
  - Pimsleur phrase → TTS.
- **Rebuilds** recheck nothing. Lesson 1 v1 checked 65 clips; later rebuilds checked 0 (only new recombination clips were added). Render is pure assembly, and the sidecar carries the clip id of every utterance.
- **Next:**
  - a retry before dropping, e.g. move an in-speech onset to the next energy minimum;
  - port the ch. 1 NL→EN→NL drill to the same bank;
  - carry recalls that are not yet due (1 h … 2 y) into the next lesson.
