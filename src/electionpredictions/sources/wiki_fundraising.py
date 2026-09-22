"""Fill fundraising gaps from the 'Fundraising' tables on each race's Wikipedia article.

Governors file with state agencies (not the FEC), so this is their only structured money source; for
federal races it backfills candidates the FEC bulk file did not match. Values are marked money_source='wikipedia'.
"""
from __future__ import annotations

import json
import re
from typing import Optional

from ..db import log_run, now_iso, rows
from ..util import clean
from .polls import article_titles
from .races import same_person
from .wikipedia import WikiTable, extract_tables, page_html, resolve_title


def _money(v) -> Optional[float]:
    s = clean(v).replace("$", "").replace(",", "").strip()
    if not s or s.lower().startswith("source") or s in {"—", "-", "n/a"}:
        return None
    m = re.match(r"-?\d+(?:\.\d+)?", s)
    return float(m.group(0)) if m else None


def fundraising_tables(tables: list[WikiTable], district: Optional[int]) -> list[WikiTable]:
    out = []
    for t in tables:
        if not t.path or not t.path[-1].lower().startswith("fundrais"):
            continue
        if district is not None and not any(re.fullmatch(rf"district {district}", p.lower()) for p in t.path):
            continue
        cols = " | ".join(t.columns).lower()
        if "candidate" in cols and "raised" in cols:
            out.append(t)
    # general-election tables first (most recent totals), then primaries
    out.sort(key=lambda t: 0 if any("general election" in p.lower() for p in t.path) else 1)
    return out


def parse_rows(t: WikiTable) -> list[dict]:
    df = t.flat()
    cols = {c.lower(): c for c in df.columns}
    cc = next((cols[c] for c in cols if "candidate" in c), None)
    rc = next((cols[c] for c in cols if "raised" in c or "receipts" in c), None)
    sc = next((cols[c] for c in cols if "spent" in c or "disburse" in c), None)
    hc = next((cols[c] for c in cols if "cash" in c), None)
    out = []
    for _, row in df.iterrows():
        name = clean(row[cc]) if cc else ""
        if not name or name.lower().startswith("source") or name.lower().startswith("candidate"):
            continue
        name = re.sub(r"\s*\((?:[A-Z]{1,3}|Ind\.?|Independent|Democratic|Republican|Libertarian|Green)\)\s*\*?\s*$", "", name).strip(" *")
        raised = _money(row[rc]) if rc else None
        if raised is None or raised <= 0:
            continue  # a zero usually means "no report yet", not a penniless nominee
        out.append(dict(name=name, receipts=raised, disbursements=_money(row[sc]) if sc else None, cash_on_hand=_money(row[hc]) if hc else None))
    return out


def load(con, verbose=True, only_missing: bool = True) -> dict:
    started = now_iso()
    try:
        con.execute("ALTER TABLE candidates ADD COLUMN money_source TEXT")
        con.commit()
    except Exception:  # noqa: BLE001 - column already exists
        pass
    con.execute("UPDATE candidates SET money_source='fec' WHERE fec_id IS NOT NULL AND money_source IS NULL")
    races = rows(con, "SELECT * FROM races ORDER BY chamber, state, district")
    stats = {"races_checked": 0, "filled": 0, "pages_without_tables": 0}
    page_cache: dict[str, list[WikiTable]] = {}
    for race in races:
        cands = rows(con, "SELECT * FROM candidates WHERE race_id=?" + (" AND receipts IS NULL" if only_missing else ""), (race["race_id"],))
        cands = [c for c in cands if c["major"]] or cands
        if not cands:
            continue
        stats["races_checked"] += 1
        titles = article_titles(race)
        if titles[0] not in page_cache:
            t = resolve_title(titles)
            page_cache[titles[0]] = extract_tables(page_html(t)) if t else []
        district = race["district"] if race["chamber"] == "house" and race["district"] else None
        tables = fundraising_tables(page_cache[titles[0]], district)
        if not tables:
            stats["pages_without_tables"] += 1
            continue
        for c in cands:
            hit = None
            for t in tables:
                for rec in parse_rows(t):
                    if same_person(rec["name"], c["name"]):
                        hit = rec
                        break
                if hit:
                    break
            if hit:
                con.execute("UPDATE candidates SET receipts=?, disbursements=?, cash_on_hand=?, money_source='wikipedia' WHERE race_id=? AND name=?",
                            (hit["receipts"], hit["disbursements"], hit["cash_on_hand"], race["race_id"], c["name"]))
                stats["filled"] += 1
        con.commit()
    if verbose:
        print(f"  wiki fundraising: {stats}")
    log_run(con, "wiki_fundraising", started, True, json.dumps(stats))
    return stats
