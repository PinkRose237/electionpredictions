"""Governor fundraising from FollowTheMoney (OpenSecrets/NIMSP state campaign-finance data).

Needs FOLLOWTHEMONEY_API_KEY (free account). Fills principal candidates that still lack money data
after the FEC and Wikipedia stages, and refreshes ones previously filled from Wikipedia.
API: https://api.followthemoney.org/?s=GA&y=2026&c-r-ot=G&gro=c-t-id&APIKey=...&mode=json
"""
from __future__ import annotations

import json
import re
from typing import Optional

from ..config import CYCLE, FOLLOWTHEMONEY_API_KEY, TTL_FEC
from ..db import log_run, now_iso, rows
from .http import get
from .races import same_person

API = "https://api.followthemoney.org/"


def _field(rec: dict, name: str) -> Optional[str]:
    v = rec.get(name)
    if isinstance(v, dict):
        return v.get(name) or v.get("id")
    return v


def parse_records(payload: dict) -> list[dict]:
    """Normalise FTM's {records: [{Candidate: {Candidate: 'LAST, FIRST'}, Total_$: {Total_$: '123'}, ...}]} shape."""
    out = []
    for rec in (payload or {}).get("records", []):
        name = _field(rec, "Candidate") or ""
        if not name:
            continue
        total = _field(rec, "Total_$")
        try:
            total_f = float(str(total).replace(",", "").replace("$", "")) if total not in (None, "") else None
        except ValueError:
            total_f = None
        if "," in name:  # 'INSLEE, JAY ROBERT' -> 'Jay Robert Inslee'
            last, first = [x.strip() for x in name.split(",", 1)]
            name = f"{first.title()} {last.title()}"
        out.append(dict(name=name, party=_field(rec, "General_Party") or _field(rec, "Specific_Party"),
                        office=_field(rec, "Office_Sought"), total=total_f, status=_field(rec, "Status_of_Candidate")))
    return out


def fetch_state(state: str, year: int = CYCLE) -> list[dict]:
    d = get(API, {"s": state, "y": year, "c-r-ot": "G", "gro": "c-t-id", "APIKey": FOLLOWTHEMONEY_API_KEY, "mode": "json"},
            kind="followthemoney", ttl=TTL_FEC)
    return parse_records(d) if isinstance(d, dict) else []


def load(con, verbose=True) -> dict:
    started = now_iso()
    if not FOLLOWTHEMONEY_API_KEY:
        if verbose:
            print("  followthemoney: skipped (no FOLLOWTHEMONEY_API_KEY)")
        return {"skipped": True}
    stats = {"states": 0, "filled": 0}
    for race in rows(con, "SELECT * FROM races WHERE chamber='governor'"):
        cands = rows(con, "SELECT * FROM candidates WHERE race_id=? AND major=1 AND (receipts IS NULL OR money_source='wikipedia')", (race["race_id"],))
        if not cands:
            continue
        recs = [r for r in fetch_state(race["state"]) if not r["office"] or "GOVERNOR" in str(r["office"]).upper() and "LIEUTENANT" not in str(r["office"]).upper()]
        stats["states"] += 1
        for c in cands:
            hit = next((r for r in recs if r["total"] and same_person(r["name"], c["name"])), None)
            if hit:
                con.execute("UPDATE candidates SET receipts=?, money_source='followthemoney' WHERE race_id=? AND name=?", (hit["total"], race["race_id"], c["name"]))
                stats["filled"] += 1
        con.commit()
    if verbose:
        print(f"  followthemoney: {stats}")
    log_run(con, "followthemoney", started, True, json.dumps(stats))
    return stats
