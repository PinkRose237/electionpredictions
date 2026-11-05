"""State-level expert ratings for 2028 (Cook, Inside Elections, Sabato, ...), once raters publish them.

Read from the "Predictions" table(s) of Wikipedia's 2028 presidential election article: one row per state (or
congressional district for Maine/Nebraska), one column per rater with the date in the header."""
from __future__ import annotations

import json
import re
from typing import Optional

from dateutil import parser as dtparser

from ..config import CONTEST_EVS, STATE_BY_NAME
from ..db import log_run, now_iso, upsert
from ..util import clean, parse_rating
from .wikipedia import extract_tables, page_html

PAGE = "2028 United States presidential election"
RATER_NAMES = {
    "cook": "Cook Political Report", "ie": "Inside Elections", "sabato": "Sabato's Crystal Ball", "econ": "The Economist",
    "st": "Split Ticket", "ddhq": "Decision Desk HQ", "cnalysis": "CNalysis", "cnn": "CNN", "npr": "NPR",
    "270towin": "270toWin", "silver": "Silver Bulletin", "fox": "Fox News", "rcp": "RealClearPolitics",
}


def rater_header(col: str) -> Optional[tuple[str, Optional[str]]]:
    """'Cook Sep. 11, 2027' -> ('Cook Political Report', '2027-09-11'); 'Sabato' -> ("Sabato's Crystal Ball", None)."""
    c = clean(col)
    m = re.match(r"^([A-Za-z0-9'&\. ]+?)(?:\s+([A-Z][a-z]{2,8}\.?\s+\d{1,2},?\s+\d{4}))?$", c)
    if not m:
        return None
    key = m.group(1).strip().lower().rstrip(".")
    if key in ("state", "evs", "ev", "electoral votes", "pvi", "2024 result", "result", "2024"):
        return None
    name = RATER_NAMES.get(key.split()[0] if key.split() else key, m.group(1).strip())
    as_of = None
    if m.group(2):
        try:
            as_of = dtparser.parse(m.group(2).replace(".", "")).date().isoformat()
        except (ValueError, OverflowError):
            as_of = None
    return name, as_of


def contest_of(cell: str) -> Optional[str]:
    s = clean(cell)
    m = re.match(r"^(ME|NE)[-–](\d)", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    m = re.match(r"^(Maine|Nebraska)'s (\d)", s, re.I)
    if m:
        return f"{STATE_BY_NAME[m.group(1).title()]}-{m.group(2)}"
    s = re.sub(r"\s*\(.*?\)|†", "", s).strip()
    if s in ("D.C.", "Washington, D.C.", "District of Columbia"):
        return "DC"
    return STATE_BY_NAME.get(s)


def fetch() -> list[dict]:
    out = []
    for t in extract_tables(page_html(PAGE) or ""):
        if not t.path or "prediction" not in t.path[-1].lower():
            continue
        df = t.flat()
        sc = next((c for c in df.columns if c.lower().startswith("state")), None)
        if not sc:
            continue
        raters = [(c, rater_header(c)) for c in df.columns if c != sc]
        raters = [(c, r) for c, r in raters if r]
        for _, row in df.iterrows():
            cid = contest_of(row[sc])
            if cid not in CONTEST_EVS:
                continue
            for c, (rater, as_of) in raters:
                pr = parse_rating(row[c])
                if pr:
                    out.append(dict(contest_id=cid, rater=rater, rating=clean(row[c]), party=pr[0], level=pr[1], as_of=as_of))
    return out


def load(con, verbose: bool = False) -> dict:
    started = now_iso()
    rs = fetch()
    con.execute("DELETE FROM ratings")
    upsert(con, "ratings", rs, keys=["contest_id", "rater"])
    con.commit()
    res = dict(ratings=len(rs), raters=len({r["rater"] for r in rs}))
    log_run(con, "ratings", started, True, json.dumps(res))
    return res
