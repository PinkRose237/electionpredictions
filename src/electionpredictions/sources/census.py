"""District and state demographics from the Census ACS 5-year API (needs CENSUS_API_KEY, free).

Used by the simulation to correlate errors across races with similar electorates (education, race),
so a polling miss among, say, college-educated suburbs moves the right seats together.
"""
from __future__ import annotations

import json

from ..config import CENSUS_API_KEY, REDISTRICTED_2026, TTL_FEC
from ..db import log_run, now_iso
from .http import get

ACS = "https://api.census.gov/data/2023/acs/acs5"
VARS = ["NAME", "B01003_001E", "B15003_001E", "B15003_022E", "B15003_023E", "B15003_024E", "B15003_025E",
        "B03002_001E", "B03002_003E", "B03002_004E", "B03002_012E"]
FIPS = {"01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO", "09": "CT", "10": "DE", "12": "FL", "13": "GA", "15": "HI",
        "16": "ID", "17": "IL", "18": "IN", "19": "IA", "20": "KS", "21": "KY", "22": "LA", "23": "ME", "24": "MD", "25": "MA", "26": "MI",
        "27": "MN", "28": "MS", "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH", "34": "NJ", "35": "NM", "36": "NY", "37": "NC",
        "38": "ND", "39": "OH", "40": "OK", "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD", "47": "TN", "48": "TX", "49": "UT",
        "50": "VT", "51": "VA", "53": "WA", "54": "WV", "55": "WI", "56": "WY"}
SQL = """
CREATE TABLE IF NOT EXISTS demographics (
    state TEXT NOT NULL, district INTEGER,         -- district NULL = whole state
    population INTEGER, pct_college REAL, pct_white_nh REAL, pct_black REAL, pct_hispanic REAL,
    PRIMARY KEY (state, district)
);
"""


def parse_table(table: list[list[str]], district: bool) -> list[dict]:
    """Census JSON is a header row followed by rows; returns dicts with derived percentages."""
    if not table or len(table) < 2:
        return []
    hdr = table[0]
    idx = {h: i for i, h in enumerate(hdr)}
    out = []
    for row in table[1:]:
        def num(k):
            try:
                v = float(row[idx[k]])
                return v if v >= 0 else None  # negative = suppressed
            except (KeyError, TypeError, ValueError):
                return None
        st = FIPS.get(row[idx["state"]]) if "state" in idx else None
        if not st:
            continue
        cd = row[idx["congressional district"]] if district and "congressional district" in idx else None
        if district:
            if cd in (None, "ZZ", "98"):
                continue
            dist = 0 if cd == "00" else int(cd)
        else:
            dist = None
        pop, adults = num("B01003_001E"), num("B15003_001E")
        coll = sum(num(k) or 0 for k in ("B15003_022E", "B15003_023E", "B15003_024E", "B15003_025E"))
        tot = num("B03002_001E")
        out.append(dict(state=st, district=dist, population=int(pop) if pop else None,
                        pct_college=100 * coll / adults if adults else None,
                        pct_white_nh=100 * (num("B03002_003E") or 0) / tot if tot else None,
                        pct_black=100 * (num("B03002_004E") or 0) / tot if tot else None,
                        pct_hispanic=100 * (num("B03002_012E") or 0) / tot if tot else None))
    return out


def load(con, verbose=True) -> dict:
    started = now_iso()
    if not CENSUS_API_KEY:
        if verbose:
            print("  census: skipped (no CENSUS_API_KEY)")
        return {"skipped": True}
    con.executescript(SQL)
    base = {"get": ",".join(VARS), "key": CENSUS_API_KEY}
    states = parse_table(get(ACS, dict(base, **{"for": "state:*"}), kind="census", ttl=TTL_FEC * 30) or [], district=False)
    dists = parse_table(get(ACS, dict(base, **{"for": "congressional district:*", "in": "state:*"}), kind="census", ttl=TTL_FEC * 30) or [], district=True)
    for r in states + dists:
        con.execute("INSERT OR REPLACE INTO demographics (state, district, population, pct_college, pct_white_nh, pct_black, pct_hispanic) VALUES (?,?,?,?,?,?,?)",
                    (r["state"], r["district"], r["population"], r["pct_college"], r["pct_white_nh"], r["pct_black"], r["pct_hispanic"]))
    con.commit()
    stats = {"states": len(states), "districts": len(dists), "redistricted_states_use_state_values": sorted(REDISTRICTED_2026)}
    if verbose:
        print(f"  census: {stats}")
    log_run(con, "census", started, True, json.dumps(stats))
    return stats
