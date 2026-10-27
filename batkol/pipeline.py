"""HP1 ch. 1 -> NL/EN/NL drill MP3 + TSV.

Stages cache JSON in the output dir; delete a file to recompute that stage.
Full chapter:  python -m batkol.pipeline --out ~/work/ch01
PoC sample:    python -m batkol.pipeline --out ~/work/poc --nl-last 12 --nl-window 0 260 --en-window 0 300
Verification:  add --verify (resumable; --verify-minutes bounds one run)
"""
import argparse
import csv
import json
import resource
import time
from pathlib import Path

import numpy as np
import torch

from . import align, asr, build, cuts, match, pair, sources, verify
from .audio import SR, cached
from .sentences import chapter_sentences

WORK = Path.home() / "work"
SRC = {lang: (Path(s["local"]), s["drive"]) for lang, s in sources.load("ch01").items()}
TSV_COLS = ["idx", "nl_text", "en_text", "nl_file", "nl_start", "nl_end", "en_file", "en_start", "en_end",
            "out_start", "nl_ids", "en_ids", "sim", "en_coverage", "flags"]


def audio(lang):
    return cached(SRC[lang][0], WORK / "cache")


class Run:
    def __init__(self, args):
        self.a = args
        self.dir = Path(args.out).expanduser()
        self.dir.mkdir(parents=True, exist_ok=True)
        for lang in ("nl", "en"):
            w = getattr(args, f"{lang}_window") or [0, len(audio(lang)) / SR]
            setattr(self, f"{lang}_window", w)

    def stage(self, name, fn):
        path = self.dir / f"{name}.json"
        if path.exists():
            return json.loads(path.read_text())
        print(f"[stage] {name} ...", flush=True)
        t = time.time()
        res = fn()
        path.write_text(json.dumps(res, ensure_ascii=False, indent=1))
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6
        print(f"[stage] {name} done in {time.time() - t:.0f} s, peak RSS so far {rss:.1f} GB", flush=True)
        return res

    def window(self, lang):
        w = getattr(self, f"{lang}_window")
        return np.array(audio(lang)[int(w[0] * SR):int(w[1] * SR)]), w[0]


def run_pairs(nl, en):
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer("sentence-transformers/LaBSE", device="cpu")
    return pair.align([s["text"] for s in nl], [s["text"] for s in en], m)


def forced(run, lang, word_tokens):
    x, t0 = run.window(lang)
    path = run.dir / f"{lang}_emission.npy"
    if not path.exists():
        np.save(path, align.emissions(x).numpy())
    em = torch.from_numpy(np.load(path))
    print(f"  {lang}: {em.shape[0]} frames x {sum(len(w) for w in word_tokens)} chars", flush=True)
    return align.align_long(em, word_tokens, t0=t0)


def run_nl_align(run, nl):
    toks = [(s["id"], t) for s in nl for t in align.spoken_tokens(s["text"], "nl")]
    res = forced(run, "nl", [t for _, t in toks])
    return [dict(sent=sid, tok=t, s=round(a, 3), e=round(b, 3), score=round(sc, 3))
            for (sid, t), (a, b, sc) in zip(toks, res)]


def run_en_asr(run):
    x, t0 = run.window("en")
    return asr.transcribe_long(x, "en", run.dir / "en_asr.jsonl", t0=t0)


def run_en_align(run, words):
    toks = [(k, t) for k, w in enumerate(words) for t in align.spoken_tokens(w["w"], "en")]
    res = forced(run, "en", [t for _, t in toks])
    return [dict(word=k, tok=t, s=round(a, 3), e=round(b, 3), score=round(sc, 3))
            for (k, t), (a, b, sc) in zip(toks, res)]


def run_en_gapfill(run, toks, min_gap=0.8, min_speech=0.25):
    """Re-transcribe gaps between aligned words that still contain speech energy
    (whisper drops short exclamations such as "Shoo!" in long-form decoding)."""
    db = cuts.frame_db(audio("en"))
    em = torch.from_numpy(np.load(run.dir / "en_emission.npy"))
    sec = align.FRAME / SR
    out, n_gaps = [], 0
    for a, b in zip(toks, toks[1:]):
        g0, g1 = a["e"], b["s"]
        if g1 - g0 < min_gap:
            continue
        thr = cuts.local_threshold(db, (g0 + g1) / 2)
        seg = db[int((g0 + 0.1) * SR / cuts.HOP):int((g1 - 0.1) * SR / cuts.HOP)]
        if (seg >= thr).sum() * cuts.HOP / SR < min_speech:
            continue
        n_gaps += 1
        words = asr.transcribe(np.array(audio("en")[int(g0 * SR):int(g1 * SR)]), "en", t0=g0)
        wt = [t for w in words for t in align.spoken_tokens(w["w"], "en")]
        if not wt:
            continue
        f0, f1 = int(g0 / sec), int(g1 / sec)
        for t, (s, e, sc) in zip(wt, align.align_words(em[f0:f1], [list(t) for t in wt], t0=f0 * sec)):
            out.append(dict(word=None, tok=t, s=round(s, 3), e=round(e, 3), score=round(sc, 3), gap=True))
    print(f"  gapfill: {n_gaps} speech gaps re-transcribed, {len(out)} tokens", flush=True)
    return out


def run_en_match(en, hyp):
    book = [(s["id"], t) for s in en for t in align.spoken_tokens(s["text"], "en")]
    sent, matched = match.assign([b[0] for b in book], [b[1] for b in book], [h["tok"] for h in hyp],
                                 [(h["s"], h["e"]) for h in hyp], strict=[bool(h.get("gap")) for h in hyp])
    cov = {}
    for (sid, _), m in zip(book, matched):
        cov.setdefault(sid, []).append(m)
    return dict(sent=sent, coverage={str(k): round(sum(v) / len(v), 3) for k, v in cov.items()})


def merge_no_pause(groups, db, nl_t, en_t, nl_by_sent, en_by_sent, max_nl_s=45.0):
    """Merge neighbouring groups when either language has no real pause between
    them: a drill unit must be separable without cutting through speech."""
    def rng(ids, by_sent):
        k = [i for s in ids for i in by_sent.get(s, [])]
        return (min(k), max(k)) if k else None

    gs = [[list(n), list(e), s, 0] for n, e, s in groups]
    i, n_merged = 0, 0
    while i < len(gs) - 1:
        u, v = gs[i], gs[i + 1]
        ru, rv = rng(u[0], nl_by_sent), rng(v[0], nl_by_sent)
        eu, ev = rng(u[1], en_by_sent), rng(v[1], en_by_sent)
        if ru and rv and eu and ev and ru[1] < rv[0] and eu[1] < ev[0]:
            pn = cuts.longest_pause(db["nl"], nl_t[ru[1]][1] - 0.05, nl_t[rv[0]][0] + 0.05)
            pe = cuts.longest_pause(db["en"], en_t[eu[1]][1] - 0.05, en_t[ev[0]][0] + 0.05)
            if min(pn, pe) < cuts.MIN_PAUSE and nl_t[rv[1]][1] - nl_t[ru[0]][0] <= max_nl_s:
                u[0] += v[0]
                u[1] += v[1]
                u[2] = min(u[2], v[2])
                u[3] += 1 + v[3]
                del gs[i + 1]
                n_merged += 1
                continue
        i += 1
    return gs, n_merged


def make_units(run, nl, en, scope, nl_words, en_toks, en_m):
    db = {lang: cuts.frame_db(audio(lang)) for lang in ("nl", "en")}
    nl_t = [(x["s"], x["e"]) for x in nl_words]
    en_t = [(x["s"], x["e"]) for x in en_toks]
    nl_by_sent, en_by_sent = {}, {}
    for i, x in enumerate(nl_words):
        nl_by_sent.setdefault(x["sent"], []).append(i)
    for i, s in enumerate(en_m["sent"]):
        if s is not None:
            en_by_sent.setdefault(s, []).append(i)
    scope, n_merged = merge_no_pause(scope, db, nl_t, en_t, nl_by_sent, en_by_sent)
    print(f"[units] {n_merged} boundaries without a pause merged -> {len(scope)} groups", flush=True)
    units = []
    for idx, (nids, eids, sim, merged) in enumerate(scope):
        u = dict(idx=idx, nl_ids=nids, en_ids=eids, sim=sim, flags=["merged_no_pause"] * bool(merged),
                 nl_text=" ".join(nl[i]["text"] for i in nids), en_text=" ".join(en[i]["text"] for i in eids))
        units.append(u)
        if not nids or not eids:
            u["flags"].append("unpaired")
            continue
        k = sorted(i for s in nids for i in nl_by_sent.get(s, []))
        a, b, f = cuts.unit_bounds(db["nl"], nl_t, k[0], k[-1])
        u.update(nl_start=round(a, 3), nl_end=round(b, 3),
                 nl_score=round(float(np.mean([nl_words[i]["score"] for i in k])), 3))
        u["flags"] += [f"nl_{x}" for x in f]
        if u["nl_score"] < 0.5:
            u["flags"].append("nl_low_align_score")
        k = sorted(i for s in eids for i in en_by_sent.get(s, []))
        if not k:
            u["flags"].append("en_not_found")
            continue
        a, b, f = cuts.unit_bounds(db["en"], en_t, k[0], k[-1])
        u.update(en_start=round(a, 3), en_end=round(b, 3), en_spoken=" ".join(en_toks[i]["tok"] for i in k),
                 en_coverage=round(float(np.mean([en_m["coverage"].get(str(i), 0) for i in eids])), 3))
        u["flags"] += [f"en_{x}" for x in f]
        if u["en_coverage"] < 0.6:
            u["flags"].append("en_low_coverage")
    return units


def assemble(run, units, name):
    ok = [u for u in units if "nl_start" in u and "en_start" in u]
    nl_c = [build.clip(SRC["nl"][0], u["nl_start"], u["nl_end"]) for u in ok]
    en_c = [build.clip(SRC["en"][0], u["en_start"], u["en_end"]) for u in ok]
    nl_c, g_nl = build.match_loudness(nl_c)
    en_c, g_en = build.match_loudness(en_c)
    gap = np.zeros(int(run.a.gap * build.OUT_SR), np.float32)
    parts, pos = [], 0
    for u, a, b in zip(ok, nl_c, en_c):
        u["out_start"] = round(pos / build.OUT_SR, 3)
        for x in (a, gap, b, gap, a, gap):
            parts.append(x)
            pos += len(x)
    out = run.dir / "out"
    out.mkdir(exist_ok=True)
    build.encode_mp3(np.concatenate(parts), out / f"{name}.mp3")
    print(f"[build] {len(ok)}/{len(units)} units, {pos / build.OUT_SR:.1f} s, gain nl {g_nl:+.1f} dB en {g_en:+.1f} dB")
    with open(out / f"{name}.tsv", "w", newline="") as f:
        wr = csv.writer(f, delimiter="\t", lineterminator="\n")
        wr.writerow(TSV_COLS)
        for u in units:
            wr.writerow([u["idx"], u["nl_text"], u["en_text"], SRC["nl"][1], u.get("nl_start", ""), u.get("nl_end", ""),
                         SRC["en"][1], u.get("en_start", ""), u.get("en_end", ""), u.get("out_start", ""),
                         ",".join(map(str, u["nl_ids"])), ",".join(map(str, u["en_ids"])), u["sim"],
                         u.get("en_coverage", ""), ";".join(u["flags"])])
    return dict(gain_nl=round(g_nl, 1), gain_en=round(g_en, 1), seconds=round(pos / build.OUT_SR, 1), units=len(ok))


def span_key(u):
    return (u.get("nl_start"), u.get("nl_end"), u.get("en_start"), u.get("en_end"))


def carry_verify(run, units, prev_units, prev_verify):
    """Start verify.jsonl from a previous build's results for identical clips."""
    old = {span_key(u): u for u in json.loads(Path(prev_units).read_text())}
    res = {r["idx"]: r for r in map(json.loads, Path(prev_verify).read_text().splitlines())}
    n = 0
    with open(run.dir / "verify.jsonl", "w") as f:
        for u in units:
            p = old.get(span_key(u))
            if p and p["idx"] in res and p["en_spoken"] == u.get("en_spoken"):
                f.write(json.dumps(dict(res[p["idx"]], idx=u["idx"]), ensure_ascii=False) + "\n")
                n += 1
    print(f"[verify] carried over {n} unchanged units", flush=True)


def run_verify(run, units, minutes):
    """Append one JSON line per unit; skips units already done."""
    path = run.dir / "verify.jsonl"
    done = {json.loads(l)["idx"] for l in path.read_text().splitlines()} if path.exists() else set()
    t_end = time.time() + minutes * 60
    todo = [u for u in units if "nl_start" in u and "en_start" in u and u["idx"] not in done]
    print(f"[verify] {len(done)} done, {len(todo)} to go", flush=True)
    with open(path, "a") as f:
        for u in todo:
            if time.time() > t_end:
                print("[verify] time budget reached; rerun to continue", flush=True)
                return False
            a = audio("nl")[int(u["nl_start"] * SR):int(u["nl_end"] * SR)]
            b = audio("en")[int(u["en_start"] * SR):int(u["en_end"] * SR)]
            r = dict(idx=u["idx"], nl=verify.check_clip(a, "nl", u["nl_text"]),
                     en=verify.check_clip(b, "en", u["en_spoken"]))
            r["en_vs_book"] = verify.edge_report(align.spoken_tokens(u["en_text"], "en"), r["en"]["hyp"].split())[0]
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", default="hp1_ch01")
    ap.add_argument("--nl-last", type=int)
    ap.add_argument("--nl-window", type=float, nargs=2)
    ap.add_argument("--en-window", type=float, nargs=2)
    ap.add_argument("--gap", type=float, default=1.0)
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--verify-minutes", type=float, default=22)
    ap.add_argument("--verify-only", action="store_true", help="resume verification of the existing build")
    ap.add_argument("--carry-verify", nargs=2, metavar=("PREV_UNITS", "PREV_VERIFY"),
                    help="reuse verification of clips identical to a previous build")
    ap.add_argument("--until", choices=["align", "build"], default="build")
    args = ap.parse_args()
    run = Run(args)
    (run.dir / "config.json").write_text(json.dumps(vars(args), indent=1))

    nl = chapter_sentences(WORK / "text/nl.ch01.txt")
    en = chapter_sentences(WORK / "text/en_a.ch01.txt")
    groups = run.stage("pairs", lambda: run_pairs(nl, en))
    scope = []
    for g in groups:
        if args.nl_last is not None and g[0] and max(g[0]) > args.nl_last:
            break
        scope.append(g)
    ctx = 3 if args.nl_last is not None else 0
    nl_last = max(i for g in scope for i in g[0]) + ctx
    en_last = max(i for g in scope for i in g[1]) + ctx
    nl_words = run.stage("nl_align", lambda: run_nl_align(run, nl[:nl_last + 1]))
    en_words = run.stage("en_asr", lambda: run_en_asr(run))
    en_toks = run.stage("en_align", lambda: run_en_align(run, en_words))
    gap_toks = run.stage("en_gapfill", lambda: run_en_gapfill(run, en_toks))
    en_toks = sorted(en_toks + gap_toks, key=lambda t: t["s"])
    en_m = run.stage("en_match2", lambda: run_en_match(en[:en_last + 1], en_toks))
    if args.until == "align":
        return
    if args.verify_only:
        run_verify(run, json.loads((run.dir / "units.json").read_text()), args.verify_minutes)
        return
    units = make_units(run, nl, en, scope, nl_words, en_toks, en_m)
    stats = assemble(run, units, args.name)
    if args.carry_verify:
        carry_verify(run, units, *args.carry_verify)
    (run.dir / "units.json").write_text(json.dumps(units, ensure_ascii=False, indent=1))
    (run.dir / "build.json").write_text(json.dumps(stats, indent=1))
    if args.verify:
        run_verify(run, units, args.verify_minutes)


if __name__ == "__main__":
    main()
