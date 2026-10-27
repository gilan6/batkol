"""NL -> EN -> NL chapter drill, planned and cut from the audio indexes only.

  python -m batkol.drill <chapter>                       # plan + render
  python -m batkol.drill ch01 --no-risk-merge --no-render --compare ~/work/ch01/units.json
                                                          # regression vs the verified HP1 drill v3

No ASR and no verification pass: word timings, pauses, cut points and risks
come from `batkol.index` (one pass per source, `batkol.analyze`).
Per unit (legacy layout): NL clip, gap, EN clip, gap, NL clip, gap.

Units are the LaBSE sentence groups (cached pairs.json). NL sentences without
an EN partner join the previous unit, so every NL sentence is drilled; EN
sentences without an NL partner are left out. Neighbouring units are merged
when either language has no real pause between them (a cut would go through
speech) and, with risk merge (default), when an edge word at the cut has an
unreliable CTC score (< LOW_SCORE: overlapping, whispered or emotional lines;
this rule caught every EN defect the re-transcriptions found in HP1), or when
an NL cut falls where the narration departs from the text for a few words
(`batkol.edition` runs: book word timings are unreliable there).
Merging stops at MAX_NL_S of Dutch speech per unit.

Output in ~/work/<chapter>/drill/: <name>.mp3, <name>.tsv, <name>_report.md, units.json.
"""
import argparse
import csv
import json
from collections import Counter
from pathlib import Path

import numpy as np

from . import build, sources
from .index import LOW_SCORE, Index
from .sentences import chapter_sentences

WORK = Path.home() / "work"
MAX_NL_S = 45.0
RUN_PAD = 0.5  # s around an edition run (whisper vs CTC timing)
TSV_COLS = ["idx", "nl_text", "en_text", "nl_file", "nl_start", "nl_end", "en_file", "en_start", "en_end",
            "out_start", "nl_ids", "en_ids", "sim", "en_coverage", "flags", "risk", "merged"]


def pairs(chapter, nl_sents, en_sents):
    p = WORK / chapter / "pairs.json"
    if not p.exists():
        from .pipeline import run_pairs
        p.write_text(json.dumps(run_pairs(nl_sents, en_sents), ensure_ascii=False, indent=1))
    return json.loads(p.read_text())


def by_sent(ix, lang):
    """Word indices per book sentence. NL words the narrator added carry the next
    book word's sentence regardless of pauses, so they are placed by the cuts."""
    d = {}
    for i, w in enumerate(ix.words):
        if w.get("sent") is not None and (lang == "en" or w["status"] != "added"):
            d.setdefault(w["sent"], []).append(i)
    return d


def span_of(d, ids):
    ks = [k for s in ids for k in d.get(s, [])]
    return (min(ks), max(ks)) if ks else None


def raw_units(groups, nl_by, en_by):
    units, carry, joined, dropped_en = [], [], [], []
    for nids, eids, sim in groups:
        if span_of(nl_by, nids) and span_of(en_by, eids):
            units.append(dict(nl_ids=carry + list(nids), en_ids=list(eids), sim=sim))
            carry = []
            continue
        dropped_en += list(eids)
        if nids:
            joined += list(nids)
            if units:
                units[-1]["nl_ids"] += list(nids)
            else:
                carry += list(nids)
    for u in units:
        u["nl"], u["en"] = span_of(nl_by, u["nl_ids"]), span_of(en_by, u["en_ids"])
    return units, joined, dropped_en


def text_runs(chapter):
    p = WORK / chapter / "edition_nl.json"
    return [(r["t"] - RUN_PAD, r["t_end"] + RUN_PAD) for r in json.loads(p.read_text())["runs"]] if p.exists() else []


def boundary(ix, u_last, v_first, lang, runs=()):
    """Cut between core words u_last and v_first. Returns end (bound closing the
    left unit) and start (bound opening the right one): bound k lies before word k.
    NL: one cut at the longest pause, so words between join a side. EN: cut at the
    first and last pause, so sound between (credits, words of left-out sentences,
    cast additions) is left out."""
    ks = range(u_last + 1, v_first + 1)
    if not ks:
        return dict(end=None, start=None, reasons=[f"{lang}_overlap"])
    ps = [k for k in ks if ix.bounds[k]["kind"] == "pause"]
    if not ps:
        k = min(ks, key=lambda k: ix.bounds[k]["depth_db"])
        return dict(end=k, start=k, reasons=[f"{lang}_no_pause"])
    if lang == "nl":
        end = start = max(ps, key=lambda k: ix.bounds[k]["pause"])
    else:
        end, start = ps[0], ps[-1]
    low = any(ix.words[w]["score"] < LOW_SCORE for w in (end - 1, start))
    g0, g1 = ix.words[end - 1]["e"], ix.words[start]["s"]
    in_run = any(a < g1 and g0 < b for a, b in runs)
    return dict(end=end, start=start, reasons=[f"{lang}_edge_score"] * low + [f"{lang}_text_run"] * in_run)


def widen(ix, k, step):
    """Chapter edges: take in NL words the narrator added with no pause between."""
    while 0 <= k + step < len(ix.words) and ix.words[k + step]["status"] == "added" \
            and ix.bounds[max(k, k + step)]["kind"] != "pause":
        k += step
    return k


def plan(nl, en, groups, risk_merge=True, max_nl_s=MAX_NL_S, runs=()):
    nl_by, en_by = by_sent(nl, "nl"), by_sent(en, "en")
    units, joined, dropped_en = raw_units(groups, nl_by, en_by)
    cuts = [(boundary(nl, u["nl"][1], v["nl"][0], "nl", runs), boundary(en, u["en"][1], v["en"][0], "en"))
            for u, v in zip(units, units[1:])]
    speech = lambda i, j: nl.words[units[j]["nl"][1]]["e"] - nl.words[units[i]["nl"][0]]["s"]
    spans, cur, merged, closed = [], [0], [], []
    for i, (cn, ce) in enumerate(cuts):
        rs = cn["reasons"] + ce["reasons"]
        hard = [r for r in rs if r.endswith(("_no_pause", "_overlap"))]
        want = hard or (rs and risk_merge)
        if want and (speech(cur[0], i + 1) <= max_nl_s or any(r.endswith("_overlap") for r in hard)):
            cur.append(i + 1)
            merged += rs
            continue
        spans.append((cur, [r for r in rs if r.endswith("_no_pause")]))
        closed.append(i)
        cur = [i + 1]
    spans.append((cur, []))
    out = []
    for g, (members, in_speech) in enumerate(spans):
        first, last = members[0], members[-1]
        if g == 0:
            na, ea = widen(nl, units[first]["nl"][0], -1), units[first]["en"][0]
        else:
            cn, ce = cuts[closed[g - 1]]
            na, ea = cn["start"], ce["start"]
        if g == len(spans) - 1:
            nb, eb = widen(nl, units[last]["nl"][1], 1), units[last]["en"][1]
        else:
            cn, ce = cuts[closed[g]]
            nb, eb = cn["end"] - 1, ce["end"] - 1
        inner = [r for i in range(first, last) for c in cuts[i] for r in c["reasons"]]
        out.append(dict(members=members, nl_ids=[s for m in members for s in units[m]["nl_ids"]],
                        en_ids=[s for m in members for s in units[m]["en_ids"]],
                        sim=min(units[m]["sim"] for m in members), nl_words=[na, nb], en_words=[ea, eb],
                        merged=sorted(set(inner)), cut_in_speech=in_speech))
    # an EN sentence without NL partner between merged units plays inside the merged EN clip
    inside = {en.words[k]["sent"] for u in out for k in range(u["en_words"][0], u["en_words"][1] + 1)}
    stats = dict(raw_units=len(units), units=len(out), merged=dict(Counter(merged)), nl_joined=joined,
                 en_dropped=[s for s in dropped_en if s not in inside], en_inside=[s for s in dropped_en if s in inside])
    return out, stats


def clips(nl, en, units, nl_sents, en_sents):
    nl_text = {s["id"]: s["text"] for s in nl_sents}
    en_text = {s["id"]: s["text"] for s in en_sents}
    for idx, u in enumerate(units):
        a = nl.span(*u["nl_words"])
        b = en.span(*u["en_words"])
        u.update(idx=idx, nl_start=a["start"], nl_end=a["end"], en_start=b["start"], en_end=b["end"],
                 nl_text=" ".join(nl_text[i] for i in u["nl_ids"]), en_text=" ".join(en_text[i] for i in u["en_ids"]),
                 en_spoken=" ".join(b["tokens"]), risk=[f"nl_{r}" for r in a["risk"]] + [f"en_{r}" for r in b["risk"]])
        u["flags"] = ["cut_in_speech"] * bool(u["cut_in_speech"] or any(
            r.endswith(("start_short", "start_none", "end_short", "end_none")) for r in u["risk"]))
    return units


def render(units, nl_src, en_src, out, name, gap_s):
    nl_c, g_nl = build.match_loudness([build.clip(nl_src, u["nl_start"], u["nl_end"]) for u in units])
    en_c, g_en = build.match_loudness([build.clip(en_src, u["en_start"], u["en_end"]) for u in units])
    gap = np.zeros(int(gap_s * build.OUT_SR), np.float32)
    parts, pos = [], 0
    for u, a, b in zip(units, nl_c, en_c):
        u["out_start"] = round(pos / build.OUT_SR, 3)
        for x in (a, gap, b, gap, a, gap):
            parts.append(x)
            pos += len(x)
    build.encode_mp3(np.concatenate(parts), out / f"{name}.mp3")
    return dict(gain_nl=round(g_nl, 1), gain_en=round(g_en, 1), seconds=round(pos / build.OUT_SR, 1))


def write_tsv(units, src, path):
    with open(path, "w", newline="") as f:
        wr = csv.writer(f, delimiter="\t", lineterminator="\n")
        wr.writerow(TSV_COLS)
        for u in units:
            wr.writerow([u["idx"], u["nl_text"], u["en_text"], src["nl"]["drive"], u["nl_start"], u["nl_end"],
                         src["en"]["drive"], u["en_start"], u["en_end"], u.get("out_start", ""),
                         ",".join(map(str, u["nl_ids"])), ",".join(map(str, u["en_ids"])), u["sim"], "",
                         ";".join(u["flags"]), ";".join(u["risk"]), ";".join(u["merged"])])


def coverage(nl, units):
    inside = np.zeros(len(nl.words), bool)
    for u in units:
        inside[u["nl_words"][0]:u["nl_words"][1] + 1] = True
    left = []
    for k in np.flatnonzero(~inside):
        if left and left[-1][1] == k - 1:
            left[-1][1] = int(k)
        else:
            left.append([int(k), int(k)])
    return float(inside.mean()), [dict(words=r, t=nl.words[r[0]]["s"], toks=" ".join(w["tok"] for w in nl.words[r[0]:r[1] + 1]),
                                       status=sorted({w["status"] for w in nl.words[r[0]:r[1] + 1]})) for r in left]


def compare(units, old_path, tol=0.02):
    """Regression vs an earlier (verified) build: same groups, cut times within tol."""
    old = {tuple(u["nl_ids"]): u for u in json.loads(Path(old_path).expanduser().read_text()) if "en_start" in u}
    same, deltas, big = 0, [], []
    for u in units:
        o = old.get(tuple(u["nl_ids"]))
        if not o or o["en_ids"] != u["en_ids"]:
            continue
        same += 1
        for k in ("nl_start", "nl_end", "en_start", "en_end"):
            d = round(u[k] - o[k], 3)
            deltas.append(abs(d))
            if abs(d) > tol:
                big.append(dict(idx=u["idx"], old_idx=o["idx"], cut=k, delta=d, risk=u["risk"]))
    deltas = np.array(deltas) if deltas else np.zeros(1)
    return dict(old_units=len(old), new_units=len(units), same_groups=same, cuts=int(len(deltas)),
                within_tol=round(float((deltas <= tol).mean()), 4), max_delta=round(float(deltas.max()), 3), big=big)


def mmss(t):
    return f"{int(t // 60)}:{t % 60:04.1f}"


def report(chapter, name, units, stats, cov, left, build_stats, cmp):
    flagged = [u for u in units if u["flags"] or u["risk"]]
    L = [f"# {name}: NL → EN → NL drill, {chapter}", "",
         "Planned and cut from the audio indexes only (no re-transcription).", ""]
    if build_stats:
        L.append(f"- MP3: `{name}.mp3`, {build_stats['seconds'] / 60:.1f} min. "
                 f"Gain NL {build_stats['gain_nl']:+} dB, EN {build_stats['gain_en']:+} dB.")
    L += [f"- Units: {stats['units']} (from {stats['raw_units']} sentence groups). "
          f"Merged boundaries by reason: " + (", ".join(f"{k} ×{v}" for k, v in stats["merged"].items()) or "none"),
          f"- NL sentences without EN partner, joined to the previous unit: {len(stats['nl_joined'])} {stats['nl_joined']}",
          f"- EN sentences without NL partner (or no EN audio found): left out {len(stats['en_dropped'])} "
          f"{stats['en_dropped']}; inside a merged EN clip {len(stats['en_inside'])} {stats['en_inside']}",
          f"- NL word coverage: {cov:.1%}" + ("" if not left else f"; left out: {len(left)} stretches"),
          f"- Cuts inside speech (must be 0): {sum(bool(u['flags']) for u in units)}",
          f"- Units with an index risk (spot-check by ear if you like): {len(flagged)}"]
    for r in left:
        L.append(f"  - NL {mmss(r['t'])} words {r['words']} ({','.join(r['status'])}): “{r['toks']}”")
    if cmp:
        L += ["", "## Regression vs earlier build", "",
              f"- {cmp['same_groups']} of {cmp['new_units']} units have the same sentence groups as one of the "
              f"{cmp['old_units']} earlier units.",
              f"- Cut times within 20 ms: {cmp['within_tol']:.1%} of {cmp['cuts']} cuts; max |Δ| {cmp['max_delta']} s."]
        for b in cmp["big"]:
            L.append(f"  - unit {b['idx']} (old {b['old_idx']}) {b['cut']}: Δ {b['delta']:+.3f} s; risk {b['risk']}")
    if flagged:
        L += ["", "## Units with risks", "", "| unit | MP3 at | flags / risk | NL start |", "|---|---|---|---|"]
        for u in flagged:
            at = mmss(u["out_start"]) if "out_start" in u else ""
            L.append(f"| {u['idx']} | {at} | {', '.join(u['flags'] + u['risk'])} | {u['nl_text'][:50]}… |")
    return "\n".join(L) + "\n"


def default_name(chapter):
    return f"hp{chapter[1]}_{chapter[2:]}" if chapter.startswith("b") else f"hp1_{chapter}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("chapter")
    ap.add_argument("--name")
    ap.add_argument("--gap", type=float, default=1.0)
    ap.add_argument("--no-risk-merge", action="store_true")
    ap.add_argument("--no-render", action="store_true", help="plan, TSV and report only")
    ap.add_argument("--compare", help="units.json of an earlier build (regression)")
    a = ap.parse_args()
    name = a.name or default_name(a.chapter)
    src = sources.load(a.chapter)
    nl, en = Index(f"nl_{a.chapter}"), Index(f"en_{a.chapter}")
    nl_sents, en_sents = chapter_sentences(src["nl"]["text"]), chapter_sentences(src["en"]["text"])
    units, stats = plan(nl, en, pairs(a.chapter, nl_sents, en_sents), risk_merge=not a.no_risk_merge,
                        runs=text_runs(a.chapter))
    units = clips(nl, en, units, nl_sents, en_sents)
    out = WORK / a.chapter / "drill"
    out.mkdir(parents=True, exist_ok=True)
    bstats = None if a.no_render else render(units, src["nl"]["local"], src["en"]["local"], out, name, a.gap)
    cov, left = coverage(nl, units)
    cmp = compare(units, a.compare) if a.compare else None
    write_tsv(units, src, out / f"{name}.tsv")
    (out / "units.json").write_text(json.dumps(units, ensure_ascii=False, indent=1))
    rep = report(a.chapter, name, units, stats, cov, left, bstats, cmp)
    (out / f"{name}_report.md").write_text(rep)
    print(rep[:3000])


if __name__ == "__main__":
    main()
