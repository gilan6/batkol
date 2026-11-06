# Setup

What a machine needs to run the whole flow, and how to check it. Numbers are observed unless marked
*(assumed)*.

## Requirements

| Item | Requirement | Why |
|---|---|---|
| OS | Linux, or Windows 11 + WSL2 Ubuntu | The lock targets `linux / x86_64`; bash scripts; ffmpeg via subprocess |
| CPU | x86_64, ≥ 4 cores | `BATKOL_THREADS` sets the threads (default 4); physical cores work best |
| RAM | 16 GB | `analyze` loads whisper and MMS_FA together (peak 4.2 GB); a 2-hour chapter's render peaks at 3 GB |
| Disk | ≥ 25 GB free | venv 1.5 GB, models ~5 GB *(assumed)*, inputs, 16 kHz caches (~130 MB per 35 min of audio) |
| GPU | none | Every model runs on CPU |

On WSL2, keep the repo and `~/work` in the Linux filesystem, not under `/mnt` (cross-filesystem I/O is
very slow), and run Claude Code inside WSL. WSL gets half the host's RAM unless `.wslconfig` says otherwise.

## Steps (one time)

1. **Packages:**
   ```bash
   sudo apt install -y git ffmpeg curl unzip
   curl -LsSf https://astral.sh/uv/install.sh | sh
   curl https://rclone.org/install.sh | sudo bash
   ```
   Check that `ffmpeg -encoders | grep libopus` is non-empty and that `ffprobe` is present. `uv` installs
   Python itself.
2. **Repo:** `git clone https://github.com/gilan6/batkol.git`, then `git config core.hooksPath scripts/hooks`
   (privacy hooks, see `CLAUDE.md`). torch and torchaudio come from the PyTorch CPU index
   (`pyproject.toml`), so no CUDA or triton wheels are installed.
3. **Sources:** copy `batkol/sources_local.example.py` to `batkol/sources_local.py` and point it at your files.
4. **rclone remote named `gdrive`** for the Drive that holds the inputs (`gdrive:batkol/`, read-only) and
   the outputs (`gdrive:batkol-out/`); the code hard-codes `gdrive:`. Drive is slow: never a working directory.
5. **State and inputs:** `bash scripts/restore_state.sh [chapter ...]` runs `uv sync`, copies saved state
   from Drive, fetches the chapters' audio and EPUBs, and downloads the Piper voice. Models download on
   first use (~4 min).
6. **Verify** (nothing here changes learner state):
   - `uv run python -m batkol.index nl_ch01 en_ch01 pims_L01` rebuilds the indexes from caches in seconds.
   - Regression, with the HP1 ch. 1 state:
     `uv run python -m batkol.interleaved ch01 --no-risk-merge --no-render --compare ~/work/ch01/units.json`
     gives 239/239 groups and ≥ 95 % of cuts within 20 ms.
   - Speed: `uv run python -m batkol.analyze b2ch01 nl --slice 60`; plan run lengths from it (6 cores:
     whisper rtf ~0.8, emissions rtf ~0.4).
   - Don't smoke-test with `batkol.lesson`: a build records learner state.
7. **Long runs** need the machine awake: on Linux `systemd-inhibit --what=idle:sleep <cmd>`; on Windows a
   power plan with no sleep while plugged in (WSL stops when Windows sleeps).
