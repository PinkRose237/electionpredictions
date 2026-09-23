"""General-election polls for every race, parsed from each race's Wikipedia article.

Senate and governor races have their own article; House districts share a per-state article with
'District N' > 'General election' > 'Polling' sections.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Optional

from dateutil import parser as dtparser

from ..config import CYCLE, DC_NAME, STATES
from ..db import log_run, now_iso, rows, upsert
from ..util import clean, last_name, parse_date_range, parse_pct, parse_sample, party_code
from .races import _col, same_person
from .wikipedia import WikiTable, extract_tables, page_html, resolve_title

NON_CAND_PREFIXES = ("poll", "date", "sample", "margin", "source", "unnamed", "lead", "other", "undecided",
                     "refused", "none", "unsure", "don't know", "dont know", "would", "someone else", "no one",
                     "not sure", "abstain", "n/a", "no opinion", "another", "neither", "notes", "ref", "rcv", "round",
                     "instant", "final")
CAND_RE = re.compile(
    r"^(?P<name>.+?)\s*\((?P<party>D|R|I|L|G|U|NL|DFL|WFP|Ind\.?|Dem\.?|Rep\.?|Lib\.?|Independent|Democratic|Democrat|Republican|Libertarian|Green|Nonpartisan|Write-in)\)\s*$",
    re.I,
)


def article_titles(race: dict) -> list[str]:
    if race["chamber"] == "president":
        if race["state"] == "DC":
            return ["2028 United States presidential election in the District of Columbia"]
        name = STATES.get(race["state"], DC_NAME)
        return [f"2028 United States presidential election in {name}"]
    name = STATES[race["state"]]
    if race["chamber"] == "senate":
        if race["special"]:
            return [f"2026 United States Senate special election in {name}", f"2026 United States Senate election in {name}"]
        return [f"2026 United States Senate election in {name}"]
    if race["chamber"] == "governor":
        return [f"2026 {name} gubernatorial election"]
    return [f"2026 United States House of Representatives elections in {name}",
            f"2026 United States House of Representatives election in {name}"]


def _cand_col(col: str, cands: list[dict]) -> Optional[tuple[str, str]]:
    c = clean(col)
    low = c.lower()
    if not c or low.startswith(NON_CAND_PREFIXES) or low in {"%", "n"}:
        return None
    m = CAND_RE.match(c)
    if m:
        return m.group("name").strip(), party_code(m.group("party"))
    if low.startswith("generic"):
        return c, ("D" if "democrat" in low else "R" if "republican" in low else "?")
    for k in cands:
        if same_person(c, k["name"]):
            return k["name"], k["party"]
    if len(c.split()) == 1:
        hits = [k for k in cands if last_name(k["name"]).lower() == c.lower()]
        if len(hits) == 1:
            return hits[0]["name"], hits[0]["party"]
    if len(c.split()) >= 2 and not any(ch.isdigit() for ch in c):
        return c, "?"
    return None


def _sponsor_lean(src: str) -> Optional[str]:
    tags = re.findall(r"\(([DR])\)", src)
    if "D" in tags and "R" in tags:
        return None
    if tags:
        return tags[0]
    return None


def _pollster(src: str) -> str:
    s = re.sub(r"\s*\([DR]\)", "", clean(src))
    s = re.sub(r"\s*(Archived|archive).*$", "", s)
    return s.strip(" /") or "Unknown"


def _find_side(ccols, side: Optional[dict]):
    if not side:
        return None
    for c, (name, party) in ccols:
        if same_person(name, side["name"]):
            return c
    return None


def parse_polling_table(t: WikiTable, race: dict, cands: list[dict], dem: Optional[dict], rep: Optional[dict],
                        seen_polls: Optional[set] = None):
    """Parse one Wikipedia polling table into poll rows (and aggregator rows).

    - Candidate columns are recognised by '(D)'/'(R)' suffixes, 'Generic X', or names in the candidate list.
    - Tables that report ranked-choice rounds keep only each poll's final round.
    - `seen_polls` de-duplicates the same poll appearing in several tables of one article."""
    df = t.flat()
    src = _col(df, "Poll source", "Pollster", "Source of poll", "Source")
    dates = _col(df, "Date")
    if src is None or dates is None:
        return [], []
    sample, moe = _col(df, "Sample"), _col(df, "Margin of error", "MoE")
    round_col = next((c for c in df.columns if re.search(r"\bround\b", str(c), re.I)), None)
    skip = {src, dates, sample, moe, round_col}
    ccols = []
    for c in df.columns:
        if c in skip:
            continue
        x = _cand_col(c, cands)
        if x:
            ccols.append((c, x))
    if len(ccols) < 2:
        return [], []
    party_of = {c: p for c, (_, p) in ccols}
    name_of = {c: n for c, (n, _) in ccols}
    other_col = next((c for c in df.columns if "other" in str(c).lower() and c not in skip), None)
    und_col = next((c for c in df.columns if "undecided" in str(c).lower() and c not in skip), None)
    dcol, rcol = _find_side(ccols, dem), _find_side(ccols, rep)
    if dcol is None and dem is None:
        dcol = next((c for c, (n, p) in ccols if p == "D"), None)
    if rcol is None and rep is None:
        rcol = next((c for c, (n, p) in ccols if p == "R"), None)
    real_matchup = dcol is not None and rcol is not None and not any("hypothetical" in p.lower() for p in t.path)
    if dcol is None:  # generic-candidate columns stand in for a missing nominee (weak, hypothetical evidence)
        dcol = next((c for c, (n, p) in ccols if p == "D" and n.lower().startswith("generic")), None)
    if rcol is None:
        rcol = next((c for c, (n, p) in ccols if p == "R" and n.lower().startswith("generic")), None)
    aggregate = "aggregat" in str(src).lower()

    def side_pct(vals: dict, col):
        """The side's share, plus same-party rivals' support (ranked-choice consolidation):
        a serious rival's voters (>=10%) mostly transfer, a minor candidate's split."""
        if col is None or vals.get(col) is None:
            return None
        party, total = party_of[col], vals[col]
        if party in ("D", "R"):
            for c, v in vals.items():
                if c != col and party_of[c] == party and v is not None:
                    total += v * (1.0 if v >= 10 else 0.5)
        return total

    polls, aggs, staged = [], [], []
    for _, row in df.iterrows():
        vals = {c: parse_pct(row[c]) for c, _ in ccols}
        if sum(v is not None for v in vals.values()) < 2:
            continue
        srctxt = clean(row[src])
        if aggregate:
            if not real_matchup:
                continue
            as_of, uc = None, _col(df, "updated")
            if uc:
                try:
                    as_of = dtparser.parse(clean(row[uc])).date().isoformat()
                except (ValueError, OverflowError):
                    as_of = None
            d, r = vals.get(dcol), vals.get(rcol)
            if d is None or r is None:
                continue
            aggs.append(dict(race_id=race["race_id"], source=re.sub(r"\[.*?\]", "", srctxt) or "Average",
                             as_of=as_of, dem=d, rep=r, margin=round(d - r, 2)))
            continue
        start, end = parse_date_range(row[dates], default_year=CYCLE)
        if end is None:
            continue
        n, pop = parse_sample(row[sample]) if sample else (None, None)
        pollster = _pollster(srctxt)
        names = sorted(name_of[c] for c, v in vals.items() if v is not None)
        pid = hashlib.sha1(f"{race['race_id']}|{pollster}|{start}|{end}|{n}|{'|'.join(names)}".encode()).hexdigest()[:16]
        # in a ranked-choice table, a non-numeric round label ('BA' = before allocation) is the first-choice row
        rnd = (parse_pct(row[round_col]) or 0.0) if round_col is not None else None
        rec = dict(
            poll_id=pid, race_id=race["race_id"], pollster=pollster, sponsor_lean=_sponsor_lean(srctxt),
            start_date=start.isoformat() if start else None, end_date=end.isoformat(),
            sample_size=n, population=pop, moe=parse_pct(row[moe]) if moe else None,
            dem_name=name_of.get(dcol), rep_name=name_of.get(rcol),
            dem_pct=side_pct(vals, dcol), rep_pct=side_pct(vals, rcol),
            other_pct=parse_pct(row[other_col]) if other_col else None,
            und_pct=parse_pct(row[und_col]) if und_col else None,
            matchup=json.dumps([[name_of[c], party_of[c], v] for c, v in vals.items() if v is not None]),
            hypothetical=int(not real_matchup), source="wikipedia",
        )
        staged.append((rnd, rec))
    if round_col is not None:  # keep only the final round of each ranked-choice poll
        final: dict[tuple, tuple] = {}
        for rnd, rec in staged:
            if rnd is None:
                continue
            g = (rec["pollster"], rec["start_date"], rec["end_date"])  # sample size can shrink by round
            if g not in final or rnd >= final[g][0]:
                final[g] = (rnd, rec)
        staged = list(final.values()) + [(r, x) for r, x in staged if r is None]
    seen_ids = set()
    for _, rec in staged:
        xkey = (rec["pollster"], rec["start_date"], rec["end_date"], rec["sample_size"], rec["dem_name"], rec["rep_name"])
        if rec["poll_id"] in seen_ids or (seen_polls is not None and xkey in seen_polls):
            continue
        seen_ids.add(rec["poll_id"])
        if seen_polls is not None:
            seen_polls.add(xkey)
        polls.append(rec)
    return polls, aggs


PRIMARY_WORDS = ("primary", "convention", "caucus", "nominat", "runoff", "first round")


def polling_tables(tables: list[WikiTable], district: Optional[int] = None) -> list[WikiTable]:
    """General-election polling tables: under a 'General election' heading, or a 'Polling' heading with no
    primary/convention/runoff context (some articles nest general polling under the wrong parent)."""
    out = []
    for t in tables:
        path_l = [p.lower() for p in t.path]
        if not any("polling" in p or p == "polls" for p in path_l):
            continue
        if district is not None:
            if not any(re.fullmatch(rf"district {district}", p) or re.fullmatch(rf"{district}(st|nd|rd|th) district", p) for p in path_l):
                continue
        if any("general election" in p for p in path_l):
            gi = next(i for i, p in enumerate(path_l) if "general election" in p)
            if any(w in p for p in path_l[gi:] for w in PRIMARY_WORDS):
                continue
            out.append(t)
        elif not any(w in p for p in path_l for w in PRIMARY_WORDS) and not any("hypothetical" in p for p in path_l[:-1]):
            cols = " | ".join(t.columns).lower()
            if "poll source" in cols or "pollster" in cols or "aggregat" in cols:
                out.append(t)
    return out


def _sides(cands: list[dict]):
    dem = next((c for c in cands if c["major"] and c["party"] == "D"), None) or next((c for c in cands if c["major"] and c["party"] == "I"), None)
    rep = next((c for c in cands if c["major"] and c["party"] == "R"), None)
    if rep is None:
        rep = next((c for c in cands if c["major"] and c["party"] == "I" and c is not dem), None)
    return dem, rep


def load(con, chambers=None, verbose=True) -> dict:
    if chambers is None:
        chambers = ("president",) if CYCLE == 2028 else ("senate", "governor", "house")
    started = now_iso()
    races = rows(con, "SELECT * FROM races WHERE chamber IN (%s) ORDER BY chamber, state, district" % ",".join("?" * len(chambers)), chambers)
    stats = {"pages": 0, "missing_pages": 0, "polls": 0, "aggregates": 0, "races_with_polls": 0}
    page_cache: dict[str, Optional[list[WikiTable]]] = {}
    for race in races:
        cands = rows(con, "SELECT * FROM candidates WHERE race_id=?", (race["race_id"],))
        dem, rep = _sides(cands)
        titles = article_titles(race)
        key = titles[0]
        if key not in page_cache:
            title = resolve_title(titles)
            if title is None:
                page_cache[key] = None
                stats["missing_pages"] += 1
                if verbose:
                    print(f"  - no article: {titles[0]}")
            else:
                html = page_html(title)
                page_cache[key] = extract_tables(html) if html else None
                stats["pages"] += 1
                con.execute("UPDATE races SET wiki_title=? WHERE race_id=?", (title, race["race_id"]))
        tables = page_cache[key]
        if race["chamber"] != "house":
            con.execute("UPDATE races SET wiki_title=? WHERE race_id=?", (resolve_title(titles), race["race_id"]))
        if not tables:
            continue
        district = race["district"] if race["chamber"] == "house" else None
        if district == 0:
            district = None
        polls, aggs = [], []
        seen_polls: set = set()
        ptables = sorted(polling_tables(tables, district),
                         key=lambda t: 0 if any(re.search(r"\bround\b", str(c), re.I) for c in t.flat().columns) else 1)
        for t in ptables:
            p, a = parse_polling_table(t, race, cands, dem, rep, seen_polls)
            polls.extend(p)
            aggs.extend(a)
        con.execute("DELETE FROM polls WHERE race_id=? AND source='wikipedia'", (race["race_id"],))
        con.execute("DELETE FROM poll_aggregates WHERE race_id=?", (race["race_id"],))
        upsert(con, "polls", polls, keys=["poll_id"])
        upsert(con, "poll_aggregates", aggs, keys=["race_id", "source"])
        stats["polls"] += len(polls)
        stats["aggregates"] += len(aggs)
        if polls:
            stats["races_with_polls"] += 1
        con.commit()
    log_run(con, "polls", started, True, json.dumps(stats))
    return stats
