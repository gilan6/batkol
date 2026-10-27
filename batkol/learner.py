"""Learner state across lessons: what was taught or reviewed in which lesson,
and what is due next on the Pimsleur ladder.

The in-lesson steps (5 s, 25 s, 2 min, 10 min) are scheduled inside a lesson.
After that, 1 h / 5 h / 1 d collapse into "next lesson", then 5 d, 25 d, 4 mo,
2 y. Lessons are assumed to be taken one per day: lesson n = day n (the user's
actual listening dates are not observable here).

State is a record of lessons; due dates are derived from it, so rebuilding a
lesson replaces its record instead of advancing anything twice.
Stored in ~/work/learner/state.json (backed up with the rest of the state).
"""
import json
from pathlib import Path

LADDER_DAYS = [1, 5, 25, 120, 730]
PATH = Path.home() / "work/learner/state.json"


class Learner:
    def __init__(self, path=PATH):
        self.path = Path(path)
        self.state = json.loads(self.path.read_text()) if self.path.exists() else {"lessons": {}, "items": {}}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.state, indent=1))

    def record(self, lesson, day, introduced, reviewed, defs):
        """introduced/reviewed: item keys; defs: key -> {kind, unit, nl_book, en_book}."""
        self.state["lessons"][lesson] = dict(day=day, introduced=sorted(introduced), reviewed=sorted(reviewed))
        self.state["items"].update(defs)
        # a rebuilt lesson may drop items: keep only definitions some lesson actually used
        used = {k for rec in self.state["lessons"].values() for k in rec["introduced"] + rec["reviewed"]}
        self.state["items"] = {k: v for k, v in self.state["items"].items() if k in used}
        self.save()

    def history(self, key, before_day):
        days = []
        for rec in self.state["lessons"].values():
            if rec["day"] < before_day and (key in rec["introduced"] or key in rec["reviewed"]):
                days.append(rec["day"])
        return sorted(days)

    def due(self, day):
        """Item keys due for review at lesson `day` (oldest first)."""
        out = []
        for key in self.state["items"]:
            h = self.history(key, day)
            if not h:
                continue
            step = len(h) - 1  # reviews done after the introduction
            if h[-1] + LADDER_DAYS[min(step, len(LADDER_DAYS) - 1)] <= day:
                out.append((h[0], key))
        return [k for _, k in sorted(out)]
