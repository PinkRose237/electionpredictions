"""Economic indicators from the Bureau of Labor Statistics public API (no key needed).

- LNS14000000  unemployment rate (seasonally adjusted, %)
- CUUR0000SA0  CPI-U, all items (index; year-over-year inflation is computed from it)
- CES0500000013 real average hourly earnings, all private employees (1982-84 dollars)
"""
from __future__ import annotations

import json
import time
from datetime import date

import requests

from ..config import CACHE_DIR, TTL_ECON, USER_AGENT
from ..db import log_run, now_iso, rows, upsert

API = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
SERIES = {"LNS14000000": "unemployment", "CUUR0000SA0": "cpi", "CES0500000013": "real_wages"}


def fetch(today: date | None = None) -> list[dict]:
    today = today or date.today()
    cache = CACHE_DIR / "bls" / f"{today.isoformat()[:7]}.json"
    payload = None
    if cache.exists() and (time.time() - cache.stat().st_mtime) < TTL_ECON:
        payload = json.loads(cache.read_text())
    if payload is None:
        r = requests.post(API, json={"seriesid": list(SERIES), "startyear": str(today.year - 2), "endyear": str(today.year)},
                          headers={"User-Agent": USER_AGENT}, timeout=60)
        r.raise_for_status()
        payload = r.json()
        if payload.get("status") != "REQUEST_SUCCEEDED":
            raise RuntimeError(f"BLS: {payload.get('message')}")
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(payload))
    out = []
    for s in payload["Results"]["series"]:
        name = SERIES.get(s["seriesID"])
        for x in s["data"]:
            if not x["period"].startswith("M") or x["period"] == "M13":
                continue
            try:
                v = float(x["value"])
            except ValueError:
                continue
            out.append(dict(series=name, period=f"{x['year']}-{x['period'][1:]}", value=v))
    return out


def indicators(con) -> dict:
    """Latest level and 12-month changes: unemployment change, CPI inflation, real wage growth."""
    by: dict[str, dict[str, float]] = {}
    for r in rows(con, "SELECT * FROM economy"):
        by.setdefault(r["series"], {})[r["period"]] = r["value"]
    out: dict = {}

    def yoy(series):
        s = by.get(series) or {}
        if not s:
            return None, None, None
        last = max(s)
        y, m = int(last[:4]), last[5:]
        prev = f"{y - 1}-{m}"
        return last, s[last], s.get(prev)

    p, u, u0 = yoy("unemployment")
    if u is not None:
        out.update(as_of=p, unemployment=u, unemployment_change=round(u - u0, 2) if u0 is not None else None)
    p, c, c0 = yoy("cpi")
    if c is not None and c0:
        out["inflation"] = round(100 * (c / c0 - 1), 2)
        out.setdefault("as_of", p)
    p, w, w0 = yoy("real_wages")
    if w is not None and w0:
        out["real_wage_growth"] = round(100 * (w / w0 - 1), 2)
    return out


def load(con, verbose: bool = False) -> dict:
    started = now_iso()
    rs = fetch()
    upsert(con, "economy", rs, keys=["series", "period"])
    con.commit()
    res = indicators(con)
    log_run(con, "economy", started, bool(rs), json.dumps(res))
    return res
