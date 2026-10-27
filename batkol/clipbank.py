"""Verified sound-bite bank: each clip is checked once, logged, then reused.

A clip is identified by its source and cut (source, start, end, fade-in).
Checks: signal (energy at the cut points vs the local silence threshold) and
re-transcription of the clip (lost or leaked words at its edges). Records go to
an append-only JSONL log; builders take only clips whose latest status allows
it and never re-check a logged clip. Human listening verdicts are appended to
the same log and override the automatic status.

Status: pass | review (needs a listening verdict) | fail.
"""
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
from rapidfuzz import fuzz

from . import asr, cuts, verify
from .align import spoken_tokens
from .audio import SR, cached

VERIFIER = "v1:turbo-edges+energy"
OVER_DB = 3.0  # a pause cut this far above the local silence threshold is in speech


def clip_id(c):
    if c["src"] == "tts":
        key = f"tts|{c['text']}"
    else:
        key = f"{c['src']}|{c['start']:.3f}|{c['end']:.3f}|{c.get('fade_in', 0.04):.3f}"
    return hashlib.sha1(key.encode()).hexdigest()[:12]


class Bank:
    def __init__(self, path, sources):
        """sources: src name -> (16 kHz audio array, frame dB array)."""
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.sources = sources
        self.log = {}
        self.checked_now = 0
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                r = json.loads(line)
                self.log[r["id"]] = r if r.get("by") != "user" else {**self.log.get(r["id"], {}), **r}

    def _append(self, rec):
        with open(self.path, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.log[rec["id"]] = rec

    def status(self, c):
        r = self.log.get(clip_id(c))
        return r["status"] if r else None

    def check(self, c, lang, kind):
        """Return the clip's record, verifying it first if it is not logged yet."""
        cid = clip_id(c)
        r = self.log.get(cid)
        if r and (r.get("by") == "user" or r.get("verifier") == VERIFIER):
            return r
        if c["src"] == "tts":
            rec = dict(id=cid, src="tts", text=c["text"], kind=kind, status="pass", verifier=VERIFIER,
                       note="synthetic; not re-transcribed", t=time.strftime("%Y-%m-%dT%H:%M:%S"))
            self._append(rec)
            return rec
        x, db = self.sources[c["src"]]
        # signal: energy at each cut vs the local silence threshold
        sig = {}
        for side, t in (("start", c["start"]), ("end", c["end"])):
            i = int(round((t * SR - cuts.WIN / 2) / cuts.HOP))
            sig[side] = round(float(db[i] - cuts.local_threshold(db, t)), 1)  # dB above threshold
        # re-transcription of the clip
        seg = np.ascontiguousarray(x[int(c["start"] * SR):int(c["end"] * SR)], dtype=np.float32)
        hyp = [t for w in asr.transcribe(seg, lang) for t in spoken_tokens(w["w"], lang)]
        ratio, flags = verify.edge_report(c["tokens"], hyp)
        reasons = []
        for f in flags:
            kind_f = f.split(":")[0]
            if kind_f.endswith(("missing", "extra")):
                reasons.append(f)
            elif kind_f.endswith("differs"):
                a, b = f.split(":", 1)[1].split("->")
                if fuzz.ratio(a, b) < 60:
                    reasons.append(f)
        hard = [r for r in reasons if r.split(":")[0].endswith(("missing", "extra"))]
        in_speech_onset = c.get("onset") == "in_speech"
        if not in_speech_onset and sig["start"] >= OVER_DB:
            hard.append(f"start cut {sig['start']} dB over silence")
        if sig["end"] >= OVER_DB:
            hard.append(f"end cut {sig['end']} dB over silence")
        status = "fail" if hard else "review" if (in_speech_onset or reasons) else "pass"
        rec = dict(id=cid, src=c["src"], start=c["start"], end=c["end"], fade_in=c.get("fade_in", 0.04),
                   lang=lang, kind=kind, tokens=c["tokens"], hyp=hyp, ratio=ratio, flags=flags,
                   signal_db_over_thr=sig, onset=c.get("onset"), status=status, reasons=sorted(set(reasons + hard)),
                   verifier=VERIFIER, t=time.strftime("%Y-%m-%dT%H:%M:%S"))
        self._append(rec)
        self.checked_now += 1
        return rec

    def verdict(self, cid, status, note=""):
        """Record a human listening verdict; it overrides the automatic status."""
        self._append(dict(id=cid, status=status, by="user", note=note, t=time.strftime("%Y-%m-%dT%H:%M:%S")))

    def summary(self):
        s = {}
        for r in self.log.values():
            s[r["status"]] = s.get(r["status"], 0) + 1
        return s


if __name__ == "__main__" and sys.argv[1] == "verdict":
    # legacy per-cut bank: python -m batkol.clipbank verdict BANK CLIP_ID pass|fail [note]
    Bank(sys.argv[2], {}).verdict(sys.argv[3], sys.argv[4], " ".join(sys.argv[5:]))


# ---- span bank (flow v2): clips identified by the words they hold ----

def span_id(idx, a, b, onset=False):
    """Identity of the clip holding words a..b of an index. Independent of the
    cut rule, so listening verdicts survive changes to cut placement."""
    w0, w1 = idx.words[a], idx.words[b]
    key = f"{idx.key}|{w0['s']:.2f}|{w1['e']:.2f}|{'onset' if onset else 'pause'}"
    return hashlib.sha1(key.encode()).hexdigest()[:12]


class SpanBank:
    """Append-only log keyed by span_id.
    by=user  listening verdict (pass|fail): the only record that gates builds.
    by=qa    sampled re-transcription result: measures the index, never gates."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.recs = {}
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                r = json.loads(line)
                self.recs.setdefault(r["id"], []).append(r)

    def add(self, rec):
        rec = dict(rec, t=time.strftime("%Y-%m-%dT%H:%M:%S"))
        with open(self.path, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.recs.setdefault(rec["id"], []).append(rec)

    def verdict(self, sid):
        v = [r for r in self.recs.get(sid, []) if r.get("by") == "user"]
        return v[-1]["status"] if v else None

    def listed_elsewhere(self, sid, name):
        """Already waiting on another lesson's listening list."""
        return any(r.get("by") == "listed" and r.get("list") != name for r in self.recs.get(sid, []))

    def list_for(self, sid, name):
        if not any(r.get("by") == "listed" and r.get("list") == name for r in self.recs.get(sid, [])):
            self.add(dict(id=sid, by="listed", list=name))


def migrate_cut_bank(old_path, new_path):
    """Carry v1 per-cut ASR results into the span bank as QA history (by=qa)."""
    from .index import Index
    key = {"nl": "nl_ch01", "en": "en_ch01", "pims": "pims_L01"}
    idx = {k: Index(v) for k, v in key.items()}
    bank, n = SpanBank(new_path), 0
    seen = set(bank.recs)
    for line in Path(old_path).read_text().splitlines():
        r = json.loads(line)
        if r.get("src") not in key or r.get("by") == "user":
            continue
        ix = idx[r["src"]]
        inside = [i for i, w in enumerate(ix.words) if w["s"] >= r["start"] - 0.03 and w["e"] <= r["end"] + 0.03]
        if not inside:
            continue
        sid = span_id(ix, inside[0], inside[-1], r.get("onset") == "in_speech")
        if sid in seen:
            continue
        seen.add(sid)
        bank.add(dict(id=sid, by="qa", source="v1-cut-bank", status=r["status"], reasons=r.get("reasons", []),
                      kind=r.get("kind"), src=r["src"], start=r["start"], end=r["end"]))
        n += 1
    return n


def qa_sample(lesson_json, bank_path, n=10, seed=0):
    """Measure the index: re-transcribe a random sample of a lesson's clips
    (plus every clip with an index risk) and log the result. Never gates."""
    import random
    from .index import Index
    side = json.loads(Path(lesson_json).read_text())["timeline"]
    clips = {r["clip_id"]: r for r in side if r["source"] in ("nl", "en", "pims")}
    risky = [c for c in clips.values() if c["risk"]]
    rest = [c for c in clips.values() if not c["risk"]]
    random.Random(seed).shuffle(rest)
    bank = SpanBank(bank_path)
    keys = {"nl": "nl_ch01", "en": "en_ch01", "pims": "pims_L01"}
    idx = {k: Index(v) for k, v in keys.items()}
    out = []
    for c in risky + rest[:n]:
        if any(r.get("by") == "qa" for r in bank.recs.get(c["clip_id"], [])):
            continue
        ix = idx[c["source"]]
        x = cached(ix.local, Path.home() / "work" / "cache")
        seg = np.ascontiguousarray(x[int(c["start"] * SR):int(c["end"] * SR)], dtype=np.float32)
        lang = "nl" if c["source"] == "nl" else "en"
        hyp = [t for w in asr.transcribe(seg, lang) for t in spoken_tokens(w["w"], lang)]
        exp = [w["tok"] for w in ix.words if w["s"] >= c["start"] - 0.03 and w["e"] <= c["end"] + 0.03]
        ratio, flags = verify.edge_report(exp, hyp)
        edge = [f for f in flags if f.split(":")[0].endswith(("missing", "extra"))]
        rec = dict(id=c["clip_id"], by="qa", source="sample", status="fail" if edge else "pass", flags=flags,
                   ratio=ratio, risk=c["risk"], kind=c["kind"], src=c["source"])
        bank.add(rec)
        out.append(rec)
    return out


if __name__ == "__main__" and sys.argv[1] in ("migrate", "qa", "verdict2"):
    if sys.argv[1] == "migrate":
        print("migrated", migrate_cut_bank(sys.argv[2], sys.argv[3]))
    elif sys.argv[1] == "qa":
        res = qa_sample(sys.argv[2], sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else 10)
        print(f"qa: {len(res)} clips, {sum(r['status'] == 'fail' for r in res)} with edge defects")
        for r in res:
            if r["status"] == "fail":
                print(" ", r["kind"], r["src"], r["flags"], r["risk"])
    else:  # python -m batkol.clipbank verdict2 BANK SPAN_ID pass|fail [note]
        SpanBank(sys.argv[2]).add(dict(id=sys.argv[3], by="user", status=sys.argv[4], note=" ".join(sys.argv[5:])))
