"""Cut chapter 1 text (heading .. next chapter heading) out of an EPUB."""
import re
import sys
from pathlib import Path

from .epub import spine_lines


# "HOOFDSTUK 1", "— CHAPTER ONE —", "ONE", "Hoofdstuk een De ergste verjaardag" (title on the
# heading line is split off); a bare digit is not a heading (page numbers in OCR editions)
def _heading(num):
    return re.compile(rf"^[—–-]?\s*(?:(?:hoofdstuk|chapter)\s+(?:{num})\b(?P<title>.*)|(?:{num.split('|', 1)[1]}))\s*[—–-]?$",
                      re.I)


START = _heading("1|een|one")
END = _heading("2|twee|two")
# Paragraphs split by page-layout line breaks: join when a line ends without
# terminal punctuation and the next one starts lowercase.
TERMINAL = tuple(".!?'\"’”–—-…:")


def chapter1(path):
    lines = [l for _, l in spine_lines(path)]
    # skip table of contents: take the first START with more than 20 lines before the next END
    # (else the longest such span: a short text)
    starts = [i for i, l in enumerate(lines) if START.match(l)]
    spans = [(s, next((j for j in range(s + 1, len(lines)) if END.match(lines[j])), None)) for s in starts]
    spans = [(s, e) for s, e in spans if e is not None]
    if not spans:
        raise SystemExit(f"chapter 1 not found in {path}: starts={starts}")
    s, e = next(((s, e) for s, e in spans if e - s > 20), max(spans, key=lambda x: x[1] - x[0]))
    m = START.match(lines[s])
    title = (m.group("title") or "").strip(" —–-")
    paras = [lines[s][:m.start("title")].strip(), title] if title else []
    for l in lines[s + bool(title):e]:
        if paras and not paras[-1].endswith(TERMINAL) and l[:1].islower():
            paras[-1] += " " + l
        else:
            paras.append(l)
    return paras


if __name__ == "__main__":
    out = Path(sys.argv[2])
    paras = chapter1(sys.argv[1])
    out.write_text("\n".join(paras) + "\n")
    words = sum(len(p.split()) for p in paras)
    print(f"{out.name}: {len(paras)} paras, {words} words")
    print("  FIRST:", " | ".join(paras[:3])[:160])
    print("  LAST: ", paras[-1][-160:])
