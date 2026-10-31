"""Pimsleur-style lesson, planned and cut from the audio indexes only.

No audio analysis here: word timings, pauses, cut points and risk flags come
from `batkol.index` (one pass per source). Items are book-token ranges, which
stay valid when the audio is reprocessed.

Per item: Pimsleur frame + EN cue -> pause (say it in Dutch) -> NL narrator ->
pause (repeat); long items get backward buildup (suffixes of the narrator's
phrase); recalls at +5 s, +25 s, +2 min, +10 min; recombination of adjacent
taught items; passage at start and end.

Clip gating uses index risks (cut not in a pause, unreliable edge-word
alignment) and the user's listening verdicts (clip bank); builds never run ASR.
"""
import json
import re
import sys
import wave
from pathlib import Path

import numpy as np

from . import build
from .clipbank import SpanBank, span_id
from .index import LOW_SCORE, Index

WORK = Path.home() / "work"
INTERVALS = [5, 25, 120, 600]
PART_INTERVALS = [25, 120]      # a part of a long clause, after its intro
WHOLE_INTERVALS = [120, 600]    # repeat-only recalls of a long clause
LONG_WORDS, LONG_SECS = 12, 4.5  # longer than this: too long to recall from an English cue
OK_DEPTH = -10                  # a cut inside speech needs a dip at least this deep (dB under speech);
                                # same bound as risky_onset (fitted on leaked cuts; -14.8 dB passed by ear)
DUE_SLACK = 8  # a recall due this soon goes before the next new item (keeps the 5 s step short)
GAP = 0.6
CHUNK_PAUSE = 0.15
MIN_PAUSE = 0.12
# onset quality for a cut inside speech: stop/fricative onsets hide the cut best
GOOD_ONSET = set("pbtdkgfvszhc")
OKAY_ONSET = set("mnlrwj")
FRAMES = {"how": "how do you say", "repeat": "listen and repeat", "remember": "do you remember how to say"}
FALLBACK = {"how": "How do you say:", "repeat": "Listen and repeat.", "remember": "Do you remember how to say:"}
VOICE = WORK / "tts/en_GB-alan-medium.onnx"


def ant_pause(d):
    return float(np.clip(1.6 * d, 2.5, 9.0))


def rep_pause(d):
    return float(np.clip(1.2 * d, 1.8, 7.0))


class Sources:
    """The three indexes plus the chapter's NL<->EN sentence groups."""

    def __init__(self, chapter="ch01"):
        self.idx = {"nl": Index(f"nl_{chapter}"), "en": Index(f"en_{chapter}"), "pims": Index("pims_L01")}
        self.units = json.loads((WORK / chapter / "units.json").read_text())
        self.nl_word = {w["book_i"]: i for i, w in enumerate(self.idx["nl"].words) if w.get("book_i") is not None}
        self.en_words = {}
        for i, w in enumerate(self.idx["en"].words):
            if w.get("book_i") is not None:
                self.en_words.setdefault(w["book_i"], []).append(i)

    def clip(self, lang, a, b, onset=False):
        c = self.idx[lang].span(a, b, onset=onset)
        c["src"] = lang
        c["id"] = span_id(self.idx[lang], a, b, onset)
        c["speech_s"] = round(self.idx[lang].words[b]["e"] - self.idx[lang].words[a]["s"], 2)
        return c

    def nl_range(self, i0, i1):
        """Word span for book tokens i0..i1, widened over words the narrator added
        at either edge when no pause separates them (they belong to the utterance)."""
        nl = self.idx["nl"]
        a, b = self.nl_word[i0], self.nl_word[i1]
        while a > 0 and nl.words[a - 1]["status"] == "added" and nl.bounds[a]["kind"] != "pause":
            a -= 1
        while b + 1 < len(nl.words) and nl.words[b + 1]["status"] == "added" and nl.bounds[b + 1]["kind"] != "pause":
            b += 1
        return a, b

    def en_range(self, j0, j1):
        ks = [k for j in range(j0, j1 + 1) for k in self.en_words.get(j, [])]
        return min(ks), max(ks)

    def unit_range(self, lang, unit):
        ids = set(self.units[unit][f"{lang}_ids"])
        ks = [i for i, w in enumerate(self.idx[lang].words) if w.get("sent") in ids]
        return ks[0], ks[-1]


def severe(c, onset_ok=False, end_ok=False):
    """Index risks that make a clip unusable: a cut that lands in speech
    (unless it is a planned cut at a checked boundary: onset_ok / end_ok)."""
    out = []
    for r in c["risk"]:
        if r.startswith(("end_short", "end_none")) and not end_ok:
            out.append(r)
        elif r.startswith(("start_short", "start_none")) and not onset_ok:
            out.append(r)
    return out


def needs_ear(c):
    """Index risks a listener settles once: unreliable edge-word alignment, an
    edge word the speaker said differently, or a start cut inside speech."""
    return [r for r in c.get("risk", []) if "_score" in r or "_word_" in r] + \
        (["onset_in_speech"] if c.get("start_kind") == "onset" else []) + \
        (["end_in_speech"] if c.get("planned_end") else [])


def onset_class(tok):
    c = tok[:1]
    return 2 if c in GOOD_ONSET else 1 if c in OKAY_ONSET else 0


def risky_onset(nl, k):
    """In-speech onset at word k likely to carry the previous word's tail.
    Provisional rule fitted on 26 cuts (3 leaked): shallow gap dip, or a short
    previous word with a moderate dip. Recalibrate with listening verdicts."""
    d = nl.bounds[k]["depth_db"]
    return d > -10 or (len(nl.words[k - 1]["tok"]) <= 3 and d > -25)


def ok_cut(ix, k):
    """A cut inside speech before word k is acceptable: deep enough dip, and no
    short word right before it (whose tail would leak)."""
    b = ix.bounds[k]
    if b["kind"] == "pause":
        return True
    return b["depth_db"] <= OK_DEPTH and not risky_onset(ix, k)


def is_long(clip):
    """Too long to recall from an English cue (speech length, without cut margins)."""
    return len(clip["tokens"]) > LONG_WORDS or clip.get("speech_s", clip["end"] - clip["start"]) > LONG_SECS


def part_clip(src, lang, a, b, first, last):
    """Clip for words a..b of a longer span; inner edges are cut inside speech."""
    c = src.clip(lang, a, b, onset=not first)
    c["fade_in"] = 0.04 if first or c["start_kind"] == "pause" else 0.01
    end_in_speech = not last and src.idx[lang].bounds[b + 1]["kind"] != "pause"
    c["fade_out"] = 0.01 if end_in_speech else 0.04
    c["planned_end"] = end_in_speech
    return c


def cue(src, p):
    """English cue: the audiobook span when given and cleanly cuttable (inner
    edges may be cut inside speech at a checked boundary), else a Piper
    reading of the gloss."""
    if p.get("en_book"):
        c, d = src.en_range(*p["en_book"])
        en = src.idx["en"]
        if ok_cut(en, c) and ok_cut(en, d + 1):
            clip = part_clip(src, "en", c, d, en.bounds[c]["kind"] == "pause", en.bounds[d + 1]["kind"] == "pause")
            if not severe(clip, onset_ok=True, end_ok=True):
                return clip
    if p.get("gloss"):
        return tts(p["gloss"])
    return None


def buildup(src, a, b):
    """Suffix pieces ~3, 6, 9 ... words of the item a..b. Start cuts prefer a
    real pause, then a good consonant onset; risky in-speech onsets are never
    used (the piece length is skipped instead)."""
    nl = src.idx["nl"]
    n = b - a + 1
    if n < 6:
        return []
    pieces, L = [], 3
    while L < n - 1:
        best = None
        for k in range(max(a + 1, b - L - 1), min(b, b - L + 2)):
            if nl.bounds[k]["kind"] == "pause":
                score = 3
            elif risky_onset(nl, k):
                continue
            else:
                score = onset_class(nl.words[k]["tok"])
            score -= 0.1 * abs((b - k + 1) - L)
            if best is None or score > best[0]:
                best = (score, k)
        if best is None:
            L += 3
            continue
        k = best[1]
        if not pieces or k < pieces[-1]["first"]:
            c = src.clip("nl", k, b, onset=True)
            c["fade_in"] = 0.04 if c["start_kind"] == "pause" else 0.01
            pieces.append(c)
        L += 3
    return pieces


def make_parts(src, item_id, unit, parts, a, b):
    """Parts of a long clause (book ranges in `parts`), each drilled like an item,
    plus buildup suffixes that start at the part boundaries."""
    out, starts = [], []
    for n, pt in enumerate(parts):
        pa, pb = src.nl_range(*pt["nl_book"])
        first, last = n == 0, n == len(parts) - 1
        if not first and not ok_cut(src.idx["nl"], pa):
            raise ValueError(f"{item_id}: part {n + 1} starts at an unsafe cut")
        nl = part_clip(src, "nl", pa, pb, first, last)
        out.append(dict(id=f"{item_id}.{n + 1}", kind="part", parent=item_id, unit=unit, nl=nl,
                        en=cue(src, pt), gloss=pt.get("gloss"), pieces=[],
                        words=dict(nl=[pa, pb]), book=dict(nl=pt["nl_book"], en=pt.get("en_book"))))
        starts.append(pa)
    suffixes = []
    for k in reversed(starts[1:]):
        c = src.clip("nl", k, b, onset=True)
        c["fade_in"] = 0.01 if c["start_kind"] == "onset" else 0.04
        suffixes.append(c)
    return out, suffixes


def resolve_item(src, it):
    a, b = src.nl_range(*it["nl_book"])
    d = dict(id=it["id"], unit=it["unit"], nl=src.clip("nl", a, b), words=dict(nl=[a, b]),
             book=dict(nl=it["nl_book"], en=it.get("en_book"), **({"gloss": it["gloss"]} if it.get("gloss") else {})),
             backfill=it.get("backfill", False))
    if it.get("parts"):
        d["parts"], d["pieces"] = make_parts(src, it["id"], it["unit"], it["parts"], a, b)
        d["book"]["parts"] = it["parts"]
        d["en"], d["long"] = None, True
        return d
    if it.get("en_book"):
        c, e = src.en_range(*it["en_book"])
        d["words"]["en"] = [c, e]
        d["en"] = cue(src, it) or tts(it.get("gloss") or " ".join(src.clip("en", c, e)["tokens"]))
    else:
        d["en"] = tts(it["gloss"])  # no audiobook equivalent: literal gloss
    d["pieces"] = buildup(src, a, b)
    d["long"] = is_long(d["nl"])
    return d


def resolve(src, spec):
    items = [resolve_item(src, it) for it in spec["items"]]
    sents = []
    for u in spec["sentences"]:
        a, b = src.unit_range("nl", u)
        c, d = src.unit_range("en", u)
        nl = src.clip("nl", a, b)
        sents.append(dict(id=f"S{u}", unit=u, nl=nl, en=src.clip("en", c, d), pieces=[], long=is_long(nl)))
    return items, sents


def find_frames(src):
    """Cleanest standalone take of each frame phrase in the Pimsleur index."""
    p_idx = src.idx["pims"]
    w = [x["tok"] for x in p_idx.words]
    found = {}
    for key, phrase in FRAMES.items():
        p = phrase.split()
        best = None
        for i in range(1, len(w) - len(p)):
            if w[i:i + len(p)] != p:
                continue
            j = i + len(p) - 1
            before, after = p_idx.bounds[i]["pause"], p_idx.bounds[j + 1]["pause"]
            if before < 0.2 or after < MIN_PAUSE:
                continue
            score = min(before, 0.5) + min(after, 0.5) + np.mean([x["score"] for x in p_idx.words[i:j + 1]])
            if best is None or score > best[0]:
                best = (score, i, j)
        if best:
            found[key] = src.clip("pims", best[1], best[2])
    return found


def tts(text):
    from piper import PiperVoice
    path = WORK / "tts" / ("tts_" + re.sub(r"\W+", "_", text.lower()).strip("_") + ".wav")
    if not path.exists():
        with wave.open(str(path), "wb") as w:
            PiperVoice.load(str(VOICE)).synthesize_wav(text, w)
    return dict(src="tts", path=str(path), text=text, id=f"tts|{text}", risk=[], tokens=text.lower().split())


def gate(src, bank, items, sents, frames):
    """Keep what is usable. NL target unusable -> drop item (no Dutch TTS);
    EN cue unusable -> English TTS; buildup piece -> drop; frame -> TTS."""
    kept, dropped = [], []
    for it in items + sents:
        bad = severe(it["nl"]) + (["user:fail"] if bank.verdict(it["nl"]["id"]) == "fail" else [])
        if bad:
            dropped.append((it["id"], "nl", bad))
            continue
        if it.get("parts"):
            ok = [pt for pt in it["parts"] if bank.verdict(pt["nl"]["id"]) != "fail"]
            if len(ok) < len(it["parts"]):
                dropped.append((it["id"], "parts", len(it["parts"]) - len(ok)))
            for pt in ok:
                if pt["en"] is None or (pt["en"]["src"] != "tts" and bank.verdict(pt["en"]["id"]) == "fail"):
                    pt["en"] = tts(pt.get("gloss") or " ".join(pt["nl"]["tokens"]))
            it["parts"] = ok
        elif it["en"]["src"] != "tts" and (severe(it["en"]) or bank.verdict(it["en"]["id"]) == "fail"):
            it["en_audiobook"] = it["en"]
            it["en"] = tts(" ".join(it["en"]["tokens"]))
        before = len(it["pieces"])
        it["pieces"] = [p for p in it["pieces"] if not severe(p, onset_ok=True) and bank.verdict(p["id"]) != "fail"]
        if len(it["pieces"]) < before:
            dropped.append((it["id"], "pieces", before - len(it["pieces"])))
        kept.append(it)
    for k in FALLBACK:
        f = frames.get(k)
        if f is None or severe(f) or bank.verdict(f["id"]) == "fail":
            frames[k] = tts(FALLBACK[k])
    return ([i for i in kept if any(i is x for x in items)], [i for i in kept if any(i is x for x in sents)],
            dropped)


# ---- scheduler ----

def seg(clip, kind, item=None):
    return dict(clip=clip, kind=kind, item=item)


def sil(d):
    return dict(silence=round(d, 2))


def dur(c):
    if "silence" in c:
        return c["silence"]
    c = c["clip"]
    if c["src"] == "tts":
        with wave.open(c["path"]) as w:
            return w.getnframes() / w.getframerate()
    return c["end"] - c["start"]


def intro_block(it, frames, first):
    d = it["nl"]["end"] - it["nl"]["start"]
    b = [seg(frames["how"], "frame"), sil(0.3), seg(it["en"], "en_cue", it["id"]), sil(ant_pause(d)),
         seg(it["nl"], "nl_target", it["id"]), sil(rep_pause(d))]
    if it["pieces"]:
        b += [seg(frames["repeat"], "frame"), sil(0.5)]
        for p in it["pieces"]:
            b += [seg(p, "buildup", it["id"]), sil(rep_pause(p["end"] - p["start"]))]
        b += [seg(it["nl"], "nl_target", it["id"]), sil(rep_pause(d))]
    elif first:
        b += [seg(frames["repeat"], "frame"), sil(0.5), seg(it["nl"], "nl_target", it["id"]), sil(rep_pause(d))]
    return b


def recall_block(it, frames, level):
    d = it["nl"]["end"] - it["nl"]["start"]
    frame = frames["remember"] if level >= 2 else frames["how"]
    return [seg(frame, "frame"), sil(0.3), seg(it["en"], "en_cue", it["id"]), sil(ant_pause(d)),
            seg(it["nl"], "nl_target", it["id"]), sil(rep_pause(d))]


def part_block(pt, frames):
    """First drill of a part: cue -> say it -> narrator -> repeat, twice."""
    d = pt["nl"]["end"] - pt["nl"]["start"]
    return [seg(frames["how"], "frame"), sil(0.3), seg(pt["en"], "en_cue", pt["id"]), sil(ant_pause(d)),
            seg(pt["nl"], "nl_target", pt["id"]), sil(rep_pause(d)), seg(pt["nl"], "nl_target", pt["id"]),
            sil(rep_pause(d))]


def whole_block(it, frames):
    """A long clause after its parts: built up from the part boundaries, then whole."""
    b = [seg(frames["repeat"], "frame"), sil(0.5)]
    for p in it["pieces"]:
        b += [seg(p, "buildup", it["id"]), sil(rep_pause(p["end"] - p["start"]))]
    d = it["nl"]["end"] - it["nl"]["start"]
    return b + [seg(it["nl"], "nl_target", it["id"]), sil(rep_pause(d))]


def repeat_block(it, frames):
    """Repeat-only recall of a long clause: narrator, then your turn (no cue)."""
    d = it["nl"]["end"] - it["nl"]["start"]
    return [seg(frames["repeat"], "frame"), sil(0.5), seg(it["nl"], "repeat_only", it["id"]), sil(rep_pause(d) + 0.5)]


def block_len(b):
    return sum(dur(c) for c in b) + GAP * len([c for c in b if "clip" in c])


def combos(src, items, max_nl_s=10.0):
    """Recombination from human audio only: two consecutive items adjacent in
    both recordings, joined as one natural span (heading excluded)."""
    out, i = [], 0
    while i < len(items) - 1:
        a, b = items[i], items[i + 1]
        adjacent = a["unit"] > 0 and all(l in a["words"] and l in b["words"] and a["words"][l][1] + 1 == b["words"][l][0]
                                         for l in ("nl", "en"))
        plain = all(x.get("en") is not None and x["en"]["src"] != "tts" and not x.get("parts") for x in (a, b))
        if plain and adjacent and b["nl"]["end"] - a["nl"]["start"] <= max_nl_s:
            nl = src.clip("nl", a["words"]["nl"][0], b["words"]["nl"][1])
            en = src.clip("en", a["words"]["en"][0], b["words"]["en"][1])
            if not severe(nl) and not severe(en):
                out.append(dict(id=f"{a['id']}+{b['id']}", unit=b["unit"], after=b["id"], pieces=[], nl=nl, en=en,
                                book=dict(nl=[a["book"]["nl"][0], b["book"]["nl"][1]],
                                          en=[a["book"]["en"][0], b["book"]["en"][1]])))
                i += 2
                continue
        i += 1
    return out


def schedule(items, sents, frames, passage, k, combo=(), reviews=()):
    """Greedy timeline: due recalls first, otherwise the next new item.
    reviews (items from earlier lessons): recalled right after the opening
    passage and again ~10 min later. Long material (with parts, or longer than
    LONG_*) is recalled repeat-only; parts are recalled with their cues."""
    chosen = items[:k]
    ids = {it["id"] for it in chosen}
    complete = {it["unit"] for it in chosen if all(o in chosen for o in items if o["unit"] == it["unit"])}
    extras = {}
    for s in sents:
        if s["unit"] in complete:
            last = [it["id"] for it in chosen if it["unit"] == s["unit"]][-1]
            extras.setdefault(last, []).append(s)
    for c in combo:
        if all(x in ids for x in c["id"].split("+")):
            extras.setdefault(c["after"], []).append(c)
    queue = []
    for i, it in enumerate(chosen):
        if it.get("parts"):
            queue += [("part", pt, False) for pt in it["parts"]] + [("whole", it, False)]
        else:
            queue.append(("intro", it, i == 0))
        queue += [("sentence", e, False) for e in extras.get(it["id"], [])]
    timeline = [sil(0.5), seg(passage, "passage"), sil(2.0)]
    t = block_len(timeline)
    pending = []  # (due, item, level, mode)
    for r in reviews:
        if r.get("parts"):
            pending += [(t, pt, 2, "cue") for pt in r["parts"]] + [(t, r, 2, "repeat"), (t + 600, r, 3, "repeat")]
        else:
            mode = "repeat" if r.get("long") else "cue"
            pending += [(t, r, 2, mode), (t + 600, r, 3, mode)]
    while queue or pending:
        pending.sort(key=lambda p: p[0])
        if pending and (pending[0][0] <= t + DUE_SLACK or not queue):
            due, it, level, mode = pending.pop(0)
            b = repeat_block(it, frames) if mode == "repeat" else recall_block(it, frames, level)
        else:
            kind, it, first = queue.pop(0)
            if kind == "part":
                b, levels, mode = part_block(it, frames), PART_INTERVALS, "cue"
            elif kind == "whole":
                b, levels, mode = whole_block(it, frames), WHOLE_INTERVALS, "repeat"
            elif kind == "sentence" and it.get("long"):
                b, levels, mode = repeat_block(it, frames), INTERVALS[2:3], "repeat"
            else:
                b = intro_block(it, frames, first)
                levels = INTERVALS if kind == "intro" else INTERVALS[2:3]
                mode = "repeat" if it.get("long") else "cue"
            end = t + block_len(b)
            pending += [(end + iv, it, lv, mode) for lv, iv in enumerate(levels)]
        timeline += b
        t += block_len(b)
    timeline += [sil(2.5), seg(passage, "passage"), sil(1.0)]
    return timeline, t + block_len(timeline[-3:])


# ---- render (pure assembly) ----

def render(src, timeline, out, name):
    files = {k: v.local for k, v in src.idx.items()}
    cache, by_src, heard = {}, {}, {}
    for c in timeline:
        if "clip" in c:
            heard[c["clip"]["id"]] = heard.get(c["clip"]["id"], 0) + 1
        if "clip" not in c or c["clip"]["id"] in cache:
            continue
        cl = c["clip"]
        if cl["src"] == "tts":
            with wave.open(cl["path"]) as w:
                x = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
                fr = w.getframerate()
            x = np.interp(np.arange(0, len(x), fr / build.OUT_SR), np.arange(len(x)), x).astype(np.float32)
        else:
            x = build.clip(files[cl["src"]], cl["start"], cl["end"], fade_in=cl.get("fade_in", build.FADE),
                           fade_out=cl.get("fade_out", build.FADE))
        cache[cl["id"]] = x
        by_src.setdefault(cl["src"], []).append(cl["id"])
    gains = {}
    for s, keys in by_src.items():
        xs, g = build.match_loudness([cache[k] for k in keys], weights=[heard[k] for k in keys])
        cache.update(zip(keys, xs))
        gains[s] = round(g, 1)
    parts, pos, sidecar = [], 0, []
    gap = np.zeros(int(GAP * build.OUT_SR), np.float32)
    for c in timeline:
        if "silence" in c:
            x = np.zeros(int(c["silence"] * build.OUT_SR), np.float32)
        else:
            cl = c["clip"]
            x = np.concatenate([cache[cl["id"]], gap])
            sidecar.append(dict(t=round(pos / build.OUT_SR, 2), kind=c["kind"], item=c["item"], source=cl["src"],
                                clip_id=cl["id"], file=src.idx[cl["src"]].drive_path if cl["src"] in src.idx
                                else "piper:" + cl["text"], start=cl.get("start"), end=cl.get("end"),
                                risk=cl.get("risk", []), start_kind=cl.get("start_kind")))
        parts.append(x)
        pos += len(x)
    build.encode_mp3(np.concatenate(parts), out / f"{name}.mp3")
    return sidecar, gains, pos / build.OUT_SR


def coverage(timeline):
    secs = {}
    for c in timeline:
        if "clip" in c:
            k = f"{c['kind']}/{c['clip']['src']}"
            secs[k] = round(secs.get(k, 0) + dur(c), 1)
    return dict(sorted(secs.items()))


def listen_check(src, timeline, bank, out, name):
    """Every clip of this lesson the index cannot vouch for and no listener has
    judged yet (needs_ear), twice each; verdicts go to the span bank."""
    seen, pieces = set(), []
    for c in timeline:
        cl = c.get("clip")
        if not cl or cl["src"] == "tts" or cl["id"] in seen:
            continue
        seen.add(cl["id"])
        why = needs_ear(cl)
        if why and bank.verdict(cl["id"]) is None and not bank.listed_elsewhere(cl["id"], name):
            pieces.append((c["item"] or c["kind"], cl, why))
    if not pieces:
        return 0
    clips = [build.clip(src.idx[p["src"]].local, p["start"], p["end"], fade_in=p.get("fade_in", build.FADE))
             for _, p, _ in pieces]
    clips = [x * 10 ** ((-18 - build.lufs(x)) / 20) if len(x) > build.OUT_SR // 2 else x for x in clips]
    g1, g2 = np.zeros(int(0.8 * build.OUT_SR), np.float32), np.zeros(int(1.8 * build.OUT_SR), np.float32)
    parts, rows, pos = [], [], 0
    for (iid, p, why), x in zip(pieces, clips):
        rows.append(dict(n=len(rows) + 1, t=round(pos / build.OUT_SR, 1), item=iid, source=p["src"],
                         clip_id=p["id"], start=p["start"], end=p["end"], why=why))
        for y in (x, g1, x, g2):
            parts.append(y)
            pos += len(y)
    build.encode_mp3(np.concatenate(parts), out / f"{name}_listen_check.mp3")
    (out / f"{name}_listen_check.json").write_text(json.dumps(rows, indent=1))
    for _, p, _ in pieces:
        bank.list_for(p["id"], name)
    return len(pieces)


def resolve_reviews(src, learner, day, chapter, resplit=None):
    """Items from earlier lessons that are due, rebuilt from their book ranges.
    resplit: id -> parts, for long items that were taught whole."""
    out = []
    for key in learner.due(day):
        d = learner.state["items"][key]
        if not key.startswith(chapter + ":"):
            continue
        iid = key.split(":", 1)[1]
        parts = (resplit or {}).get(iid) or d.get("parts")
        if parts:
            r = resolve_item(src, dict(id=iid, unit=d["unit"], nl_book=d["nl_book"], en_book=d.get("en_book"),
                                       parts=parts))
        elif d["kind"] == "sentence":
            a, b = src.unit_range("nl", d["unit"])
            c, e = src.unit_range("en", d["unit"])
            nl = src.clip("nl", a, b)
            r = dict(id=iid, unit=d["unit"], nl=nl, en=src.clip("en", c, e), pieces=[], long=is_long(nl))
        else:
            r = resolve_item(src, dict(id=iid, unit=d["unit"], nl_book=d["nl_book"], en_book=d["en_book"],
                                       **({"gloss": d["gloss"]} if d.get("gloss") else {})))
            r["pieces"] = []
        r["key"] = key
        out.append(r)
    return out


def defs_of(chapter, things, kind):
    out = {}
    for t in things:
        bk = t.get("book", {})
        out[f"{chapter}:{t['id']}"] = dict(kind=kind, unit=t["unit"], nl_book=bk.get("nl"), en_book=bk.get("en"),
                                           **({"parts": bk["parts"]} if bk.get("parts") else {}),
                                           **({"gloss": bk["gloss"]} if bk.get("gloss") else {}))
    return out


def uncovered(src, learner, chapter):
    """NL book tokens of the units reached so far that no taught item covers."""
    items = [d for k, d in learner.state["items"].items() if k.startswith(chapter + ":") and d["kind"] == "item"]
    if not items:
        return []
    last_unit = max(d["unit"] for d in items)
    covered = set()
    for d in items:
        covered.update(range(d["nl_book"][0], d["nl_book"][1] + 1))
    gaps, cur = [], None
    for u in range(last_unit + 1):
        a, b = src.unit_range("nl", u)
        for w in src.idx["nl"].words[a:b + 1]:
            bi = w.get("book_i")
            if bi is None:
                continue
            if bi in covered:
                cur = None
            elif cur and cur["book"][1] == bi - 1:
                cur["book"][1] = bi
                cur["words"] += 1
            else:
                cur = dict(unit=u, book=[bi, bi], words=1)
                gaps.append(cur)
    return gaps


def main(spec_path, out, name=None):
    from .learner import Learner
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    spec = json.loads(Path(spec_path).read_text())
    name = name or spec.get("lesson", "lesson01")
    chapter, day = spec.get("chapter", "ch01"), spec.get("day", 1)
    src = Sources(chapter)
    bank = SpanBank(WORK / "bank/spans.jsonl")
    learner = Learner()
    items, sents = resolve(src, spec)
    frames = find_frames(src)
    items, sents, dropped = gate(src, bank, items, sents, frames)
    resplit = spec.get("resplit", {})
    reviews, _, r_dropped = gate(src, bank, resolve_reviews(src, learner, day, chapter, resplit), [], frames)
    dropped += r_dropped
    sent_spans = {s["nl"]["id"] for s in sents}
    combo = [c for c in combos(src, items) if c["nl"]["id"] not in sent_spans]  # same span as a sentence drill
    best = None
    for k in range(len(items), 0, -1):
        new = [it for it in items[:k] if not it.get("backfill")] or items[:k]
        last = src.unit_range("nl", new[-1]["unit"])[1]
        passage = src.clip("nl", src.unit_range("nl", new[0]["unit"])[0], last)
        tl, length = schedule(items, sents, frames, passage, k, combo, reviews)
        if length <= (spec["minutes"] + spec.get("tolerance_min", 0.5)) * 60:
            best = (k, tl, length)
            break
    k, tl, length = best
    taught = {c["item"] for c in tl if c.get("item")} | {c["item"].split(".")[0] for c in tl if c.get("item")}
    new_items = [it for it in items[:k]]
    new_combos = [c for c in combo if c["id"] in taught]
    new_sents = [s for s in sents if s["id"] in taught]
    learner.record(name, day,
                   introduced=[f"{chapter}:{t['id']}" for t in new_items + new_combos + new_sents],
                   reviewed=[r["key"] for r in reviews if r["id"] in taught],
                   defs={**defs_of(chapter, new_items, "item"), **defs_of(chapter, new_combos, "combo"),
                         **defs_of(chapter, new_sents, "sentence"),
                         **defs_of(chapter, [r for r in reviews if r["id"] in resplit], "item")})
    sidecar, gains, secs = render(src, tl, out, name)
    rep = dict(lesson=name, day=day, items=[it["id"] for it in items[:k]],
               reviews=[r["id"] for r in reviews], recombinations=[c["id"] for c in new_combos + new_sents],
               minutes=round(secs / 60, 2), gains_db=gains,
               coverage_s=coverage(tl), frames={kk: v["src"] for kk, v in frames.items()}, dropped=dropped,
               en_cues_tts=sorted({c["item"] for c in tl if c.get("kind") == "en_cue" and c["clip"]["src"] == "tts"}),
               parts={it["id"]: len(it["parts"]) for it in items[:k] + reviews if it.get("parts")},
               uncovered=uncovered(src, learner, chapter),
               index_versions={kk: v.version for kk, v in src.idx.items()})
    (out / f"{name}.json").write_text(json.dumps(dict(report=rep, timeline=sidecar), ensure_ascii=False, indent=1))
    rep["listen_check_clips"] = listen_check(src, tl, bank, out, name)
    print(json.dumps(rep, indent=1))
    return rep


def chunk_view(src, unit):
    """Pause-bounded chunks of a unit in both languages, with book-token ranges
    (for the item-selection step; prints book text to the console only)."""
    out = {}
    for lang in ("nl", "en"):
        ix = src.idx[lang]
        a, b = src.unit_range(lang, unit)
        chunks, cur = [], []
        for k in range(a, b + 1):
            cur.append(k)
            if ix.bounds[k + 1]["pause"] >= CHUNK_PAUSE or k == b:
                chunks.append(cur)
                cur = []
        rows = []
        for c in chunks:
            bi = [ix.words[k]["book_i"] for k in c if ix.words[k].get("book_i") is not None]
            rows.append(dict(book=[min(bi), max(bi)] if bi else None, words=len(c),
                             secs=round(ix.words[c[-1]]["e"] - ix.words[c[0]]["s"], 1),
                             text=" ".join(ix.words[k]["tok"] for k in c)))
        out[lang] = rows
    return out


if __name__ == "__main__":
    if sys.argv[1] == "view":  # python -m batkol.lesson view FIRST_UNIT LAST_UNIT
        s = Sources()
        for u in range(int(sys.argv[2]), int(sys.argv[3]) + 1):
            v = chunk_view(s, u)
            print(f"--- unit {u}")
            for lang in ("nl", "en"):
                for i, r in enumerate(v[lang]):
                    print(f"  {lang}[{i}] {r['book']} {r['words']}w {r['secs']}s | {r['text']}")
    else:
        main(*sys.argv[1:])
