# Moving the project to the laptop, then adding 50languages (plan, 2026-10-27)

No book text in this file. Facts are observed in the repo, the docs or earlier sessions unless marked
*(assumed)*. Hardware figures come from the cloud container (4 vCPU, 16 GB, no GPU).

## 1. What the project does now

| Product | Code | State (2026-10-24) |
|---|---|---|
| (a) NL→EN→NL chapter drill: per unit, NL clip, 1 s, EN clip, 1 s, NL clip, 1 s | `drill.py` (index-only); `pipeline.py` is the legacy HP1 builder | HP1 ch. 1 v3 and HP2 ch. 1 (56.4 min, 121 units) are on Drive in `batkol-out/poc/` |
| (b) Pimsleur-style lessons: frame + EN cue, pause, narrator, repeat; buildup; recalls; reviews from learner state | `lesson.py`, `learner.py`, `clipbank.py`, specs in `batkol/lessons/` | HP1 ch. 1, lessons 1–5 (units 1–17). Lesson 6 starts at U18; items U18–U24 are already in `lesson05.json` |

Shared flow (`docs/flow_v2.md`): **analyze** (whisper large-v3-turbo int8 + MMS_FA CTC + gap pass)
→ **edition** check → **index** → plan, cut and render with no ASR.

- Models: whisper large-v3-turbo (CTranslate2, CPU int8), torchaudio MMS_FA (1.2 GB), LaBSE, Piper `en_GB-alan-medium`.
- Data: Drive through rclone.
  - Inputs: `gdrive:batkol/` (read-only).
  - State: `gdrive:batkol-out/state/` (63 MB).
  - Outputs: `gdrive:batkol-out/poc/`.
- None of it needs a GPU. Every model runs on CPU (`device="cpu"` everywhere).

### Git state

- `main` holds only an empty README.
- All code is on three unmerged `claude/*` branches. They form one linear chain.
- `claude/intelligent-wozniak-uparf9` (e8305f4) contains everything. This branch is fast-forwarded to it.

### Open work carried over

From `docs/flow_v2.md` §4 and `docs/book2_ch01.md`:
1. Lesson 2 listening list: 18 clips pending. HP2 drill: not listened to.
2. Lesson 6 onward (HP1 ch. 1 from U18).
3. Port the HP1 ch. 1 drill to the index; remove per-clip verification from `pipeline.py`.
4. NL narrator additions right before a sentence. Stopped after two failed fixes. Next test: gap plus the first 1–2 s of speech.
5. More chapters, which need a registry entry each in `sources_local.py`.

## 2. What changes on the laptop, and why it helps

| Cloud pain (observed) | On the laptop |
|---|---|
| Container is ephemeral: restore at start, back up after every costly step | `~/work` persists. Drive becomes an off-site backup and the phone listening outbox |
| Drive token in an env var expired again and again (`invalid_grant`) and blocked two sessions | rclone config on disk. Renewing is one local command with a browser (§4 step 4) |
| Every long step had to stay ≤ 25 min inside a live session | Same rule (resumable stages), but runs can go overnight. Whole books become practical (~25 min per chapter for both languages, so ~7 h for HP1) *(assumed from HP1/HP2 rates)* |
| Proxy blocked `download-r2.pytorch.org` and **50languages.com** (403, checked 2026-10-27) | Not blocked |

## 3. Laptop requirements

| Item | Requirement | Why |
|---|---|---|
| OS | Linux, or Windows 11 + **WSL2 Ubuntu 24.04** | `[tool.uv] environments` locks to `linux / x86_64`; bash scripts; ffmpeg via subprocess. Native Windows or macOS would mean porting, which is not worth it |
| CPU | x86_64, ≥ 4 cores | Lock file is x86_64-only. Threads are hard-coded to 4 (`asr.py`, `align.py`) |
| RAM | 16 GB recommended | Whisper and MMS_FA are loaded together in `analyze`. Observed fine at 16 GB; 8 GB not tested |
| Disk | ≥ 25 GB free | See the breakdown below |
| GPU | none | All models run on CPU int8/fp32 |

Disk breakdown (sizes *(assumed)* unless stated):
- venv ~6 GB: the lock pulls 43 CUDA/triton wheels (counted in `uv.lock`; ~3 GB) that a CPU-only machine never uses (§6, decision 1).
- Models ~5 GB in the Hugging Face and torch caches (MMS_FA 1.2 GB observed).
- Inputs per chapter: tens of MB of opus. The HP2 EN source is a 1 GB m4b.
- 16 kHz caches: ~130 MB per 35 min of audio. State: 63 MB.

**WSL2 specifics:**
- Keep the repo and `~/work` inside the Linux filesystem, not `/mnt/c`. Cross-filesystem I/O is very slow.
- WSL takes 50 % of host RAM by default. On a 16 GB laptop, set `memory=12GB` in `%UserProfile%\.wslconfig`.
- Listen to outputs from Windows at `\\wsl$\Ubuntu\home\<user>\work\...`.
- Run Claude Code inside WSL, so it uses the Linux tools.

## 4. Setup steps (one time)

1. **Packages:**
   ```bash
   sudo apt install -y git ffmpeg curl unzip
   curl -LsSf https://astral.sh/uv/install.sh | sh
   curl https://rclone.org/install.sh | sudo bash
   ```
   - Check that `ffmpeg -encoders | grep libopus` is non-empty and that `ffprobe` is present.
   - `uv` installs Python 3.11–3.13 itself.
2. **Claude Code** in the same shell: native installer, then `/login`. Optionally `gh auth login`, for PRs from the laptop.
3. **Repo:**
   - `git clone https://github.com/gilan6/batkol.git ~/batkol` (`main`).
   - Switch torch and torchaudio to the CPU index (§6), then run `uv lock`. Check that `uv.lock`
     has no `nvidia-*` or `triton` packages left.
4. **rclone remote named `gdrive`: an alias for the mounted Drive.** The code hard-codes `gdrive:`.
   No OAuth client or token, so no `invalid_grant`.
   - Google Drive for desktop mounts Drive on Windows as `G:`. Mount it in WSL:
     `sudo mkdir -p /mnt/g && sudo mount -t drvfs G: /mnt/g -o uid=1000,gid=1000`, and add
     `G: /mnt/g drvfs defaults,uid=1000,gid=1000 0 0` to `/etc/fstab`.
   - `rclone config create gdrive alias remote="/mnt/g/My Drive"`.
   - Nothing enforces read-only any more (the old token's `drive.file` scope did). Write only inside
     `batkol-out/`; `batkol/` is read-only input. Never delete on G:.
   - `/mnt/g` streams from Drive and is slow: never a working directory.
   - Observed 2026-10-27:
     - `rclone lsd` lists `batkol/` and `batkol-out/`; `state/` is 85 objects, 62.6 MiB.
     - Every path in `batkol/sources_local.py` exists under the mount. The HP2 m4b keeps its U+A789 colon.
     - `backup_state.sh` writes with modtimes set and no errors, so `RCLONE_LOCAL_NO_SET_MODTIME` is not needed.
     - Not yet observed: the fstab line remounting `G:` after a WSL restart.
5. **Seed state and inputs:**
   - Run `bash scripts/restore_state.sh ch01 b2ch01`. It runs `uv sync`, copies state from Drive, fetches the HP1 and HP2 ch. 1 audio and EPUBs plus Pimsleur L01, and downloads the Piper voice.
   - Models download on first use (~4 min observed).
6. **Verify. Nothing here changes learner state.**
   - `uv run python -m batkol.index nl_ch01 en_ch01 pims_L01` should rebuild the indexes from caches in seconds.
   - Regression gate (from `docs/book2_ch01.md`):
     `uv run python -m batkol.drill ch01 --no-risk-merge --no-render --compare ~/work/ch01/units.json`.
     Expect 239/239 groups and ≥ 95 % of cuts within 20 ms (cloud: 95.3 %).
   - Laptop speed: `uv run python -m batkol.analyze b2ch01 nl --slice 60`. Cloud reference: whisper
     rtf 0.33, emissions rtf 0.25. Plan run lengths from this number.
   - Do **not** smoke-test with `batkol.lesson`: a build records learner state.
   - Observed on the laptop (2026-10-27). Setup: Ryzen 5 PRO 4650U (6 cores / 12 threads), Ubuntu 22.04.4,
     ffmpeg 4.4.2, torch 2.14.1+cpu, 7.5 GB visible to WSL (no `.wslconfig`); venv 1.5 GB.
     - Index rebuild: 43 s for the three, first 16 kHz decodes included. The indexes equal the cloud ones
       except the `local` path.
     - Regression: 239/239 groups, 95.3 % of 956 cuts within 20 ms; `units.json` is byte-identical to the cloud run.
     - Slice, two runs, 4 threads: whisper rtf 0.85, emissions rtf 0.46. That is ~2.6× and ~1.8× the cloud.
       Models load in 35 s cached (127 s with downloads); peak RSS 4.2 GB.
     - So HP2 NL whisper + emissions ≈ 24 min (cloud ~10). §2's per-chapter projections are
       ~2.5× longer at this rate *(assumed; align and gap passes not timed)*. Re-time after §5.2.
7. **Keep the laptop awake during long runs:**
   - Linux: `systemd-inhibit --what=idle:sleep <cmd>`.
   - Windows: a power plan with no sleep while plugged in. WSL stops when Windows sleeps.

## 5. Repo changes for local use (small, after step 6 passes)

1. **`CLAUDE.md`, local section:**
   - no per-session restore;
   - `backup_state.sh` after costly steps, as an off-site copy (still required: the laptop disk is now the only live copy);
   - remove the proxy notes.
   - Keep the working rules, the no-book-text-in-git rule and the no-paid-API rule unchanged.
2. **Thread count from an env var** (`BATKOL_THREADS`, default 4) in `asr.py` and `align.py`. Then
   re-time the slice with the laptop's real core count. Physical cores, not threads, usually win for
   CTranslate2 *(assumed)*.
   - Done 2026-10-31. Slice of HP2 ch. 2 NL with `BATKOL_THREADS=6` (the 6 physical cores): whisper
     rtf 0.78, emissions rtf 0.37, models loaded in 52 s (4 threads, §4 step 6: 0.85 and 0.46).
     A 21-min chapter is then ~16 min whisper + ~8 min emissions: `analyze --asr-only` splits the
     pass in two, so each step stays under 25 min. 12 threads not tried.
3. **Chapter registry:** generate `sources_local.py` entries for the remaining chapters (globs, as for
   HP2), so whole books can be queued.

## 6. Decisions taken (2026-10-27)

- **Laptop:** Windows 11, x86_64, 16 GB, no GPU → WSL2 Ubuntu.
- **CUDA wheels dropped.** torch and torchaudio come from the CPU index (`download.pytorch.org/whl/cpu`).
  - The relock must run on the laptop: the cloud proxy blocks `download-r2.pytorch.org` (tried 2026-10-27).
  - Gate: the §4 step 6 regression passes on the CPU stack before the new lock is committed.
- **Laptop only.** Cloud sessions are retired, because they can no longer `uv sync`. Drive stays as backup and listening outbox.
- **Git:** all work merged into `main`. Work from `main` (or short branches off it) locally.

## 7. Expansion: Pimsleur-like lessons from 50languages Dutch audio

### What the source offers (F0, observed 2026-10-27 on lesson 1)

- **Files.** `gdrive:batkol/ENNL-all.zip` (79 MB) holds `ENNL001.mp3` … `ENNL100.mp3` (1–2 MB each) and
  `_readme.htm`: one MP3 per lesson, not per sentence. Working copy in `~/work/in/50l/`.
- **License** (`_readme.htm`): CC BY-NC-ND 3.0 US, © Goethe Verlag, "free for private use and for public
  schools". Private, non-commercial use fits. Do not share or publish the remixed lessons.
- **Format.** MP3, 32 kHz mono, 48 kbps, no tags. Lesson 1: 174 s, −18.9 LUFS, true peak −1.4 dBFS.
- **Layout of lesson 1.** The full table, with text, is in `~/work/50l/ENNL001.md` (not in git).
  - Intro: 4 EN clips of publisher credits (0.5–13.4 s). Outro: ~1.8 s of low-level sound with no words *(assumed music)*.
  - Header: the lesson number and the title, each as a triplet. The number's EN clip starts with ~5.7 s of
    music (−33 dB) that runs to within 30 ms of the word.
  - Body: 18 sentences in 6 blocks of 3.
  - Every item is a triplet **EN → NL → NL**. Clips are separated by digital silence (floor −120 dB),
    so clip edges are exact cut points. Speech is trimmed to within ~0–40 ms of each edge.
  - Gaps: EN→NL 1.47–1.52 s, NL→NL 1.08–1.12 s, between sentences ~1.5 s, between blocks 2.49–2.52 s.
- **Speakers.** The two NL readings are different takes (cross-correlation 0.04–0.17). They are probably two
  speakers: median f0 ~160 Hz for the first, ~227 Hz for the second, which is also 0–50 % longer. EN f0 is too
  noisy to tell *(simple autocorrelation tracker)*.
- **Language.** Whisper's detection per role window: EN p ≥ 0.98, NL p ≥ 0.996. The gap pattern alone
  identifies the roles.
- **Whisper text** (one pass, clips batched by role into ~28 s windows): good but not exact.
  - 1 of 60 clips came back empty: its word timestamp fell outside the clip.
  - The two NL readings disagree on one word of one sentence.
  - Low confidence on the number words.
  - Word times run ~0.5 s early in batched windows. Clip edges do not depend on them.
- **Cost.** 3 min 55 s for lesson 1; whisper took 221 s for 7 windows. Each window took 28–36 s whatever its
  audio length (12 s of audio took 33 s): whisper pads every call to 30 s. All 100 lessons ≈ 6.5 h *(assumed)*.
- **Not yet observed:** lessons 2–100 (does every lesson have intro, number, title, 18 sentences?); the site's text.
- The lesson-1 analysis ran from scratch scripts, not repo code. F1 turns them into `fiftylang.py`.

### Why it fits the pipeline, and what is new

- **The text is known, and it is the spoken text** *(assumed until the site text is fetched)*.
  - The edition check should always say `book`.
  - Pairing is by triplet position, so LaBSE is not needed. Never pair by text: one EN sentence occurs
    twice in lesson 1 (singular and plural "you").
- **The English cue is human audio**, not Piper. This meets the no-TTS spirit better than the HP gloss fallback.
- **Clean pauses between sentences** come for free: digital silence between clips (observed).
- **Two NL readings per sentence** (probably a male and a female speaker): a drill can use either or both.
- **New:** short sentences mean fewer `parts`. Backward buildup still needs cuts inside speech
  (`ok_cut` / `risky_onset`), and those rules were calibrated on one narrator only. New speakers mean
  new listening verdicts before trusting them.

### Design: make a 50languages lesson look like a chapter

- **`batkol/fiftylang.py` (new): split, then fetch text.**
  - For lesson *k*, extract `ENNL<k>.mp3` from the zip into `~/work/in/50l/`. Split it at digital silence and
    assign roles from the gap pattern: EN, NL reading 1, NL reading 2; intro, header and outro kept apart.
  - Concatenate each role's clips into one opus with ≥ 0.6 s of silence between sentences, and record the offsets.
  - Fetch the sentence texts once from the site (throttled, cached). Write `~/work/text/{nl,en}.fl<k>.txt`,
    one sentence per line. That text stays out of git, like book text.
  - With the site text, no whisper is needed: roles come from the gap pattern, and word times come from
    MMS_FA on the known text. Whisper is then only a sampled check.
- **Registry:** chapter ids `fl001` … `fl100` in `sources_local.py`, with a local source instead of a Drive path.
- **Unchanged:**
  - `analyze` / `edition` / `index` work on them as is, with tiny compute: ~2–3 min of audio per lesson *(assumed)*.
  - EN could skip whisper, because the text is exact (MMS_FA on the known text, as NL does).
- **Lesson builder:**
  - `lesson.Sources` hard-codes the HP chapter's `units.json` and `pims_L01`. Add a 1:1 units file for `fl*` chapters.
  - Specs keep the same shape: `nl_book` / `en_book` token ranges.
  - Pimsleur frames stay from `pims_L01`.
- **Learner state:** namespace item ids by source (`fl003:S07`), so HP and 50L reviews can share one
  ladder. Whether lessons interleave both sources is a user decision; the default is separate lesson series.

### Milestones (each ends with a check the user can hear or read)

| Step | Work | Check |
|---|---|---|
| F0 | Audio and license: **done 2026-10-27** (zip on Drive, lesson 1 analysed; see above). Left: the site's text and its structure | Short note in this file: formats, counts, license text |
| F1 | `fiftylang.py` split + concat for lessons 1–3, text fetch; registry entries | 20 triplets per lesson; offsets match sentence count; listen to one concat file |
| F2 | `analyze --slice 60`, then full `analyze` / `edition` / `index` for fl001 NL and EN | Edition `book`; index pause boundaries at every sentence join |
| F3 | Lesson spec + build of fl001 (~15 min); listening list of in-speech buildup cuts | User verdicts in the span bank; refit `risky_onset` if any fail |
| F4 | Batch the remaining lessons overnight; lesson series continues from learner state | Per-lesson reports; `uncovered` stays empty |

## 8. Order of work

1. §4 setup and the verification gate. Then commit the CPU lock.
2. §5 repo changes (`CLAUDE.md` is already updated for the laptop).
3. Carried-over listening (lesson 2, HP2 drill). Their verdicts gate the cut rules that 50L reuses.
4. F0–F3 (50languages), in parallel with HP lessons 6+ and new chapter drills, which are now overnight batch jobs.
