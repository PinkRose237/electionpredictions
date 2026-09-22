"""Expert race ratings (Cook, Sabato, Inside Elections, DDHQ, Silver Bulletin, ...) from Wikipedia's
aggregation tables."""
from __future__ import annotations

import re
from typing import Optional

from dateutil import parser as dtparser

from ..config import STATES
from ..db import upsert
from ..util import clean, parse_rating, race_id, state_abbr
from .races import HOUSE_PAGE, GOV_PAGE, SENATE_PAGE, _col, _district_number, _row_str
from .wikipedia import extract_tables, find_tables, page_html

HOUSE_RATINGS_PAGE = "2026 United States House of Representatives election ratings"

RATER_NAMES = {
    "cook": "Cook Political Report",
    "ie": "Inside Elections",
    "sabato": "Sabato's Crystal Ball",
    "econ": "The Economist",
    "st": "Split Ticket",
    "ddhq": "Decision Desk HQ",
    "fpo": "FPO",
    "fox": "Fox News",
    "rcp": "RealClearPolitics",
    "silver": "Silver Bulletin",
    "cnalysis": "CNalysis",
    "politico": "Politico",
    "elections daily": "Elections Daily",
    "ed": "Elections Daily",
    "270towin": "270toWin",
    "rttwh": "Race to the WH",
}


def _parse_rater_header(col: str) -> Optional[tuple[str, Optional[str]]]:
    """'Cook Sep. 11, 2026' -> ('Cook Political Report', '2026-09-11')"""
    c = clean(col)
    m = re.match(r"^([A-Za-z0-9'&\. ]+?)\s+([A-Z][a-z]{2,8}\.?\s+\d{1,2},?\s+\d{4})", c)
    if not m:
        return None
    key = m.group(1).strip().lower().rstrip(".")
    name = RATER_NAMES.get(key, m.group(1).strip())
    try:
        as_of = dtparser.parse(m.group(2).replace(".", "")).date().isoformat()
    except (ValueError, OverflowError):
        as_of = None
    return name, as_of


def _ratings_from_table(df, id_fn) -> list[dict]:
    out = []
    rater_cols = [(c, _parse_rater_header(c)) for c in df.columns]
    rater_cols = [(c, r) for c, r in rater_cols if r]
    for _, row in df.iterrows():
        rid = id_fn(row)
        if not rid:
            continue
        for c, (rater, as_of) in rater_cols:
            pr = parse_rating(row[c])
            if not pr:
                continue
            party, level, flip = pr
            out.append(dict(race_id=rid, rater=rater, rating=clean(row[c]), party=party, level=level, flip=int(flip), as_of=as_of))
    return out


def senate_ratings() -> list[dict]:
    tables = extract_tables(page_html(SENATE_PAGE))
    out = []
    for t in find_tables(tables, endswith=["Predictions"]):
        df = t.flat()
        sc = _col(df, "State")
        if not sc:
            continue

        def id_fn(row):
            raw = _row_str(row, sc)
            st = state_abbr(raw)
            return race_id("senate", st, special="special" in raw.lower()) if st else None

        out.extend(_ratings_from_table(df, id_fn))
    return out


def governor_ratings() -> list[dict]:
    tables = extract_tables(page_html(GOV_PAGE))
    out = []
    for t in find_tables(tables, endswith=["Predictions"]):
        df = t.flat()
        sc = _col(df, "State")
        if not sc:
            continue

        def id_fn(row):
            st = state_abbr(_row_str(row, sc))
            return race_id("governor", st) if st else None

        out.extend(_ratings_from_table(df, id_fn))
    return out


def house_ratings() -> tuple[list[dict], dict[str, float]]:
    """Returns ratings rows plus a {race_id: pvi} map from the ratings page (CPVI column)."""
    from ..util import parse_pvi

    tables = extract_tables(page_html(HOUSE_RATINGS_PAGE))
    out, pvis = [], {}
    for t in tables:
        df = t.flat()
        dc = _col(df, "District")
        if not dc or not any(_parse_rater_header(c) for c in df.columns):
            continue
        pvc = _col(df, "PVI")

        def id_fn(row):
            loc = _row_str(row, dc)
            st = state_abbr(re.sub(r"\s+(\d+|at-large)$", "", loc, flags=re.I))
            dist = _district_number(loc)
            if st is None or dist is None:
                return None
            rid = race_id("house", st, dist)
            if pvc:
                pv = parse_pvi(row[pvc])
                if pv is not None:
                    pvis[rid] = pv
            return rid

        out.extend(_ratings_from_table(df, id_fn))
    return out, pvis


def load_all(con) -> dict:
    counts = {}
    sen = senate_ratings()
    gov = governor_ratings()
    hou, pvis = house_ratings()
    con.execute("DELETE FROM ratings")
    upsert(con, "ratings", sen + gov + hou, keys=["race_id", "rater"])
    for rid, pv in pvis.items():
        con.execute("UPDATE races SET pvi=? WHERE race_id=? AND (pvi IS NULL OR pvi<>?)", (pv, rid, pv))
    con.commit()
    counts.update(senate=len(sen), governor=len(gov), house=len(hou), house_pvi_updates=len(pvis))
    return counts
