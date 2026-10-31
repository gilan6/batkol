"""The one audio pass per source. Everything later reads the index it ends in.

  python -m batkol.analyze <chapter> nl|en             # resumable: rerun to continue
  python -m batkol.analyze <chapter> nl|en --slice 60  # time a 60 s slice first (writes no cache)
  python -m batkol.analyze <chapter> nl|en --asr-only  # stop after whisper: splits a pass that would run
                                                       # over 25 min (laptop: ~21 min chapters)
Threads: BATKOL_THREADS (default 4). Progress bars go to stderr; log the run and tail -f it.

Stages, cached in ~/work/<chapter>/ and skipped when present:
  <lang>_asr.jsonl     whisper long-form, 5-min windows (resumable)
  <lang>_emission.npy  CTC emissions (MMS_FA)
  -- the chapter text must exist from here on (`batkol.edition` writes it) --
  nl: nl_align.json    book tokens force-aligned
  en: en_align.json    whisper tokens force-aligned
      en_gapfill.json  batched gap pass (words long-form whisper dropped)
      en_match2.json   book sentence of every spoken token
  index                ~/work/index/<lang>_<chapter>.json (NL gap pass runs inside)
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch

from . import align, asr, cuts, index, sources
from .audio import SR, cached
from .sentences import chapter_sentences

WORK = Path.home() / "work"


def stage(path, fn):
    if path.exists():
        return json.loads(path.read_text())
    print(f"[stage] {path.name} ...", flush=True)
    t = time.time()
    res = fn()
    path.write_text(json.dumps(res, ensure_ascii=False))
    print(f"[stage] {path.name} done in {time.time() - t:.0f} s", flush=True)
    return res


def emissions(x, path):
    if not path.exists():
        print(f"[stage] {path.name} ...", flush=True)
        t = time.time()
        np.save(path, align.emissions(x).numpy())
        print(f"[stage] {path.name} done in {time.time() - t:.0f} s", flush=True)
    return torch.from_numpy(np.load(path))


def nl_align(em, sents):
    toks = [(s["id"], t) for s in sents for t in align.spoken_tokens(s["text"], "nl")]
    res = align.align_long(em, [t for _, t in toks])
    return [dict(sent=sid, tok=t, s=round(a, 3), e=round(b, 3), score=round(sc, 3))
            for (sid, t), (a, b, sc) in zip(toks, res)]


def en_align(em, words):
    toks = [(k, t) for k, w in enumerate(words) for t in align.spoken_tokens(w["w"], "en")]
    res = align.align_long(em, [t for _, t in toks])
    return [dict(word=k, tok=t, s=round(a, 3), e=round(b, 3), score=round(sc, 3))
            for (k, t), (a, b, sc) in zip(toks, res)]


def en_gapfill(x, em, toks, run):
    """Batched like the NL gap pass; gap selection as the legacy EN pass
    (>= 0.8 s gaps with >= 0.25 s of speech energy: the cast's music bed
    makes shorter ones mostly noise). Non-book tokens are dropped at index time."""
    db = cuts.frame_db(x)
    kept = index.gapfill("en", toks, index.boundaries(toks, db), x, em, run / "en_gapfill.jsonl",
                         min_gap=0.8, min_speech=0.25, max_tokens=12)
    return [dict(t, word=None, gap=True) for t in kept]


def text_gate(run, lang, text, cache):
    """The text-vs-audio check decides whether the book text can be used as is
    (no gate for a stage already cached, e.g. HP1 ch. 1 from before the check)."""
    if (run / cache).exists():
        return None
    if not text.exists():
        return f"{text} missing"
    p = run / f"edition_{lang}.json"
    if not p.exists():
        return f"run `python -m batkol.edition {run.name} {lang}` first (needs {lang}_asr.jsonl)"
    d = json.loads(p.read_text())["decision"]
    if d == "book":
        return None
    return f"edition check decided '{d}' (see {p.with_suffix('.md')}); the book text cannot be aligned as is"


def time_slice(x, lang, dur):
    t0 = min(300.0, len(x) / SR / 3)
    seg = np.ascontiguousarray(x[int(t0 * SR):int((t0 + dur) * SR)], dtype=np.float32)
    t = time.time()
    asr.transcribe(np.zeros(SR, np.float32), lang)
    align.model()
    load = time.time() - t
    t = time.time()
    n = len(asr.transcribe(seg, lang))
    a = time.time() - t
    t = time.time()
    align.emissions(seg)
    e = time.time() - t
    full = len(x) / SR
    print(f"slice {dur:.0f} s at {t0:.0f} s: whisper {a:.1f} s ({n} words, rtf {a / dur:.3f}), "
          f"emissions {e:.1f} s (rtf {e / dur:.3f}); models loaded in {load:.0f} s")
    print(f"projected for {full / 60:.1f} min of audio: whisper {a / dur * full / 60:.1f} min, "
          f"emissions {e / dur * full / 60:.1f} min")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("chapter")
    ap.add_argument("lang", choices=["nl", "en"])
    ap.add_argument("--slice", type=float, help="time this many seconds of audio, write nothing")
    ap.add_argument("--asr-only", action="store_true", help="stop after the whisper pass")
    a = ap.parse_args()
    src = sources.load(a.chapter)[a.lang]
    run = WORK / a.chapter
    run.mkdir(parents=True, exist_ok=True)
    (WORK / "cache").mkdir(exist_ok=True)
    x = np.array(cached(src["local"], WORK / "cache"))
    print(f"{a.chapter} {a.lang}: {len(x) / SR / 60:.1f} min of audio", flush=True)
    if a.slice:
        return time_slice(x, a.lang, a.slice)
    words = asr.transcribe_long(x, a.lang, run / f"{a.lang}_asr.jsonl")
    print(f"[asr] {len(words)} words", flush=True)
    if a.asr_only:
        return
    em = emissions(x, run / f"{a.lang}_emission.npy")
    text = Path(src["text"])
    if a.lang == "nl":
        why = text_gate(run, "nl", text, "nl_align.json")
        if why:
            raise SystemExit(f"[stop] audio-only stages done; {why}")
        stage(run / "nl_align.json", lambda: nl_align(em, chapter_sentences(text)))
    else:
        toks = stage(run / "en_align.json", lambda: en_align(em, words))
        gap = stage(run / "en_gapfill.json", lambda: en_gapfill(x, em, toks, run))
        why = text_gate(run, "en", text, "en_match2.json")
        if why:
            raise SystemExit(f"[stop] audio-only stages done; {why}")
        from .pipeline import run_en_match
        stage(run / "en_match2.json", lambda: run_en_match(chapter_sentences(text),
                                                           sorted(toks + gap, key=lambda t: t["s"])))
    index.build(f"{a.lang}_{a.chapter}")


if __name__ == "__main__":
    main()
