"""faster-whisper transcription with word timestamps."""
import json
import os
from pathlib import Path

from faster_whisper import WhisperModel

from . import progress

SR = 16000
THREADS = int(os.environ.get("BATKOL_THREADS", 4))  # CPU threads; align.py reads the same variable

_models = {}


def segments(audio, lang, size="large-v3-turbo", beam=5, t0=0.0, on_segment=None):
    """on_segment(end_s) is called as each segment is decoded (end_s within `audio`), for progress bars."""
    if size not in _models:
        _models[size] = WhisperModel(size, device="cpu", compute_type="int8", cpu_threads=THREADS)
    segs, _ = _models[size].transcribe(audio, language=lang, beam_size=beam, word_timestamps=True,
                                       condition_on_previous_text=False)
    out = []
    for seg in segs:  # lazy: each step decodes one segment
        if on_segment:
            on_segment(seg.end)
        if seg.words:
            out.append([dict(w=w.word.strip(), s=t0 + w.start, e=t0 + w.end, p=w.probability) for w in seg.words])
    return out


def transcribe(audio, lang, t0=0.0, **kw):
    return [w for seg in segments(audio, lang, t0=t0, **kw) for w in seg]


def transcribe_long(audio, lang, cache, t0=0.0, win_s=300):
    """Resumable: 5-min windows, one JSON line each in `cache`. The last segment
    of a window is dropped and re-transcribed at the start of the next one, so
    no word is cut by a window edge. The progress bar advances per decoded segment."""
    cache = Path(cache)
    recs = [json.loads(l) for l in cache.read_text().splitlines()] if cache.exists() else []
    t = recs[-1]["next"] if recs else 0.0
    dur = len(audio) / SR
    pb = progress.bar(f"whisper {lang}", dur, t, disable=t >= dur - 0.5)
    with open(cache, "a") as f:
        while t < dur - 0.5:
            final = t + win_s >= dur
            segs = segments(audio[int(t * SR):int((t + win_s) * SR)], lang, t0=t0 + t,
                            on_segment=lambda e: progress.to(pb, t + e))
            if not final and len(segs) > 1:
                nxt, segs = segs[-1][0]["s"] - t0, segs[:-1]
            else:
                nxt = min(dur, t + win_s)
            rec = dict(start=t, next=nxt, words=[w for s in segs for w in s])
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            progress.to(pb, nxt)
            progress.note(f"  asr window {t:.0f}-{nxt:.0f} s: {len(rec['words'])} words")
            t = nxt
    pb.close()
    recs = [json.loads(l) for l in cache.read_text().splitlines()]
    return [w for r in recs for w in r["words"]]
