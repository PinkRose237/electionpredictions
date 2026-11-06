"""Written summaries for the site: the national outlook and each competitive contest.

Generated after the final simulation from its numbers and the evidence, cached by an input hash so an update
re-writes only what changed. The text is published as the forecast's own prose (it never refers to how it was
written). Without OPENCODE_API_KEY the site shows the numbers without these paragraphs."""
from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import llm
from . import config
from .db import log_run, now_iso, rows, upsert

PROMPT_VERSION = "1"
VOICE = """Voice: plain, neutral prose in the third person, written as the forecast itself. Refer to evidence directly
("national polls show", "Pennsylvania voted for..."). Never mention a model, simulation, specification, dossier,
analyst, artificial intelligence or yourself, and do not quote the forecast's own probabilities. No markdown.
Use only the information provided; never invent polls, events or numbers; never express a preference."""

NATIONAL_SYSTEM = """You write the national overview of a nonpartisan forecast of the 2028 U.S. presidential election.
Return ONLY a JSON object:
{
  "summary": string,          // 130-190 words, two short paragraphs separated by a blank line: where the race stands and why
  "key_factors": [string],    // 3 to 5 short national factors, most important first
  "nominations": {"D": string, "R": string},   // one sentence each on the state of each party's nomination contest
  "watch": string             // one sentence: what could move the race next
}
""" + VOICE

CONTEST_SYSTEM = """You write the summary for one state (or congressional district) in a nonpartisan forecast of the 2028
U.S. presidential election. Return ONLY a JSON object:
{
  "overview": string,         // 80-130 words, two short paragraphs separated by a blank line
  "key_factors": [string],    // 2 to 4 short factors, most important first
  "watch": string             // one sentence: what could change the outlook here
}
""" + VOICE


def _h(payload) -> str:
    return hashlib.sha1((PROMPT_VERSION + json.dumps(payload, sort_keys=True, default=str)).encode()).hexdigest()[:16]


def _half(v):
    """Round to the nearest half point: summaries are rewritten when numbers move, not on decimal noise."""
    return None if v is None else round(float(v) * 2) / 2


def _r(v, nd=1):
    return None if v is None else round(float(v), nd)


def national_payload(con, final: dict, spec: dict) -> dict:
    ev = final["evidence"]
    news = [dict(t=n["title"], src=n["source"], d=(n["published"] or "")[:10])
            for n in rows(con, "SELECT * FROM news WHERE topic IN ('NATIONAL','D','R','POLLS') ORDER BY published DESC LIMIT 25")]
    from .revision import current_storylines
    from .sources import midterm2026

    mid = midterm2026.summary()
    env = ev["environment"]
    return dict(
        dem_ev=round(final["ec"]["dem_ev"]["mean"] / 5) * 5, dem_ev_range=[final["ec"]["dem_ev"]["p10"] // 10 * 10, final["ec"]["dem_ev"]["p90"] // 10 * 10],
        favoured="D" if final["ec"]["p_dem"] > final["ec"]["p_rep"] else "R", popular_vote_margin=_half(final["popular"]["margin"]),
        environment=dict(total=_half(env["environment"]), polls=_half(env.get("polls")), fundamentals=_half(env["fundamentals"]),
                         poll_weight=_r(env["poll_weight"], 1), adjustment=_half(env.get("adjustment"))),
        approval=ev["approval"] and dict(net=_r(ev["approval"]["net"], 0), as_of=ev["approval"].get("as_of")),
        economy=ev["economy"],
        national_polls=None if not ev.get("national_polls") else dict(average=_half(ev["national_polls"]["g"]), n=ev["national_polls"]["n_polls"],
                                                                     strengths={k: _half(v["strength"]) for k, v in ev["national_polls"]["strengths"].items()}),
        midterm_2026_house_vote=mid and dict(margin=_half(mid["house_vote"]["margin"]), seats=mid["seats"]["house"]),
        third_party=spec.get("third_party"),
        nominees={p: [dict(name=c["name"], odds=_r(c["p"], 2)) for c in spec["nominees"][p][:6]] for p in ("D", "R")},
        closest=[dict(id=c["contest_id"], margin=_half(c["margin"])) for c in sorted(final["contests"], key=lambda c: abs(c["p_dem"] - 0.5))[:10]],
        storylines=[dict(title=x["title"], detail=x.get("detail"), leans=x.get("leans")) for x in current_storylines(con)],
        headlines=news[:15],
    )


def contest_payload(con, c: dict, final: dict, spec: dict) -> dict:
    from .model.contests import contests as contest_list

    meta = next(x for x in contest_list(spec) if x["contest_id"] == c["contest_id"])
    polls = [dict(pollster=p["pollster"], end=p["end_date"], dem=p["dem_name"], rep=p["rep_name"], dem_pct=p["dem_pct"], rep_pct=p["rep_pct"])
             for p in rows(con, "SELECT * FROM polls WHERE contest_id=? ORDER BY end_date DESC LIMIT 8", (c["contest_id"],))]
    news = [dict(t=n["title"], src=n["source"], d=(n["published"] or "")[:10])
            for n in rows(con, "SELECT * FROM news WHERE topic=? ORDER BY published DESC LIMIT 8", (c["contest_id"],))]
    homes = [dict(name=x["name"], party=p) for p in ("D", "R") for x in spec["nominees"][p] if x.get("home_state") == meta["state"]]
    from .sources import midterm2026

    mid = (midterm2026.summary() or {}).get("statewide", {}).get(meta["state"]) if not meta["district"] else None
    return dict(contest=meta["name"], electoral_votes=meta["evs"], result_2020=meta["margin20"], result_2024=meta["margin24"],
                lean_vs_nation=_half(c["lean"]), expected_margin=_half(c["margin"]), range_80pct=[round(c["p10"]), round(c["p90"])],
                tipping_point_odds=round(c["tip"], 2), national_environment=_half(final["evidence"]["environment"]["environment"]),
                state_adjustment=(spec["state_adjustments"].get(c["contest_id"]) or None), home_state_candidates=homes,
                midterm_2026_statewide=mid and {k: v.get("margin") for k, v in mid.items()},
                polls=polls, headlines=news[:6])


def write(con, final: dict, spec: dict, verbose: bool = True, workers: int = 10, budget_s: float = 360.0) -> dict:
    """(Re)write the summaries whose inputs changed: the national overview first, then contests by importance.
    Stops starting new ones after `budget_s` seconds so the summaries never hold up an update; the rest are
    written on the next run (their inputs still differ from what is stored)."""
    import time

    started = now_iso()
    t0 = time.time()
    stats = dict(written=0, cached=0, errors=0, deferred=0)
    if not llm.available():
        if verbose:
            print("  narrative: skipped (no OPENCODE_API_KEY)")
        return dict(skipped=True)
    existing = {r["key"]: r["input_hash"] for r in rows(con, "SELECT key, input_hash FROM narratives")}
    jobs = []
    p = national_payload(con, final, spec)
    jobs.append(("NATIONAL", NATIONAL_SYSTEM, p, _h(p)))
    ranked = sorted(final["contests"], key=lambda c: (-c["tip"], abs(c["p_dem"] - 0.5)))
    for c in ranked:
        if 0.02 <= c["p_dem"] <= 0.98 or c["tip"] >= 0.01:
            p = contest_payload(con, c, final, spec)
            jobs.append((c["contest_id"], CONTEST_SYSTEM, p, _h(p)))
    todo = [j for j in jobs if existing.get(j[0]) != j[3]]
    stats["cached"] = len(jobs) - len(todo)

    def one(job):
        if time.time() - t0 > budget_s:
            return job[0], None, None, None
        key, system, payload, h = job
        body, model = llm.ask_json_with(system, "Information (JSON):\n" + json.dumps(payload, default=str), config.AI_MODELS_NARRATIVE,
                                        max_tokens=3000, timeout=120)
        return key, h, body, model

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(one, j) for j in todo]
        for f in as_completed(futs):
            try:
                key, h, body, model = f.result()
            except llm.AuthError as e:
                print(f"  narrative: {e}")
                stats["errors"] += 1
                break
            except Exception as e:  # noqa: BLE001
                stats["errors"] += 1
                if verbose:
                    print(f"  narrative failed: {str(e)[:200]}")
                continue
            if body is None:
                stats["deferred"] += 1
                continue
            upsert(con, "narratives", [dict(key=key, input_hash=h, body=json.dumps(clean(body)), model=model, generated_at=now_iso())], keys=["key"])
            con.commit()
            stats["written"] += 1
    stats["seconds"] = round(time.time() - t0)
    if verbose:
        print(f"  narrative: {stats}")
    log_run(con, "narrative", started, stats["errors"] == 0, json.dumps(stats))
    return stats


def _paras(text: str, limit: int) -> str:
    from .revision import scrub

    return "\n\n".join(p for p in (scrub(x, limit) for x in str(text or "").split("\n\n")) if p)


def clean(body: dict) -> dict:
    from .revision import scrub

    out = {}
    for k, lim in (("summary", 1400), ("overview", 1100), ("watch", 300)):
        if body.get(k):
            v = _paras(body[k], lim)
            if v:
                out[k] = v
    kf = body.get("key_factors")
    if isinstance(kf, list):
        out["key_factors"] = [x for x in (scrub(x, 160) for x in kf) if x][:5]
    nm = body.get("nominations")
    if isinstance(nm, dict):
        out["nominations"] = {k: scrub(v, 400) for k, v in nm.items() if k in ("D", "R") and scrub(v, 400)}
    return out


def load(con) -> dict[str, dict]:
    try:
        return {r["key"]: dict(json.loads(r["body"]), generated_at=r["generated_at"]) for r in rows(con, "SELECT * FROM narratives")}
    except Exception:  # noqa: BLE001
        return {}


def stale_keys(con, final: dict) -> None:
    """Drop summaries of contests that are no longer competitive (so the site doesn't show outdated prose)."""
    keep = {"NATIONAL"} | {c["contest_id"] for c in final["contests"] if 0.02 <= c["p_dem"] <= 0.98 or c["tip"] >= 0.01}
    for k in [r["key"] for r in rows(con, "SELECT key FROM narratives")]:
        if k not in keep:
            con.execute("DELETE FROM narratives WHERE key=?", (k,))
    con.commit()
