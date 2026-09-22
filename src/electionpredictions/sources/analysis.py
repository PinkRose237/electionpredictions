"""Optional: short, neutral AI-written race briefs from the collected data and headlines.

Runs only when Anthropic API credentials are available (ANTHROPIC_API_KEY, or an `ant auth login`
profile). Briefs are regenerated only when a race's inputs change, so a daily run costs little.
"""
from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from ..db import log_run, now_iso, rows, upsert

MODEL = "claude-opus-5"
SYSTEM = """You write short, neutral race briefs for a nonpartisan U.S. election forecast website.
You will be given structured data about one 2026 race (candidates, partisan lean, expert ratings, polls,
fundraising, prediction-market odds, the model's forecast) and recent news headlines.

Write 120-180 words of plain prose in two short paragraphs, no headings, no bullet points, no markdown.
Paragraph 1: where the race stands and why (lean, incumbency, polling, ratings, money). Paragraph 2: what
the recent headlines suggest is driving the race and what to watch. Attribute claims to their source
("polls show", "raters call it", "according to headlines from X"). Use only the information provided;
do not invent events, quotes or numbers. Never express a preference for any candidate or party.
If the data is thin, say so briefly instead of padding."""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS briefs (
    race_id TEXT PRIMARY KEY,
    brief TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    model TEXT,
    generated_at TEXT
);
"""


def _race_payload(con, race_id: str) -> Optional[dict]:
    race = rows(con, "SELECT * FROM races WHERE race_id=?", (race_id,))
    if not race:
        return None
    race = race[0]
    fc = rows(con, "SELECT * FROM forecasts WHERE race_id=? ORDER BY run_date DESC LIMIT 1", (race_id,))
    f = fc[0] if fc else None
    detail = json.loads(f["detail"]) if f else {}
    cands = rows(con, "SELECT name, party, is_incumbent, major, receipts, cash_on_hand FROM candidates WHERE race_id=? AND major=1", (race_id,))
    ratings = rows(con, "SELECT rater, rating, as_of FROM ratings WHERE race_id=?", (race_id,))
    polls = rows(con, "SELECT pollster, sponsor_lean, end_date, sample_size, dem_name, dem_pct, rep_name, rep_pct, hypothetical FROM polls WHERE race_id=? AND hypothetical=0 ORDER BY end_date DESC LIMIT 8", (race_id,))
    markets = rows(con, "SELECT platform, p_dem, p_rep, p_other FROM markets WHERE race_id=?", (race_id,))
    news = rows(con, "SELECT title, source, published FROM news WHERE race_id=? ORDER BY published DESC LIMIT 12", (race_id,))
    return dict(
        race=dict(name=race["name"], chamber=race["chamber"], state=race["state"], incumbent=race["incumbent"],
                  incumbent_party=race["incumbent_party"], incumbent_running=bool(race["incumbent_running"]),
                  pvi_dem_minus_rep=race["pvi"], status=race["status"]),
        candidates=cands, expert_ratings=ratings, recent_polls=polls, prediction_markets=markets,
        model_forecast=dict(p_dem=round(f["p_dem"], 3) if f else None, margin_dem_minus_rep=round(f["margin"], 1) if f else None,
                            label=detail.get("label"), notes=detail.get("notes")),
        headlines=news,
    )


def _hash(payload: dict) -> str:
    return hashlib.sha1(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _generate(client, payload: dict) -> str:
    import anthropic

    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=1024,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "low"},
        system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": "Race data (JSON):\n" + json.dumps(payload, default=str)}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"refused: {getattr(response.stop_details, 'category', None)}")
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    if response.stop_reason == "max_tokens" or not text:
        raise RuntimeError(f"incomplete response (stop_reason={response.stop_reason})")
    return text


def select_race_ids(con) -> list[str]:
    return [r["race_id"] for r in rows(con, """
        SELECT r.race_id FROM races r
        WHERE r.chamber IN ('senate','governor')
           OR EXISTS (SELECT 1 FROM ratings g WHERE g.race_id=r.race_id)
           OR EXISTS (SELECT 1 FROM polls p WHERE p.race_id=r.race_id AND p.hypothetical=0)
        ORDER BY r.chamber, r.state, r.district""")]


def load(con, verbose=True, race_ids: Optional[list[str]] = None, workers: int = 6, limit: Optional[int] = None) -> dict:
    import anthropic

    started = now_iso()
    con.executescript(SCHEMA_SQL)
    client = anthropic.Anthropic(max_retries=3)
    race_ids = race_ids or select_race_ids(con)
    if limit:
        race_ids = race_ids[:limit]
    existing = {r["race_id"]: r["input_hash"] for r in rows(con, "SELECT race_id, input_hash FROM briefs")}
    todo = []
    for rid in race_ids:
        payload = _race_payload(con, rid)
        if not payload:
            continue
        h = _hash(payload)
        if existing.get(rid) != h:
            todo.append((rid, payload, h))
    stats = {"candidates": len(race_ids), "regenerated": 0, "unchanged": len(race_ids) - len(todo), "errors": 0}
    if not todo:
        log_run(con, "analysis", started, True, json.dumps(stats))
        return stats
    # one probe call first so a missing credential fails fast instead of 200 times
    try:
        rid, payload, h = todo[0]
        text = _generate(client, payload)
        upsert(con, "briefs", [dict(race_id=rid, brief=text, input_hash=h, model=MODEL, generated_at=now_iso())], keys=["race_id"])
        con.commit()
        stats["regenerated"] += 1
    except anthropic.AuthenticationError:
        print("  analysis: no valid Anthropic credentials (set ANTHROPIC_API_KEY or run `ant auth login`); skipping.")
        log_run(con, "analysis", started, False, "no credentials")
        return stats
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_generate, client, payload): (rid, h) for rid, payload, h in todo[1:]}
        for fut in as_completed(futs):
            rid, h = futs[fut]
            try:
                text = fut.result()
            except Exception as e:  # noqa: BLE001
                stats["errors"] += 1
                if verbose:
                    print(f"  analysis: {rid} failed: {e!r}")
                continue
            upsert(con, "briefs", [dict(race_id=rid, brief=text, input_hash=h, model=MODEL, generated_at=now_iso())], keys=["race_id"])
            con.commit()
            stats["regenerated"] += 1
    if verbose:
        print(f"  analysis: {stats}")
    log_run(con, "analysis", started, stats["errors"] == 0, json.dumps(stats))
    return stats
