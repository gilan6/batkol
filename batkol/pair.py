"""NL<->EN sentence alignment, n:m groups, LaBSE similarity + DP (bertalign-style)."""
import numpy as np

MOVES = [(1, 1), (1, 2), (2, 1), (2, 2), (1, 3), (3, 1), (1, 0), (0, 1)]
MERGE_PENALTY = 0.1  # per extra sentence in a group
SKIP_PENALTY = 0.3   # per unmatched sentence
SPLIT_MIN = 0.55     # 2:2 -> two 1:1 when both diagonal pairs are at least this similar


def span_embeddings(model, sents, max_n=3):
    keys, texts = [], []
    for i in range(len(sents)):
        for n in range(1, max_n + 1):
            if i + n <= len(sents):
                keys.append((i, n))
                texts.append(" ".join(sents[i:i + n]))
    emb = model.encode(texts, batch_size=32, normalize_embeddings=True, show_progress_bar=False)
    return dict(zip(keys, emb))


def align(nl, en, model):
    """nl, en: lists of sentence strings. Returns [(nl_ids, en_ids, sim)]."""
    enl, een = span_embeddings(model, nl), span_embeddings(model, en)
    N, M = len(nl), len(en)
    best = np.full((N + 1, M + 1), -np.inf)
    back = {}
    best[0, 0] = 0.0
    for i in range(N + 1):
        for j in range(M + 1):
            for n, m in MOVES:
                if i < n or j < m or best[i - n, j - m] == -np.inf:
                    continue
                if n and m:
                    sim = float(enl[(i - n, n)] @ een[(j - m, m)])
                    s = sim * (n + m) / 2 - MERGE_PENALTY * (n + m - 2)
                else:
                    sim, s = 0.0, -SKIP_PENALTY
                if best[i - n, j - m] + s > best[i, j]:
                    best[i, j] = best[i - n, j - m] + s
                    back[(i, j)] = (n, m, sim)
    groups, i, j = [], N, M
    while i or j:
        n, m, sim = back[(i, j)]
        groups.append((list(range(i - n, i)), list(range(j - m, j)), round(sim, 3)))
        i, j = i - n, j - m
    return split_diagonal(groups[::-1], enl, een)


def split_diagonal(groups, enl, een):
    """Concatenations score high on shared topic; prefer smaller drill units when
    the 2:2 group decomposes into two credible 1:1 pairs."""
    out = []
    for nids, eids, sim in groups:
        if len(nids) == 2 and len(eids) == 2:
            a = float(enl[(nids[0], 1)] @ een[(eids[0], 1)])
            b = float(enl[(nids[1], 1)] @ een[(eids[1], 1)])
            if min(a, b) >= SPLIT_MIN:
                out += [([nids[0]], [eids[0]], round(a, 3)), ([nids[1]], [eids[1]], round(b, 3))]
                continue
        out.append((nids, eids, sim))
    return out
