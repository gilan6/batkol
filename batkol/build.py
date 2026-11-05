"""Audio for every output (interleaved audiobook, lessons): cut clips, level them, limit and encode MP3."""
import re
import subprocess
import tempfile

import numpy as np
from scipy.ndimage import minimum_filter1d, uniform_filter1d

from .audio import decode

OUT_SR = 44100
FADE = 0.04
TARGET_LUFS = -18.0        # every source (narrators, cue voices, frames, TTS) lands here, in every output
TRIM_DB = 3.0              # an utterance further than this from the target is pulled back to that edge
MAX_TRIM_DB = 6.0          # ... by at most this much, so a clip of near-silence is never boosted into noise
CEILING = 10 ** (-1 / 20)  # -1 dBFS: the limiter on the final mix
LOOK = 0.005               # s: the limiter's look-ahead
BLOCK_S = 60               # the mix is limited and encoded in blocks of this length (memory)


def clip(src, start, end, fade_in=FADE, fade_out=FADE):
    x = decode(src, start, end - start, sr=OUT_SR).copy()
    for n, sl in ((min(int(fade_in * OUT_SR), len(x) // 2), "in"), (min(int(fade_out * OUT_SR), len(x) // 2), "out")):
        ramp = np.linspace(0, 1, n, dtype=np.float32)
        if sl == "in":
            x[:n] *= ramp
        else:
            x[len(x) - n:] *= ramp[::-1]
    return x


def lufs(x):
    """Integrated loudness via ffmpeg ebur128."""
    with tempfile.NamedTemporaryFile(suffix=".f32") as f:
        x.astype(np.float32).tofile(f.name)
        r = subprocess.run(["ffmpeg", "-hide_banner", "-f", "f32le", "-ar", str(OUT_SR), "-ac", "1", "-i", f.name,
                            "-af", "ebur128", "-f", "null", "-"], capture_output=True, text=True)
    return float(re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr)[-1])


def match_loudness(clips, target=TARGET_LUFS, weights=None):
    """Cross-source leveling. One static gain brings the source to the target (keeping the performance's own
    dynamics); then an utterance more than TRIM_DB off (a whisper, a shout, a quiet take) is pulled back
    toward the target, by at most MAX_TRIM_DB. No peak cap on the gain: capping it left quiet sources
    several dB under loud ones. Peaks are handled once, by the limiter in encode_mp3.
    weights: how often each clip is heard, so the gain fits what the listener hears most."""
    g = target - lufs(np.concatenate([c for c, w in zip(clips, weights or [1] * len(clips)) for _ in range(w)]))
    out = []
    for c in clips:
        x = c * np.float32(10 ** (g / 20))
        if len(x) >= OUT_SR // 2:
            off = lufs(x) - target
            if -60 < off + target and abs(off) > TRIM_DB:
                x = x * np.float32(10 ** (-np.sign(off) * min(abs(off) - TRIM_DB, MAX_TRIM_DB) / 20))
        out.append(x)
    return out, g


def limit(x, ceiling=CEILING, look=LOOK):
    """Look-ahead peak limiter: the gain dips smoothly (over `look` s) around samples above the ceiling,
    and stays at 1 everywhere else, so the level set by match_loudness is kept."""
    need = np.minimum(1.0, ceiling / np.maximum(np.abs(x), 1e-9)).astype(np.float32)
    if need.min() >= 1.0:
        return x
    n = int(look * OUT_SR)
    # the minimum spreads each dip over +-n samples; averaging over n+1 keeps the gain <= need at every peak
    return x * uniform_filter1d(minimum_filter1d(need, 2 * n + 1), n + 1)


def limited(x):
    """The limited mix in BLOCK_S blocks, each limited with more than the filters' reach (1.5 x look) of
    samples on both sides, so the blocks join into what limiting the mix in one piece gives. In one piece
    the temporaries are ~5x the mix: a 130-min chapter (1.4 GB) ran out of memory (2026-11-02)."""
    step, pad = BLOCK_S * OUT_SR, 2 * int(LOOK * OUT_SR) + 2
    for a in range(0, len(x), step):
        a0, b, b0 = max(0, a - pad), min(len(x), a + step), min(len(x), a + step + pad)
        yield limit(x[a0:b0])[a - a0:b - a0]


def encode_mp3(x, path, bitrate="96k"):
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(OUT_SR), "-ac", "1", "-i", "-",
                          "-c:a", "libmp3lame", "-b:a", bitrate, str(path)], stdin=subprocess.PIPE)
    for y in limited(x):
        p.stdin.write(y.astype(np.float32).tobytes())
    p.stdin.close()
    if p.wait():
        raise subprocess.CalledProcessError(p.returncode, "ffmpeg")
