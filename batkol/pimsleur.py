"""Pimsleur lesson -> English narrator words with precise times (for stock frames).

The lesson is transcribed as English: the narrator's frames come out right,
Dutch turns come out as noise and are never selected as frames.
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch

from . import align, asr
from .audio import cached

WORK = Path.home() / "work"


def process(src, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    x = np.array(cached(src, WORK / "cache"))
    t = time.time()
    words = asr.transcribe_long(x, "en", out_dir / "asr.jsonl")
    print(f"asr: {len(words)} words, {time.time() - t:.0f} s", flush=True)
    em_path = out_dir / "emission.npy"
    if not em_path.exists():
        np.save(em_path, align.emissions(x).numpy())
    em = torch.from_numpy(np.load(em_path))
    toks = [(k, tok) for k, w in enumerate(words) for tok in align.spoken_tokens(w["w"], "en")]
    res = align.align_long(em, [tok for _, tok in toks])
    out = [dict(word=k, tok=tok, s=round(a, 3), e=round(b, 3), score=round(sc, 3))
           for (k, tok), (a, b, sc) in zip(toks, res)]
    (out_dir / "align.json").write_text(json.dumps(out))
    print(f"aligned {len(out)} tokens, {time.time() - t:.0f} s total", flush=True)


if __name__ == "__main__":
    process(sys.argv[1], sys.argv[2])
