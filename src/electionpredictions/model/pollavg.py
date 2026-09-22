"""Weighted polling average for one race."""
from __future__ import annotations

import math
from datetime import date
from typing import Optional

from ..config import days_to_election

POP_WEIGHT = {"LV": 1.0, "RV": 0.9, "A": 0.8, "V": 0.85}

# Pollster quality tiers (weight multipliers), informed by the last published 538 pollster ratings (2024) and
# recent-cycle accuracy. Unknown pollsters get 1.0; the sponsor penalty below still applies on top of this.
POLLSTER_TIER = {
    1.15: ["new york times", "siena", "marist", "quinnipiac", "fox news", "cnn", "ssrs", "abc news", "washington post", "marquette",
           "selzer", "monmouth", "suffolk", "surveyusa", "mason-dixon", "muhlenberg", "emerson", "yougov", "ipsos", "atlasintel",
           "wall street journal", "nbc news", "cbs news", "ap-norc", "pew", "gallup", "beacon research", "shaw & co", "hart research",
           "public opinion strategies", "data for progress", "civiqs", "elway", "franklin & marshall", "st. anselm", "umass", "morning consult",
           "the hill", "harrisx", "echelon insights", "impact research", "gbao", "global strategy group", "fabrizio", "wpa", "cygnal",
           "public policy polling", "ppp", "research co", "univ", "university", "college"],
    0.75: ["rasmussen", "trafalgar", "insideradvantage", "quantus", "big data poll", "patriot polling", "co/efficient", "coefficient",
           "rmg research", "wick", "tipp", "victory insights", "on message", "onmessage", "spry strategies", "remington", "bullfinch",
           "1892", "kaplan strategies", "targoz", "quantus insights", "noble predictive", "j.l. partners", "redfield", "wilton",
           "american pulse", "overton insights", "napolitan"],
}


def pollster_weight(name: str) -> float:
    n = (name or "").lower()
    for w, keys in POLLSTER_TIER.items():
        if any(k in n for k in keys):
            return w
    return 1.0
SPONSOR_SHIFT = 1.5      # points moved toward the other party for partisan-sponsored polls
SPONSOR_WEIGHT = 0.6
BASE_POLL_SD = 4.0       # irreducible race-poll error (excluding the national component)
THIN_POLL_SD = 6.0       # extra error for a single average-quality poll, shrinking with sqrt(n_eff)


def average(polls: list[dict], today: date) -> Optional[dict]:
    """polls: rows from the polls table. Returns a dict or None if nothing usable."""
    usable = [p for p in polls if p["dem_pct"] is not None and p["rep_pct"] is not None and p["end_date"]]
    if not usable:
        return None
    real = [p for p in usable if not p["hypothetical"]]
    hyp_only = not real
    pool = real if real else usable
    dte = days_to_election(today)
    half_life = min(45.0, max(14.0, 14.0 + dte / 4.0))
    max_age = 120 if dte > 60 else 90
    rows_ = []
    for p in pool:
        end = date.fromisoformat(p["end_date"])
        age = max(0, (today - end).days)
        if age > max_age:
            continue
        recency = 0.5 ** (age / half_life)
        n = p["sample_size"] or 400
        size = math.sqrt(min(n, 2500) / 600.0)
        sponsor = SPONSOR_WEIGHT if p["sponsor_lean"] in ("D", "R") else 1.0
        pop = POP_WEIGHT.get(p["population"] or "RV", 0.9)
        w = recency * size * sponsor * pop * pollster_weight(p["pollster"]) * (0.5 if p["hypothetical"] else 1.0)
        m = p["dem_pct"] - p["rep_pct"]
        if p["sponsor_lean"] == "D":
            m -= SPONSOR_SHIFT
        elif p["sponsor_lean"] == "R":
            m += SPONSOR_SHIFT
        rows_.append((p, w, m, age))
    if not rows_:
        return None
    # cap any single pollster's share: total weight <= 1.5x its heaviest poll
    by_pollster: dict[str, list[float]] = {}
    for p, w, _, _ in rows_:
        by_pollster.setdefault(p["pollster"], []).append(w)
    scale = {k: (min(1.0, 1.5 * max(ws) / sum(ws)) if sum(ws) > 0 else 1.0) for k, ws in by_pollster.items()}
    W = sum(w * scale[p["pollster"]] for p, w, _, _ in rows_)
    if W <= 0:
        return None
    margin = sum(w * scale[p["pollster"]] * m for p, w, m, _ in rows_) / W
    newest = min(age for _, _, _, age in rows_)
    poll_sd = math.sqrt(BASE_POLL_SD ** 2 + (THIN_POLL_SD / math.sqrt(W)) ** 2 + (newest / 30.0) ** 2 * 4.0)
    if hyp_only:
        poll_sd = math.sqrt(poll_sd ** 2 + 9.0)
    weights = {p["poll_id"]: round(w * scale[p["pollster"]], 4) for p, w, _, _ in rows_}
    return dict(
        margin=margin, n_eff=W, n_polls=len(rows_), poll_sd=poll_sd, newest_age=newest,
        last_poll=max(p["end_date"] for p, _, _, _ in rows_), hypothetical_only=hyp_only,
        weights=weights, half_life=half_life,
    )
