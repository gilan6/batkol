"""Where each chapter's inputs live on Drive and where they land in ~/work.

One entry per chapter id; index keys are <lang>_<chapter> (nl_ch01, en_b2ch01).
An id ends in ch<number>: the chapter `batkol.edition` cuts from the EPUBs.
A Drive path given as (folder, rclone glob; a leading ** reaches any depth) is
resolved once by `fetch` (rclone, case-insensitive): audio must match exactly
one file; an EPUB glob may match several editions, all kept as candidates for
`batkol.edition`. The resolved paths are recorded in
~/work/<chapter>/sources.json, which downstream reads.

  python -m batkol.sources fetch b2ch01   # resolve + download inputs
  python -m batkol.sources show b2ch01
"""
import json
import re
import subprocess
import sys
from pathlib import Path

WORK = Path.home() / "work"
REMOTE = "gdrive:"
AUDIO_EXT = "{opus,mp3,m4a,m4b,ogg,flac,aac}"

# The chapter registry names your own files, so it lives in batkol/sources_local.py (git-ignored).
# Start from batkol/sources_local.example.py, which documents the fields.
try:
    from .sources_local import CHAPTERS, PIMS_L01
except ImportError:
    CHAPTERS, PIMS_L01 = {}, None


def number(chapter):
    """Chapter number from the id: ch01 -> 1, b2ch02 -> 2."""
    m = re.search(r"ch(\d+)$", chapter)
    if not m:
        raise SystemExit(f"{chapter}: a chapter id ends in ch<number> (ch01, b2ch02)")
    return int(m.group(1))


def rclone_find(folder, glob):
    r = subprocess.run(["rclone", "lsf", "-R", "--files-only", "--ignore-case", "--include", glob, REMOTE + folder],
                       capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"rclone lsf {folder}: {r.stderr.strip()[-300:]}")
    return sorted(f"{folder}/{p}" for p in r.stdout.splitlines() if p)


def _exact(chapter):
    c = CHAPTERS.get(chapter)
    return c is not None and all(isinstance(c[lang]["audio"], str) and isinstance(c[lang]["epubs"], dict) for lang in ("nl", "en"))


def _entry(chapter, lang, audio, epubs):
    c = CHAPTERS[chapter][lang]
    suffix = ".opus" if c.get("cut") else Path(audio).suffix
    return dict(drive=audio, cut=c.get("cut"), local=str(WORK / "in" / f"{lang}_{chapter}{suffix}"),
                text=str(WORK / c["text"]),
                epubs={name: dict(drive=p, local=str(WORK / "in" / f"{name}.epub")) for name, p in epubs.items()})


def resolve(chapter):
    """Drive paths for one chapter; globs go through rclone."""
    if chapter not in CHAPTERS:
        raise SystemExit(f"{chapter}: not in batkol/sources_local.py (start from sources_local.example.py)")
    out = {}
    for lang in ("nl", "en"):
        c = CHAPTERS[chapter][lang]
        audio = [c["audio"]] if isinstance(c["audio"], str) else rclone_find(*c["audio"])
        if len(audio) != 1:
            raise SystemExit(f"{chapter} {lang} audio {c['audio']}: {len(audio)} matches, need 1:\n  " +
                             "\n  ".join(audio))
        epubs = c["epubs"] if isinstance(c["epubs"], dict) else \
            {f"{lang}_{chapter}_{i}": p for i, p in enumerate(rclone_find(*c["epubs"]), 1)}
        if not epubs:
            raise SystemExit(f"{chapter} {lang}: no EPUB matches {c['epubs']}")
        out[lang] = _entry(chapter, lang, audio[0], epubs)
    return out


def load(chapter):
    """Resolved sources of a chapter: {lang: {drive, local, text, epubs}}."""
    if _exact(chapter):
        return resolve(chapter)
    p = WORK / chapter / "sources.json"
    if not p.exists():
        raise SystemExit(f"{p} missing: run `python -m batkol.sources fetch {chapter}` first")
    return json.loads(p.read_text())


def cut_chapter(drive, title, local, pad=0.5):
    """Whole-book audio: download once to ~/work/in/raw, cut one chapter (by its chapter-mark title) to opus."""
    raw = WORK / "in" / "raw" / Path(drive).name
    if not raw.exists():
        raw.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["rclone", "copyto", REMOTE + drive, str(raw)], check=True)
    marks = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_chapters", "-of", "json", str(raw)],
                                      capture_output=True, text=True, check=True).stdout)["chapters"]
    m = [c for c in marks if " ".join(c.get("tags", {}).get("title", "").split()) == title]  # titles use NBSP
    if len(m) != 1:
        raise SystemExit(f"{raw.name}: chapter {title!r}: {len(m)} matches")
    a, b = max(0.0, float(m[0]["start_time"]) - pad), float(m[0]["end_time"]) + pad
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{a:.3f}", "-to", f"{b:.3f}", "-i", str(raw),
                    "-map", "0:a:0", "-c:a", "libopus", "-b:a", "96k", local], check=True)


def fetch(chapter):
    res = resolve(chapter)
    (WORK / chapter).mkdir(parents=True, exist_ok=True)
    (WORK / "in").mkdir(parents=True, exist_ok=True)
    (WORK / chapter / "sources.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    for lang, s in res.items():
        for drive, local in [(s["drive"], s["local"])] + [(e["drive"], e["local"]) for e in s["epubs"].values()]:
            if Path(local).exists():
                pass
            elif drive == s["drive"] and s.get("cut"):
                cut_chapter(drive, s["cut"], local)
            else:
                subprocess.run(["rclone", "copyto", REMOTE + drive, local], check=True)
            print(f"{lang}: {Path(local).name}  <-  {drive}")
    return res


if __name__ == "__main__":
    cmd, chapter = sys.argv[1], sys.argv[2]
    if cmd == "fetch":
        fetch(chapter)
    else:
        print(json.dumps(load(chapter), ensure_ascii=False, indent=1))
