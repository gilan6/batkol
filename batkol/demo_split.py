"""Demo of splitting long clauses (no lesson schedule, only the new parts).

For each clause: pieces cut at clause boundaries inside running speech, each
drilled with its own English cue (audiobook span, or a Piper literal gloss
where the translation was restructured); then the whole clause built up from
the pieces (last piece, last two, ... all); then a repeat-only recall.
Clauses and split words are given by book-token ranges; glosses are my own
English, not book text.
"""
import json
import sys
from pathlib import Path

from .lesson import (Sources, ant_pause, find_frames, rep_pause, render, seg, sil, tts)

CLAUSES = [
    dict(name="useful", unit=4, nl_book=[102, 118], split_before=["omdat", "om"],
         cues=[dict(en_book=[97, 101]), dict(en_book=[102, 113]), dict(en_book=[114, 117])]),
    dict(name="mysterious", unit=1, nl_book=[27, 53], split_before=["van", "dat", "waren"],
         cues=[dict(gloss="And if there had ever been people"), dict(gloss="of whom you would think"),
               dict(gloss="that they would never get involved in anything strange or mysterious"),
               dict(gloss="it was them.")]),
]
HEADERS = {"useful": "Example one. Pieces with English from the audiobook.",
           "mysterious": "Example two. Pieces with a literal English translation."}


def pieces(src, c):
    nl = src.idx["nl"]
    a, b = src.nl_range(*c["nl_book"])
    starts, k = [a], a
    for tok in c["split_before"]:  # next occurrence of each split word, in order
        k = next(i for i in range(k + 1, b + 1) if nl.words[i]["tok"] == tok)
        starts.append(k)
    out = []
    for p, s0 in enumerate(starts):
        e0 = starts[p + 1] - 1 if p + 1 < len(starts) else b
        cl = src.clip("nl", s0, e0, onset=p > 0)
        cl["fade_in"] = 0.04 if p == 0 else 0.01
        cl["fade_out"] = 0.04 if p + 1 == len(starts) else 0.01
        cl["depth_db"] = nl.bounds[s0]["depth_db"] if p else None
        out.append(cl)
    whole = src.clip("nl", a, b)
    suffixes = []
    for s0 in reversed(starts[1:]):
        cl = src.clip("nl", s0, b, onset=True)
        cl["fade_in"] = 0.01
        suffixes.append(cl)
    return out, whole, suffixes


def cue(src, spec):
    if "gloss" in spec:
        return tts(spec["gloss"])
    a, b = src.en_range(*spec["en_book"])
    return src.clip("en", a, b)


def main(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    src = Sources()
    frames = find_frames(src)
    tl = []
    for c in CLAUSES:
        ps, whole, suffixes = pieces(src, c)
        cues = [cue(src, q) for q in c["cues"]]
        tl += [seg(tts(HEADERS[c["name"]]), "header"), sil(1.0)]
        for i, (p, q) in enumerate(zip(ps, cues)):  # each piece: cue -> say it -> narrator -> repeat
            d = p["end"] - p["start"]
            tl += [seg(frames["how"], "frame"), sil(0.3), seg(q, "piece_cue", f"{c['name']}.{i + 1}"),
                   sil(ant_pause(d)), seg(p, "piece", f"{c['name']}.{i + 1}"), sil(rep_pause(d)),
                   seg(p, "piece", f"{c['name']}.{i + 1}"), sil(rep_pause(d))]
        tl += [seg(frames["repeat"], "frame"), sil(0.5)]  # whole clause, built up from its pieces
        for sfx in suffixes + [whole]:
            d = sfx["end"] - sfx["start"]
            tl += [seg(sfx, "buildup" if sfx is not whole else "whole", c["name"]), sil(rep_pause(d))]
        d = whole["end"] - whole["start"]
        tl += [sil(2.0), seg(whole, "repeat_only", c["name"]), sil(rep_pause(d) + 1.0), sil(1.5)]
    sidecar, gains, secs = render(src, tl, out, "split_demo")
    notes = [dict(t=r["t"], kind=r["kind"], item=r["item"], source=r["source"], risk=r["risk"],
                  start_kind=r["start_kind"]) for r in sidecar if r["kind"] not in ("frame",)]
    (out / "split_demo.json").write_text(json.dumps(dict(minutes=round(secs / 60, 2), gains_db=gains,
                                                         timeline=notes), indent=1))
    print(f"{secs / 60:.2f} min, gains {gains}")
    for c in CLAUSES:
        ps, _, _ = pieces(src, c)
        print(c["name"], [(round(p["end"] - p["start"], 2), p["depth_db"]) for p in ps])
    return notes


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else Path.home() / "work/demo_split")
