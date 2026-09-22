"""Optional: short, neutral AI-written race briefs from the collected data and headlines.

Uses OpenCode Zen (OpenAI-compatible HTTP API) with Meta's Muse Spark 1.3 Contributor model by default.
Needs OPENCODE_API_KEY (https://opencode.ai/auth). Briefs are regenerated only when a race's inputs change.
Note: the '-contributor' model tier lets the provider use prompts/completions for training; the inputs here
are public election data, but switch AI_MODEL to 'muse-spark-1.3' if you prefer the paid non-contributor tier.
"""
from __future__ import annotations

import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import requests

from ..config import AI_BASE_URL, AI_MODEL, OPENCODE_API_KEY, USER_AGENT
from ..db import log_run, now_iso, rows, upsert

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


class AuthError(RuntimeError):
    pass


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


def _post(path: str, body: dict, timeout: int = 120) -> requests.Response:
    return requests.post(f"{AI_BASE_URL.rstrip('/')}/{path.lstrip('/')}", json=body, timeout=timeout,
                         headers={"Authorization": f"Bearer {OPENCODE_API_KEY}", "Content-Type": "application/json", "User-Agent": USER_AGENT})


def _extract_text(data: dict) -> str:
    """Text from either a chat-completions or a responses-API payload."""
    if isinstance(data.get("choices"), list) and data["choices"]:
        msg = data["choices"][0].get("message") or {}
        content = msg.get("content")
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        return (content or "").strip()
    if data.get("output_text"):
        return str(data["output_text"]).strip()
    text = []
    for item in data.get("output", []) or []:
        for part in item.get("content", []) or []:
            if part.get("type") in ("output_text", "text") and part.get("text"):
                text.append(part["text"])
    return "".join(text).strip()


def generate_brief(payload: dict, retries: int = 3) -> str:
    """One brief via OpenCode Zen. Tries /chat/completions, then /responses if the model only speaks that."""
    user = "Race data (JSON):\n" + json.dumps(payload, default=str)
    attempts = [
        ("chat/completions", {"model": AI_MODEL, "temperature": 0.3, "max_tokens": 700,
                              "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]}),
        ("responses", {"model": AI_MODEL, "instructions": SYSTEM, "max_output_tokens": 700,
                       "input": [{"role": "user", "content": user}]}),
    ]
    last = None
    for path, body in attempts:
        for attempt in range(retries):
            r = _post(path, body)
            if r.status_code in (401, 403):
                raise AuthError(f"OpenCode rejected the API key (HTTP {r.status_code})")
            if r.status_code in (404, 405) or (r.status_code == 400 and "endpoint" in r.text.lower()):
                last = f"{path}: HTTP {r.status_code}"
                break  # try the other endpoint shape
            if r.status_code == 429 or r.status_code >= 500:
                last = f"{path}: HTTP {r.status_code}"
                time.sleep(3 * (attempt + 1))
                continue
            if not r.ok:
                raise RuntimeError(f"{path}: HTTP {r.status_code}: {r.text[:200]}")
            text = _extract_text(r.json())
            if not text:
                raise RuntimeError(f"{path}: empty response")
            return text
    raise RuntimeError(f"OpenCode request failed ({last})")


def select_race_ids(con) -> list[str]:
    return [r["race_id"] for r in rows(con, """
        SELECT r.race_id FROM races r
        WHERE r.chamber IN ('senate','governor')
           OR EXISTS (SELECT 1 FROM ratings g WHERE g.race_id=r.race_id)
           OR EXISTS (SELECT 1 FROM polls p WHERE p.race_id=r.race_id AND p.hypothetical=0)
        ORDER BY r.chamber, r.state, r.district""")]


def load(con, verbose=True, race_ids: Optional[list[str]] = None, workers: int = 4, limit: Optional[int] = None) -> dict:
    started = now_iso()
    con.executescript(SCHEMA_SQL)
    if not OPENCODE_API_KEY:
        if verbose:
            print("  analysis: skipped (no OPENCODE_API_KEY)")
        return {"skipped": True}
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
    stats = {"model": AI_MODEL, "candidates": len(race_ids), "regenerated": 0, "unchanged": len(race_ids) - len(todo), "errors": 0}
    if not todo:
        log_run(con, "analysis", started, True, json.dumps(stats))
        return stats
    # one probe call first so a bad key fails fast instead of 200 times
    try:
        rid, payload, h = todo[0]
        text = generate_brief(payload)
        upsert(con, "briefs", [dict(race_id=rid, brief=text, input_hash=h, model=AI_MODEL, generated_at=now_iso())], keys=["race_id"])
        con.commit()
        stats["regenerated"] += 1
    except AuthError as e:
        print(f"  analysis: {e}; skipping.")
        log_run(con, "analysis", started, False, str(e))
        return stats
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(generate_brief, payload): (rid, h) for rid, payload, h in todo[1:]}
        for fut in as_completed(futs):
            rid, h = futs[fut]
            try:
                text = fut.result()
            except Exception as e:  # noqa: BLE001
                stats["errors"] += 1
                if verbose:
                    print(f"  analysis: {rid} failed: {e!r}")
                continue
            upsert(con, "briefs", [dict(race_id=rid, brief=text, input_hash=h, model=AI_MODEL, generated_at=now_iso())], keys=["race_id"])
            con.commit()
            stats["regenerated"] += 1
    if verbose:
        print(f"  analysis: {stats}")
    log_run(con, "analysis", started, stats["errors"] == 0, json.dumps(stats))
    return stats
