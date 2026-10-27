"""Audio I/O via ffmpeg: decode once to a 16 kHz mono float32 cache."""
import subprocess
from pathlib import Path

import numpy as np

SR = 16000


def decode(src, start=None, dur=None, sr=SR):
    cmd = ["ffmpeg", "-v", "error"]
    if start is not None:
        cmd += ["-ss", f"{start:.3f}"]
    if dur is not None:
        cmd += ["-t", f"{dur:.3f}"]
    cmd += ["-i", str(src), "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"]
    return np.frombuffer(subprocess.run(cmd, check=True, capture_output=True).stdout, np.float32)


def cached(src, cache_dir):
    """Whole file at 16 kHz mono, cached as .npy next to other work files."""
    out = Path(cache_dir) / (Path(src).stem + ".16k.npy")
    if not out.exists():
        np.save(out, decode(src))
    return np.load(out, mmap_mode="r")
