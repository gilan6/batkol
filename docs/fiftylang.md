# Lessons from 50languages (design, 2026-10-27)

No sentence text in this file. Numbers are observed unless marked *(assumed)*.

## What the source offers (observed on lesson 1)

- **Files.** `ENNL-all.zip` (79 MB, under `gdrive:batkol/`) holds `ENNL001.mp3` … `ENNL100.mp3` (1–2 MB
  each) and `_readme.htm`: one MP3 per lesson, not per sentence. Working copy in `~/work/in/50l/`.
- **License** (`_readme.htm`): CC BY-NC-ND 3.0 US, © Goethe Verlag, "free for private use and for public
  schools". Private, non-commercial use fits. Do not share or publish the remixed lessons.
- **Format.** MP3, 32 kHz mono, 48 kbps, no tags. Lesson 1: 174 s, −18.9 LUFS, true peak −1.4 dBFS.
- **Layout of lesson 1.**
  - Intro: 4 EN clips of publisher credits (0.5–13.4 s). Outro: ~1.8 s of low-level sound with no words
    *(assumed music)*.
  - Header: the lesson number and the title, each as a triplet. The number's EN clip starts with ~5.7 s of
    music (−33 dB) that runs to within 30 ms of the word.
  - Body: 18 sentences in 6 blocks of 3.
  - Every item is a triplet **EN → NL → NL**. Clips are separated by digital silence (floor −120 dB), so
    clip edges are exact cut points. Speech is trimmed to within ~0–40 ms of each edge.
  - Gaps: EN→NL 1.47–1.52 s, NL→NL 1.08–1.12 s, between sentences ~1.5 s, between blocks 2.49–2.52 s.
- **Speakers.** The two NL readings are different takes (cross-correlation 0.04–0.17), probably two
  speakers: median f0 ~160 Hz for the first, ~227 Hz for the second, which is also 0–50 % longer.
- **Language.** Whisper's detection per role window: EN p ≥ 0.98, NL p ≥ 0.996. The gap pattern alone
  identifies the roles.
- **Whisper text** (clips batched by role into ~28 s windows) is good but not exact: 1 of 60 clips came
  back empty (its word timestamp fell outside the clip), the two NL readings disagree on one word, number
  words get low confidence, and word times run ~0.5 s early. Clip edges don't depend on them.
- **Cost.** 3 min 55 s for lesson 1. Whisper pads every call to 30 s, so each window took 28–36 s whatever
  its length. All 100 lessons ≈ 6.5 h *(assumed)*.
- **Not yet observed:** lessons 2–100; the site's text.

## Why it fits the pipeline

- **The text is known, and it is the spoken text** *(assumed until the site text is fetched)*, so the
  edition check should always say `book`. Pairing is by triplet position, never by text (one EN sentence
  occurs twice in lesson 1, for singular and plural "you"), so LaBSE is not needed.
- **The English cue is human audio**, not Piper.
- **Clean pauses** come for free: digital silence between clips.
- **Two NL readings per sentence**: an item can use either or both.
- **New:** backward buildup still needs cuts inside speech (`ok_cut` / `risky_onset`), calibrated on one
  narrator only; new speakers need new listening verdicts before those rules are trusted.

## Design: a 50languages lesson as a chapter

- **`batkol/fiftylang.py` (planned): split, then fetch text.**
  - Extract `ENNL<k>.mp3` into `~/work/in/50l/`, split it at digital silence and assign roles from the gap
    pattern: EN, NL reading 1, NL reading 2; intro, header and outro apart.
  - Concatenate each role's clips into one opus with ≥ 0.6 s of silence between sentences; record offsets.
  - Fetch the sentence texts once from the site (throttled, cached) into `~/work/text/{nl,en}.fl<k>.txt`,
    out of git like book text. With the text, word times come from MMS_FA; whisper is only a sampled check.
- **Registry:** chapter ids `fl001` … `fl100` in `sources_local.py`, with a local source.
- **Unchanged:** `analyze` / `edition` / `index` work as is (~2–3 min of audio per lesson *(assumed)*).
- **Lesson builder:** a 1:1 units file for `fl*` chapters (`lesson.Sources` hard-codes the HP chapter's
  `units.json` and `pims_L01`). Specs keep `nl_book` / `en_book` ranges; frames stay from `pims_L01`.
- **Learner state:** item ids namespaced by source (`fl003:S07`), so HP and 50languages reviews share one
  ladder. Whether lesson series interleave is a user decision (default: separate series).
