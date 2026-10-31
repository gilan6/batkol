"""Audio index: the single analysis pass over a source file.

Everything downstream (pairing, chunking, cut planning, scheduling, rendering)
reads this file; nothing downstream runs ASR or alignment on audio again.

Per source `~/work/index/<key>.json`:
  words       spoken words in time order: tok, s, e, score (CTC), sent (book
              sentence id or null), status vs the book text:
                ok | fuzzy (spelling) | differs (other word heard) |
                unheard (aligned book word the ASR did not hear) |
                added (spoken, not in the book) | asr (no book, e.g. Pimsleur)
  omitted     book tokens never spoken (cast drift)
  bounds      n+1 boundaries; bounds[k] lies before word k:
                pause (s, longest quiet run), kind pause|short|none,
                cut_end (clip ending at word k-1), cut_start (clip starting at
                word k), onset (cut for a start inside speech) + onset_db
                (dB over the local silence threshold there), depth_db (gap
                minimum vs local speech level), speech_in_gap (s of energy
                above threshold not covered by words)
  unindexed   speech-energy regions (>= 0.3 s) with no word: credits, effects,
              words the ASR missed
Built from cached stage outputs (alignment, ASR, emissions) + frame energy.
"""
import difflib
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
from rapidfuzz import fuzz

from . import align, cuts, progress, sources
from .audio import SR, cached
from .sentences import chapter_sentences

WORK = Path.home() / "work"
VERSION = "index-v1"
FUZZY = 75
LOW_SCORE = 0.3  # CTC score below this: word position unreliable (overlap, whisper, effects)


def _energy_tools(db):
    def thr_at(t):
        return cuts.local_threshold(db, t)

    def speech_level(t, span=15.0):
        i, w = int(t * SR / cuts.HOP), int(span * SR / cuts.HOP)
        return float(np.percentile(db[max(0, i - w):i + w], 95))

    def frames(a, b):
        return max(0, int(a * SR / cuts.HOP)), max(0, int(np.ceil(b * SR / cuts.HOP)))

    return thr_at, speech_level, frames


def boundaries(words, db, pad=0.05, edge=1.0):
    thr_at, speech_level, frames = _energy_tools(db)
    out = []
    n = len(words)
    for k in range(n + 1):
        a = words[k - 1]["e"] if k else words[0]["s"] - edge
        b = words[k]["s"] if k < n else words[-1]["e"] + edge
        lo, hi = a - pad, b + pad
        thr = thr_at((a + b) / 2)
        i0, i1 = frames(lo, hi)
        seg = db[i0:i1 + 1]
        runs = [(s, e) for s, e in cuts._runs(seg < thr) if (e - s) * cuts.HOP / SR >= cuts.MIN_SIL]
        pause = max([(e - s) * cuts.HOP / SR for s, e in runs], default=0.0)
        kind = "pause" if pause >= cuts.MIN_PAUSE else "short" if runs else "none"
        cut_end, f_end = cuts.snap(db, thr, lo, hi, "end")
        cut_start, f_start = cuts.snap(db, thr, lo, hi, "start")
        rec = dict(k=k, gap=[round(a, 3), round(b, 3)], pause=round(pause, 3), kind=kind,
                   cut_end=round(cut_end, 3), cut_start=round(cut_start, 3), thr=round(thr, 1),
                   depth_db=round(float(seg.min()) - speech_level((a + b) / 2), 1) if len(seg) else 0.0)
        if k < n:  # onset cut for a clip starting inside speech at word k
            s = words[k]["s"]
            j0, j1 = frames(s - 0.05, s + 0.02)
            j = j0 + int(np.argmin(db[j0:j1 + 1]))
            rec["onset"] = round((j * cuts.HOP + cuts.WIN / 2) / SR, 3)
            rec["onset_db"] = round(float(db[j]) - thr_at(s), 1)
        if b - a > 0.2:  # sound in the gap that no word accounts for
            g0, g1 = frames(a + 0.1, b - 0.1)
            rec["speech_in_gap"] = round(float((db[g0:g1] >= thr).sum()) * cuts.HOP / SR, 2)
        out.append(rec)
    return out


def unindexed(words, db, min_len=0.3):
    """Speech-energy runs (local threshold) lying entirely between words."""
    thr_at, _, frames = _energy_tools(db)
    covered = np.zeros(len(db), bool)
    for w in words:
        i0, i1 = frames(w["s"] - 0.05, w["e"] + 0.05)
        covered[i0:i1 + 1] = True
    out = []
    step = int(30 * SR / cuts.HOP)
    for c0 in range(0, len(db), step):
        seg = db[c0:c0 + step]
        thr = cuts.threshold(seg)[0]
        loud = (seg >= thr) & ~covered[c0:c0 + step]
        for s, e in cuts._runs(loud):
            if (e - s) * cuts.HOP / SR >= min_len:
                out.append([round((c0 + s) * cuts.HOP / SR, 2), round((c0 + e) * cuts.HOP / SR, 2)])
    return out


def diff_to_book(book, spoken):
    """difflib between book tokens and spoken tokens.
    Returns per spoken token (book_index or None, status), and omitted book indices."""
    sm = difflib.SequenceMatcher(None, book, spoken, autojunk=False)
    rel = [(None, "added")] * len(spoken)
    hit = [False] * len(book)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            for k in range(i2 - i1):
                rel[j1 + k] = (i1 + k, "ok")
                hit[i1 + k] = True
        elif op == "replace":
            for k in range(j2 - j1):
                bi = i1 + k * (i2 - i1) // (j2 - j1)
                rel[j1 + k] = (bi, "fuzzy" if fuzz.ratio(spoken[j1 + k], book[bi]) >= FUZZY else "differs")
                hit[bi] = True
    return rel, [i for i, h in enumerate(hit) if not h]


def gapfill(lang, words, bounds, x, em, cache_path, min_gap=0.4, min_speech=0.08, min_score=0.5, max_tokens=4,
            window_s=28.0, sep_s=1.0):
    """Part of the single pass: re-transcribe gaps between aligned words that
    still hold speech energy (long-form whisper drops short words such as
    "Nee," "Ja," "Shoo!"). Gaps are packed into ~28 s windows separated by
    1 s of silence, because whisper costs the same per 30 s window however
    little audio it holds; words map back to their gap by time. Cached per
    gap (resumable). Only short, confidently aligned results become words,
    which filters hallucinations on breaths and noise."""
    from . import asr
    from .align import spoken_tokens as st
    done = {}
    if cache_path.exists():
        for line in cache_path.read_text().splitlines():
            r = json.loads(line)
            done[f"{r['gap'][0]:.3f}-{r['gap'][1]:.3f}"] = r["toks"]
    todo = [tuple(b["gap"]) for b in bounds
            if b["k"] not in (0, len(words)) and b["gap"][1] - b["gap"][0] >= min_gap
            and b.get("speech_in_gap", 0) >= min_speech and f"{b['gap'][0]:.3f}-{b['gap'][1]:.3f}" not in done]
    batches, cur, used = [], [], 0.0
    for a, z in todo:
        if cur and used + (z - a) + sep_s > window_s:
            batches.append(cur)
            cur, used = [], 0.0
        cur.append((a, z))
        used += (z - a) + sep_s
    if cur:
        batches.append(cur)
    sec = align.FRAME / SR
    pb = progress.bar(f"gapfill {lang}", sum(z - a + sep_s for b in batches for a, z in b), disable=not batches)
    with open(cache_path, "a") as f:
        for bi, batch in enumerate(batches):
            parts, offsets, t = [], [], 0.0
            for a, z in batch:
                seg = np.asarray(x[int(a * SR):int(z * SR)], dtype=np.float32)
                offsets.append((t, t + len(seg) / SR))
                parts += [seg, np.zeros(int(sep_s * SR), np.float32)]
                t += len(seg) / SR + sep_s
            base = pb.n
            pb.set_description(f"gapfill {lang} window {bi + 1}/{len(batches)}", refresh=False)
            hyp = asr.transcribe(np.concatenate(parts), lang, on_segment=lambda e: progress.to(pb, base + e))
            per = [[] for _ in batch]
            for w in hyp:
                m = (w["s"] + w["e"]) / 2
                for i, (o0, o1) in enumerate(offsets):
                    if o0 - 0.05 <= m <= o1 + 0.05:
                        per[i].append(w)
                        break
            for (a, z), ws in zip(batch, per):
                toks = [tk for w in ws for tk in st(w["w"], lang)]
                res = []
                if toks and len(toks) <= max_tokens:
                    f0, f1 = int((a - 0.02) / sec), int((z + 0.02) / sec) + 1
                    al = align.align_words(em[f0:f1], [list(tk) for tk in toks], t0=f0 * sec)
                    res = [dict(tok=tk, s=round(s, 3), e=round(e, 3), score=round(sc, 3))
                           for tk, (s, e, sc) in zip(toks, al)]
                f.write(json.dumps(dict(gap=[a, z], toks=res, raw=" ".join(w["w"] for w in ws)), ensure_ascii=False) + "\n")
                done[f"{a:.3f}-{z:.3f}"] = res
            f.flush()
            progress.to(pb, base + t)
    pb.close()
    kept = [tk for res in done.values() for tk in res if tk["score"] >= min_score]
    print(f"  gapfill {lang}: {len(todo)} gaps transcribed now in {len(batches)} windows, {len(done)} cached, "
          f"{len(kept)} words kept", flush=True)
    return kept


def book_tokens(text_path, lang):
    out = []
    for s in chapter_sentences(text_path):
        out += [(s["id"], t) for t in align.spoken_tokens(s["text"], lang)]
    return out


def build_nl(run_dir, text_path, src_key, src_audio, drive_path):
    """NL: words = book text force-aligned to the narration; the narrator's own
    transcript marks words not heard (`unheard`/`differs`) and adds words he
    spoke that are not in the book (`added`, aligned into their gap)."""
    run_dir = Path(run_dir)
    nl = json.loads((run_dir / "nl_align.json").read_text())
    book = book_tokens(text_path, "nl")
    words = [dict(tok=w["tok"], s=w["s"], e=w["e"], score=w["score"], sent=w["sent"], book_i=i, status="ok")
             for i, w in enumerate(nl)]
    asr_path = run_dir / "nl_asr.jsonl"
    added = []
    if asr_path.exists():
        recs = [json.loads(l) for l in asr_path.read_text().splitlines()]
        hyp = [(t, w) for r in recs for w in r["words"] for t in align.spoken_tokens(w["w"], "nl")]
        sm = difflib.SequenceMatcher(None, [b[1] for b in book], [h[0] for h in hyp], autojunk=False)
        heard = [False] * len(book)
        em = torch.from_numpy(np.load(run_dir / "nl_emission.npy"))
        sec = align.FRAME / SR
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op == "equal":
                for k in range(i2 - i1):
                    heard[i1 + k] = True
            elif op == "replace":
                for k in range(i2 - i1):
                    hj = j1 + k * (j2 - j1) // (i2 - i1)
                    words[i1 + k]["status"] = "fuzzy" if fuzz.ratio(book[i1 + k][1], hyp[hj][0]) >= FUZZY else "differs"
                    words[i1 + k]["heard"] = hyp[hj][0]
                    heard[i1 + k] = True
            elif op == "insert" and 0 < i1 < len(book):
                # spoken words between book words i1-1 and i1: place them if a real gap with sound is there
                a, b = words[i1 - 1]["e"], words[i1]["s"]
                toks = [h[0] for h in hyp[j1:j2]]
                if b - a < 0.15 or len(toks) > 6:
                    continue
                f0, f1 = int((a - 0.02) / sec), int((b + 0.02) / sec) + 1
                res = align.align_words(em[f0:f1], [list(t) for t in toks], t0=f0 * sec)
                for t, (s, e, sc) in zip(toks, res):
                    if sc >= 0.3:
                        added.append(dict(tok=t, s=round(s, 3), e=round(e, 3), score=round(sc, 3),
                                          sent=words[i1]["sent"], book_i=None, status="added"))
        for i, h in enumerate(heard):
            if not h:
                words[i]["status"] = "unheard"
    words = sorted(words + added, key=lambda w: w["s"])
    # one-time gap pass (cached): words the long-form transcript dropped
    x = cached(src_audio, WORK / "cache")
    db = cuts.frame_db(x)
    em = torch.from_numpy(np.load(run_dir / "nl_emission.npy"))
    extra = gapfill("nl", words, boundaries(words, db), x, em, run_dir / "nl_gapfill.jsonl")
    nxt = [w["s"] for w in words]
    for t in extra:
        if any(w["s"] < t["e"] and t["s"] < w["e"] for w in words):  # overlaps an aligned word: not new
            continue
        i = min(len(words) - 1, int(np.searchsorted(nxt, t["s"])))
        added.append(dict(tok=t["tok"], s=t["s"], e=t["e"], score=t["score"], sent=words[i]["sent"], book_i=None,
                          status="added", gap=True))
    words = sorted([w for w in words if w["status"] != "added"] + added, key=lambda w: w["s"])
    return finish(src_key, "nl", src_audio, drive_path, words, [], dict(asr=asr_path.exists()))


def build_en(run_dir, text_path, src_key, src_audio, drive_path):
    """EN: words = what the cast actually said (ASR, CTC-aligned, incl. gap
    re-transcriptions); mapped onto the book text; omitted book words listed."""
    run_dir = Path(run_dir)
    toks = sorted(json.loads((run_dir / "en_align.json").read_text())
                  + json.loads((run_dir / "en_gapfill.json").read_text()), key=lambda t: t["s"])
    book = book_tokens(text_path, "en")
    sent = json.loads((run_dir / "en_match2.json").read_text())["sent"]
    rel, omitted = diff_to_book([b[1] for b in book], [t["tok"] for t in toks])
    words, dropped = [], []
    for t, (bi, st), s in zip(toks, rel, sent):
        if t.get("gap") and st not in ("ok", "fuzzy"):
            # gap re-transcriptions are mostly whisper hallucinations over music,
            # effects and silence ("thank you", "i'll see you next time"): keep
            # only those that match the book; log the rest as sound, not words
            dropped.append([t["s"], t["e"], t["tok"]])
            continue
        words.append(dict(tok=t["tok"], s=t["s"], e=t["e"], score=t["score"], sent=s, book_i=bi, status=st,
                          **({"gap": True} if t.get("gap") else {})))
    om = [dict(book_i=i, sent=book[i][0], tok=book[i][1]) for i in omitted]
    return finish(src_key, "en", src_audio, drive_path, words, om, dict(gap_tokens_dropped=dropped))


def build_plain(asr_dir, src_key, src_audio, drive_path, lang="en"):
    toks = json.loads((Path(asr_dir) / "align.json").read_text())
    words = [dict(tok=t["tok"], s=t["s"], e=t["e"], score=t["score"], sent=None, book_i=None, status="asr")
             for t in toks]
    return finish(src_key, lang, src_audio, drive_path, words, [], {})


def finish(key, lang, src_audio, drive_path, words, omitted, meta):
    t = time.time()
    x = cached(src_audio, WORK / "cache")
    db = cuts.frame_db(x)
    idx = dict(version=VERSION, key=key, lang=lang, drive_path=drive_path, local=str(src_audio),
               duration=round(len(x) / SR, 3), meta=meta, words=words, omitted=omitted,
               bounds=boundaries(words, db), unindexed=unindexed(words, db))
    out = WORK / "index" / f"{key}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(idx, ensure_ascii=False))
    st = {}
    for w in words:
        st[w["status"]] = st.get(w["status"], 0) + 1
    kinds = {}
    for b in idx["bounds"]:
        kinds[b["kind"]] = kinds.get(b["kind"], 0) + 1
    print(f"[index] {key}: {len(words)} words {st}, omitted {len(omitted)}, boundaries {kinds}, "
          f"unindexed regions {len(idx['unindexed'])}, {time.time() - t:.0f} s", flush=True)
    return idx


class Index:
    """Read-only queries for planners: clip spans by word range, from the index alone."""

    def __init__(self, key):
        d = json.loads((WORK / "index" / f"{key}.json").read_text())
        self.__dict__.update(d)

    def span(self, a, b, onset=False):
        """Clip for words a..b. onset=True: start may be cut inside speech (buildup piece)."""
        sb, eb = self.bounds[a], self.bounds[b + 1]
        risk = []
        if onset and sb["kind"] != "pause":
            start, how = sb["onset"], "onset"
            if sb["onset_db"] >= 0:
                risk.append(f"onset_loud:{sb['onset_db']}")
        else:
            start, how = sb["cut_start"], sb["kind"]
            if sb["kind"] != "pause":
                risk.append(f"start_{sb['kind']}")
        end = eb["cut_end"]
        if eb["kind"] != "pause":
            risk.append(f"end_{eb['kind']}")
        for side, w in (("start", self.words[a]), ("end", self.words[b])):
            if w["status"] in ("differs", "unheard", "added"):
                risk.append(f"{side}_word_{w['status']}")
            if w["score"] < LOW_SCORE:
                risk.append(f"{side}_word_score:{w['score']}")
        return dict(src=self.key, start=start, end=end, first=a, last=b, start_kind=how,
                    tokens=[w["tok"] for w in self.words[a:b + 1]], risk=risk)


SOURCES = {  # sources outside the chapter registry (batkol.sources)
    "pims_L01": dict(kind="plain", run="pims01", audio="in/pims/Lesson01.mp3",
                     drive=sources.PIMS_L01),
}
DEFAULT = ["nl_ch01", "en_ch01", "pims_L01"]


def build(key):
    """key: pims_L01, or <lang>_<chapter> for a chapter in batkol.sources."""
    if key in SOURCES:
        s = SOURCES[key]
        return build_plain(WORK / s["run"], key, WORK / s["audio"], s["drive"])
    lang, chapter = key.split("_", 1)
    s = sources.load(chapter)[lang]
    fn = build_nl if lang == "nl" else build_en
    return fn(WORK / chapter, Path(s["text"]), key, Path(s["local"]), s["drive"])


if __name__ == "__main__":
    for key in sys.argv[1:] or DEFAULT:
        build(key)
