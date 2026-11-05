"""Calibration: re-derive the data-driven parts of the spec on every run.

Starting from the latest published spec, calibration
- rebuilds each party's candidate field and nomination odds from primary polling (smoothed 50/50 with the
  previous odds so one poll cannot reset the race), adding newly polled or declared candidates;
- sets each candidate's strength from the national trial-heat regression (how they run against the field
  relative to an average-strength nominee), and their home state from the candidate list;
- leaves structural weights, uncertainty and state adjustments where the last revision put them.
The result is the *proposal*: the spec the model runs on when no revision is made, and the starting point the
revision step reviews against the evidence.
"""
from __future__ import annotations

import copy
from datetime import date

from ..config import days_to_election
from ..db import rows
from ..sources.primaries import KNOWN_HOME_STATES
from . import evidence as ev
from .spec import MAX_NOMINEES, OTHER, validate


def nomination_evidence(con, spec: dict, today: date) -> dict:
    dte = days_to_election(today)
    nat = ev.national_poll_model(rows(con, "SELECT * FROM polls WHERE scope='national'"), today, spec)
    cands = rows(con, "SELECT * FROM candidates")
    out = {}
    for party in ("D", "R"):
        avg = ev.primary_average(con, party, today)
        declared = [c["name"] for c in cands if c["party"] == party and c["status"] in ("declared", "exploratory")]
        out[party] = dict(average=avg, implied=ev.implied_nominee_odds(avg["shares"], dte, extra_names=declared), declared=declared,
                          field=[dict(name=c["name"], status=c["status"], home_state=c["home_state"]) for c in cands if c["party"] == party])
    out["strengths"] = (nat or {}).get("strengths", {})
    out["national_polls"] = None if not nat else dict(g=round(nat["g"], 2), n_polls=nat["n_polls"], n_eff=nat["n_eff"])
    return out


def calibrate(con, prev: dict, today: date | None = None) -> tuple[dict, dict, list[str]]:
    """Return (proposal spec, nomination evidence, notes)."""
    today = today or date.today()
    nomev = nomination_evidence(con, prev, today)
    home_of = {c["name"]: c["home_state"] for p in ("D", "R") for c in nomev[p]["field"] if c.get("home_state")}
    prop = copy.deepcopy(prev)
    for party in ("D", "R"):
        implied = nomev[party]["implied"]
        prev_by = {c["name"]: c for c in prev["nominees"][party]}
        has_history = any(c["name"] != OTHER for c in prev["nominees"][party])
        names = [n for n in implied if n != OTHER] + [n for n in prev_by if n != OTHER and n not in implied]
        field = []
        for name in names:
            p_data = implied.get(name, 0.0)
            p_prev = (prev_by.get(name) or {}).get("p", 0.0)
            p = 0.5 * p_prev + 0.5 * p_data if has_history else p_data
            s = nomev["strengths"].get(name)
            eff = s["strength"] if s and s["party"] == party else (prev_by.get(name) or {}).get("effect", 0.0)
            home = home_of.get(name) or KNOWN_HOME_STATES.get(name) or (prev_by.get(name) or {}).get("home_state")
            field.append(dict(name=name, p=p, effect=round(eff, 2), home_state=home))
        field.sort(key=lambda c: -c["p"])
        keep = field[:MAX_NOMINEES]
        other_prev = (prev_by.get(OTHER) or {}).get("p", 0.0)
        other = (0.5 * other_prev + 0.5 * implied.get(OTHER, 0.0) if has_history else implied.get(OTHER, 0.0)) + sum(c["p"] for c in field[MAX_NOMINEES:])
        prop["nominees"][party] = keep + [dict(name=OTHER, p=other, effect=0.0, home_state=None)]
    notes: list[str] = []
    return validate(prop, prev, notes), nomev, notes
