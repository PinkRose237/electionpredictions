"""The decision layer: an LLM reviews every race's evidence and sets the forecast.

Flow (see cli.run): ingest -> quantitative baseline (model) -> per-race decisions + national review (this
module) -> final simulation on the decided numbers -> export. Decisions are strict JSON so the site can
render them like any other model output. Provider: OpenCode Zen (OpenAI-compatible), model AI_MODEL.

Guardrails live in model/forecast.py (bounded shifts, sd limits, fallback to the baseline when a decision
is missing or malformed); this module only produces and caches decisions keyed by an input hash, so a
daily run re-decides only races whose evidence changed.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import requests

from ..config import AI_BASE_URL, AI_MODEL, OPENCODE_API_KEY, USER_AGENT
from ..db import log_run, now_iso, rows, upsert
from ..util import prob_label

LABELS = ["Safe D", "Likely D", "Lean D", "Tossup", "Lean R", "Likely R", "Safe R"]
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ai_decisions (
    race_id TEXT PRIMARY KEY, input_hash TEXT NOT NULL, decision TEXT NOT NULL, model TEXT, generated_at TEXT
);
CREATE TABLE IF NOT EXISTS ai_national (
    id INTEGER PRIMARY KEY CHECK (id = 1), input_hash TEXT NOT NULL, decision TEXT NOT NULL, model TEXT, generated_at TEXT
);
"""

RACE_SYSTEM = """You are the lead analyst of a nonpartisan U.S. election forecast. For the race described, decide the
forecast yourself from the evidence: partisan lean, incumbency, expert ratings, polls (recency, quality, sponsor),
fundraising and outside spending, prediction markets, recent headlines, and the quantitative baseline model.
Treat the baseline as a strong prior; move away from it only when specific evidence justifies it, and never
by more than about eight points of margin.

Return ONLY a JSON object with exactly these keys:
{
  "margin": number,        // your final expected margin, Democratic minus Republican, in points (negative = R ahead)
  "sd": number,            // your uncertainty about that margin in points, between 3 and 10 (wider when polling is thin or old)
  "p_dem": number,         // probability the Democratic-side candidate wins, 0-1, consistent with margin and sd
  "label": string,         // one of: Safe D, Likely D, Lean D, Tossup, Lean R, Likely R, Safe R
  "confidence": string,    // low, medium or high
  "key_factors": [string], // 2 to 4 short factors, most important first
  "rationale": string,     // one or two sentences on why you landed here
  "watch": string,         // one sentence: what could change this
  "overview": string       // 100-160 words, two short paragraphs, neutral tone, plain prose, no markdown
}
Calibration: Safe means at least 97% for the favorite, Likely 85-97%, Lean 65-85%, Tossup 35-65%. An uncontested
or same-party general election is Safe for the party on the ballot. Use only the information provided; never
invent polls, events or numbers; never express a preference for any candidate or party.
Voice for "overview", "rationale" and "watch": write as the forecast itself, in plain third person about the race.
Never mention the baseline, the model, the dossier, this review, an analyst, or yourself; refer to evidence directly
("polls show", "raters call it", "Ossoff has raised", "markets price"). Do not quote the forecast's own probability."""

NATIONAL_SYSTEM = """You are the lead analyst of a nonpartisan U.S. election forecast reviewing the national picture for the
2026 midterms. You are given the generic-ballot averages, the quantitative model's chamber-level outputs, the
prediction markets' chamber odds and a sample of recent headlines. Decide two adjustments that apply to every race:

Return ONLY a JSON object with exactly these keys:
{
  "environment_adjustment": number,   // points to add to the national environment for every race, Democratic-positive, between -3 and 3 (0 = the generic ballot average is right)
  "uncertainty_multiplier": number,   // scale for the shared national polling-error term, between 0.7 and 1.5 (1 = historical average)
  "summary": string,                  // 120-180 words, two short paragraphs, neutral tone, plain prose, no markdown: where the House, Senate and governorships stand and why
  "key_factors": [string],            // 3 to 5 short national factors
  "chambers": {"house": string, "senate": string, "governor": string}   // one sentence each
}
Use only the information provided; never express a preference for any party.
Voice for "summary" and "chambers": write as the forecast itself, in plain third person. Describe where each chamber
stands and why using the evidence (generic ballot, polls, money, seats in play, markets); do not mention the model,
a baseline, this review, an analyst, or yourself, and do not quote the forecast's own control probabilities."""


class AuthError(RuntimeError):
    pass


# ---------------------------------------------------------------------------- dossiers
def _round(v, nd=1):
    return None if v is None else round(float(v), nd)


def race_dossier(con, race_id: str) -> Optional[dict]:
    race = rows(con, "SELECT * FROM races WHERE race_id=?", (race_id,))
    if not race:
        return None
    race = race[0]
    fc = rows(con, "SELECT * FROM forecasts WHERE race_id=? ORDER BY run_date DESC LIMIT 1", (race_id,))
    detail = json.loads(fc[0]["detail"]) if fc else {}
    try:
        outside = {o["name"]: o for o in rows(con, "SELECT * FROM outside_spending WHERE race_id=?", (race_id,))}
    except Exception:  # noqa: BLE001
        outside = {}
    cands = []
    for c in rows(con, "SELECT * FROM candidates WHERE race_id=? ORDER BY major DESC, name", (race_id,)):
        o = outside.get(c["name"]) or {}
        cands.append(dict(name=c["name"], party=c["party"], incumbent=bool(c["is_incumbent"]), principal=bool(c["major"]),
                          raised=_round(c["receipts"], 0), cash_on_hand=_round(c["cash_on_hand"], 0),
                          outside_support=_round(o.get("support"), 0), outside_oppose=_round(o.get("oppose"), 0)))
    polls = [dict(pollster=p["pollster"], sponsor_lean=p["sponsor_lean"], end_date=p["end_date"], n=p["sample_size"], pop=p["population"],
                  dem=p["dem_pct"], rep=p["rep_pct"], hypothetical=bool(p["hypothetical"]))
             for p in rows(con, "SELECT * FROM polls WHERE race_id=? ORDER BY hypothetical, end_date DESC LIMIT 12", (race_id,))]
    aggs = [dict(source=a["source"], as_of=a["as_of"], margin=a["margin"]) for a in rows(con, "SELECT * FROM poll_aggregates WHERE race_id=?", (race_id,))]
    ratings = [dict(rater=r["rater"], rating=r["rating"], as_of=r["as_of"]) for r in rows(con, "SELECT * FROM ratings WHERE race_id=?", (race_id,))]
    markets = [dict(platform=m["platform"], p_dem=_round(m["p_dem"], 2), p_rep=_round(m["p_rep"], 2), p_other=_round(m["p_other"], 2))
               for m in rows(con, "SELECT * FROM markets WHERE race_id=?", (race_id,))]
    news = [dict(title=n["title"], source=n["source"], published=(n["published"] or "")[:10])
            for n in rows(con, "SELECT * FROM news WHERE race_id=? ORDER BY published DESC LIMIT 12", (race_id,))]
    fund = detail.get("fund") or {}
    poll = detail.get("poll") or {}
    rating = detail.get("rating") or {}
    return dict(
        race=dict(id=race_id, name=race["name"], chamber=race["chamber"], state=race["state"], district=race["district"],
                  incumbent=race["incumbent"], incumbent_party=race["incumbent_party"], incumbent_running=bool(race["incumbent_running"]),
                  holder_party=race["holder_party"], pvi_dem_minus_rep=race["pvi"], status=race["status"], uncontested=bool(detail.get("uncontested"))),
        candidates=cands, expert_ratings=ratings, polls=polls, poll_averages_elsewhere=aggs, prediction_markets=markets, headlines=news,
        baseline_model=dict(
            margin=_round(detail.get("prior_margin") if not poll else None), fundamentals=dict(margin=_round(fund.get("margin")), lean=_round(fund.get("lean")),
            environment=_round(fund.get("environment")), incumbency=_round(fund.get("incumbency")), money=_round(fund.get("money"))),
            rating_consensus=dict(label=rating.get("label"), implied_margin=_round(rating.get("margin")), n_raters=rating.get("n")),
            polling_average=dict(margin=_round(poll.get("margin")), n_polls=poll.get("n_polls"), effective_n=_round(poll.get("n_eff")), last_poll=poll.get("last_poll")) if poll else None,
            combined_margin=_round(fc[0]["margin"]) if fc else None, sd=_round(detail.get("sigma_total")), p_dem=_round(detail.get("p_dem_analytic"), 3),
            label=detail.get("label"), notes=detail.get("notes"),
        ),
    )


def national_dossier(con) -> dict:
    gb = rows(con, "SELECT source, as_of, dem, rep, margin FROM generic_ballot ORDER BY as_of DESC LIMIT 8")
    chambers = [dict(chamber=c["chamber"], p_dem_control=_round(c["p_dem"], 3), dem_seats_mean=_round(c["dem_seats_mean"]),
                     dem_seats_p10=c["dem_seats_p10"], dem_seats_p90=c["dem_seats_p90"])
                for c in rows(con, "SELECT * FROM chamber_forecasts WHERE run_date=(SELECT max(run_date) FROM chamber_forecasts)")]
    markets = [dict(race_id=m["race_id"], platform=m["platform"], p_dem=_round(m["p_dem"], 2)) for m in rows(con, "SELECT * FROM markets WHERE race_id LIKE '%-CONTROL'")]
    labels = rows(con, "SELECT json_extract(detail, '$.label') label, count(*) n FROM forecasts WHERE run_date=(SELECT max(run_date) FROM forecasts) GROUP BY 1")
    news = [dict(title=n["title"], source=n["source"], published=(n["published"] or "")[:10])
            for n in rows(con, "SELECT n.* FROM news n JOIN races r USING(race_id) WHERE r.chamber='senate' ORDER BY n.published DESC LIMIT 25")]
    return dict(generic_ballot=gb, quantitative_chambers=chambers, chamber_markets=markets, race_label_counts=labels, recent_headlines=news)


PROMPT_VERSION = "2"


def _hash(payload) -> str:
    return hashlib.sha1((PROMPT_VERSION + json.dumps(payload, sort_keys=True, default=str)).encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------- HTTP + parsing
# OpenCode Go routes requests by session; one id per pipeline run keeps prompt-cache reuse across races.
SESSION_ID = os.environ.get("OPENCODE_SESSION_ID") or f"electionpredictions-{uuid.uuid4()}"


def _headers() -> dict:
    return {"Authorization": f"Bearer {OPENCODE_API_KEY}", "Content-Type": "application/json", "User-Agent": USER_AGENT,
            "x-opencode-session": SESSION_ID}


def _post(path: str, body: dict, timeout: int = 180) -> requests.Response:
    return requests.post(f"{AI_BASE_URL.rstrip('/')}/{path.lstrip('/')}", json=body, timeout=timeout, headers=_headers())


def _extract_text(data: dict) -> str:
    if isinstance(data.get("choices"), list) and data["choices"]:
        content = (data["choices"][0].get("message") or {}).get("content")
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


def parse_json(text: str) -> dict:
    """Pull the first JSON object out of a model reply (tolerates code fences and preamble)."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError("no JSON object in response")


def complete(system: str, user: str, retries: int = 3) -> str:
    attempts = [
        # reasoning models spend part of the cap thinking before the JSON, so leave generous room
        ("chat/completions", {"model": AI_MODEL, "temperature": 0.2, "max_tokens": 4000,
                              "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}),
        ("responses", {"model": AI_MODEL, "instructions": system, "max_output_tokens": 4000, "input": [{"role": "user", "content": user}]}),
    ]
    if AI_MODEL.startswith("muse-spark"):
        attempts.reverse()  # Muse Spark is served through the Responses API on OpenCode Zen; chat/completions 500s
    last = None
    denied = []
    for path, body in attempts:
        for attempt in range(retries):
            r = _post(path, body)
            if r.status_code == 401:
                raise AuthError(f"OpenCode rejected the API key (HTTP 401): {r.text[:200]}")
            if r.status_code == 402:
                raise AuthError(f"OpenCode account has no credit (HTTP 402): {r.text[:200]} — add funds at opencode.ai")
            if r.status_code == 403:
                # can be a per-endpoint or per-model permission rather than a bad key: try the other shape first
                denied.append(f"{path}: HTTP 403: {r.text[:200]}")
                break
            if r.status_code in (404, 405) or (r.status_code == 400 and "endpoint" in r.text.lower()):
                last = f"{path}: HTTP {r.status_code}: {r.text[:120]}"
                break
            if r.status_code == 429 or r.status_code >= 500:
                last = f"{path}: HTTP {r.status_code}"
                time.sleep(4 * (attempt + 1))
                continue
            if not r.ok:
                raise RuntimeError(f"{path}: HTTP {r.status_code}: {r.text[:200]}")
            text = _extract_text(r.json())
            if not text:
                raise RuntimeError(f"{path}: empty response")
            return text
    if denied and len(denied) == len(attempts):
        raise AuthError("OpenCode refused both endpoints (check the key and that the model is enabled for it): " + " | ".join(denied))
    raise RuntimeError(f"OpenCode request failed ({last or denied})")


def probe() -> dict:
    """One tiny request per endpoint shape; returns statuses and response snippets for diagnosis."""
    out = {"base_url": AI_BASE_URL, "model": AI_MODEL, "key_present": bool(OPENCODE_API_KEY), "key_prefix": OPENCODE_API_KEY[:6] + "…" if OPENCODE_API_KEY else None,
           "session": SESSION_ID}
    tests = [
        ("chat/completions", {"model": AI_MODEL, "max_tokens": 20, "messages": [{"role": "user", "content": "Reply with the single word OK."}]}),
        ("responses", {"model": AI_MODEL, "max_output_tokens": 20, "input": [{"role": "user", "content": "Reply with the single word OK."}]}),
        ("models", None),
    ]
    for path, body in tests:
        try:
            if body is None:
                r = requests.get(f"{AI_BASE_URL.rstrip('/')}/{path}", timeout=60, headers=_headers())
            else:
                r = _post(path, body, timeout=60)
            snippet = r.text[:300].replace("\n", " ")
            entry = {"status": r.status_code, "body": snippet}
            if r.ok and body is not None:
                try:
                    entry["text"] = _extract_text(r.json())[:80]
                except Exception as e:  # noqa: BLE001
                    entry["parse_error"] = repr(e)
            if r.ok and body is None:
                try:
                    ids = [m.get("id") for m in (r.json().get("data") or [])]
                    entry["models"] = [i for i in ids if i and "muse" in i.lower()][:10] or ids[:10]
                except Exception as e:  # noqa: BLE001
                    entry["parse_error"] = repr(e)
            out[path] = entry
        except Exception as e:  # noqa: BLE001
            out[path] = {"error": repr(e)}
    return out


# ---------------------------------------------------------------------------- validation
def validate_race_decision(d: dict, baseline_margin: Optional[float]) -> dict:
    """Coerce/clean a race decision; raises ValueError when unusable."""
    out = {}
    try:
        out["margin"] = float(d["margin"])
        out["sd"] = float(d.get("sd", 6.0))
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError(f"missing numeric margin/sd: {e}") from e
    if not (-60 <= out["margin"] <= 60):
        raise ValueError("margin out of range")
    out["sd"] = min(12.0, max(2.5, out["sd"]))
    try:
        p = float(d.get("p_dem"))
    except (TypeError, ValueError):
        p = None
    out["p_dem"] = min(1.0, max(0.0, p)) if p is not None else None
    label = str(d.get("label", "")).strip()
    out["label"] = label if label in LABELS else (prob_label(out["p_dem"]) if out["p_dem"] is not None else None)
    conf = str(d.get("confidence", "medium")).lower()
    out["confidence"] = conf if conf in ("low", "medium", "high") else "medium"
    kf = d.get("key_factors") or []
    out["key_factors"] = [str(x).strip() for x in kf if str(x).strip()][:5] if isinstance(kf, list) else []
    for k in ("rationale", "watch", "overview"):
        out[k] = str(d.get(k) or "").strip()
    out["baseline_margin"] = baseline_margin
    return out


def validate_national_decision(d: dict) -> dict:
    out = dict(
        environment_adjustment=min(3.0, max(-3.0, float(d.get("environment_adjustment", 0) or 0))),
        uncertainty_multiplier=min(1.5, max(0.7, float(d.get("uncertainty_multiplier", 1) or 1))),
        summary=str(d.get("summary") or "").strip(),
        key_factors=[str(x).strip() for x in (d.get("key_factors") or []) if str(x).strip()][:6],
        chambers={k: str(v).strip() for k, v in (d.get("chambers") or {}).items() if k in ("house", "senate", "governor")},
    )
    return out


# ---------------------------------------------------------------------------- decisions
def decide_race(dossier: dict) -> dict:
    user = "Race dossier (JSON):\n" + json.dumps(dossier, default=str)
    text = complete(RACE_SYSTEM, user)
    try:
        d = parse_json(text)
    except (ValueError, json.JSONDecodeError):
        text = complete(RACE_SYSTEM, user + "\n\nYour previous reply was not valid JSON. Reply with the JSON object only.")
        d = parse_json(text)
    return validate_race_decision(d, (dossier.get("baseline_model") or {}).get("combined_margin"))


def decide_national(dossier: dict) -> dict:
    user = "National dossier (JSON):\n" + json.dumps(dossier, default=str)
    text = complete(NATIONAL_SYSTEM, user)
    try:
        d = parse_json(text)
    except (ValueError, json.JSONDecodeError):
        text = complete(NATIONAL_SYSTEM, user + "\n\nYour previous reply was not valid JSON. Reply with the JSON object only.")
        d = parse_json(text)
    return validate_national_decision(d)


def load(con, verbose=True, race_ids: Optional[list[str]] = None, workers: int = 4, limit: Optional[int] = None, max_calls: int = 700) -> dict:
    """Decide every race whose evidence changed, then the national review."""
    started = now_iso()
    con.executescript(SCHEMA_SQL)
    if not OPENCODE_API_KEY:
        if verbose:
            print("  ai: skipped (no OPENCODE_API_KEY); the quantitative baseline stands")
        return {"skipped": True}
    if not rows(con, "SELECT 1 FROM forecasts LIMIT 1"):
        raise SystemExit("Run the model once before the ai stage (it needs the baseline).")
    race_ids = race_ids or [r["race_id"] for r in rows(con, "SELECT race_id FROM races ORDER BY chamber, state, district")]
    if limit:
        race_ids = race_ids[:limit]
    existing = {r["race_id"]: r["input_hash"] for r in rows(con, "SELECT race_id, input_hash FROM ai_decisions")}
    todo = []
    for rid in race_ids:
        dossier = race_dossier(con, rid)
        if not dossier or dossier["race"].get("uncontested"):
            continue
        h = _hash(dossier)
        if existing.get(rid) != h:
            todo.append((rid, dossier, h))
    stats = {"model": AI_MODEL, "races": len(race_ids), "decided": 0, "to_decide": len(todo), "errors": 0, "national": False}
    if len(todo) > max_calls:
        if verbose:
            print(f"  ai: {len(todo)} races need decisions; capping at {max_calls} this run (AI_MAX_CALLS)")
        todo = todo[:max_calls]

    def save(rid, dec, h):
        upsert(con, "ai_decisions", [dict(race_id=rid, input_hash=h, decision=json.dumps(dec), model=AI_MODEL, generated_at=now_iso())], keys=["race_id"])
        con.commit()

    if todo:
        try:  # probe with one race so a bad key fails fast
            rid, dossier, h = todo[0]
            save(rid, decide_race(dossier), h)
            stats["decided"] += 1
        except AuthError as e:
            print(f"  ai: {e}; skipping.")
            log_run(con, "ai", started, False, str(e))
            return stats
        except Exception as e:  # noqa: BLE001
            stats["errors"] += 1
            if verbose:
                print(f"  ai: {todo[0][0]} failed: {e!r}")
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(decide_race, dossier): (rid, h) for rid, dossier, h in todo[1:]}
            for fut in as_completed(futs):
                rid, h = futs[fut]
                try:
                    save(rid, fut.result(), h)
                    stats["decided"] += 1
                except Exception as e:  # noqa: BLE001
                    stats["errors"] += 1
                    if verbose:
                        print(f"  ai: {rid} failed: {e!r}")
    try:
        nd = national_dossier(con)
        h = _hash(nd)
        cur = rows(con, "SELECT input_hash FROM ai_national WHERE id=1")
        if not cur or cur[0]["input_hash"] != h:
            dec = decide_national(nd)
            con.execute("INSERT INTO ai_national (id, input_hash, decision, model, generated_at) VALUES (1,?,?,?,?) "
                        "ON CONFLICT(id) DO UPDATE SET input_hash=excluded.input_hash, decision=excluded.decision, model=excluded.model, generated_at=excluded.generated_at",
                        (h, json.dumps(dec), AI_MODEL, now_iso()))
            con.commit()
        stats["national"] = True
    except Exception as e:  # noqa: BLE001
        stats["errors"] += 1
        if verbose:
            print(f"  ai: national review failed: {e!r}")
    if verbose:
        print(f"  ai: {stats}")
    log_run(con, "ai", started, stats["errors"] == 0, json.dumps(stats))
    return stats


def decisions(con) -> tuple[dict[str, dict], Optional[dict]]:
    """Latest decisions keyed by race id, and the national review (or None). Safe when the tables don't exist."""
    try:
        per_race = {r["race_id"]: json.loads(r["decision"]) for r in rows(con, "SELECT race_id, decision FROM ai_decisions")}
        nat = rows(con, "SELECT decision FROM ai_national WHERE id=1")
        return per_race, (json.loads(nat[0]["decision"]) if nat else None)
    except Exception:  # noqa: BLE001
        return {}, None
