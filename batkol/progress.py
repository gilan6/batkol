"""Live progress of a long pass (whisper, emissions, gap pass) in seconds of audio, with ETA.

The bar goes to stderr. Run a pass with its output in a log the user can watch:
  uv run python -m batkol.analyze b2ch02 nl > ~/work/logs/b2ch02_nl.log 2>&1   # tail -f it
"""
import sys

from tqdm import tqdm

FORMAT = "{desc} {percentage:3.0f}%|{bar:30}| {n:.0f}/{total:.0f} s audio [{elapsed}<{remaining}]"


def bar(desc, total_s, done_s=0.0, **kw):
    return tqdm(total=round(total_s, 1), initial=round(done_s, 1), desc=desc, bar_format=FORMAT, mininterval=1.0,
                file=sys.stderr, **kw)


def to(pb, s):
    """Move the bar to s seconds (a window re-done from an earlier point moves it back)."""
    pb.update(s - pb.n)


def note(msg):
    """A log line printed above the bar."""
    tqdm.write(msg, file=sys.stderr)
