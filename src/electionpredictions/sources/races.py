"""Build the race universe (Senate, governor, House) and candidate lists from Wikipedia."""
from __future__ import annotations

import re
from typing import Optional

import pandas as pd

from ..config import STATES
from ..db import now_iso, upsert
from ..util import clean, parse_pvi, race_id, split_candidates, state_abbr
from .wikipedia import extract_tables, find_tables, link_map, page_html

SENATE_PAGE = "2026 United States Senate elections"
HOUSE_PAGE = "2026 United States House of Representatives elections"
GOV_PAGE = "2026 United States gubernatorial elections"


def _col(df: pd.DataFrame, *names: str) -> Optional[str]:
    """Find the first column whose name contains any of the given substrings (case-insensitive)."""
    for n in names:
        for c in df.columns:
            if n.lower() in str(c).lower():
                return c
    return None


def _incumbent_running(status: str, incumbent: str) -> Optional[int]:
    s = status.lower()
    if not incumbent or incumbent.lower() in {"vacant", "none", "new seat", "n/a"}:
        return 0
    if any(k in s for k in ("retir", "term-limited", "term limited", "lost", "resign", "withdr", "not seeking", "defeated", "running for", "died", "deceased")):
        return 0
    if any(k in s for k in ("renominated", "advanced", "running", "seeking", "unopposed", "nominated")):
        return 1
    return None


def _norm_name(n: str) -> str:
    n = clean(n).lower()
    n = re.sub(r"\(.*?\)", "", n)
    n = re.sub(r"[^a-z ]", "", n)
    toks = [t for t in n.split() if len(t) > 1 and t not in {"jr", "sr", "ii", "iii", "iv"}]
    return " ".join(toks)


def same_person(a: str, b: str) -> bool:
    na, nb = _norm_name(a), _norm_name(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    ta, tb = na.split(), nb.split()
    # same last name and same first token (handles middle initials, nicknames not handled)
    return bool(ta and tb and ta[-1] == tb[-1] and ta[0] == tb[0])


def principal_candidates(cands: list[tuple[str, str]], incumbent: str | None) -> tuple[Optional[tuple[str, str]], Optional[tuple[str, str]]]:
    """Pick the Democratic-side and Republican-side principal candidate.

    An independent stands in for a missing major-party nominee (e.g. Nebraska Senate)."""
    def pick(party: str):
        same = [c for c in cands if c[1] == party]
        if not same:
            return None
        if incumbent:
            for c in same:
                if same_person(c[0], incumbent):
                    return c
        return same[0]

    d, r = pick("D"), pick("R")
    inds = [c for c in cands if c[1] == "I"]
    if d is None and inds:
        d = inds[0]
    elif r is None and inds and d is not None:
        r = inds[0]
    return d, r


def _row_str(row, col) -> str:
    return clean(row[col]) if col is not None and col in row.index else ""


def build_senate() -> tuple[list[dict], list[dict]]:
    html = page_html(SENATE_PAGE)
    tables = extract_tables(html)
    races, cands = [], []
    pvi_by_state: dict[str, float] = {}
    for t in find_tables(tables, endswith=["Predictions"]):
        df = t.flat()
        sc, pc = _col(df, "State"), _col(df, "PVI")
        if sc and pc:
            for _, row in df.iterrows():
                st = _row_str(row, sc)
                pvi_by_state[st] = parse_pvi(row[pc])
    for special, suffix in ((False, "Elections leading to the next Congress"), (True, "Special elections during the preceding Congress")):
        for t in find_tables(tables, endswith=[suffix]):
            df = t.flat()
            sc = _col(df, "State")
            if sc is None or _col(df, "Candidates") is None:
                continue
            nc, pc, stc, cc, pvc, lr = _col(df, "Senator"), _col(df, "Party"), _col(df, "Results", "Status"), _col(df, "Candidates"), _col(df, "PVI"), _col(df, "Last race", "Last election")
            links = link_map(t.html)
            for _, row in df.iterrows():
                st_raw = _row_str(row, sc)
                st = state_abbr(st_raw)
                if not st:
                    continue
                rid = race_id("senate", st, special=special)
                incumbent = _row_str(row, nc)
                incumbent = re.sub(r"\s*\((retiring|term-limited|appointed).*?\)", "", incumbent, flags=re.I)
                party = _party(_row_str(row, pc))
                status = _row_str(row, stc)
                clist = split_candidates(row[cc]) if cc else []
                pvi = parse_pvi(row[pvc]) if pvc else None
                if pvi is None:
                    pvi = pvi_by_state.get(st_raw) or pvi_by_state.get(STATES[st])
                races.append(dict(
                    race_id=rid, chamber="senate", state=st, district=None, special=int(special),
                    name=f"{STATES[st]} Senate" + (" (special)" if special else ""),
                    incumbent=incumbent or None, incumbent_party=party, incumbent_running=_incumbent_running(status, incumbent),
                    holder_party=party, pvi=pvi, last_result=_row_str(row, lr) or None, status=status or None,
                    wiki_title=None, updated_at=now_iso(),
                ))
                cands.extend(_cand_rows(rid, clist, incumbent, links))
    return races, cands


def build_governors() -> tuple[list[dict], list[dict]]:
    html = page_html(GOV_PAGE)
    tables = extract_tables(html)
    races, cands = [], []
    pvi_by_state: dict[str, float] = {}
    for t in find_tables(tables, endswith=["Predictions"]):
        df = t.flat()
        sc, pc = _col(df, "State"), _col(df, "PVI")
        if sc and pc:
            for _, row in df.iterrows():
                pvi_by_state[_row_str(row, sc)] = parse_pvi(row[pc])
    for t in find_tables(tables, endswith=["Race summary", "States"]):
        df = t.flat()
        sc, cc = _col(df, "State"), _col(df, "Candidates")
        if sc is None or cc is None:
            continue
        nc, pc, stc, lr = _col(df, "Governor"), _col(df, "Party"), _col(df, "Status"), _col(df, "Last race")
        links = link_map(t.html)
        for _, row in df.iterrows():
            st = state_abbr(_row_str(row, sc))
            if not st:
                continue
            rid = race_id("governor", st)
            incumbent = _row_str(row, nc)
            party = _party(_row_str(row, pc))
            status = _row_str(row, stc)
            clist = split_candidates(row[cc])
            races.append(dict(
                race_id=rid, chamber="governor", state=st, district=None, special=0,
                name=f"{STATES[st]} Governor",
                incumbent=incumbent or None, incumbent_party=party, incumbent_running=_incumbent_running(status, incumbent),
                holder_party=party, pvi=pvi_by_state.get(STATES[st]), last_result=_row_str(row, lr) or None,
                status=status or None, wiki_title=None, updated_at=now_iso(),
            ))
            cands.extend(_cand_rows(rid, clist, incumbent, links))
    return races, cands


def build_house() -> tuple[list[dict], list[dict]]:
    html = page_html(HOUSE_PAGE)
    tables = extract_tables(html)
    races, cands = [], []
    grouped: dict[str, list[dict]] = {}
    for t in tables:
        if not t.path or t.path[-1] not in STATES.values():
            continue
        st = state_abbr(t.path[-1])
        df = t.flat()
        dc, cc = _col(df, "Location", "District"), _col(df, "Candidates")
        if dc is None or cc is None:
            continue
        pvc, mc, pc, stc = _col(df, "PVI"), _col(df, "Member", "Incumbent"), _col(df, "Party"), _col(df, "Status")
        links = link_map(t.html)
        for _, row in df.iterrows():
            loc = _row_str(row, dc)
            dist = _district_number(loc)
            if dist is None:
                continue
            rid = race_id("house", st, dist)
            raw_inc = _row_str(row, mc)
            status = _row_str(row, stc)
            incumbent = re.sub(r"\s*Redistricted from.*$", "", raw_inc, flags=re.I).strip()
            incumbent = re.sub(r"\s*\(.*?\)", "", incumbent).strip()
            if not incumbent or re.match(r"^(vacant|none|new seat|n/a|tbd)$", incumbent, re.I):
                incumbent = None
            party = _party(_row_str(row, pc)) if incumbent else None
            holder = party
            if incumbent is None:
                m = re.search(r"\((D|R|I)\)\s*(resigned|died)", status)
                holder = m.group(1) if m else None
            grouped.setdefault(rid, []).append(dict(
                st=st, dist=dist, incumbent=incumbent, party=party, holder=holder, status=status,
                running=_incumbent_running(status, incumbent or ""),
                pvi=parse_pvi(row[pvc]) if pvc else None, clist=split_candidates(row[cc]), links=links,
            ))
    for rid, rows_ in grouped.items():
        # prefer the row whose incumbent is actually on the November ballot, then any named incumbent
        best = next((r for r in rows_ if r["running"] == 1 and r["incumbent"]), None) or \
               next((r for r in rows_ if r["incumbent"]), None) or rows_[0]
        st, dist = best["st"], best["dist"]
        holder = best["holder"] or next((r["holder"] for r in rows_ if r["holder"]), None)
        races.append(dict(
            race_id=rid, chamber="house", state=st, district=dist, special=0,
            name=f"{st}-{dist:02d}" if dist else f"{st} at-large",
            incumbent=best["incumbent"], incumbent_party=best["party"],
            incumbent_running=best["running"] if best["incumbent"] else 0,
            holder_party=holder, pvi=best["pvi"], last_result=None,
            status=" / ".join(dict.fromkeys(r["status"] for r in rows_ if r["status"])) or None,
            wiki_title=None, updated_at=now_iso(),
        ))
        cands.extend(_cand_rows(rid, best["clist"], best["incumbent"], best["links"]))
    return races, cands


def _district_number(loc: str) -> Optional[int]:
    loc = clean(loc)
    if not loc:
        return None
    if re.search(r"at-large|at large", loc, re.I):
        return 0
    m = re.search(r"(\d+)\s*$", loc)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)(st|nd|rd|th)", loc)
    return int(m.group(1)) if m else None


def _party(s: str) -> Optional[str]:
    s = clean(s).lower()
    if not s:
        return None
    if s.startswith(("democratic", "democrat", "dfl")):
        return "D"
    if s.startswith("republican"):
        return "R"
    if s.startswith("independent"):
        return "I"
    return "O"


def is_incumbent_name(name: str, incumbent: str | None, links: dict[str, str] | None = None) -> bool:
    """Match a candidate to the incumbent, preferring article links over name similarity."""
    if not incumbent:
        return False
    if links:
        h_inc = links.get(incumbent) or next((h for t, h in links.items() if same_person(t, incumbent)), None)
        h_c = links.get(name)
        if h_inc and h_c:
            return h_inc == h_c
        if h_inc and not h_c:
            # incumbent is linked but this candidate is not -> different (unlinked) person
            return False
    return same_person(name, incumbent)


def principal_candidates_linked(clist, incumbent, links):
    def pick(party):
        same = [c for c in clist if c[1] == party]
        if not same:
            return None
        for c in same:
            if is_incumbent_name(c[0], incumbent, links):
                return c
        return same[0]
    d, r = pick("D"), pick("R")
    inds = [c for c in clist if c[1] == "I"]
    if d is None and inds:
        d = inds[0]
    elif r is None and inds and d is not None:
        r = inds[0]
    return d, r


def _cand_rows(rid: str, clist: list[tuple[str, str]], incumbent: str | None, links: dict[str, str] | None = None) -> list[dict]:
    d, r = principal_candidates_linked(clist, incumbent, links)
    out = []
    seen = set()
    for name, party in clist:
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(dict(
            race_id=rid, name=name, party=party,
            is_incumbent=int(is_incumbent_name(name, incumbent, links)),
            major=int((d is not None and name == d[0]) or (r is not None and name == r[0])),
            fec_id=None, receipts=None, disbursements=None, cash_on_hand=None, coverage_end=None,
        ))
    return out


def load_all(con) -> dict:
    counts = {}
    for label, fn in (("senate", build_senate), ("governor", build_governors), ("house", build_house)):
        races, cands = fn()
        upsert(con, "races", races, keys=["race_id"])
        # replace candidate lists wholesale for these races (keep FEC columns if same name)
        for r in races:
            con.execute("DELETE FROM candidates WHERE race_id=? AND name NOT IN (%s)" % ",".join("?" * len([c for c in cands if c["race_id"] == r["race_id"]]) or "''"),
                        [r["race_id"]] + [c["name"] for c in cands if c["race_id"] == r["race_id"]])
        for c in cands:
            con.execute(
                "INSERT INTO candidates (race_id,name,party,is_incumbent,major) VALUES (?,?,?,?,?) "
                "ON CONFLICT(race_id,name) DO UPDATE SET party=excluded.party, is_incumbent=excluded.is_incumbent, major=excluded.major",
                (c["race_id"], c["name"], c["party"], c["is_incumbent"], c["major"]),
            )
        con.commit()
        counts[label] = (len(races), len(cands))
    return counts
