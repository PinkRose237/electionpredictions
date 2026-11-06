"""Calibration: re-derive the data-driven parts of the spec on every run.

The proposal is the latest published spec moved by *how much the evidence has changed since that spec was
made* (its stored basis):

    odds_now     = odds_in_spec     + (poll-implied odds now     - poll-implied odds in the basis)
    strength_now = strength_in_spec + (regression strength now   - regression strength in the basis)

So a revision's judgment (say, cutting a candidate who has ruled out a run) stands until new polling says
something new, while fresh polls still move the model on every run, revision or not. Newly polled or declared
candidates join the field; a spec without a basis (the seed) takes the evidence as is. Structural weights,
uncertainty and state adjustments are left where the last revision put them.
"""
from __future__ import annotations

import copy
from datetime import date
from typing import Optional

from ..config import days_to_election
from ..db import rows
from ..sources.primaries import KNOWN_HOME_STATES
from . import evidence as ev
from .spec import MAX_NOMINEES, OTHER, upgrade, validate


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
    out["house_effects"] = (nat or {}).get("house_effects", {})
    out["national_polls"] = None if not nat else dict(g=round(nat["g"], 2), n_polls=nat["n_polls"], n_eff=nat["n_eff"])
    return out


def basis_of(nomev: dict) -> dict:
    """The evidence a spec is built on, stored with its version."""
    return dict(implied={p: {k: round(v, 5) for k, v in nomev[p]["implied"].items()} for p in ("D", "R")},
                strengths={k: dict(party=v["party"], strength=v["strength"]) for k, v in nomev["strengths"].items()})


def calibrate(con, prev: dict, today: date | None = None, basis: Optional[dict] = None) -> tuple[dict, dict, list[str]]:
    """Return (proposal spec, nomination evidence, notes)."""
    today = today or date.today()
    prev = upgrade(prev)
    nomev = nomination_evidence(con, prev, today)
    home_of = {c["name"]: c["home_state"] for p in ("D", "R") for c in nomev[p]["field"] if c.get("home_state")}
    prop = copy.deepcopy(prev)
    notes: list[str] = []
    for party in ("D", "R"):
        implied = nomev[party]["implied"]
        prev_by = {c["name"]: c for c in prev["nominees"][party]}
        has_history = any(c["name"] != OTHER for c in prev["nominees"][party])
        b_implied = (basis or {}).get("implied", {}).get(party)
        names = [n for n in implied if n != OTHER] + [n for n in prev_by if n != OTHER and n not in implied]
        field = []
        for name in names:
            p_data = implied.get(name, 0.0)
            prev_c = prev_by.get(name)
            if not has_history or b_implied is None:
                p = 0.5 * (prev_c or {}).get("p", 0.0) + 0.5 * p_data if has_history else p_data
            elif prev_c is None:
                # newly in the evidence (or dropped earlier and re-surfacing): only what is new since the basis
                p = max(0.0, p_data - b_implied.get(name, 0.0)) if name in b_implied else p_data
            else:
                p = max(0.0, prev_c["p"] + p_data - b_implied.get(name, 0.0))
            s = nomev["strengths"].get(name)
            s_now = s["strength"] if s and s["party"] == party else None
            if prev_c is None:
                eff = s_now if s_now is not None else 0.0
            elif s_now is None:
                eff = prev_c["effect"]                       # no current polling: keep the judgment
            elif basis is None:
                eff = s_now                                  # no record of the evidence behind the old value
            else:                                            # move by what polling has learned since the basis
                s_then = ((basis.get("strengths") or {}).get(name) or {}).get("strength") or 0.0
                eff = prev_c["effect"] + (s_now - s_then)
            home = (prev_c or {}).get("home_state") or home_of.get(name) or KNOWN_HOME_STATES.get(name)
            field.append(dict(name=name, p=p, effect=round(eff, 2), home_state=home))
        field.sort(key=lambda c: -c["p"])
        keep = field[:MAX_NOMINEES]
        other_prev = (prev_by.get(OTHER) or {}).get("p", 0.0)
        if not has_history:
            other = implied.get(OTHER, 0.0)
        elif b_implied is None:
            other = 0.5 * other_prev + 0.5 * implied.get(OTHER, 0.0)
        else:
            other = max(0.0, other_prev + implied.get(OTHER, 0.0) - b_implied.get(OTHER, 0.0))
        other += sum(c["p"] for c in field[MAX_NOMINEES:])
        prop["nominees"][party] = keep + [dict(name=OTHER, p=other, effect=0.0, home_state=None)]
    return validate(prop, prev, notes), nomev, notes
