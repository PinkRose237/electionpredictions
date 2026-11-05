"""The model-revision step: on every run the model's specification is rebuilt against the latest evidence.

Flow (see pipeline.py):
    ingest -> calibrate (data-driven proposal) -> baseline simulation of the proposal
           -> revision: a reviewer (LLM) reads the full evidence dossier, the proposal, its diagnostics and the
              recent revision history, and returns a complete new spec with a reason for each change
           -> guardrails (spec.validate: bounds, per-revision step limits, normalised odds)
           -> new spec version + changelog -> final simulation -> export.
The reviewer never sees prediction markets (they stay an independent comparison). A revision is cached by an
input hash: when neither the evidence nor the proposal changed since the last revision, no call is made.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Optional

from . import llm
from .config import AI_MODEL, ELECTION_DATE, INCUMBENT_PARTY, days_to_election
from .db import log_run, now_iso, rows
from .model.spec import BOUNDS, DESCRIPTIONS, EFFECT_BOUNDS, EFFECT_STEP, MAX_NOMINEES, MAX_STATE_ADJ, STATE_ADJ_BOUNDS, STATE_ADJ_STEP, validate

PROMPT_VERSION = "1"

SYSTEM = f"""You are the chief modeler of a nonpartisan forecast of the 2028 United States presidential election
(November 7, 2028; 538 electoral votes; 270 to win; the White House party is {INCUMBENT_PARTY} and the seat is open).
The forecast engine is fixed; what it computes is set by a JSON specification. On every update you rebuild that
specification from the latest evidence so the model adapts as the campaign develops.

You receive a dossier with: the current specification; the calibration proposal (a mechanical, data-driven update
of it); bounds, the largest allowed change per update, and a description of every parameter; the evidence
(national and state trial-heat polls with a regression of each candidate's polling strength, primary polling and
each party's candidate field, presidential approval, the economy, expert ratings, fundraising, recent headlines);
diagnostics of what the proposal produces; and the recent revision history.

Decide the specification for this update. Principles:
- Start from the proposal. Change a parameter only when specific evidence in the dossier justifies it, and say why.
  Stability matters: an update with no new evidence should change little or nothing.
- Nominee odds ("p"): your best estimate of who each party nominates. Weigh primary polling, who has declared or
  ruled out a run (from the field list and headlines), fundraising and the calendar. Far from the primaries, keep
  real weight on "Other" (someone not yet listed). At most {MAX_NOMINEES} named candidates per party plus "Other".
- Candidate "effect": points of general-election margin the nominee is worth to their own party versus an average
  nominee (positive = stronger), within {EFFECT_BOUNDS[0]:g} to {EFFECT_BOUNDS[1]:g}, at most {EFFECT_STEP:g} change per
  update. Ground it in the polling-strength regression; head-to-head polls this early are weak evidence.
- "home_state": two-letter code of the candidate's home state, or null.
- state_adjustments: only for evidence the rest of the model misses (consistent state polling beyond what the lean
  update already absorbed, a structural change in a state's electorate). Each within {STATE_ADJ_BOUNDS[0]:g} to
  {STATE_ADJ_BOUNDS[1]:g} points (Democratic-positive), at most {STATE_ADJ_STEP:g} change per update, at most
  {MAX_STATE_ADJ}, each with a reason. Omit a state to remove its adjustment.
- Uncertainty: two years out the honest range is wide; narrow it only as real information arrives.
- Use only the dossier. Never invent polls, events, candidates or numbers. Never express a preference for any
  party or candidate.

Return ONLY a JSON object:
{{
  "title": string,      // headline for this update's changelog entry, at most 80 characters
  "summary": string,    // 2-3 sentences, plain language: what changed in the model and why
  "reasons": {{ "<parameter path, or nominees.D / nominees.R / nominees.D.<name> / state_adjustments.<contest>>": string }},
  "spec": {{ ... the complete specification, same shape as the proposal ... }}
}}
Voice for title, summary and reasons: they are published in the forecast's public model log. Write about the model
and the evidence in the third person ("The model now gives Newsom...", "State polls of Nevada..."). Never mention
artificial intelligence, a language model, an assistant, a reviewer, a prompt, a dossier, or yourself."""


def _round(v, nd=1):
    return None if v is None else round(float(v), nd)


def dossier(con, prev: dict, proposal: dict, nomev: dict, baseline: dict, today: date) -> dict:
    ev = baseline["evidence"]
    nat = ev.get("national_polls") or {}
    polls = rows(con, "SELECT * FROM polls WHERE scope='national' ORDER BY end_date DESC LIMIT 40")
    spolls = rows(con, "SELECT * FROM polls WHERE scope='state' ORDER BY end_date DESC LIMIT 40")

    def poll_row(p):
        return dict(pollster=p["pollster"], end=p["end_date"], n=p["sample_size"], pop=p["population"], dem=p["dem_name"], rep=p["rep_name"],
                    dem_pct=p["dem_pct"], rep_pct=p["rep_pct"], third_party=p["other_pct"], contest=p["contest_id"])

    def news(topic, n):
        return [dict(t=r["title"], src=r["source"], d=(r["published"] or "")[:10])
                for r in rows(con, "SELECT * FROM news WHERE topic=? ORDER BY published DESC LIMIT ?", (topic, n))]

    cand_news = {}
    for party in ("D", "R"):
        for c in proposal["nominees"][party][:8]:
            if c["name"] != "Other":
                items = news(c["name"], 4)
                if items:
                    cand_news[c["name"]] = items
    prim_polls = {p: [dict(pollster=r["pollster"], end=r["end_date"], shares=json.loads(r["shares"]))
                      for r in rows(con, "SELECT * FROM primary_polls WHERE party=? ORDER BY end_date DESC LIMIT 8", (p,))] for p in ("D", "R")}
    by_id = {c["contest_id"]: c for c in baseline["contests"]}
    close = sorted(baseline["contests"], key=lambda c: abs(c["p_dem"] - 0.5))[:14]
    history = [dict(version=r["version"], date=r["run_date"], title=r["title"], summary=r["summary"])
               for r in rows(con, "SELECT version, run_date, title, summary FROM model_specs ORDER BY version DESC LIMIT 6")]
    money = rows(con, "SELECT name, party, receipts, cash, coverage_end FROM money ORDER BY receipts DESC LIMIT 15")
    return dict(
        today=today.isoformat(), election_date=ELECTION_DATE.isoformat(), days_to_election=days_to_election(today),
        parameters={p: dict(low=lo, high=hi, max_step=st, meaning=DESCRIPTIONS.get(p)) for p, (lo, hi, st) in BOUNDS.items()},
        current_spec=prev, proposal=proposal, recent_revisions=history,
        evidence=dict(
            national_environment=ev["environment"], fundamentals=ev["fundamentals"], approval=ev["approval"], economy=ev["economy"],
            national_poll_regression=dict(average_matchup_margin=nat.get("g"), sd=nat.get("g_sd"), n_polls=nat.get("n_polls"),
                                          last_poll=nat.get("last_poll"), candidate_strengths=nat.get("strengths")),
            national_polls=[poll_row(p) for p in polls], state_polls=[poll_row(p) for p in spolls],
            state_poll_updates=ev["state_updates"],
            primaries={p: dict(average=nomev[p]["average"].get("shares"), n_polls=nomev[p]["average"].get("n_polls"),
                               aggregates=nomev[p]["average"].get("aggregates"), poll_implied_odds={k: round(v, 3) for k, v in nomev[p]["implied"].items()},
                               field=nomev[p]["field"], recent_polls=prim_polls[p]) for p in ("D", "R")},
            expert_ratings=ev["ratings"], fundraising=money,
            headlines=dict(national=news("NATIONAL", 12), democratic_primary=news("D", 10), republican_primary=news("R", 10),
                           polls=news("POLLS", 8), candidates=cand_news),
        ),
        diagnostics=dict(
            proposal_result=dict(p_dem=_round(baseline["ec"]["p_dem"], 3), p_rep=_round(baseline["ec"]["p_rep"], 3),
                                 dem_ev=dict(mean=_round(baseline["ec"]["dem_ev"]["mean"]), p10=baseline["ec"]["dem_ev"]["p10"], p90=baseline["ec"]["dem_ev"]["p90"]),
                                 popular_vote_margin=_round(baseline["popular"]["margin"]), uncertainty=baseline["uncertainty"]),
            closest_contests=[dict(id=c["contest_id"], margin=_round(c["margin"]), p_dem=_round(c["p_dem"], 3), tipping_point=_round(c["tip"], 3),
                                   lean=_round(c["lean"]), poll_shift=_round(c["poll_shift"]), adjustment=_round(c["adjustment"])) for c in close],
            if_nominee={p: [dict(name=x["name"], p_nominee=_round(x["p_nominee"], 3), p_win=_round(x["p_win_if_nominee"], 3))
                            for x in baseline["conditional"][p]] for p in ("D", "R")},
            top_matchups=[dict(dem=s["dem"], rep=s["rep"], p=_round(s["p"], 3), p_dem=_round(s["p_dem"], 3)) for s in baseline["scenarios"][:8]],
            tipping_point_leaders=sorted(({"id": k, "p": _round(v["tip"], 3)} for k, v in by_id.items()), key=lambda x: -x["p"])[:8],
        ),
    )


def input_hash(d: dict) -> str:
    slim = {k: v for k, v in d.items() if k not in ("today", "days_to_election", "recent_revisions")}
    return hashlib.sha1((PROMPT_VERSION + AI_MODEL + json.dumps(slim, sort_keys=True, default=str)).encode()).hexdigest()[:16]


def revise(con, prev: dict, proposal: dict, nomev: dict, baseline: dict, today: date, verbose: bool = True) -> Optional[dict]:
    """Returns {spec, title, summary, reasons, notes, input_hash, reused} or None when no revision could be made."""
    started = now_iso()
    if not llm.available():
        if verbose:
            print("  revision: skipped (no OPENCODE_API_KEY); the calibrated spec stands")
        return None
    d = dossier(con, prev, proposal, nomev, baseline, today)
    h = input_hash(d)
    last = rows(con, "SELECT input_hash FROM model_specs WHERE origin='revision' ORDER BY version DESC LIMIT 1")
    if last and last[0]["input_hash"] == h:
        if verbose:
            print("  revision: evidence unchanged since the last revision; keeping it")
        return dict(spec=prev, title=None, summary=None, reasons={}, notes=[], input_hash=h, reused=True)
    try:
        reply = llm.ask_json(SYSTEM, "Dossier (JSON):\n" + json.dumps(d, default=str), max_tokens=12000)
    except llm.AuthError as e:
        print(f"  revision: {e}; the calibrated spec stands")
        log_run(con, "revision", started, False, str(e))
        return None
    except Exception as e:  # noqa: BLE001
        print(f"  revision: failed ({e!r}); the calibrated spec stands")
        log_run(con, "revision", started, False, repr(e))
        return None
    notes: list[str] = []
    raw = reply.get("spec") if isinstance(reply.get("spec"), dict) else {}
    spec = validate(raw, prev, notes) if raw else proposal
    reasons = {str(k): str(v).strip()[:300] for k, v in (reply.get("reasons") or {}).items() if str(v).strip()} if isinstance(reply.get("reasons"), dict) else {}
    out = dict(spec=spec, title=str(reply.get("title") or "").strip()[:100] or None, summary=str(reply.get("summary") or "").strip()[:900] or None,
               reasons=reasons, notes=notes, input_hash=h, reused=False)
    log_run(con, "revision", started, True, json.dumps(dict(title=out["title"], clamped=len(notes))))
    if verbose:
        print(f"  revision: {out['title']!r} ({len(notes)} values limited by guardrails)")
    return out
