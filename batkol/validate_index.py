"""Does the audio index alone predict what clip re-transcription found?

For every historical clip (ch01 drill v1 and v3, lesson clip bank) the index
gives the words inside the cut ("index transcript"); its edge diff against the
expected tokens is compared with the edge diff whisper produced on the clip.
Run: uv run python -m batkol.validate_index [nl|en|all]
"""
import bisect
import json
import sys
from collections import Counter
from pathlib import Path

from batkol import verify
from batkol.align import spoken_tokens
from batkol.index import Index
from batkol.sentences import chapter_sentences

W = Path.home() / "work"
TOL = 0.03
LOW_SCORE = 0.3  # edge word whose CTC alignment is unreliable (overlap, whisper, effects)


class Words:
    def __init__(self, idx):
        self.idx = idx
        self.starts = [w["s"] for w in idx.words]
        self.unindexed = idx.unindexed

    def risk(self, cs, ce):
        """Signal risk per edge from the index: the cut lands inside a word, in a
        boundary without a real pause, or the clip margin holds sound that no
        word accounts for."""
        out = set()
        inside = [i for i in range(max(0, bisect.bisect_left(self.starts, cs - 5) - 1), len(self.starts))
                  if self.starts[i] < ce and self.idx.words[i]["e"] > cs]
        for side, t in (("start", cs), ("end", ce)):
            for w in self.idx.words[max(0, bisect.bisect_left(self.starts, t) - 3):bisect.bisect_left(self.starts, t) + 2]:
                if w["s"] + 0.02 < t < w["e"] - 0.02:
                    out.add(side)
        full = [i for i in inside if cs - TOL <= self.idx.words[i]["s"] and self.idx.words[i]["e"] <= ce + TOL]
        if full:
            a, b = full[0], full[-1]
            if self.idx.bounds[a]["kind"] != "pause" or self.idx.words[a]["score"] < LOW_SCORE:
                out.add("start")
            if self.idx.bounds[b + 1]["kind"] != "pause" or self.idx.words[b]["score"] < LOW_SCORE:
                out.add("end")
            for side, (m0, m1) in (("start", (cs, self.idx.words[a]["s"])), ("end", (self.idx.words[b]["e"], ce))):
                if sum(max(0.0, min(m1, u1) - max(m0, u0)) for u0, u1 in self.unindexed) >= 0.1:
                    out.add(side)
        return out

    def transcript(self, cs, ce):
        """Tokens whose midpoint lies inside [cs, ce]; words cut through are reported."""
        toks, partial = [], []
        i = max(0, bisect.bisect_left(self.starts, cs - 5) - 1)
        while i < len(self.idx.words) and self.idx.words[i]["s"] < ce:
            w = self.idx.words[i]
            if w["e"] > cs + TOL and w["s"] < ce - TOL:
                if cs <= (w["s"] + w["e"]) / 2 <= ce:
                    toks.append(w["tok"])
                if w["s"] < cs - TOL or w["e"] > ce + TOL:
                    partial.append(w["tok"])
            i += 1
        return toks, partial


def edge_flags(flags, lang=None):
    """missing/extra at either edge -> set of (side, kind)."""
    out = set()
    for f in flags:
        k = f.split(":")[0]
        if k.endswith(("missing", "extra")):
            side, kind = k.split("_")
            out.add((side, kind))
    return out


def compare_any(rows, label):
    """Per edge: any ASR-found defect vs index flag (token diff or signal risk)."""
    c, misses = Counter(), []
    for truth, pred, risk, info in rows:
        for side in ("start", "end"):
            t = any(s == side for s, _ in truth)
            p = any(s == side for s, _ in pred) or side in risk
            c[(t, p)] += 1
            if t and not p:
                misses.append((info, side, sorted(truth)))
    tp, fn, fp, tn = c[(True, True)], c[(True, False)], c[(False, True)], c[(False, False)]
    print(f"{label} [tokens+signal]: ASR-found defective edges {tp + fn}, index flagged {tp} "
          f"(recall {tp / max(1, tp + fn):.0%}); index flags on clean edges {fp} of {fp + tn} ({fp / max(1, fp + tn):.1%})")
    for m in misses:
        print(f"    missed: {m}")
    return dict(defective_edges=tp + fn, flagged=tp, recall=round(tp / max(1, tp + fn), 3),
                false_flags=fp, clean_edges=fp + tn)


def compare(rows, label):
    """rows: (truth_flags_set, predicted_flags_set, partial_words, info)."""
    c = Counter()
    misses, false = [], []
    for truth, pred, partial, info in rows:
        for e in {(s, k) for s in ("start", "end") for k in ("missing", "extra")}:
            t, p = e in truth, e in pred
            c[(t, p)] += 1
            if t and not p:
                misses.append((info, e))
            if p and not t:
                false.append((info, e))
    tp, fn, fp = c[(True, True)], c[(True, False)], c[(False, True)]
    print(f"{label}: ASR-found edge defects {tp + fn}, index predicted {tp} (recall {tp / max(1, tp + fn):.0%}), "
          f"index-only flags {fp}, edges checked {sum(c.values())}")
    for info, e in misses:
        print(f"    missed by index: {info} {e}")
    for info, e in false[:8]:
        print(f"    index-only: {info} {e}")
    return dict(found=tp + fn, predicted=tp, recall=round(tp / max(1, tp + fn), 3), index_only=fp)


def drill(units_path, verify_path, langs, label):
    units = {u["idx"]: u for u in json.loads(Path(units_path).read_text())}
    ver = [json.loads(l) for l in Path(verify_path).read_text().splitlines()]
    nl_sent = {s["id"]: s["text"] for s in chapter_sentences(W / "text/nl.ch01.txt")}
    res = {}
    for lang in langs:
        words = Words(Index(f"{lang}_ch01"))
        rows, rows_any = [], []
        for v in ver:
            u = units[v["idx"]]
            if f"{lang}_start" not in u:
                continue
            if lang == "nl":
                exp = [t for i in u["nl_ids"] for t in spoken_tokens(nl_sent[i], "nl")]
            else:
                exp = u["en_spoken"].split()
            toks, partial = words.transcript(u[f"{lang}_start"], u[f"{lang}_end"])
            pred = edge_flags(verify.edge_report(exp, toks)[1])
            truth = edge_flags(v[lang]["flags"] if lang in v else v["en_vs_spoken"]["flags"])
            rows.append((truth, pred, partial, f"unit {v['idx']}"))
            rows_any.append((truth, pred, words.risk(u[f"{lang}_start"], u[f"{lang}_end"]), f"unit {v['idx']}"))
        res[lang] = dict(tokens=compare(rows, f"{label} {lang}"), any=compare_any(rows_any, f"{label} {lang}"))
    return res


def bank():
    key = {"nl": "nl_ch01", "en": "en_ch01", "pims": "pims_L01"}
    words = {k: Words(Index(v)) for k, v in key.items()}
    rows, rows_any = [], []
    recs = {}
    for l in (W / "bank/clips.jsonl").read_text().splitlines():
        r = json.loads(l)
        if r.get("by") != "user" and r["src"] in key:
            recs[r["id"]] = r
    for r in recs.values():
        toks, partial = words[r["src"]].transcript(r["start"], r["end"])
        pred = edge_flags(verify.edge_report(r["tokens"], toks)[1])
        rows.append((edge_flags(r["flags"]), pred, partial, f"{r['kind']} {r['start']}"))
        risk = words[r["src"]].risk(r["start"], r["end"])
        if r.get("onset") == "in_speech":
            risk.discard("start")  # planned onset inside speech: judged by ear, not by this rule
        rows_any.append((edge_flags(r["flags"]), pred, risk, f"{r['kind']} {r['start']}"))
    return dict(tokens=compare(rows, "lesson clip bank"), any=compare_any(rows_any, "lesson clip bank"))


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    langs = ["nl", "en"] if which == "all" else [which]
    out = {"v1": drill(W / "ch01/v1/units.json", W / "ch01/v1/verify.jsonl", langs, "ch01 v1"),
           "v3": drill(W / "ch01/units.json", W / "ch01/verify.jsonl", langs, "ch01 v3")}
    if which == "all":
        out["bank"] = bank()
    (W / "index" / f"validation_{which}.json").write_text(json.dumps(out, indent=1))
