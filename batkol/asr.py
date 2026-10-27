"""faster-whisper transcription with word timestamps."""
import json
from pathlib import Path

from faster_whisper import WhisperModel

SR = 16000

_models = {}


def segments(audio, lang, size="large-v3-turbo", beam=5, t0=0.0):
    if size not in _models:
        _models[size] = WhisperModel(size, device="cpu", compute_type="int8", cpu_threads=4)
    segs, _ = _models[size].transcribe(audio, language=lang, beam_size=beam, word_timestamps=True,
                                       condition_on_previous_text=False)
    return [[dict(w=w.word.strip(), s=t0 + w.start, e=t0 + w.end, p=w.probability) for w in seg.words]
            for seg in segs if seg.words]


def transcribe(audio, lang, t0=0.0, **kw):
    return [w for seg in segments(audio, lang, t0=t0, **kw) for w in seg]


def transcribe_long(audio, lang, cache, t0=0.0, win_s=300):
    """Resumable: 5-min windows, one JSON line each in `cache`. The last segment
    of a window is dropped and re-transcribed at the start of the next one, so
    no word is cut by a window edge."""
    cache = Path(cache)
    recs = [json.loads(l) for l in cache.read_text().splitlines()] if cache.exists() else []
    t = recs[-1]["next"] if recs else 0.0
    dur = len(audio) / SR
    with open(cache, "a") as f:
        while t < dur - 0.5:
            final = t + win_s >= dur
            segs = segments(audio[int(t * SR):int((t + win_s) * SR)], lang, t0=t0 + t)
            if not final and len(segs) > 1:
                nxt, segs = segs[-1][0]["s"] - t0, segs[:-1]
            else:
                nxt = min(dur, t + win_s)
            rec = dict(start=t, next=nxt, words=[w for s in segs for w in s])
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            print(f"  asr window {t:.0f}-{nxt:.0f} s: {len(rec['words'])} words", flush=True)
            t = nxt
    recs = [json.loads(l) for l in cache.read_text().splitlines()]
    return [w for r in recs for w in r["words"]]
