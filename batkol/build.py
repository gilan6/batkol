"""Assemble NL -> EN -> NL drill audio and encode MP3."""
import re
import subprocess
import tempfile

import numpy as np

from .audio import decode

OUT_SR = 44100
FADE = 0.04


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


def match_loudness(clips, target=-18.0, peak=0.89):
    """One static gain per source (keeps the performance's own dynamics)."""
    g = 10 ** ((target - lufs(np.concatenate(clips))) / 20)
    g = min(g, peak / max(float(np.abs(c).max()) for c in clips))
    return [c * g for c in clips], 20 * np.log10(g)


def encode_mp3(x, path, bitrate="96k"):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(OUT_SR), "-ac", "1", "-i", "-",
                    "-c:a", "libmp3lame", "-b:a", bitrate, str(path)], input=x.astype(np.float32).tobytes(), check=True)
