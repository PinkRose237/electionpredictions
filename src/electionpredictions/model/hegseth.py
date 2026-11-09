"""A separate, judgment-based competing-risk model for Hegseth's current tenure.

No election-model inputs or market prices. Row-vector continuous-time Markov chain:
serving -> impeached -> removed, with firing/resignation possible before or after
impeachment. Absorbing states retain whether impeachment happened before departure.
"""
from __future__ import annotations

from datetime import date, timedelta
from itertools import product
from math import isfinite

import numpy as np
from scipy.linalg import expm

TERM_END = date(2029, 1, 20)
RATE_KEYS = ("firing", "resignation", "impeachment", "conviction")
RATE_BOUNDS = {"firing": (0.00001, 0.05), "resignation": (0.00001, 0.05),
               "impeachment": (0.00001, 0.15), "conviction": (0.000001, 0.05)}
# Deliberate starting assumptions, NOT historical frequencies or fitted estimates.
BACKGROUND = dict(firing=0.0005, resignation=0.0008, impeachment=0.0005, conviction=0.0001)
INITIAL_RATES = dict(firing=0.003, resignation=0.002, impeachment=0.025, conviction=0.0015)
METRICS = ("forced_exit", "fired", "impeached", "removed", "resigned", "any_exit", "still_serving")


def validate_rates(raw: dict) -> dict:
    """Reject an incomplete/nonfinite specification; clamp finite rates to published bounds."""
    out = {}
    for key in RATE_KEYS:
        value = raw[key]
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not isfinite(value):
            raise ValueError(f"Invalid {key} rate")
        lo, hi = RATE_BOUNDS[key]
        out[key] = min(hi, max(lo, value))
    return out


def _generator(rates: dict) -> np.ndarray:
    # U, I, fired-before, fired-after, resigned-before, resigned-after, removed
    q = np.zeros((7, 7))
    q[0, 1], q[0, 2], q[0, 4] = rates["impeachment"], rates["firing"], rates["resignation"]
    q[1, 3], q[1, 5], q[1, 6] = rates["firing"], rates["resignation"], rates["conviction"]
    for i in (0, 1):
        q[i, i] = -q[i].sum()
    return q


def probabilities(days: int, rates: dict, *, status: str = "serving", was_impeached: bool = False,
                  elevated_days: int = 90, scale: float = 1.0) -> dict:
    """First 90 days of a review use its rates, then background assumptions take over.

    Impeachment after departure and return to office are outside this forecast's scope.
    All dates are exclusive deadlines: by Jan 20 means before the term ends that day.
    """
    initial = {"serving": 0, "impeached": 1, "fired": 3 if was_impeached else 2,
               "resigned": 5 if was_impeached else 4, "removed": 6}[status]
    p = np.eye(7)[initial]
    days = max(0, days)
    near = min(days, max(0, elevated_days))
    for duration, rs in ((near, rates), (days - near, BACKGROUND)):
        if duration:
            p = p @ expm(_generator({k: rs[k] * scale for k in RATE_KEYS}) * duration)
    p = np.maximum(p, 0)
    p /= p.sum()
    fired, resigned, removed = p[2] + p[3], p[4] + p[5], p[6]
    return dict(forced_exit=float(fired + removed), fired=float(fired),
                impeached=float(p[1] + p[3] + p[5] + removed), removed=float(removed),
                resigned=float(resigned), any_exit=float(fired + resigned + removed),
                still_serving=float(p[0] + p[1]))


def forecast(today: date, rates: dict, reviewed_on: date, *, status="serving", was_impeached=False) -> list[dict]:
    """All horizons share one process; sensitivity envelopes are NOT confidence intervals."""
    rates = validate_rates(rates)
    elevated = max(0, 90 - max(0, (today - reviewed_on).days))
    out = []
    for key, label, deadline in (("30d", "Next 30 days", today + timedelta(days=30)),
                                 ("90d", "Next 90 days", today + timedelta(days=90)),
                                 ("term", "End of term", TERM_END)):
        deadline = min(TERM_END, deadline)
        days = max(0, (deadline - today).days)
        kwargs = dict(status=status, was_impeached=was_impeached, elevated_days=elevated)
        p = probabilities(days, rates, **kwargs)
        # Firing competes with impeachment/removal. Enumerate independent low/high
        # rates rather than assuming every metric rises when all rates rise together.
        variants = []
        for scales in product((0.5, 2.0), repeat=4):
            varied = {k: rates[k] * s for k, s in zip(RATE_KEYS, scales)}
            # Also vary long-run background rates together (two more scenarios).
            for background_scale in (0.5, 2.0):
                adjusted = {k: varied[k] / background_scale for k in RATE_KEYS}
                variants.append(probabilities(days, adjusted, scale=background_scale, **kwargs))
        ranges = {k: [min(v[k] for v in variants + [p]), max(v[k] for v in variants + [p])] for k in METRICS}
        out.append(dict(id=key, label=label, deadline=deadline.isoformat(), days=days,
                        probabilities=p, sensitivity=ranges))
    return out
