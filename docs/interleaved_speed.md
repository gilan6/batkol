# Interleaved audiobook: the first Dutch play at 0.8× (2026-11-05)

No book text in this file. Numbers are observed unless marked *(assumed)*.

## Layout

Per unit the interleaved audiobook plays the Dutch clip, 1 s, the English clip, 1 s, the Dutch clip
again, 1 s. Since 2026-11-05 the first Dutch play is slowed to 0.8× with the pitch kept; the English
and the second Dutch play are at normal speed. You hear the sentence slowly, get its meaning, then
hear it at full speed.

```bash
uv run python -m batkol.interleaved b2ch04                    # default --speeds 0.8,1,1
uv run python -m batkol.interleaved b2ch04 --speeds 1,1,1     # every play at normal speed (the layout before 2026-11-05)
```

- `--speeds` gives the speeds of the first Dutch play, the English play and the second Dutch play.
  `[0.8, 1, 1]` (quoted) is accepted too. Each speed must be 0.5–2: ffmpeg 4.4's atempo takes 0.5–100,
  but above 2 it skips pieces of audio instead of blending them (ffmpeg's documentation), and below
  0.5 it would need two filters in a row.
- A play at speed 1 is the leveled clip as is. Any other speed stretches the leveled clip
  (`build.atempo`), so the leveling (`build.match_loudness`) does not depend on the speeds.
- `build.atempo` feeds 0.3 s of silence after the clip, so atempo's last window reaches the clip's
  end, trims the output to round(length / speed) samples, and fails if ffmpeg returns fewer.
- The TSV and `units.json` give each play's start in the MP3: `out_start` (the unit, i.e. its first
  Dutch play), `out_en`, `out_nl2`. The report lists the speeds.
- `--out DIR` writes somewhere other than `~/work/<chapter>/interleaved/`.

## How the method and the speed were chosen

An experiment in a folder outside the repo (deleted afterwards), on the first sentences of HP2 ch. 2.
Every sample was leveled to −18 LUFS, and the choice was made by ear.

| Method | How it stretches | Result |
|---|---|---|
| rubberband (ffmpeg; defaults, and long window with smooth transients) | phase vocoder | metallic, worst on a long *ee* vowel; 1–3 dB of energy lost |
| plain slowdown (`asetrate` + `aresample`) | plays the samples slower | the pitch drops with the speed |
| Praat PSOLA ("Lengthen (overlap-add)") | repeats whole voice periods | pitch kept |
| ffmpeg `atempo` | time-domain overlap-add (WSOLA-like) | pitch kept; **chosen** |

- **What was compared, in order.**
  1. The chapter's first 12 units in the interleaved layout, both NL plays slowed by rubberband to 0.9×
     and 0.8×: metallic.
  2. One sentence at 0.9× and 0.8× by each stretcher.
  3. Five sentences, each as the original, then plain slowdown, atempo and PSOLA at 0.8×: atempo best.
  4. Three sentences as the original, at 0.8× and at 0.75×, one file for atempo and one for PSOLA.
  5. One unit in the interleaved layout with the first NL play at 0.8× by atempo, which became this flow.
- **Pitch**, frame by frame (Praat, 10 ms frames, 60–400 Hz) over the five sentences: the stretched
  version at time t / 0.8 against the original at t. Median ratio: atempo 0.999 (80 % of frames within
  3 % of it), PSOLA 1.001 (87 %), plain slowdown 0.800.
- **A ratio of small integers** (3/4 against 4/5) has no technical advantage: the stretchers work on
  short windows at any ratio; only how much the sound is stretched matters.
- **Cost**, measured on chapter 4 (266 Dutch clips, 37.4 min of Dutch): 19.4 s of atempo for one slowed
  play, i.e. 0.52 s per minute of Dutch, 73 ms per clip, mostly starting ffmpeg. One continuous 60 s
  piece takes 0.24 s. The audio analysis is not affected.

## Chapter 4 rebuilt

- **Run.** `python -m batkol.interleaved b2ch04` from a snapshot of `8ff98cb`: 3.1 min wall, peak memory
  3.0 GB (at `--speeds 1,1,1`: 2.6 min, 2.7 GB).
- **Nothing else changed.** At `--speeds 1,1,1` the MP3 is byte-identical to the 2026-11-03 build. At
  `0.8,1,1` the 266 units, their sentence ids, cut times, flags, risks and merges are identical to it.
- **Length.** 132.5 min, from 123.1: the first play of the chapter's 37.4 min of Dutch takes 46.8 min.
- **Play starts** (`out_start`, `out_en`, `out_nl2`) agree with the clip lengths and speeds within 6 ms
  over 797 plays, and the TSV's end agrees with the MP3's length within 37 ms.
- **Levels** per play (LUFS): first NL median −19.4 (p10 −21.3, p90 −15.6), EN −18.7 (−19.5, −16.5),
  second NL −19.6 (−21.5, −15.8). The slowed play measures a median 0.2 dB above the second play of the
  same unit (p10 0.0, p90 +0.35). Whole file −18.5 LUFS (was −18.6), true peak −0.8 dBTP.

## Not covered

- Speeds above 1 were neither heard nor measured; speeds other than 0.75×, 0.8× and 0.9× were not heard.
  The code path is the same for every speed, but listen to a one-sentence sample before a whole chapter.
