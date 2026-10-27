"""Step 2: time each heavy component on a 1-minute slice."""
import json
import re
import sys
import time
from pathlib import Path

import numpy as np
from rapidfuzz import fuzz
from rapidfuzz.distance import Levenshtein

from .audio import SR, cached
from .textnorm import words

WORK = Path.home() / "work"


def locate(hyp_words, book_words):
    """Best-matching book span for a transcript (sliding window)."""
    n = len(hyp_words)
    hyp = " ".join(hyp_words)
    best = max(range(0, len(book_words) - n), key=lambda i: fuzz.ratio(hyp, " ".join(book_words[i:i + n])))
    return best, best + n


def wer(hyp, ref):
    return Levenshtein.distance(hyp, ref) / max(1, len(ref))


def whisper_run(size, audio, lang, beam):
    from faster_whisper import WhisperModel
    t = time.time()
    model = WhisperModel(size, device="cpu", compute_type="int8", cpu_threads=4)
    load_s = time.time() - t
    t = time.time()
    segs, _ = model.transcribe(audio, language=lang, beam_size=beam, word_timestamps=True,
                               condition_on_previous_text=False)
    ws = [w for s in segs for w in s.words]
    return ws, load_s, time.time() - t


def bench_whisper(lang, start, dur, sizes, beams):
    audio = np.array(cached(WORK / "in" / f"{lang}_ch01.opus", WORK / "cache")[int(start * SR):int((start + dur) * SR)])
    book = words((WORK / "text" / f"{'en_a' if lang == 'en' else 'nl'}.ch01.txt").read_text())
    res = []
    for size in sizes:
        for beam in beams:
            ws, load_s, run_s = whisper_run(size, audio, lang, beam)
            hyp = words(" ".join(w.word for w in ws))
            i, j = locate(hyp, book)
            ref = book[i:j]
            # drop 3 edge words: slice cuts mid-sentence
            e = wer(hyp[3:-3], ref[3:-3])
            r = dict(model=size, beam=beam, load_s=round(load_s, 1), run_s=round(run_s, 1),
                     rtf=round(run_s / dur, 3), words=len(hyp), wer_vs_book=round(e, 3))
            print(json.dumps(r), flush=True)
            res.append(r)
    return res


def bench_mms(start, dur):
    import torch
    import torchaudio
    from faster_whisper import WhisperModel
    torch.set_num_threads(4)
    audio = np.array(cached(WORK / "in" / "nl_ch01.opus", WORK / "cache")[int(start * SR):int((start + dur) * SR)])
    # book span for this slice, located via a quick whisper pass
    m = WhisperModel("small", device="cpu", compute_type="int8", cpu_threads=4)
    hyp_ws = [w for s in m.transcribe(audio, language="nl", beam_size=1, word_timestamps=True)[0] for w in s.words]
    book = words((WORK / "text" / "nl.ch01.txt").read_text())
    i, j = locate(words(" ".join(w.word for w in hyp_ws)), book)
    text = book[i + 1:j - 1]
    bundle = torchaudio.pipelines.MMS_FA
    t = time.time()
    model = bundle.get_model(with_star=True)
    load_s = time.time() - t
    tok, aligner = bundle.get_tokenizer(), bundle.get_aligner()
    t = time.time()
    with torch.inference_mode():
        emission, _ = model(torch.from_numpy(audio)[None])
    emit_s = time.time() - t
    t = time.time()
    spans = aligner(emission[0], tok(text))
    align_s = time.time() - t
    fr = len(audio) / emission.size(1) / SR
    al = [(text[k], start + sp[0].start * fr, start + sp[-1].end * fr, float(np.mean([s.score for s in sp])))
          for k, sp in enumerate(spans)]
    # agreement with whisper word starts for identical words (rough sanity)
    hyp = [(words(w.word), start + w.start) for w in hyp_ws]
    hyp = [(x[0], t0) for x, t0 in hyp if len(x) == 1]
    diffs, hj = [], 0
    for w, a0, _, _ in al:
        for k in range(hj, min(hj + 6, len(hyp))):
            if hyp[k][0] == w:
                diffs.append(abs(hyp[k][1] - a0)); hj = k + 1; break
    r = dict(model="MMS_FA", load_s=round(load_s, 1), emit_s=round(emit_s, 1), align_s=round(align_s, 2),
             rtf=round((emit_s + align_s) / dur, 3), words=len(text),
             mean_score=round(float(np.mean([a[3] for a in al])), 3),
             low_score_words=sum(a[3] < 0.3 for a in al),
             whisper_start_agree_median_s=round(float(np.median(diffs)), 3), matched=len(diffs))
    print(json.dumps(r), flush=True)
    for w, a0, a1, sc in al[:8]:
        print(f"   {w:15s} {a0:8.2f} {a1:8.2f} {sc:.2f}")
    return r


def bench_labse():
    from sentence_transformers import SentenceTransformer
    import torch
    torch.set_num_threads(4)
    split = lambda t: [s for s in re.split(r"(?<=[.!?])\s+", t.replace("\n", " ")) if s.strip()]
    nl = split((WORK / "text" / "nl.ch01.txt").read_text())
    en = split((WORK / "text" / "en_a.ch01.txt").read_text())
    t = time.time()
    m = SentenceTransformer("sentence-transformers/LaBSE", device="cpu")
    load_s = time.time() - t
    t = time.time()
    m.encode(nl + en, batch_size=32, normalize_embeddings=True)
    r = dict(model="LaBSE", load_s=round(load_s, 1), encode_s=round(time.time() - t, 1), n_sent=len(nl) + len(en),
             nl=len(nl), en=len(en))
    print(json.dumps(r), flush=True)
    return r


if __name__ == "__main__":
    (WORK / "cache").mkdir(exist_ok=True)
    what = sys.argv[1]
    if what == "mms":
        bench_mms(float(sys.argv[2]), 60)
    elif what == "whisper":
        bench_whisper(sys.argv[2], float(sys.argv[3]), 60, sys.argv[4].split(","), [int(b) for b in sys.argv[5].split(",")])
    elif what == "labse":
        bench_labse()
