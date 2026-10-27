"""Re-transcribe every cut clip and compare with what it should contain."""
import difflib

import numpy as np

from . import asr
from .align import spoken_tokens
from .audio import SR


def edge_report(ref, hyp):
    """Token diff at clip edges: missing (cut too tight) or extra (neighbour leaked)."""
    ops = [o for o in difflib.SequenceMatcher(None, ref, hyp, autojunk=False).get_opcodes()]
    flags = []
    for pos, (op, i1, i2, j1, j2) in (("start", ops[0]), ("end", ops[-1])):
        if op == "delete":
            flags.append(f"{pos}_missing:{' '.join(ref[i1:i2])}")
        elif op == "insert":
            flags.append(f"{pos}_extra:{' '.join(hyp[j1:j2])}")
        elif op == "replace":
            flags.append(f"{pos}_differs:{' '.join(ref[i1:i2])}->{' '.join(hyp[j1:j2])}")
    ratio = difflib.SequenceMatcher(None, ref, hyp, autojunk=False).ratio()
    return round(ratio, 3), flags


def check_clip(audio16k, lang, ref_text):
    hyp_words = asr.transcribe(np.ascontiguousarray(audio16k, dtype=np.float32), lang)
    hyp = [t for w in hyp_words for t in spoken_tokens(w["w"], lang)]
    ref = spoken_tokens(ref_text, lang)
    ratio, flags = edge_report(ref, hyp)
    return dict(hyp=" ".join(hyp), ratio=ratio, flags=flags)
