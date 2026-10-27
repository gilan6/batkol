"""Word normalization shared by aligners and matchers."""
import re
import unicodedata

WORD = re.compile(r"[a-z0-9']+")


def fold(s):
    """lowercase, strip diacritics, unify apostrophes."""
    s = unicodedata.normalize("NFKD", s.replace("’", "'").replace("‘", "'"))
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def words(s):
    """Normalized word tokens; quote-only apostrophes dropped."""
    return [w.strip("'") for w in WORD.findall(fold(s)) if w.strip("'")]
