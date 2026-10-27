"""Does the audiobook follow the text? Whisper transcript vs each candidate text.

  python -m batkol.edition <chapter> nl|en

Needs <lang>_asr.jsonl (`batkol.analyze`). Candidates: chapter 1 of every EPUB
the registry found for the chapter (`batkol.sources`), plus the chapter text
already in ~/work/text (e.g. the repaired HP1 text), which is never overwritten.
Book tokens are diffed against the spoken tokens: shares of the book tokens
(ok, fuzzy = spelling, differs, unheard), spoken tokens not in the book
(added), and every run where audio and text part for >= RUN tokens. The
candidate with the most ok tokens wins; its text becomes the chapter text and
~/work/<chapter>/edition_<lang>.json records the decision and the runs:
  book       force-align the text as is: ok+fuzzy >= MIN_MATCH (NL). Runs are
             local: alignment re-syncs on the matching words around them, so the
             clip of a unit holding a run is still complete (tested on a fixture
             with a reworded sentence); only a cut inside a run is unsafe, and
             `batkol.drill` merges across those (nl_text_run). EN is always book:
             its index is built from what the cast said.
  reconcile  NL, ok+fuzzy < MIN_MATCH: too far from the text to force-align it;
             analyze refuses (a reconciliation step is not written)
  stop       ok < MIN_OK for every candidate: wrong file or wrong chapter
The report (with book text, so Drive only, never git) is edition_<lang>.md.
"""
import difflib
import json
import sys
from pathlib import Path

from rapidfuzz import fuzz

from . import sources
from .align import spoken_tokens
from .chapter import chapter1
from .index import FUZZY
from .sentences import chapter_sentences

WORK = Path.home() / "work"
RUN = 4            # tokens: shorter differences are mostly ASR misses (HP1 NL: 109 single `differs`)
JOIN = 2           # runs separated by at most this many equal tokens are one run
MIN_MATCH = 0.85   # HP1 ch. 1 NL: ~0.97 ok + ~0.015 fuzzy
MIN_OK = 0.70


def spoken(asr_path, lang):
    recs = [json.loads(l) for l in Path(asr_path).read_text().splitlines()]
    return [(t, w["s"], w["e"]) for r in recs for w in r["words"] for t in spoken_tokens(w["w"], lang)]


def book(text_path, lang):
    sents = chapter_sentences(text_path)
    return [(s["id"], t) for s in sents for t in spoken_tokens(s["text"], lang)]


def compare(btoks, stoks):
    b, s = [t for _, t in btoks], [t[0] for t in stoks]
    ops = difflib.SequenceMatcher(None, b, s, autojunk=False).get_opcodes()
    n = dict(ok=0, fuzzy=0, differs=0, unheard=0, added=0)
    for op, i1, i2, j1, j2 in ops:
        if op == "equal":
            n["ok"] += i2 - i1
        elif op == "delete":
            n["unheard"] += i2 - i1
        elif op == "insert":
            n["added"] += j2 - j1
        else:
            for k in range(i2 - i1):
                hj = j1 + k * (j2 - j1) // (i2 - i1)
                n["fuzzy" if fuzz.ratio(b[i1 + k], s[hj]) >= FUZZY else "differs"] += 1
            n["added"] += max(0, (j2 - j1) - (i2 - i1))
    eq = [k for k, o in enumerate(ops) if o[0] == "equal"]
    first, last = (eq[0], eq[-1]) if eq else (len(ops), -1)
    # runs: non-equal stretches between the first and last match, joined over tiny equal
    # blocks; a run's size counts only its non-equal tokens
    runs, cur = [], None
    for k in range(first + 1, last):
        op, i1, i2, j1, j2 = ops[k]
        if op == "equal":
            if cur and i2 - i1 > JOIN:
                runs.append(cur)
                cur = None
            continue
        if cur is None:
            cur = dict(i1=i1, j1=j1, nb=0, ns=0, kinds=set())
        cur.update(i2=i2, j2=j2, nb=cur["nb"] + i2 - i1, ns=cur["ns"] + j2 - j1, kinds=cur["kinds"] | {op})
    if cur:
        runs.append(cur)
    long_runs = []
    for r in runs:
        if max(r["nb"], r["ns"]) < RUN:
            continue
        kinds = r["kinds"]
        t0 = stoks[min(r["j1"], len(stoks) - 1)][1]
        t1 = stoks[min(max(r["j2"] - 1, r["j1"]), len(stoks) - 1)][2]
        long_runs.append(dict(t=round(t0, 2), t_end=round(max(t0, t1), 2), sent=btoks[min(r["i1"], len(btoks) - 1)][0],
                              book_n=r["nb"], spoken_n=r["ns"],
                              kind="delete" if kinds == {"delete"} else "insert" if kinds == {"insert"} else "replace",
                              book=" ".join(b[r["i1"]:r["i2"]]), spoken=" ".join(s[r["j1"]:r["j2"]])))
    intro = ops[first][3] if eq else len(s)
    outro = len(s) - ops[last][4] if eq else 0
    nb = max(1, len(b))
    return dict(book_tokens=len(b), spoken_tokens=len(s), **n,
                ok_share=round(n["ok"] / nb, 4), match=round((n["ok"] + n["fuzzy"]) / nb, 4),
                inner_runs=sum(r["kind"] != "delete" for r in long_runs),
                runs_per_k=round(1000 * sum(r["kind"] != "delete" for r in long_runs) / nb, 2),
                intro_spoken=intro, outro_spoken=outro), long_runs


def decide(lang, best):
    if best is None or best["ok_share"] < MIN_OK:
        return "stop", f"best ok share {best and best['ok_share']} < {MIN_OK}: wrong file or chapter"
    if lang == "en":
        return "book", "EN index is built from what the cast said; the text only maps it to sentences"
    if best["match"] >= MIN_MATCH:
        return "book", f"match {best['match']} >= {MIN_MATCH}; {best['inner_runs']} runs, cuts inside them are merged"
    return "reconcile", f"match {best['match']} < {MIN_MATCH}: too far from the text to force-align it"


def mmss(t):
    return f"{int(t // 60)}:{t % 60:04.1f}"


def main(chapter, lang):
    src = sources.load(chapter)[lang]
    run = WORK / chapter
    stoks = spoken(run / f"{lang}_asr.jsonl", lang)
    text = Path(src["text"])
    cands = {}
    if text.exists():
        cands["current"] = (text.read_text().splitlines(), str(text))
    for name, e in src["epubs"].items():
        try:
            cands[name] = (chapter1(e["local"]), e["drive"])
        except SystemExit as err:
            print(f"[edition] {name}: {err}")
    tmp = run / f"edition_{lang}.tmp.txt"
    res = {}
    for name, (paras, origin) in cands.items():
        tmp.write_text("\n".join(paras) + "\n")
        res[name] = compare(book(tmp, lang), stoks)
        res[name][0]["origin"] = origin
        print(f"[edition] {name}: " + ", ".join(f"{k} {v}" for k, v in res[name][0].items() if k != "origin"))
    tmp.unlink(missing_ok=True)
    best = max(res, key=lambda k: res[k][0]["ok_share"]) if res else None
    decision, why = decide(lang, res[best][0] if best else None)
    if decision != "stop" and best != "current":
        if text.exists():
            why += f"; {text.name} kept (exists), though {best} matches better"
        else:
            text.parent.mkdir(parents=True, exist_ok=True)
            text.write_text("\n".join(cands[best][0]) + "\n")
            why += f"; wrote {text.name} from {best}"
    out = dict(decision=decision, why=why, chosen=best, candidates={k: v[0] for k, v in res.items()},
               runs=res[best][1] if best else [])
    (run / f"edition_{lang}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    L = [f"# {chapter} {lang.upper()}: audiobook vs text", "", f"**Decision: {decision}**: {why}", "",
         "| candidate | book tok | ok | fuzzy | differs | unheard | added | match | runs/1000 | intro/outro spoken |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for k, (st, _) in res.items():
        L.append(f"| {k} | {st['book_tokens']} | {st['ok_share']:.1%} | {st['fuzzy']} | {st['differs']} | "
                 f"{st['unheard']} | {st['added']} | {st['match']:.1%} | {st['runs_per_k']} | "
                 f"{st['intro_spoken']}/{st['outro_spoken']} |")
    L += ["", "Sources: " + "; ".join(f"{k} = `{st['origin']}`" for k, (st, _) in res.items()), ""]
    if best:
        L += [f"## Runs of >= {RUN} tokens where audio and text part ({best})", ""]
        for r in res[best][1]:
            L.append(f"- {mmss(r['t'])} sent {r['sent']}, {r['kind']} ({r['book_n']} book / {r['spoken_n']} spoken): "
                     f"book “{r['book']}” / heard “{r['spoken']}”")
    (run / f"edition_{lang}.md").write_text("\n".join(L) + "\n")
    print(f"[edition] {chapter} {lang}: {decision} ({why})")
    return out


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
