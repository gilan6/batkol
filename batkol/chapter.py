"""Cut one chapter's text (its heading .. the next chapter's heading) out of an EPUB."""
import re
import sys
from pathlib import Path

from num2words import num2words

from .epub import spine_lines


# "HOOFDSTUK 2", "— CHAPTER TWO —", "TWO", "Hoofdstuk twee <title>" (a title on the heading
# line is split off); a bare digit is not a heading (page numbers in OCR editions).
# The number may not run on ("twenty" is not "TWENTY-ONE").
def _heading(n):
    words = "|".join(re.escape(num2words(n, lang=lang)) for lang in ("nl", "en"))
    return re.compile(rf"^[—–-]?\s*(?:(?:hoofdstuk|chapter)\s+(?:{n}|{words})(?![\w-])(?P<title>.*)|(?:{words}))\s*[—–-]?$",
                      re.I)


# Paragraphs split by page-layout line breaks: join when a line ends without
# terminal punctuation and the next one starts lowercase.
TERMINAL = tuple(".!?'\"’”–—-…:")


def chapter_paras(path, n=1):
    start, end = _heading(n), _heading(n + 1)
    lines = [l for _, l in spine_lines(path)]
    # skip table of contents: take the first start with more than 20 lines before the next end
    # (else the longest such span: a short text)
    starts = [i for i, l in enumerate(lines) if start.match(l)]
    spans = [(s, next((j for j in range(s + 1, len(lines)) if end.match(lines[j])), None)) for s in starts]
    spans = [(s, e) for s, e in spans if e is not None]
    if not spans:
        raise SystemExit(f"chapter {n} not found in {path}: starts={starts} (a chapter ends at the next one's "
                         "heading, so the last chapter is not supported yet)")
    s, e = next(((s, e) for s, e in spans if e - s > 20), max(spans, key=lambda x: x[1] - x[0]))
    m = start.match(lines[s])
    title = (m.group("title") or "").strip(" —–-")
    paras = [lines[s][:m.start("title")].strip(), title] if title else []
    for l in lines[s + bool(title):e]:
        if paras and not paras[-1].endswith(TERMINAL) and l[:1].islower():
            paras[-1] += " " + l
        else:
            paras.append(l)
    return paras


if __name__ == "__main__":  # python -m batkol.chapter <epub> <out.txt> [chapter number, default 1]
    out = Path(sys.argv[2])
    paras = chapter_paras(sys.argv[1], int(sys.argv[3]) if len(sys.argv) > 3 else 1)
    out.write_text("\n".join(paras) + "\n")
    words = sum(len(p.split()) for p in paras)
    print(f"{out.name}: {len(paras)} paras, {words} words")
    print("  FIRST:", " | ".join(paras[:3])[:160])
    print("  LAST: ", paras[-1][-160:])
