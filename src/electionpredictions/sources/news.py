"""Recent news coverage per race via Google News RSS search."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

import feedparser
from dateutil import parser as dtparser

from ..config import STATES, TTL_NEWS
from ..db import log_run, now_iso, rows, upsert
from ..util import last_name, ordinal
from .http import get

RSS = "https://news.google.com/rss/search"


def query_for(race: dict, dem: Optional[dict], rep: Optional[dict]) -> str:
    st = STATES[race["state"]]
    names = [last_name(c["name"]) for c in (dem, rep) if c]
    who = " OR ".join(f'"{n}"' for n in names)
    if race["chamber"] == "senate":
        base = f"{st} Senate race"
    elif race["chamber"] == "governor":
        base = f"{st} governor race"
    else:
        base = f"{st} {ordinal(race['district'])} congressional district" if race["district"] else f"{st} at-large congressional district"
    return f"{base} ({who})" if who else f"{base} 2026"


def fetch(query: str, limit: int = 15) -> list[dict]:
    text = get(RSS, {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"}, kind="news", ttl=TTL_NEWS, as_json=False)
    if not text:
        return []
    feed = feedparser.parse(text)
    out = []
    for e in feed.entries[:limit]:
        title = e.get("title", "")
        src = (e.get("source") or {}).get("title") or ""
        if src and title.endswith(" - " + src):
            title = title[: -len(src) - 3]
        pub = None
        if e.get("published"):
            try:
                pub = dtparser.parse(e["published"]).astimezone(timezone.utc).replace(microsecond=0).isoformat()
            except (ValueError, OverflowError, TypeError):
                pub = None
        if e.get("link"):
            out.append(dict(url=e["link"], title=title, source=src, published=pub))
    return out


def select_races(con) -> list[dict]:
    return rows(con, """
        SELECT r.* FROM races r
        WHERE r.chamber IN ('senate','governor')
           OR EXISTS (SELECT 1 FROM ratings g WHERE g.race_id=r.race_id)
           OR EXISTS (SELECT 1 FROM polls p WHERE p.race_id=r.race_id)
        ORDER BY r.chamber, r.state, r.district""")


def load(con, verbose=True, races: Optional[list[dict]] = None) -> dict:
    started = now_iso()
    races = races or select_races(con)
    stats = {"races": len(races), "items": 0, "empty": 0}
    for race in races:
        cands = rows(con, "SELECT * FROM candidates WHERE race_id=? AND major=1", (race["race_id"],))
        dem = next((c for c in cands if c["party"] == "D"), None) or next((c for c in cands if c["party"] == "I"), None)
        rep = next((c for c in cands if c["party"] == "R"), None)
        items = fetch(query_for(race, dem, rep))
        if not items:
            stats["empty"] += 1
            continue
        con.execute("DELETE FROM news WHERE race_id=?", (race["race_id"],))
        upsert(con, "news", [dict(race_id=race["race_id"], fetched_at=now_iso(), **it) for it in items], keys=["race_id", "url"])
        stats["items"] += len(items)
        con.commit()
    if verbose:
        print(f"  news: {stats}")
    log_run(con, "news", started, True, json.dumps(stats))
    return stats
