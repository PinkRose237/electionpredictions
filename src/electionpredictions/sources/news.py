"""Recent coverage via Google News RSS: the race overall, each party's contest, the leading candidates
and the closest states. Context for the model-revision step and the site; never a direct model input."""
from __future__ import annotations

import json
from datetime import timezone

import feedparser
from dateutil import parser as dtparser

from ..config import TTL_NEWS
from ..db import log_run, now_iso, rows, upsert
from .http import get

RSS = "https://news.google.com/rss/search"
NATIONAL_QUERIES = {
    "NATIONAL": "2028 presidential election",
    "D": "2028 Democratic presidential primary",
    "R": "2028 Republican presidential primary",
    "POLLS": "2028 presidential poll",
}


def fetch(query: str, limit: int = 12) -> list[dict]:
    text = get(RSS, {"q": query + " when:30d", "hl": "en-US", "gl": "US", "ceid": "US:en"}, kind="news", ttl=TTL_NEWS, as_json=False)
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


def topics(con, n_candidates: int = 10, n_states: int = 8) -> dict[str, str]:
    """Search topics: national ones, the top candidates by current nomination odds (or polling), the closest states."""
    out = dict(NATIONAL_QUERIES)
    try:
        spec = rows(con, "SELECT spec FROM model_specs ORDER BY version DESC LIMIT 1")
        noms = []
        if spec:
            s = json.loads(spec[0]["spec"])
            for party in ("D", "R"):
                noms += [(c["p"], c["name"]) for c in s["nominees"][party] if c["name"] != "Other"]
        else:  # first run: the primary-poll leaders
            for a in rows(con, "SELECT shares FROM primary_averages WHERE source='Average'"):
                noms += [(v / 100.0, k) for k, v in json.loads(a["shares"]).items()]
        for _, name in sorted(noms, reverse=True)[:n_candidates]:
            out[name] = f'"{name}" 2028'
    except Exception:  # noqa: BLE001
        pass
    from ..config import STATES

    close = rows(con, "SELECT contest_id FROM forecasts WHERE run_date=(SELECT max(run_date) FROM forecasts) "
                      "AND contest_id NOT LIKE '%-%' ORDER BY abs(p_dem-0.5) LIMIT ?", (n_states,))
    for c in close:
        out[c["contest_id"]] = f"{STATES[c['contest_id']]} 2028 presidential"
    return out


def load(con, verbose: bool = False) -> dict:
    started = now_iso()
    n = 0
    tps = topics(con)
    for topic, q in tps.items():
        items = fetch(q)
        if items:
            con.execute("DELETE FROM news WHERE topic=?", (topic,))
            n += upsert(con, "news", [dict(topic=topic, fetched_at=now_iso(), **it) for it in items], keys=["topic", "url"])
    con.commit()
    res = dict(topics=len(tps), items=n)
    log_run(con, "news", started, True, json.dumps(res))
    return res
