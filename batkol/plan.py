"""Chapter plan: every drill item of a chapter, chosen once.

Per unit (NL<->EN sentence group), the pause-bounded chunks of both languages
are aligned monotonically: groups of 1-3 NL chunks to 1-4 EN chunks, scored by
LaBSE similarity (the same DP shape as sentence pairing). A group becomes an
item when its NL side is 2-18 words / <= 7 s and the pairing is credible;
everything else stays passage-only. Items are stored as book-token ranges (no
text). Hand-picked items in lesson specs override the automatic ones for their
units. Lessons then just take the next untaught items in chapter order.

Run (needs the analysis extra, once per chapter):
  uv run python -m batkol.plan build ch01      -> batkol/lessons/ch01_plan.json
  uv run python -m batkol.plan compare ch01    -> agreement with hand-picked items
"""
import json
import sys
from pathlib import Path

import numpy as np

from .lesson import Sources, chunk_view

LESSONS = Path(__file__).parent / "lessons"
MAX_NL, MAX_EN = 3, 4         # chunks per group
BASE = 0.5                    # a pair scores its similarity above this: splitting pays only when both halves translate
MERGE_PENALTY = 0.1           # per extra NL chunk in a group
MERGE_EN = 0.02               # per extra EN chunk (an EN chunk joins the cue unless it lowers similarity)
SKIP_NL = 0.3                 # NL chunk left unpaired (passage only)
SKIP_EN = 0.05                # EN chunk left out of every cue (cast lines often have no NL counterpart)
SMALL = 0.6                   # < 3-word NL group or skipped chunk: it should join a neighbour
MIN_WORDS, MAX_WORDS, MAX_SECS = 2, 18, 7.0
OK_SIM, LOOSE_SIM = 0.5, 0.4
SENTENCE_MAX_S = 12.0


def unit_chunks(src, unit):
    v = chunk_view(src, unit)
    return [c for c in v["nl"] if c["book"]], [c for c in v["en"] if c["book"]]


def skip_cost(chunk, lang):
    small = chunk["words"] < 3
    return SKIP_NL + (SMALL if small else 0.0) if lang == "nl" else SKIP_EN + (SMALL / 2 if small else 0.0)


def align_unit(nl, en, emb):
    """Monotonic n:m alignment of chunk groups. emb(lang, i, k) -> unit vector."""
    N, M = len(nl), len(en)
    best = np.full((N + 1, M + 1), -np.inf)
    best[0, 0] = 0.0
    back = {}
    for i in range(N + 1):
        for j in range(M + 1):
            if best[i, j] == -np.inf:
                continue
            moves = [(a, b) for a in range(1, MAX_NL + 1) for b in range(1, MAX_EN + 1)] + [(1, 0), (0, 1)]
            for a, b in moves:
                ni, nj = i + a, j + b
                if ni > N or nj > M:
                    continue
                if a and b:
                    sim = float(emb("nl", i, a) @ emb("en", j, b))
                    s = sim - BASE - MERGE_PENALTY * (a - 1) - MERGE_EN * (b - 1)
                    if sum(c["words"] for c in nl[i:i + a]) < 3:
                        s -= SMALL
                else:
                    sim, s = None, -(skip_cost(nl[i], "nl") if a else skip_cost(en[j], "en"))
                if best[i, j] + s > best[ni, nj]:
                    best[ni, nj] = best[i, j] + s
                    back[(ni, nj)] = (i, j, a, b, sim)
    groups, ij = [], (N, M)
    while ij != (0, 0):
        i, j, a, b, sim = back[ij]
        groups.append((i, a, j, b, sim))
        ij = (i, j)
    return groups[::-1]


def embeddings(chapter, texts):
    """LaBSE vectors for the candidate group texts, cached (npz + key list)."""
    path = Path.home() / "work" / chapter / "plan_embeddings.npz"
    keys = list(texts)
    if path.exists():
        z = np.load(path, allow_pickle=True)
        cached = dict(zip([tuple(k) for k in z["keys"]], z["vecs"]))
        if all(k in cached for k in keys):
            return cached
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer("sentence-transformers/LaBSE", device="cpu")
    vecs = model.encode([texts[k] for k in keys], batch_size=64, normalize_embeddings=True, show_progress_bar=False)
    np.savez(path, keys=np.array(keys, dtype=object), vecs=vecs)
    return dict(zip(keys, vecs))


def build(chapter):
    src = Sources(chapter)
    units = range(len(src.units))
    chunks = {u: unit_chunks(src, u) for u in units}
    # embed every candidate group text once
    texts = {}
    for u, (nl, en) in chunks.items():
        for lang, cs, mx in (("nl", nl, MAX_NL), ("en", en, MAX_EN)):
            for i in range(len(cs)):
                for k in range(1, mx + 1):
                    if i + k <= len(cs):
                        texts[(u, lang, i, k)] = " ".join(c["text"] for c in cs[i:i + k])
    E = embeddings(chapter, texts)
    items, sentences = [], []
    for u in units:
        nl, en = chunks[u]
        if not nl or not en:
            continue
        unit_items = []
        groups = [g for g in align_unit(nl, en, lambda lang, s, k, u=u: E[(u, lang, s, k)]) if g[1] and g[3]]
        if groups:
            # units are sentence-aligned: a pair holding the unit's first (last) NL chunk
            # gets the unit's first (last) EN chunks as well
            i, a, j, b, sim = groups[0]
            if i == 0 and j > 0:
                groups[0] = (i, a, 0, b + j, sim)
            i, a, j, b, sim = groups[-1]
            if i + a == len(nl) and j + b < len(en):
                groups[-1] = (i, a, j, len(en) - j, sim)
        for i, a, j, b, sim in groups:
            g_nl, g_en = nl[i:i + a], en[j:j + b]
            words = sum(c["words"] for c in g_nl)
            secs = round(sum(c["secs"] for c in g_nl), 1)
            item = dict(id=f"u{u:03d}.{len(unit_items) + 1}", unit=u,
                        nl_book=[g_nl[0]["book"][0], g_nl[-1]["book"][1]],
                        en_book=[g_en[0]["book"][0], g_en[-1]["book"][1]],
                        sim=round(sim, 3), words=words, secs=secs)
            if words < MIN_WORDS or words > MAX_WORDS or secs > MAX_SECS or sim < LOOSE_SIM:
                continue  # passage only
            if sim < OK_SIM:
                item["equivalence"] = "loose"
            unit_items.append(item)
        items += unit_items
        nl_secs = src.idx["nl"].words[src.unit_range("nl", u)[1]]["e"] - src.idx["nl"].words[src.unit_range("nl", u)[0]]["s"]
        if len(unit_items) >= 2 and nl_secs <= SENTENCE_MAX_S:
            sentences.append(u)
    return dict(chapter=chapter, items=items, sentences=sentences)


def manual_items(chapter):
    """Hand-picked items of the existing lesson specs (they override the plan)."""
    out, sents = {}, set()
    for p in sorted(LESSONS.glob("lesson*.json")):
        spec = json.loads(p.read_text())
        if spec.get("chapter", "ch01") != chapter:
            continue
        for it in spec["items"]:
            out[it["id"]] = {k: it[k] for k in ("id", "unit", "nl_book", "en_book")} | (
                {"equivalence": it["equivalence"]} if "equivalence" in it else {})
        sents |= set(spec.get("sentences", []))
    return list(out.values()), sorted(sents)


def merge(auto, chapter):
    """Plan = hand-picked items for the units they cover + automatic items elsewhere."""
    man, man_sents = manual_items(chapter)
    covered = {it["unit"] for it in man}
    last_manual_unit = max(covered) if covered else -1
    items = sorted(man, key=lambda it: it["nl_book"][0]) + [it for it in auto["items"] if it["unit"] > last_manual_unit]
    sentences = sorted(set(man_sents) | {u for u in auto["sentences"] if u > last_manual_unit})
    return dict(chapter=chapter, comment="Drill items in chapter order as book-token ranges (no text). "
                "Hand-picked items (lesson specs) for units <= %d, automatic chunk pairing after that." % last_manual_unit,
                items=items, sentences=sentences)


def compare(auto, chapter):
    """Agreement of automatic items with the hand-picked ones on the units both cover."""
    man, _ = manual_items(chapter)
    units = {it["unit"] for it in man}
    a = [it for it in auto["items"] if it["unit"] in units]
    exact = sum(any(x["nl_book"] == m["nl_book"] and x["en_book"] == m["en_book"] for x in a) for m in man)
    nl_same = sum(any(x["nl_book"] == m["nl_book"] for x in a) for m in man)
    extra = [x for x in a if not any(x["nl_book"] == m["nl_book"] for m in man)]
    missing = [m for m in man if not any(x["nl_book"] == m["nl_book"] for x in a)]
    en_diff = [(m["id"], m["en_book"], x["en_book"], x["sim"]) for m in man for x in a
               if x["nl_book"] == m["nl_book"] and x["en_book"] != m["en_book"]]
    return dict(manual=len(man), auto=len(a), exact=exact, same_nl_span=nl_same, en_differs=en_diff,
                auto_only=[(x["id"], x["nl_book"], x["en_book"], x["sim"]) for x in extra],
                manual_only=[(m["id"], m["nl_book"], m["en_book"]) for m in missing])


if __name__ == "__main__":
    cmd, chapter = sys.argv[1], sys.argv[2]
    auto = build(chapter)
    if cmd == "compare":
        print(json.dumps(compare(auto, chapter), indent=1))
    elif cmd == "build":
        plan = merge(auto, chapter)
        (LESSONS / f"{chapter}_plan.json").write_text(json.dumps(plan, indent=1))
        print(f"{len(plan['items'])} items, {len(plan['sentences'])} sentence drills -> lessons/{chapter}_plan.json")
