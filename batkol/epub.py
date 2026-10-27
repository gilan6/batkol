"""EPUB -> plain text lines in spine order."""
import re
import sys
import warnings
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
warnings.filterwarnings("ignore", category=UserWarning, module="ebooklib")
warnings.filterwarnings("ignore", category=FutureWarning, module="ebooklib")

XML_ENC = re.compile(rb'^<\?xml[^>]*encoding=["\']([\w.-]+)["\']')


def decode(raw):
    """Honor the XML-declared encoding; treat latin-1 as cp1252 like browsers do."""
    m = XML_ENC.match(raw.lstrip())
    enc = m.group(1).decode().lower() if m else "utf-8"
    if enc in ("iso-8859-1", "latin-1", "latin1", "us-ascii"):
        enc = "cp1252"
    return raw.decode(enc, errors="strict")


BLOCKS = ["p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "br", "blockquote", "tr"]


def spine_lines(path):
    """Yield (doc_name, line) for every non-empty text block, spine order."""
    book = epub.read_epub(path, options={"ignore_ncx": True})
    for idref, _ in book.spine:
        item = book.get_item_with_id(idref)
        if item is None or item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        soup = BeautifulSoup(decode(item.content), "lxml")
        body = soup.body or soup
        for tag in body.find_all(BLOCKS):
            tag.insert_before("\n")
            tag.insert_after("\n")
        for line in body.get_text().split("\n"):
            line = " ".join(line.replace("­", "").split())
            if line:
                yield item.get_name(), line


if __name__ == "__main__":
    lines = list(spine_lines(sys.argv[1]))
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    print(f"# {len(lines)} lines, {sum(len(l) for _, l in lines)} chars")
    for i, (doc, line) in enumerate(lines[:n]):
        print(f"{i}\t{doc}\t{line[:110]}")
