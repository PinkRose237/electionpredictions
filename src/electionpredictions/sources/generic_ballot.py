"""Generic congressional ballot: the aggregator averages table on the House elections page."""
from __future__ import annotations

import re

from dateutil import parser as dtparser

from ..config import CYCLE
from ..db import upsert
from ..util import clean, parse_pct
from .races import HOUSE_PAGE, _col, _row_str
from .wikipedia import extract_tables, find_tables, page_html

# National trial-heat polling for 2028. Its tables are matchup-specific (named candidates), so
# there is usually no generic-average table to read; when absent the environment stays neutral.
PRES_AVG_PAGE = "Nationwide opinion polling for the 2028 United States presidential election"


def fetch() -> list[dict]:
    tables = extract_tables(page_html(HOUSE_PAGE))
    out = []
    for t in find_tables(tables, contains=["Generic congressional ballot"]):
        df = t.flat()
        sc, dc, rc, uc = _col(df, "Source"), _col(df, "Democrat"), _col(df, "Republican"), _col(df, "Dates updated", "updated")
        if not (sc and dc and rc):
            continue
        for _, row in df.iterrows():
            src = re.sub(r"\[.*?\]", "", _row_str(row, sc)).strip()
            d, r = parse_pct(row[dc]), parse_pct(row[rc])
            if d is None or r is None:
                continue
            as_of = None
            if uc:
                try:
                    as_of = dtparser.parse(_row_str(row, uc)).date().isoformat()
                except (ValueError, OverflowError):
                    as_of = None
            out.append(dict(source=src or "unknown", as_of=as_of or "", dem=d, rep=r, margin=round(d - r, 2)))
    return out


def fetch_pres() -> list[dict]:
    """National D-vs-R average for 2028, if the nationwide polling page carries one."""
    tables = extract_tables(page_html(PRES_AVG_PAGE))
    out = []
    for t in find_tables(tables, contains=["Average", "Generic"]):
        df = t.flat()
        sc, dc, rc, uc = _col(df, "Source"), _col(df, "Democrat"), _col(df, "Republican"), _col(df, "Dates updated", "updated")
        if not (sc and dc and rc):
            continue
        for _, row in df.iterrows():
            src = re.sub(r"\[.*?\]", "", _row_str(row, sc)).strip()
            d, r = parse_pct(row[dc]), parse_pct(row[rc])
            if d is None or r is None:
                continue
            as_of = None
            if uc:
                try:
                    as_of = dtparser.parse(_row_str(row, uc)).date().isoformat()
                except (ValueError, OverflowError):
                    as_of = None
            out.append(dict(source=src or "unknown", as_of=as_of or "", dem=d, rep=r, margin=round(d - r, 2)))
    return out


def load(con) -> int:
    rows = fetch_pres() if CYCLE == 2028 else fetch()
    n = upsert(con, "generic_ballot", rows, keys=["source", "as_of"])
    con.commit()
    return n
