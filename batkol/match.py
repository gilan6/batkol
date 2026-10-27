"""Map book sentences onto spoken tokens (EN: cast audio drifts from the book)."""
import difflib

from rapidfuzz import fuzz

FUZZY_MIN = 75  # misheard words recovered from gaps ("shoot" for "shoo")


def assign(book_tok_sent, book_toks, hyp_toks, hyp_times, max_insert=3, strict=None):
    """Give each spoken token the id of the book sentence it belongs to (or None).

    equal/replace blocks map positionally; short insertions attach to the
    time-nearest neighbour; long insertions and anything before the first or
    after the last matched token stay unassigned (credits, cast additions).
    """
    sm = difflib.SequenceMatcher(None, book_toks, hyp_toks, autojunk=False)
    ops = sm.get_opcodes()
    sent = [None] * len(hyp_toks)
    matched = [False] * len(book_toks)
    first_eq = next(j1 for op, _, _, j1, _ in ops if op == "equal")
    last_eq = max(j2 for op, _, _, _, j2 in ops if op == "equal")
    inserts = []
    confident = set()  # spoken tokens with an exact or near-exact book counterpart
    for op, i1, i2, j1, j2 in ops:
        if op == "equal":
            for k in range(i2 - i1):
                sent[j1 + k] = book_tok_sent[i1 + k]
                matched[i1 + k] = True
                confident.add(j1 + k)
        elif op == "replace" and first_eq <= j1 and j2 <= last_eq:
            for k in range(j2 - j1):
                bi = i1 + k * (i2 - i1) // (j2 - j1)
                sent[j1 + k] = book_tok_sent[bi]
                if fuzz.ratio(hyp_toks[j1 + k], book_toks[bi]) >= FUZZY_MIN:
                    confident.add(j1 + k)
        elif op == "insert" and first_eq <= j1 and j2 <= last_eq and j2 - j1 <= max_insert:
            inserts.append((j1, j2))
    for j1, j2 in inserts:
        prev_s, next_s = sent[j1 - 1], sent[j2] if j2 < len(sent) else None
        gap_prev = hyp_times[j1][0] - hyp_times[j1 - 1][1]
        gap_next = hyp_times[j2][0] - hyp_times[j2 - 1][1] if j2 < len(sent) else 1e9
        for k in range(j1, j2):
            sent[k] = prev_s if gap_prev <= gap_next else next_s
    if strict:  # e.g. gap re-transcriptions: keep only (near-)exact book matches
        sent = [s if not strict[j] or j in confident else None for j, s in enumerate(sent)]
    return sent, matched
