"""Passage view for item selection: words with indices and the pauses between them."""
import json
from pathlib import Path

from . import cuts
from .pipeline import audio

WORK = Path.home() / "work"
PAUSE = 0.15


def pause_after(db, words, i):
    """Longest quiet run (s) between word i and word i+1."""
    if i + 1 >= len(words):
        return 9.9
    return cuts.longest_pause(db, words[i]["e"] - 0.02, words[i + 1]["s"] + 0.02)


def view(run_dir, groups, lang):
    """Per group: tokens of that language, with '|' where a pause >= PAUSE follows."""
    d = Path(run_dir)
    db = cuts.frame_db(audio(lang))
    if lang == "nl":
        words = json.loads((d / "nl_align.json").read_text())
        sent = [w["sent"] for w in words]
    else:
        words = sorted(json.loads((d / "en_align.json").read_text()) + json.loads((d / "en_gapfill.json").read_text()),
                       key=lambda t: t["s"])
        sent = json.loads((d / "en_match2.json").read_text())["sent"]
    out = []
    for g in groups:
        ids = set(g)
        ks = [i for i, s in enumerate(sent) if s in ids]
        toks = []
        for i in ks:
            p = pause_after(db, words, i)
            toks.append((i, words[i]["tok"], round(p, 2)))
        out.append(toks)
    return out
