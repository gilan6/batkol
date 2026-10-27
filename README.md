# Batkol

*Bat kol* (Hebrew בת קול, "daughter of a voice") is an echo: a real voice that comes back to you.

**Built by an AI agent, to be run by an AI agent.** The author never read the code: every
change and every run goes through Claude Code. Batkol is a tool to adjust and build on, not a
finished app: ask the agent to change any part of it.

**Every target-language word you hear is a real native speaker, from audio you provide.** Nothing in the target
language is ever synthesized.

## What it does

This project turns native content you already own into audio for practising listening and
pronunciation. You hear short pieces of real native speech and mimic them, many times over.
It makes two kinds of audio: Pimsleur-style lessons, and an interleaved audiobook that plays
a chapter sentence by sentence in both languages.

The first case built is Dutch for English speakers, from the Harry Potter audiobooks: Jan
Meng's Dutch reading, the English audiobook, and instruction phrases from Pimsleur Dutch I.

Target-language audio is always cut from the recording. If a clip can't be cut cleanly, the
item is dropped, not synthesized. Native-language audio (cues and instructions) also comes
from recordings when they exist, and falls back to an offline TTS voice (Piper) when they
don't.

The same pipeline also builds lessons from learner content: 50languages, a free course whose
100 lessons say every sentence in English and then twice in Dutch.

## What it makes

Batkol's output is MP3 files, for any audio player, with no screen needed. The videos below
exist only for this page: they add captions so you can follow what you hear. Each example's
MP3 is linked under it.

### Pimsleur-style lessons

Each item is an instruction and an English cue, then a pause where you say it in Dutch. The
Dutch narrator follows, then a pause where you repeat. Long phrases are built up from their
end, and items come back at growing intervals and as reviews in later lessons. Lessons train
pronunciation, and they also improve comprehension.

https://github.com/user-attachments/assets/c7c386ac-30b8-4532-8bec-c2c519485a46

*Example: one item from lesson 1 (45 s). "How do you say…", the English line, your turn,
the Dutch narrator, your turn. Then "Listen and repeat", and the phrase built up from its end.
[Listen to the MP3](https://github.com/gilan6/batkol/releases/download/readme-examples/lesson_example.mp3)*

### Interleaved audiobook

One MP3 per chapter: every sentence in Dutch, then English, then Dutch again, with 1 s
gaps. You hear the sentence, get its meaning, then hear it again knowing what it says. It
trains listening comprehension.

https://github.com/user-attachments/assets/4238a3bf-8a58-4b0a-9928-600003d51b92

*Example: one sentence from book 2, chapter 1 (10 s), taken from the 56-minute chapter file.
[Listen to the MP3](https://github.com/gilan6/batkol/releases/download/readme-examples/interleaved_example.mp3)*

### Lessons from learner content (50languages)

The same lesson pattern, built from 50languages. Each Dutch sentence comes from two
speakers, and you repeat after both. How the source is laid out, and how lessons are built
from it, is in `docs/local_plan.md` §7.

https://github.com/user-attachments/assets/ad3b84dd-73da-471b-823a-ce329506836a

*Example: one item from lesson 1 (21 s). "How do you say…", the English line, your turn, then the first and
the second Dutch speaker, each followed by your turn. Audio © Goethe Verlag (50languages),
CC BY-NC-ND 3.0. [Listen to the MP3](https://github.com/gilan6/batkol/releases/download/readme-examples/fiftylang_example.mp3)*

## What you bring

- **Required:** target-language audio and its text, for example an audiobook and its EPUB.
- **Optional:** the same work in your own language. Its recording gives natural cues and is
  needed for the interleaved audiobook; without it, lesson cues are read by Piper.
- **Optional:** instruction phrases from a course you own. Without them, Piper reads them.

The repo holds code and lesson specs only, which point at positions in the book. No book
text or audio is in git. Your own file paths go in `batkol/sources_local.py`, which git
ignores; start from `batkol/sources_local.example.py`.

## How to use it

Open the repo in Claude Code and ask in plain words, for example:

- "Set up this laptop from docs/local_plan.md."
- "Add chapter 2 of book 1 and build its interleaved audiobook."
- "Build lesson 6."
- "Listening list for lesson 6: 3 and 7 sound clipped."

`CLAUDE.md` is the agent's manual: where things live, the commands, and the working rules.
`docs/` holds the design notes, with measured numbers.

Today, quality is checked by ear, not by code review. Each lesson comes with a short listening
list of its riskiest cuts. Your pass/fail verdicts are stored, and a failed clip is never used
again. That is the current behavior, not a fixed rule: like the rest of Batkol, it can be
changed, for example to add automatic checks.

Requirements: Linux or Windows with WSL2 (x86_64), CPU only, 16 GB RAM, uv and ffmpeg, plus
rclone if your inputs live on Google Drive.
