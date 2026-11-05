"""Presidential job approval: the aggregator table on Wikipedia's "Opinion polling on the second Trump presidency".

The incumbent president's net approval is the main input of the fundamentals estimate of the national
environment (the White House party is defending an open seat in 2028)."""
from __future__ import annotations

import json

from dateutil import parser as dtparser

from ..db import log_run, now_iso, upsert
from ..util import clean, parse_pct
from .wikipedia import extract_tables, page_html

PAGE = "Opinion polling on the second Trump presidency"


def parse(df) -> list[dict]:
    cols = list(df.columns)
    agg = next((c for c in cols if c.lower().startswith("aggregator")), None)
    upd = next((c for c in cols if c.lower().startswith("updated")), None)
    ap = next((c for c in cols if c.lower().startswith("approve")), None)
    dis = next((c for c in cols if c.lower().startswith("disapprove")), None)
    if not (agg and ap and dis):
        return []
    out = []
    for _, row in df.iterrows():
        a, d = parse_pct(row[ap]), parse_pct(row[dis])
        src = clean(row[agg])
        if a is None or d is None or not src:
            continue
        try:
            as_of = dtparser.parse(clean(row[upd])).date().isoformat() if upd else now_iso()[:10]
        except (ValueError, OverflowError):
            as_of = now_iso()[:10]
        out.append(dict(source=src, as_of=as_of, approve=a, disapprove=d, net=round(a - d, 2)))
    return out


def fetch() -> list[dict]:
    for t in extract_tables(page_html(PAGE) or ""):
        low = [p.lower() for p in t.path]
        if "aggregate polls" in low and low[-1] == "approval":
            return parse(t.flat())
    return []


def load(con, verbose: bool = False) -> dict:
    started = now_iso()
    rs = fetch()
    upsert(con, "approval", rs, keys=["source", "as_of"])
    con.commit()
    avg = next((r for r in rs if r["source"].lower() == "average"), None)
    res = dict(aggregators=len(rs), net=avg["net"] if avg else None)
    log_run(con, "approval", started, bool(rs), json.dumps(res))
    return res
