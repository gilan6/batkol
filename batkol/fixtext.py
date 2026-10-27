"""Repair OCR text (base) using a second edition (ref) plus a reviewed fix list.

- Dash tokens present in ref but missing in base are restored.
- fixes.tsv (kept outside git): `old<TAB>new` token sequences; each `old` must
  occur exactly once in base.
"""
import difflib
import re
import sys
from pathlib import Path

PUNCT = re.compile(r"[‘’'“”\"–—\-.,;:!?…()]")
DASH_ONLY = re.compile(r"^[–—]['’]?$")


def norm(tok):
    return PUNCT.sub("", tok.lower())


def restore_dashes(base, ref):
    """base/ref: lists of paragraphs. Returns (paragraphs, n_inserted)."""
    btoks = [(pi, t) for pi, p in enumerate(base) for t in p.split()]
    rtoks = [t for p in ref for t in p.split()]
    sm = difflib.SequenceMatcher(None, [norm(t) for t in rtoks], [norm(t) for _, t in btoks], autojunk=False)
    inserts = {}  # base token index -> dash tokens to put before it
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "delete" and all(DASH_ONLY.match(t) for t in rtoks[i1:i2]):
            inserts[j1] = [t.replace("’", "'") for t in rtoks[i1:i2]]
    out = [[] for _ in base]
    for j, (pi, t) in enumerate(btoks):
        # attach to the paragraph of the preceding token (dash ends a clause)
        if j in inserts:
            out[btoks[j - 1][0] if j else pi].extend(inserts[j])
        out[pi].append(t)
    return [" ".join(p) for p in out], sum(len(v) for v in inserts.values())


def apply_fixes(paras, fixes_path):
    text = "\n".join(paras)
    applied = 0
    for line in Path(fixes_path).read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        old, new = line.split("\t")
        pat = re.compile(r"(?<!\S)" + re.escape(old) + r"(?!\S)")
        hits = len(pat.findall(text))
        if hits != 1:
            raise SystemExit(f"fix {old!r}: expected 1 match, found {hits}")
        text = pat.sub(lambda _: new, text)
        applied += 1
    return text.split("\n"), applied


if __name__ == "__main__":
    base_p, ref_p, fixes_p, out_p = sys.argv[1:5]
    base = Path(base_p).read_text().splitlines()
    ref = Path(ref_p).read_text().splitlines()
    paras, n_dash = restore_dashes(base, ref)
    paras, n_fix = apply_fixes(paras, fixes_p)
    Path(out_p).write_text("\n".join(paras) + "\n")
    print(f"{out_p}: {n_dash} dashes restored, {n_fix} fixes applied, {len(paras)} paras")
