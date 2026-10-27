"""Summarize a pipeline run: build stats, cut margins, verification, flagged units."""
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

from . import cuts
from .audio import SR
from .pipeline import audio


def cut_margins(units):
    """Per cut: dB at the cut vs local threshold, and speech-free margin into the clip."""
    out = {}
    for lang in ("nl", "en"):
        db = cuts.frame_db(audio(lang))
        rows = []
        for u in units:
            for side in ("start", "end"):
                t = u.get(f"{lang}_{side}")
                if t is None:
                    continue
                thr = cuts.local_threshold(db, t)
                i = int(round((t * SR - cuts.WIN / 2) / cuts.HOP))
                rng = range(i, min(len(db), i + 300)) if side == "start" else range(i, max(-1, i - 300), -1)
                m = next((abs(k - i) for k in rng if db[k] >= thr), 300) * cuts.HOP / SR
                rows.append(dict(idx=u["idx"], side=side, db=float(db[i]), thr=float(thr), margin=m))
        out[lang] = rows
    return out


def compute_defects(units, ver, margins, over_db=3.0):
    """Suspect units: cut energy >= over_db above the local silence threshold, or
    re-transcription shows a lost (NL) / lost-or-leaked (EN) word at a clip edge.
    Dutch extra words are the narrator's own additions, not cut errors."""
    speech = {lang: sorted({r["idx"] for r in rows if r["db"] >= r["thr"] + over_db}) for lang, rows in margins.items()}
    edge = {lang: sorted({i for i, v in ver.items() for f in v[lang]["flags"]
                          if f.split(":")[0].endswith("missing" if lang == "nl" else ("missing", "extra"))})
            for lang in ("nl", "en")}
    missing = sorted(u["idx"] for u in units if "en_not_found" in u["flags"])
    bad = sorted(set().union(*speech.values(), *edge.values(), missing))
    return dict(cut_in_speech=speech, verify_edge=edge, en_not_found=missing, likely_defective=bad)


def main(run_dir, name):
    d = Path(run_dir).expanduser()
    units = json.loads((d / "units.json").read_text())
    build = json.loads((d / "build.json").read_text())
    ver = {}
    if (d / "verify.jsonl").exists():
        ver = {r["idx"]: r for r in map(json.loads, (d / "verify.jsonl").read_text().splitlines())}
    shapes = Counter(f"{len(u['nl_ids'])}:{len(u['en_ids'])}" for u in units)
    flags = Counter(f.split(":")[0] for u in units for f in u["flags"])
    margins = cut_margins(units)
    defects = compute_defects(units, ver, margins)
    (d / "defects.json").write_text(json.dumps(defects, indent=1))
    L = [f"# {name}: NL → EN → NL drill, HP1 chapter 1", ""]
    L.append(f"- MP3: `{name}.mp3`, {build['seconds'] / 60:.1f} min, {build['units']} units "
             f"(of {len(units)} groups; the rest are unpaired, TSV only). Gain NL {build['gain_nl']:+} dB, EN {build['gain_en']:+} dB.")
    L.append(f"- Group shapes NL:EN: " + ", ".join(f"{k} ×{v}" for k, v in shapes.most_common()))
    L.append(f"- Flags: " + (", ".join(f"{k} ×{v}" for k, v in flags.most_common()) or "none"))
    durs = [u["nl_end"] - u["nl_start"] for u in units if "nl_start" in u]
    L.append(f"- NL clip length: median {np.median(durs):.1f} s, max {max(durs):.1f} s")
    L += ["", "## Cuts (signal check)"]
    for lang, rows in margins.items():
        above = [r for r in rows if r["db"] >= r["thr"]]
        mg = [r["margin"] for r in rows]
        L.append(f"- {lang.upper()}: {len(rows)} cuts, {len(above)} at/above local silence threshold; "
                 f"speech-free margin min {min(mg):.2f} s, p10 {np.percentile(mg, 10):.2f} s, median {np.median(mg):.2f} s")
        for r in above:
            L.append(f"  - unit {r['idx']} {r['side']}: {r['db']:.1f} dB vs thr {r['thr']:.1f} dB")
    if ver:
        L += ["", f"## Verification (re-transcription of {len(ver)} units × 2 clips)"]
        for lang in ("nl", "en"):
            ratios = [v[lang]["ratio"] for v in ver.values()]
            edge = [(i, f) for i, v in ver.items() for f in v[lang]["flags"]
                    if f.split(":")[0].endswith(("missing", "extra"))]
            L.append(f"- {lang.upper()}: text match median {np.median(ratios):.3f}, p10 {np.percentile(ratios, 10):.3f}; "
                     f"edge words missing/extra: {len(edge)}")
            for i, f in edge:
                L.append(f"  - unit {i}: {f}")
        worst = sorted(ver.values(), key=lambda v: v["nl"]["ratio"] + v["en"]["ratio"])[:10]
        L += ["", "Lowest combined match (NL + EN):", ""]
        for v in worst:
            u = units[v["idx"]]
            L.append(f"- unit {v['idx']}: NL {v['nl']['ratio']}, EN {v['en']['ratio']}: {u['nl_text'][:70]}…")
    L += ["", "## Suspect units", "",
          f"- Cut in speech (>= 3 dB over local silence threshold): NL {defects['cut_in_speech']['nl']}, EN {defects['cut_in_speech']['en']}",
          f"- Edge word lost/leaked (re-transcription): NL {defects['verify_edge']['nl']}, EN {defects['verify_edge']['en']}",
          f"- No EN clip: {defects['en_not_found']}",
          f"- Distinct suspect units: {len(defects['likely_defective'])} of {len(units)}"]
    flagged = [u for u in units if u["flags"]]
    if flagged:
        L += ["", "## Flagged units", ""]
        for u in flagged:
            L.append(f"- {u['idx']} ({','.join(map(str, u['nl_ids']))} : {','.join(map(str, u['en_ids']))}, sim {u['sim']}): "
                     f"{';'.join(u['flags'])}: NL “{u['nl_text'][:60]}” / EN “{u['en_text'][:60]}”")
    notes = d / "notes.md"
    if notes.exists():
        L += ["", notes.read_text()]
    (d / "out" / f"{name}_report.md").write_text("\n".join(L) + "\n")
    print("\n".join(L[:40]))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "hp1_ch01")


def annotate_tsv(run_dir, name):
    """Add verification + suspect columns to the TSV (no audio rebuild)."""
    import csv
    d = Path(run_dir).expanduser()
    ver = {r["idx"]: r for r in map(json.loads, (d / "verify.jsonl").read_text().splitlines())}
    defects = json.loads((d / "defects.json").read_text())
    reasons = {}
    for lang, ids in defects["cut_in_speech"].items():
        for i in ids:
            reasons.setdefault(i, []).append(f"{lang}_cut_in_speech")
    for lang, ids in defects["verify_edge"].items():
        for i in ids:
            reasons.setdefault(i, []).append(f"{lang}_edge_word")
    for i in defects.get("en_not_found", []):
        reasons.setdefault(i, []).append("en_not_found")
    path = d / "out" / f"{name}.tsv"
    rows = list(csv.reader(path.open(), delimiter="\t"))
    head = rows[0][:15] + ["nl_check", "en_check", "en_vs_book", "suspect"]
    out = [head]
    for r in rows[1:]:
        i, v = int(r[0]), ver.get(int(r[0]))
        out.append(r[:15] + [v["nl"]["ratio"] if v else "", v["en"]["ratio"] if v else "",
                             v["en_vs_book"] if v else "", ";".join(reasons.get(i, []))])
    with path.open("w", newline="") as f:
        csv.writer(f, delimiter="\t", lineterminator="\n").writerows(out)
