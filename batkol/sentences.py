"""Chapter text -> sentences. First two paragraphs (chapter number + title) form one heading unit."""
import re
from pathlib import Path

END = re.compile(r"[.!?…]+[’'”\")\]]*(?=\s)")
OPEN = "‘'“\"(–—-"


def split_para(p):
    out, start = [], 0
    for m in END.finditer(p):
        rest = p[m.end():].lstrip()
        nxt = rest.lstrip(OPEN + " ")[:1]
        if nxt and (nxt.isupper() or nxt.isdigit()):
            out.append(p[start:m.end()].strip())
            start = m.end()
    tail = p[start:].strip()
    if tail:
        out.append(tail)
    return out


def chapter_sentences(path):
    paras = Path(path).read_text().splitlines()
    head = " – ".join(p.strip("—– ") for p in paras[:2])
    sents = [dict(id=0, para=0, text=head, heading=True)]
    for pi, p in enumerate(paras[2:], start=1):
        for s in split_para(p):
            sents.append(dict(id=len(sents), para=pi, text=s, heading=False))
    return sents


if __name__ == "__main__":
    import sys
    ss = chapter_sentences(sys.argv[1])
    print(len(ss), "sentences")
    for s in ss[: int(sys.argv[2]) if len(sys.argv) > 2 else 20]:
        print(s["id"], s["para"], s["text"])
