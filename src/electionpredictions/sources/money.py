"""Presidential campaign fundraising from the FEC API (office P, 2028 cycle).

With the shared DEMO_KEY the API allows only a handful of requests an hour; this stage makes one or two.
Context for the candidate field page and the model-revision step."""
from __future__ import annotations

import json
import re
import unicodedata

from ..config import FEC_API_KEY, TTL_FEC
from ..db import log_run, now_iso, rows, upsert
from .http import get

BASE = "https://api.open.fec.gov/v1"
PARTY = {"DEM": "D", "REP": "R"}


def _ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().upper()


def fetch(max_pages: int = 2) -> list[dict]:
    out = []
    for page in range(1, max_pages + 1):
        d = get(f"{BASE}/candidates/totals/", dict(api_key=FEC_API_KEY, cycle=2028, election_year=2028, office="P", per_page=100,
                                                     page=page, sort="-receipts", election_full="true"), kind="fec", ttl=TTL_FEC, retries=1)
        if not d:
            break
        out.extend(d.get("results") or [])
        if page >= (d.get("pagination") or {}).get("pages", 1):
            break
    return out


def match(name: str, party: str, fec_rows: list[dict]):
    toks = _ascii(re.sub(r"\s+(Jr\.?|Sr\.?|II|III)$", "", name)).replace(".", "").split()
    if not toks:
        return None
    last, first = toks[-1], toks[0]
    hits = []
    for f in fec_rows:
        fl = _ascii(f.get("name", "")).replace(".", "")
        surname = fl.split(",")[0].strip()
        if last not in re.split(r"[\s\-]+", surname):
            continue
        if PARTY.get(f.get("party") or "") not in (None, party):
            continue
        hits.append((first[:2] in fl.split(",")[-1][:6], f.get("receipts") or 0, f))
    if not hits:
        return None
    hits.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return hits[0][2]


def load(con, verbose: bool = False) -> dict:
    started = now_iso()
    fec = fetch()
    cands = rows(con, "SELECT party, name FROM candidates")
    out = []
    for c in cands:
        f = match(c["name"], c["party"], fec)
        if not f or not f.get("receipts"):
            continue
        out.append(dict(name=c["name"], party=c["party"], candidate_id=f.get("candidate_id"), receipts=f.get("receipts"),
                        disbursements=f.get("disbursements"), cash=f.get("last_cash_on_hand_end_period") or f.get("cash_on_hand_end_period"),
                        coverage_end=(f.get("coverage_end_date") or "")[:10] or None, source="fec"))
    if out:
        con.execute("DELETE FROM money")
        upsert(con, "money", out, keys=["name"])
        con.commit()
    res = dict(fec_rows=len(fec), matched=len(out))
    log_run(con, "money", started, True, json.dumps(res))
    return res
