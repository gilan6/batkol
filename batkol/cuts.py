"""Snap clip boundaries into real silences found from signal energy."""
import numpy as np

from .audio import SR

HOP = 160    # 10 ms
WIN = 480    # 30 ms
LEAD = 0.15  # keep this much silence before speech onset
TAIL = 0.25  # and after speech offset (decay, reverb)
MIN_SIL = 0.06
MIN_PAUSE = 0.12  # shorter quiet stretches are stop closures / run-on speech, not pauses


def frame_db(audio):
    a = np.asarray(audio, dtype=np.float64)
    cs = np.concatenate([[0.0], np.cumsum(a * a)])
    n = (len(a) - WIN) // HOP + 1
    k = np.arange(n) * HOP
    return 10 * np.log10((cs[k + WIN] - cs[k]) / WIN + 1e-12)


def threshold(db):
    """Silence threshold relative to the file's own floor and speech level."""
    floor, speech = np.percentile(db, 10), np.percentile(db, 95)
    return max(floor + 10, speech - 40), floor, speech


def _runs(mask):
    """[(start_idx, end_idx_exclusive)] of True runs."""
    d = np.diff(np.concatenate([[0], mask.astype(np.int8), [0]]))
    return list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)))


def snap(db, thr, a, b, side):
    """Cut point inside [a, b] (seconds). side='start' cuts LEAD before speech,
    'end' cuts TAIL after it. Returns (time, flag)."""
    t = lambda i: (i * HOP + WIN / 2) / SR
    i0, i1 = max(0, int(a * SR / HOP)), min(len(db), int(np.ceil(b * SR / HOP)) + 1)
    if i1 - i0 < 2:
        return (a + b) / 2, "tight"
    seg = db[i0:i1]
    runs = [(s, e) for s, e in _runs(seg < thr) if (e - s) * HOP / SR >= MIN_SIL]
    if not runs:
        return t(i0 + int(np.argmin(seg))), "no_silence"
    # nearest real pause to the speech: first after a unit's end, last before its start,
    # so unaligned speech further away (an untranscribed word) never leaks in
    real = [r for r in runs if (r[1] - r[0]) * HOP / SR >= MIN_PAUSE]
    if real:
        s, e = real[0] if side == "end" else real[-1]
    else:
        s, e = max(runs, key=lambda r: r[1] - r[0])
    # frame centres: conservative bounds of the pause
    rs, re_ = t(i0 + s), t(i0 + e - 1)
    # short pause: share it so an end cut never reaches the next onset
    k = min(1.0, (re_ - rs) / (LEAD + TAIL))
    flag = "" if real else "short_pause"
    return (re_ - LEAD * k, flag) if side == "start" else (rs + TAIL * k, flag)


def longest_pause(db, a, b):
    """Longest quiet run (s) inside [a, b], local threshold."""
    thr = local_threshold(db, (a + b) / 2)
    i0, i1 = max(0, int(a * SR / HOP)), int(np.ceil(b * SR / HOP)) + 1
    return max([(e - s) * HOP / SR for s, e in _runs(db[i0:i1] < thr)], default=0.0)


def local_threshold(db, t, span=15.0):
    """Threshold from the +-span seconds around t (background level can change)."""
    i, w = int(t * SR / HOP), int(span * SR / HOP)
    return threshold(db[max(0, i - w):i + w])[0]


def unit_bounds(db, words, first, last, pad=0.05, edge_search=1.0):
    """words: [(start, end)] of the spoken word list; unit spans words[first..last]."""
    s, e = words[first][0], words[last][1]
    a = words[first - 1][1] - pad if first > 0 else s - edge_search
    b = words[last + 1][0] + pad if last + 1 < len(words) else e + edge_search
    cs, f1 = snap(db, local_threshold(db, s), a, s + pad, "start")
    ce, f2 = snap(db, local_threshold(db, e), e - pad, b, "end")
    return cs, ce, [f"{side}:{f}" for side, f in (("start", f1), ("end", f2)) if f]
