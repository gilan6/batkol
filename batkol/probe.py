"""Transcribe head/tail slices of an audio file (faster-whisper) for orientation."""
import subprocess
import sys
import time

import numpy as np
from faster_whisper import WhisperModel

SR = 16000


def load(path, start, dur):
    cmd = ["ffmpeg", "-v", "error", "-ss", str(start), "-t", str(dur), "-i", path,
           "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"]
    return np.frombuffer(subprocess.run(cmd, check=True, capture_output=True).stdout, np.float32)


def main(path, lang, total, model_size="small", slice_s=60):
    model = WhisperModel(model_size, device="cpu", compute_type="int8", cpu_threads=4)
    for start in (0, max(0, total - slice_s)):
        audio = load(path, start, slice_s)
        t = time.time()
        segs, _ = model.transcribe(audio, language=lang, beam_size=1, vad_filter=False)
        segs = list(segs)
        print(f"## {path} @ {start:.0f}s  ({time.time() - t:.1f}s wall for {slice_s}s)")
        for s in segs:
            print(f"  [{start + s.start:7.1f}-{start + s.end:7.1f}] {s.text.strip()}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], float(sys.argv[3]), *(sys.argv[4:5] or []))


def window(path, lang, start, dur, model_size="small"):
    model = WhisperModel(model_size, device="cpu", compute_type="int8", cpu_threads=4)
    segs, _ = model.transcribe(load(path, start, dur), language=lang, beam_size=1)
    for s in segs:
        print(f"  [{start + s.start:7.1f}-{start + s.end:7.1f}] {s.text.strip()}")
