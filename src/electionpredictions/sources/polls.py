"""General-election trial heats for 2028 (named matchups), national and statewide.

Source: the "Opinion polling > General election" section of Wikipedia's 2028 presidential election article,
one table per matchup under headings like "Nationwide > JD Vance vs. Gavin Newsom" or
"Statewide > Nevada > JD Vance vs. Gavin Newsom". Column headers carry surnames with a party tag
("Vance (R)"); the heading carries the full names, which we map the surnames back onto.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Optional

from ..config import STATE_BY_NAME
from ..db import log_run, now_iso, upsert
from ..util import clean, parse_date_range, parse_pct, parse_sample, party_code
from .wikipedia import WikiTable, extract_tables, page_html

PAGE = "2028 United States presidential election"
HEAD_RE = re.compile(r"^(?P<name>.+?)\s*\((?P<party>[A-Za-z.]+)\)\s*$")
SKIP_COLS = ("poll", "date", "sample", "margin", "moe", "source", "lead", "undecided", "other", "unnamed", "refused")


def _pollster(src: str) -> tuple[str, Optional[str]]:
    s = clean(src)
    tags = re.findall(r"\(([DR])\)", s)
    lean = tags[0] if len(set(tags)) == 1 else None
    s = re.sub(r"\s*\([DR]\)", "", s)
    return s.strip(" /") or "Unknown", lean


def heading_names(heading: str) -> list[str]:
    """'JD Vance vs. Gavin Newsom vs. Aaron Rodgers as an Independent' -> ['JD Vance', 'Gavin Newsom', 'Aaron Rodgers']"""
    parts = re.split(r"\s+vs\.?\s+", clean(heading))
    return [re.sub(r"\s+as an? .*$", "", p).strip() for p in parts if p.strip()]


def _full_name(surname: str, names: list[str]) -> str:
    s = surname.lower().strip()
    for n in names:
        nl = n.lower()
        if nl == s or nl.endswith(" " + s) or s in nl.split():
            return n
    return surname


def parse_matchup_table(t: WikiTable, scope: str, contest_id: Optional[str]) -> list[dict]:
    df = t.flat()
    cols = list(df.columns)
    src = next((c for c in cols if c.lower().startswith(("poll source", "pollster", "polling firm"))), None)
    dates = next((c for c in cols if c.lower().startswith("date")), None)
    sample = next((c for c in cols if c.lower().startswith("sample")), None)
    if not src or not dates:
        return []
    names = heading_names(t.path[-1])
    cand_cols = []
    for c in cols:
        m = HEAD_RE.match(c)
        if not m or c.lower().startswith(SKIP_COLS):
            continue
        cand_cols.append((c, _full_name(m.group("name"), names), party_code(m.group("party"))))
    dem = next(((c, n) for c, n, p in cand_cols if p == "D"), None)
    rep = next(((c, n) for c, n, p in cand_cols if p == "R"), None)
    if not dem or not rep:
        return []
    und = next((c for c in cols if c.lower().startswith("undecided")), None)
    out = []
    for _, row in df.iterrows():
        pollster, lean = _pollster(row[src])
        if not pollster or pollster.lower().startswith(("aggregat", "average")):
            continue
        start, end = parse_date_range(row[dates])
        d, r = parse_pct(row[dem[0]]), parse_pct(row[rep[0]])
        if end is None or d is None or r is None:
            continue
        n, pop = parse_sample(row[sample]) if sample else (None, None)
        matchup = [[nm, p, parse_pct(row[c])] for c, nm, p in cand_cols]
        third = [m for m in matchup if m[1] not in ("D", "R") and m[2] is not None]
        key = f"{scope}|{contest_id}|{pollster}|{end}|{dem[1]}|{rep[1]}|{len(third)}"
        out.append(dict(
            poll_id=hashlib.sha1(key.encode()).hexdigest()[:16], scope=scope, contest_id=contest_id,
            pollster=pollster, sponsor_lean=lean, start_date=start.isoformat() if start else None, end_date=end.isoformat(),
            sample_size=n, population=pop, dem_name=dem[1], rep_name=rep[1], dem_pct=d, rep_pct=r,
            other_pct=sum(m[2] for m in third) if third else None, und_pct=parse_pct(row[und]) if und else None,
            matchup=json.dumps(matchup), source=f"wikipedia:{PAGE}",
        ))
    return out


def _contest_for(path: list[str]) -> Optional[str]:
    """Statewide tables sit under 'Statewide > <State>' (or '<State>'s 2nd congressional district')."""
    for p in path:
        m = re.match(r"^(Maine|Nebraska)'s (\d)(st|nd|rd) congressional district", p, re.I)
        if m:
            return f"{STATE_BY_NAME[m.group(1).title()]}-{m.group(2)}"
    for p in reversed(path[:-1]):
        st = STATE_BY_NAME.get(clean(p)) or ("DC" if clean(p) in ("Washington, D.C.", "D.C.") else None)
        if st:
            return st
    return None


def fetch() -> list[dict]:
    tables = extract_tables(page_html(PAGE))
    out, seen = [], set()
    for t in tables:
        low = [p.lower() for p in t.path]
        if "general election" not in low or " vs" not in (t.path[-1] if t.path else "").lower():
            continue
        if "nationwide" in low:
            scope, cid = "national", None
        elif "statewide" in low:
            scope, cid = "state", _contest_for(t.path)
            if not cid:
                continue
        else:
            continue
        for p in parse_matchup_table(t, scope, cid):
            if p["poll_id"] not in seen:
                seen.add(p["poll_id"])
                out.append(p)
    return out


def load(con, verbose: bool = False) -> dict:
    started = now_iso()
    polls = fetch()
    con.execute("DELETE FROM polls")
    upsert(con, "polls", polls, keys=["poll_id"])
    con.commit()
    res = dict(national=sum(p["scope"] == "national" for p in polls), state=sum(p["scope"] == "state" for p in polls))
    log_run(con, "polls", started, True, json.dumps(res))
    return res
