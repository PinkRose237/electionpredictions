"""The 2028 nomination contests: candidate fields and national primary polling for both parties.

Sources (Wikipedia):
- "Nationwide opinion polling for the 2028 {Democratic,Republican} Party presidential primaries": the
  aggregator table ("Polling aggregation") and the individual polls, one table per year.
- "2028 {Democratic,Republican} Party presidential primaries" and the main 2028 article: declared and
  exploratory candidates (with their home state).
Everyone who appears in primary polling but has not declared is listed as a potential candidate.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Optional

from dateutil import parser as dtparser

from ..config import STATE_BY_NAME
from ..db import log_run, now_iso, rows, upsert
from ..util import clean, parse_date_range, parse_pct, parse_sample
from .wikipedia import extract_tables, page_html

PARTY_WORD = {"D": "Democratic", "R": "Republican"}
POLL_PAGE = "Nationwide opinion polling for the 2028 {} Party presidential primaries"
PRIMARY_PAGE = "2028 {} Party presidential primaries"
MAIN_PAGE = "2028 United States presidential election"
NON_CANDIDATE = ("poll", "date", "sample", "margin", "moe", "other", "undecided", "lead", "aggregator", "updated",
                 "source", "unnamed", "none", "someone", "refused", "don't", "no one", "not sure")

# Home states of frequently polled figures (the declared-candidate tables carry their own; this covers
# people who have not declared). Used for the home-state effect; the model revision can override it.
KNOWN_HOME_STATES = {
    "Gavin Newsom": "CA", "Kamala Harris": "CA", "Alexandria Ocasio-Cortez": "NY", "Pete Buttigieg": "MI",
    "Josh Shapiro": "PA", "Gretchen Whitmer": "MI", "JB Pritzker": "IL", "Andy Beshear": "KY", "Mark Kelly": "AZ",
    "Jon Ossoff": "GA", "Cory Booker": "NJ", "Tim Walz": "MN", "Wes Moore": "MD", "Ruben Gallego": "AZ",
    "Chris Murphy": "CT", "Ro Khanna": "CA", "Raphael Warnock": "GA", "Amy Klobuchar": "MN", "Roy Cooper": "NC",
    "Phil Murphy": "NJ", "Bernie Sanders": "VT", "Elizabeth Warren": "MA", "Jasmine Crockett": "TX",
    "Mark Cuban": "TX", "Stephen A. Smith": "NY", "Hunter Biden": "DE", "Michelle Obama": "IL", "Rahm Emanuel": "IL",
    "Abigail Spanberger": "VA", "Mikie Sherrill": "NJ", "Zohran Mamdani": "NY", "Jared Polis": "CO",
    "JD Vance": "OH", "Marco Rubio": "FL", "Ron DeSantis": "FL", "Ted Cruz": "TX", "Donald Trump Jr.": "FL",
    "Robert F. Kennedy Jr.": "CA", "Nikki Haley": "SC", "Vivek Ramaswamy": "OH", "Tucker Carlson": "FL",
    "Glenn Youngkin": "VA", "Brian Kemp": "GA", "Josh Hawley": "MO", "Tom Cotton": "AR", "Sarah Huckabee Sanders": "AR",
    "Kristi Noem": "SD", "Greg Abbott": "TX", "Steve Bannon": "VA", "Byron Donalds": "FL", "Tim Scott": "SC",
    "Rand Paul": "KY", "Marjorie Taylor Greene": "GA", "Ivanka Trump": "FL", "Donald Trump": "FL", "Aaron Rodgers": "NY",
}
# Not eligible in 2028 (two-term limit, 22nd Amendment): polled in early surveys, never a nominee.
INELIGIBLE = {"Donald Trump", "Barack Obama", "George W. Bush", "Bill Clinton"}
ALIASES = {"J.D. Vance": "JD Vance", "J. D. Vance": "JD Vance", "AOC": "Alexandria Ocasio-Cortez", "J. B. Pritzker": "JB Pritzker",
           "RFK Jr.": "Robert F. Kennedy Jr.", "Robert Kennedy Jr.": "Robert F. Kennedy Jr."}


def canonical(name: str) -> str:
    n = clean(name)
    n = re.sub(r"\s*\((D|R|I)\)$", "", n).strip()
    return ALIASES.get(n, n)


def _is_candidate_col(c: str) -> bool:
    low = c.lower().strip()
    return bool(low) and not low.startswith(NON_CANDIDATE) and not any(ch.isdigit() for ch in low) and len(low.split()) >= 2


def parse_poll_table(df, party: str, year_hint: Optional[int]) -> list[dict]:
    cols = list(df.columns)
    src = next((c for c in cols if c.lower().startswith(("poll source", "pollster", "polling firm"))), None)
    dates = next((c for c in cols if c.lower().startswith("date")), None)
    sample = next((c for c in cols if c.lower().startswith("sample")), None)
    if not src or not dates:
        return []
    cands = [c for c in cols if _is_candidate_col(c)]
    out = []
    for _, row in df.iterrows():
        pollster = re.sub(r"\s*\([DR]\)", "", clean(row[src])).strip(" /")
        if not pollster:
            continue
        start, end = parse_date_range(row[dates], default_year=year_hint)
        if end is None:
            continue
        shares = {canonical(c): parse_pct(row[c]) for c in cands}
        shares = {k: v for k, v in shares.items() if v is not None and k not in INELIGIBLE}
        if len(shares) < 2 or sum(shares.values()) < 20:
            continue
        n, pop = parse_sample(row[sample]) if sample else (None, None)
        key = f"{party}|{pollster}|{end}|{sorted(shares.items())}"
        out.append(dict(poll_id=hashlib.sha1(key.encode()).hexdigest()[:16], party=party, pollster=pollster,
                        start_date=start.isoformat() if start else None, end_date=end.isoformat(), sample_size=n,
                        population=pop, shares=json.dumps(shares), source=f"wikipedia:{POLL_PAGE.format(PARTY_WORD[party])}"))
    return out


def parse_aggregates(df, party: str) -> list[dict]:
    cols = list(df.columns)
    agg = next((c for c in cols if c.lower().startswith("aggregator")), None)
    upd = next((c for c in cols if c.lower().startswith("updated")), None)
    if not agg:
        return []
    cands = [c for c in cols if _is_candidate_col(c)]
    out = []
    for _, row in df.iterrows():
        source = clean(row[agg])
        if not source:
            continue
        shares = {canonical(c): parse_pct(row[c]) for c in cands}
        shares = {k: v for k, v in shares.items() if v is not None and k not in INELIGIBLE}
        if not shares:
            continue
        as_of = None
        try:
            as_of = dtparser.parse(clean(row[upd])).date().isoformat() if upd else None
        except (ValueError, OverflowError):
            as_of = None
        out.append(dict(party=party, source="Average" if source.lower() in ("aggregate", "average") else source,
                        as_of=as_of, shares=json.dumps(shares)))
    return out


def parse_declared(df, party: str, status: str) -> list[dict]:
    cols = list(df.columns)
    cc = next((c for c in cols if c.lower().startswith("candidate")), None)
    if not cc:
        return []
    sc = next((c for c in cols if c.lower() == "state"), None)
    ec = next((c for c in cols if c.lower().startswith("experience")), None)
    ac = next((c for c in cols if "announce" in c.lower()), None)
    out = []
    for _, row in df.iterrows():
        name = canonical(row[cc])
        if not name or len(name.split()) < 2:
            continue
        st = STATE_BY_NAME.get(clean(row[sc])) if sc else None
        out.append(dict(party=party, name=name, status=status, home_state=st or KNOWN_HOME_STATES.get(name),
                        experience=clean(row[ec])[:160] if ec else None, announced=clean(row[ac]) if ac else None))
    return out


def fetch(party: str) -> dict:
    word = PARTY_WORD[party]
    polls, aggs, cands = [], [], []
    for t in extract_tables(page_html(POLL_PAGE.format(word)) or ""):
        df = t.flat()
        head = (t.path[-1] if t.path else "").lower()
        if "aggregat" in head or any(c.lower().startswith("aggregator") for c in df.columns):
            aggs.extend(parse_aggregates(df, party))
        elif "head-to-head" in " ".join(t.path).lower():
            continue
        else:
            m = re.match(r"^(20\d\d)$", head.strip())
            polls.extend(parse_poll_table(df, party, int(m.group(1)) if m else None))
    for page in (PRIMARY_PAGE.format(word), MAIN_PAGE):
        html = page_html(page)
        if not html:
            continue
        for t in extract_tables(html):
            path = " > ".join(t.path).lower()
            if page == MAIN_PAGE and f"{word.lower()} party primaries" not in path:
                continue
            if path.endswith("declared"):
                cands.extend(parse_declared(t.flat(), party, "declared"))
            elif "exploratory" in path:
                cands.extend(parse_declared(t.flat(), party, "exploratory"))
    return dict(polls=polls, aggregates=aggs, candidates=cands)


def load(con, verbose: bool = False) -> dict:
    started = now_iso()
    res = {}
    fetched = {p: fetch(p) for p in ("D", "R")}
    seen_polls = {r["poll_id"]: r["first_seen"] for r in rows(con, "SELECT poll_id, first_seen FROM primary_polls")}
    n_new = sum(len(f["polls"]) for f in fetched.values())
    if seen_polls and n_new < 0.5 * len(seen_polls):
        msg = f"only {n_new} primary polls parsed (had {len(seen_polls)}); keeping the previous field and polls"
        log_run(con, "primaries", started, False, msg)
        return dict(kept=len(seen_polls), parsed=n_new, note=msg)
    now = now_iso()
    con.execute("DELETE FROM primary_polls")
    con.execute("DELETE FROM primary_averages")
    con.execute("DELETE FROM candidates")
    for party in ("D", "R"):
        f = fetched[party]
        for pp in f["polls"]:
            pp["first_seen"] = seen_polls.get(pp["poll_id"]) or now
        seen = {}
        for c in f["candidates"]:
            if c["name"] not in seen or seen[c["name"]]["status"] != "declared":
                seen[c["name"]] = c
        polled: dict[str, float] = {}
        for p in f["polls"]:
            for k, v in json.loads(p["shares"]).items():
                polled[k] = max(polled.get(k, 0.0), v)
        for a in f["aggregates"]:
            for k, v in json.loads(a["shares"]).items():
                polled[k] = max(polled.get(k, 0.0), v)
        for name, top in polled.items():
            if name not in seen and top >= 2.0:
                seen[name] = dict(party=party, name=name, status="potential", home_state=KNOWN_HOME_STATES.get(name),
                                  experience=None, announced=None)
        upsert(con, "primary_polls", f["polls"], keys=["poll_id"])
        upsert(con, "primary_averages", f["aggregates"], keys=["party", "source"])
        upsert(con, "candidates", [dict(c, source="wikipedia", updated_at=now_iso()) for c in seen.values()], keys=["party", "name"])
        res[party] = dict(polls=len(f["polls"]), aggregates=len(f["aggregates"]), candidates=len(seen),
                          declared=sum(c["status"] == "declared" for c in seen.values()))
    con.commit()
    log_run(con, "primaries", started, True, json.dumps(res))
    return res
