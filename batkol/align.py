"""CTC forced alignment with torchaudio MMS_FA (multilingual, romanized a-z ')."""
import os

import numpy as np
import torch
import torchaudio
import torchaudio.functional as F
from num2words import num2words

from . import progress
from .audio import SR
from .textnorm import words

FRAME = 320  # samples per emission frame (20 ms at 16 kHz)
BUNDLE = torchaudio.pipelines.MMS_FA
THREADS = int(os.environ.get("BATKOL_THREADS", 4))  # CPU threads, as in asr.py
_model = None


def model():
    global _model
    if _model is None:
        torch.set_num_threads(THREADS)
        _model = BUNDLE.get_model(with_star=True).eval()
    return _model


def spoken_tokens(text, lang):
    """Normalized tokens as spoken: lowercase, no diacritics, digits spelled out."""
    out = []
    for w in words(text):
        if w.isdigit():
            out += words(num2words(int(w), lang=lang))
        else:
            out.append(w)
    return out


def emissions(audio, chunk_s=30, ctx_s=2):
    """Frame log-probs for long audio: 30 s chunks with 2 s context each side."""
    hop, pad = chunk_s * SR, ctx_s * SR  # both multiples of FRAME
    out = []
    pb = progress.bar("emissions", len(audio) / SR)
    with torch.inference_mode():
        for s in range(0, len(audio), hop):
            a0, a1 = max(0, s - pad), min(len(audio), s + hop + pad)
            x = torch.from_numpy(np.ascontiguousarray(audio[a0:a1], dtype=np.float32))[None]
            em, _ = model()(x)
            k0 = (s - a0) // FRAME
            out.append(em[0, k0:k0 + (min(s + hop, len(audio)) - s) // FRAME])
            progress.to(pb, min(s + hop, len(audio)) / SR)
    pb.close()
    return torch.cat(out)


def align_words(emission, word_tokens, t0=0.0):
    """Align token words between leading/trailing star (absorbs unrelated audio).

    Returns [(start_s, end_s, score)] per word, absolute times (t0 = window start).
    """
    d = BUNDLE.get_dict()
    ids = [[d["*"]]]
    for w in word_tokens:
        ids.append([d[c] for c in w if c in d] or [d["*"]])
    ids.append([d["*"]])
    flat = torch.tensor([i for w in ids for i in w], dtype=torch.int32)
    ali, scores = F.forced_align(emission[None], flat[None], blank=0)
    spans = F.merge_tokens(ali[0], scores[0].exp())
    res, k = [], 0
    sec = FRAME / SR
    for w in ids:
        sp = spans[k:k + len(w)]
        k += len(w)
        res.append((t0 + sp[0].start * sec, t0 + sp[-1].end * sec, float(np.mean([s.score for s in sp]))))
    return res[1:-1]


def align_long(emission, word_tokens, t0=0.0, win_s=120, words_per_s=1.6, keep_tail=10, end_guard_s=10):
    """Sequential windowed alignment (one global pass overflows torchaudio's
    32-bit index past ~2^31 frame x state cells).

    Each window gets a text block that fits comfortably (trailing star absorbs
    the leftover audio); all but the last few words are kept and the next
    window starts 0.5 s before the first word not kept. If the block's last word
    lands near the window end, the text was too dense: retry with half.
    """
    sec = FRAME / SR
    res, f0, w0 = [], 0, 0
    n = int(win_s * words_per_s)
    while w0 < len(word_tokens):
        # last window: either the text or the audio runs out -> take all that is left of both
        final = w0 + n >= len(word_tokens) or f0 + int(win_s / sec) >= len(emission)
        block = word_tokens[w0:] if final else word_tokens[w0:w0 + n]
        f1 = len(emission) if final else f0 + int(win_s / sec)
        out = align_words(emission[f0:f1], block, t0 + f0 * sec)
        if not final and out[-1][1] > t0 + (f1 * sec) - end_guard_s:
            if n <= 20:
                raise RuntimeError(f"alignment cannot fit text at {t0 + f0 * sec:.1f} s")
            n //= 2
            continue
        keep = len(out) if final else len(out) - keep_tail
        res += out[:keep]
        w0 += keep
        if w0 < len(word_tokens):
            f0 = max(int((out[keep - 1][1] - t0) / sec), int((out[keep][0] - t0 - 0.5) / sec))
        n = int(win_s * words_per_s)
    return res
