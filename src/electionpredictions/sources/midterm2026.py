"""The November 2026 midterm results, read from the archived 2026 site (no network): the most recent national
test of the parties. Evidence for the revision step and the site; not a direct simulation input.

- national House popular vote (raw sum over all 435 races, so uncontested seats count as cast)
- seats won so far in the House and among the Senate seats up, and governorships
- every 2026 statewide Senate and governor margin, and how it compares with the national House margin
"""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Optional

from ..config import ARCHIVE_2026_DATA_DIR


def _load(name: str) -> Optional[dict]:
    p = ARCHIVE_2026_DATA_DIR / name
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def summary() -> Optional[dict]:
    p = ARCHIVE_2026_DATA_DIR / "results-auto.json"
    try:
        stamp = (str(p), p.stat().st_mtime)
    except OSError:
        return None
    return _summary(stamp)


@lru_cache(maxsize=4)
def _summary(stamp) -> Optional[dict]:
    res = _load("results-auto.json")
    if not res or not res.get("races"):
        return None
    races = res["races"]
    manual = ((_load("results.json") or {}).get("races") or {})
    house = dict(dem=0, rep=0, other=0)
    seats = {"house": {"D": 0, "R": 0, "counting": 0}, "senate": {"D": 0, "R": 0, "counting": 0}, "governor": {"D": 0, "R": 0, "counting": 0}}
    statewide: dict[str, dict] = {}
    for rid, r in races.items():
        v = r.get("votes") or {}
        d, rep, oth = v.get("dem") or 0, v.get("rep") or 0, v.get("other") or 0
        parts = rid.split("-")
        chamber = "senate" if "SEN" in parts else "governor" if "GOV" in parts else "house"
        if chamber == "house":
            house["dem"] += d
            house["rep"] += rep
            house["other"] += oth
        winner = (manual.get(rid) or {}).get("winner") or (r.get("winner") if r.get("status") == "called" else None)
        if winner in ("dem", "D"):
            seats[chamber]["D"] += 1
        elif winner in ("rep", "R"):
            seats[chamber]["R"] += 1
        else:
            seats[chamber]["counting"] += 1
        if chamber != "house" and d + rep > 0:
            tot = d + rep + oth
            statewide.setdefault(parts[0], {})[("senate_special" if "SP" in parts else chamber)] = dict(
                margin=round(100 * (d - rep) / tot, 1), reporting=r.get("reporting"), status=r.get("status"))
    tot = sum(house.values())
    if not tot:
        return None
    nat = round(100 * (house["dem"] - house["rep"]) / tot, 2)
    for st, rr in statewide.items():
        for k, x in rr.items():
            x["vs_national_house"] = round(x["margin"] - nat, 1)
    return dict(as_of=res.get("updated_at"), house_vote=dict(house, margin=nat, dem_pct=round(100 * house["dem"] / tot, 1),
                                                                  rep_pct=round(100 * house["rep"] / tot, 1)),
                seats=seats, statewide=statewide)
