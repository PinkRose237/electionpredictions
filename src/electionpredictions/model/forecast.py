"""Combine polls, fundamentals and ratings per race, then simulate correlated outcomes."""
from __future__ import annotations

import json
import math
from datetime import date
from typing import Optional

import numpy as np
from scipy.stats import norm

from ..config import GOVERNORS_NOT_UP, REDISTRICTED_2026, REGION_OF, SENATE_NOT_UP, days_to_election
from ..db import log_run, now_iso, rows, upsert
from ..util import prob_label
from .fundamentals import PARAMS, RATING_SD, RATING_WEIGHT, fundamentals, rating_summary
from .pollavg import average

# D-side independents who have said they will not caucus with Democrats
NON_CAUCUSING_INDEPENDENTS = {"NE-SEN"}
SIGMA_REGION = 1.0
SIGMA_STATE = 1.5
SIGMA_DEMO = 1.0   # per standardised demographic axis (college share, white non-Hispanic share)
T_DF = 5
AI_MAX_SHIFT = 10.0   # a race decision may move the margin at most this far from the quantitative baseline


def national_sigma(dte: int) -> float:
    """Generic-ballot / uniform-swing error: ~1.5 on election day, ~2.5 six weeks out, ~4.5 a year out."""
    return 1.5 + 3.0 * math.sqrt(max(dte, 0) / 365.0)


def generic_ballot(con) -> dict:
    gb = rows(con, "SELECT * FROM generic_ballot ORDER BY as_of DESC")
    if not gb:
        return dict(margin=0.0, dem=None, rep=None, sources=[])
    latest = gb[0]["as_of"]
    cur = [g for g in gb if g["as_of"] == latest]
    avg = next((g for g in cur if g["source"].lower() == "average"), None)
    srcs = [g for g in cur if g["source"].lower() != "average"]
    if avg:
        m, d, r = avg["margin"], avg["dem"], avg["rep"]
    else:
        m = float(np.mean([g["margin"] for g in cur]))
        d = float(np.mean([g["dem"] for g in cur]))
        r = float(np.mean([g["rep"] for g in cur]))
    return dict(margin=m, dem=d, rep=r, as_of=latest, sources=srcs)


def _sides(cands: list[dict]):
    dem = next((c for c in cands if c["major"] and c["party"] == "D"), None) or \
          next((c for c in cands if c["major"] and c["party"] == "I"), None)
    rep = next((c for c in cands if c["major"] and c["party"] == "R"), None)
    if rep is None:
        rep = next((c for c in cands if c["major"] and c["party"] == "I" and c is not dem), None)
    return dem, rep


def race_forecast(race: dict, cands: list[dict], ratings: list[dict], polls: list[dict], generic: float, today: date) -> dict:
    dem, rep = _sides(cands)
    P = PARAMS[race["chamber"]]
    notes: list[str] = []
    res: dict = dict(race_id=race["race_id"], dem=dem, rep=rep, uncontested=False, notes=notes)

    # ---- uncontested / same-party general elections
    if dem is None and rep is None:
        notes.append("No general-election candidates parsed yet; fundamentals only.")
    elif dem is None or rep is None:
        winner = "D" if rep is None else "R"
        who = (dem or rep)["name"]
        notes.append(f"Only one side has a candidate ({who}); treated as a {winner} win.")
        res.update(uncontested=True, mu=100.0 if winner == "D" else -100.0, sigma_race=0.01, sigma_total=0.01,
                   p_dem=1.0 if winner == "D" else 0.0, prior_margin=None, prior_sd=None, poll=None,
                   fund=fundamentals(race, dem, rep, generic), rating=rating_summary(ratings, race["holder_party"]),
                   poll_weight=0.0, env_w=0.0)
        return res

    fund = fundamentals(race, dem, rep, generic)
    dem_side_party = dem["party"] if dem else "D"
    rating = rating_summary(ratings, race["holder_party"], dem_side_party, fund["margin"])
    if rating and not rating["implicit"]:
        prior = (1 - RATING_WEIGHT) * fund["margin"] + RATING_WEIGHT * rating["margin"]
        prior_sd = math.sqrt(((1 - RATING_WEIGHT) * fund["sd"]) ** 2 + (RATING_WEIGHT * RATING_SD) ** 2 + 2.0 ** 2)
    elif rating and rating["implicit"]:
        prior = (1 - RATING_WEIGHT) * fund["margin"] + RATING_WEIGHT * rating["margin"]
        prior_sd = fund["sd"]
        if rating.get("basis") == "fundamentals":
            notes.append("No expert rater lists this race; fundamentals point clearly one way (post-redistricting), so it is treated as safe for that party.")
        else:
            notes.append("No expert rater lists this race; treated as safe for the party holding the seat.")
    else:
        prior, prior_sd = fund["margin"], fund["sd"]
        notes.append("New or vacant seat with no expert ratings; fundamentals only.")

    poll = average(polls, today)
    if poll:
        w = (1 / poll["poll_sd"] ** 2) / (1 / poll["poll_sd"] ** 2 + 1 / prior_sd ** 2)
        mu = w * poll["margin"] + (1 - w) * prior
        var = 1 / (1 / poll["poll_sd"] ** 2 + 1 / prior_sd ** 2)
        if poll["hypothetical_only"]:
            notes.append("Only hypothetical-matchup polls are available; they get half weight and extra uncertainty.")
        if poll["newest_age"] > 45:
            notes.append(f"Newest usable poll is {poll['newest_age']} days old; polling uncertainty inflated.")
    else:
        w, mu, var = 0.0, prior, prior_sd ** 2
        notes.append("No usable general-election polls; forecast rests on fundamentals and expert ratings.")
    if race["incumbent_running"] and race["incumbent"]:
        notes.append(f"Incumbent {race['incumbent']} ({race['incumbent_party']}) is running.")
    elif race["incumbent"]:
        notes.append(f"Open seat: {race['incumbent']} ({race['incumbent_party']}) is not on the ballot.")
    if dem_side_party == "I":
        notes.append(f"{dem['name']} is an independent standing in for the Democratic side.")
    if rep and rep["party"] == "I":
        notes.append(f"{rep['name']} is an independent standing in for the Republican side.")

    sigma_race = math.sqrt(var + P["floor"] ** 2)
    res.update(mu=mu, sigma_race=sigma_race, prior_margin=prior, prior_sd=prior_sd, poll=poll, fund=fund, rating=rating,
               poll_weight=w, env_w=P["env_w"])
    return res


def demographic_z(results: list[dict], demo: dict) -> Optional[np.ndarray]:
    """(n_races, k) standardised demographic scores, or None when no Census data is loaded.

    House races use their district's values except in states that redrew maps for 2026 (ACS predates those
    lines), which fall back to the statewide values; Senate and governor races use statewide values."""
    if not demo:
        return None
    axes = ("pct_college", "pct_white_nh")
    raw = []
    for r in results:
        key = (r["state"], None)
        if r["chamber"] == "house" and r["state"] not in REDISTRICTED_2026 and (r["state"], r.get("district")) in demo:
            key = (r["state"], r.get("district"))
        rec = demo.get(key) or demo.get((r["state"], None)) or {}
        raw.append([rec.get(a) if rec.get(a) is not None else np.nan for a in axes])
    z = np.array(raw, dtype=float)
    mean = np.nanmean(z, axis=0)
    sd = np.nanstd(z, axis=0)
    sd[sd == 0] = 1.0
    z = (z - mean) / sd
    return np.nan_to_num(z, nan=0.0)


def simulate(results: list[dict], dte: int, n_sims: int = 20000, seed: Optional[int] = None, demo: Optional[dict] = None,
             nat_shift: float = 0.0, nat_sigma_mult: float = 1.0) -> np.ndarray:
    """Return a (n_sims, n_races) boolean matrix of D-side wins.

    nat_shift / nat_sigma_mult come from the national review: a shared shift of the environment (points) and a
    scale on the shared national error term."""
    rng = np.random.default_rng(seed)
    n = len(results)
    mu = np.array([r["mu"] for r in results])
    sig = np.array([r["sigma_race"] for r in results])
    env_w = np.array([r["env_w"] for r in results])
    states = sorted({r["state"] for r in results})
    regions = sorted(set(REGION_OF.values()))
    s_idx = np.array([states.index(r["state"]) for r in results])
    r_idx = np.array([regions.index(REGION_OF[r["state"]]) for r in results])
    fixed = np.array([r["uncontested"] for r in results])

    d_nat = nat_shift + rng.normal(0, national_sigma(dte) * nat_sigma_mult, size=(n_sims, 1))
    d_reg = rng.normal(0, SIGMA_REGION, size=(n_sims, len(regions)))[:, r_idx]
    d_state = rng.normal(0, SIGMA_STATE, size=(n_sims, len(states)))[:, s_idx]
    t = rng.standard_t(T_DF, size=(n_sims, n)) / math.sqrt(T_DF / (T_DF - 2))
    margins = mu + env_w * d_nat + d_reg + d_state + sig * t
    z = demographic_z(results, demo or {})
    if z is not None:
        d_demo = rng.normal(0, SIGMA_DEMO, size=(n_sims, z.shape[1]))
        margins = margins + d_demo @ z.T   # a miss along an axis moves demographically similar races together
    margins[:, fixed] = mu[fixed]
    return margins > 0


def apply_decisions(results: list[dict], decisions: dict[str, dict]) -> int:
    """Replace each race's centre and spread with the analyst decision, within guardrails. Returns count applied."""
    n = 0
    for r in results:
        d = decisions.get(r["race_id"])
        if not d or r.get("uncontested") or not isinstance(d.get("margin"), (int, float)):
            continue
        base = r["mu"]
        mu = min(base + AI_MAX_SHIFT, max(base - AI_MAX_SHIFT, float(d["margin"])))
        sd = min(12.0, max(2.5, float(d.get("sd") or r["sigma_race"])))
        r["quant_mu"], r["quant_sigma"] = base, r["sigma_race"]
        r["mu"], r["sigma_race"] = mu, sd
        r["ai"] = dict(margin=float(d["margin"]), applied_margin=mu, capped=abs(mu - float(d["margin"])) > 1e-9, sd=sd,
                       p_dem=d.get("p_dem"), label=d.get("label"), confidence=d.get("confidence"),
                       key_factors=d.get("key_factors") or [], rationale=d.get("rationale"), watch=d.get("watch"), overview=d.get("overview"))
        if r["ai"]["capped"]:
            r["notes"].append(f"Analyst margin of {d['margin']:+.1f} was limited to {mu:+.1f} (max {AI_MAX_SHIFT:g} points from the baseline).")
        n += 1
    return n


def run(con, today: Optional[date] = None, n_sims: int = 20000, seed: Optional[int] = None, verbose: bool = True, use_ai: bool = True) -> dict:
    started = now_iso()
    today = today or date.today()
    dte = days_to_election(today)
    gb = generic_ballot(con)
    races = rows(con, "SELECT * FROM races ORDER BY chamber, state, district, special")
    cands_by = _group(rows(con, "SELECT * FROM candidates"), "race_id")
    try:  # outside spending and demographics exist only when the keyed stages have run
        for o in rows(con, "SELECT * FROM outside_spending"):
            for c in cands_by.get(o["race_id"], []):
                if c["name"] == o["name"]:
                    c["ie_support"], c["ie_oppose"] = o["support"], o["oppose"]
    except Exception:  # noqa: BLE001
        pass
    try:
        demo = {(d["state"], d["district"]): d for d in rows(con, "SELECT * FROM demographics")}
    except Exception:  # noqa: BLE001
        demo = {}
    ratings_by = _group(rows(con, "SELECT * FROM ratings"), "race_id")
    polls_by = _group(rows(con, "SELECT * FROM polls"), "race_id")

    results = []
    for race in races:
        r = race_forecast(race, cands_by.get(race["race_id"], []), ratings_by.get(race["race_id"], []),
                          polls_by.get(race["race_id"], []), gb["margin"], today)
        r.update(chamber=race["chamber"], state=race["state"], district=race["district"], holder_party=race["holder_party"])
        results.append(r)

    ai_applied, national = 0, None
    if use_ai:
        from ..sources.ai import decisions as load_decisions

        per_race, national = load_decisions(con)
        ai_applied = apply_decisions(results, per_race)
    nat_shift = float((national or {}).get("environment_adjustment") or 0.0)
    nat_mult = float((national or {}).get("uncertainty_multiplier") or 1.0)
    wins = simulate(results, dte, n_sims=n_sims, seed=seed, demo=demo, nat_shift=nat_shift, nat_sigma_mult=nat_mult)
    sig_nat = national_sigma(dte)
    for i, r in enumerate(results):
        r["p_dem"] = float(wins[:, i].mean())
        r["sigma_total"] = math.sqrt(r["sigma_race"] ** 2 + (r["env_w"] * sig_nat * nat_mult) ** 2 + SIGMA_REGION ** 2 + SIGMA_STATE ** 2) if not r["uncontested"] else 0.01
        r["p_dem_analytic"] = float(norm.cdf((r["mu"] + r["env_w"] * nat_shift) / r["sigma_total"])) if not r["uncontested"] else r["p_dem"]
        r["label"] = prob_label(r["p_dem"])
        hp = r["holder_party"]
        r["flip_prob"] = (1 - r["p_dem"]) if hp == "D" else r["p_dem"] if hp == "R" else None

    chambers = {}
    for chamber, not_up, needed_frac in (("house", {"D": 0, "R": 0}, None), ("senate", SENATE_NOT_UP, None), ("governor", GOVERNORS_NOT_UP, None)):
        idx = [i for i, r in enumerate(results) if r["chamber"] == chamber]
        d_caucus = np.array([1 if not (results[i]["dem"] and results[i]["dem"]["party"] == "I" and results[i]["race_id"] in NON_CAUCUSING_INDEPENDENTS) else 0 for i in idx])
        w = wins[:, idx]
        d_seats = not_up["D"] + (w * d_caucus).sum(axis=1)
        r_seats = not_up["R"] + (~w).sum(axis=1)
        total = {"house": 435, "senate": 100, "governor": 50}[chamber]
        needed = {"house": 218, "senate": 51, "governor": 26}[chamber]
        if chamber == "senate":
            p_dem = float((d_seats >= 51).mean())
            p_rep = float((r_seats >= 50).mean())
        else:
            p_dem = float((d_seats >= needed).mean())
            p_rep = float((r_seats >= needed).mean())
        hist = np.bincount(d_seats.astype(int), minlength=total + 1) / n_sims
        holders = [results[i]["holder_party"] for i in idx]
        exp_flip_d = float(sum(results[i]["p_dem"] for i in idx if results[i]["holder_party"] == "R"))
        exp_flip_r = float(sum(1 - results[i]["p_dem"] for i in idx if results[i]["holder_party"] == "D"))
        chambers[chamber] = dict(
            total=total, seats_up=len(idx), needed=needed, not_up=not_up,
            p_dem=p_dem, p_rep=p_rep, p_neither=max(0.0, 1 - p_dem - p_rep),
            dem_seats=_pct(d_seats), rep_seats=_pct(r_seats),
            histogram=[dict(seats=int(s), p=float(p)) for s, p in enumerate(hist) if p > 0],
            expected_flips={"D": exp_flip_d, "R": exp_flip_r},
            current={"D": holders.count("D") + not_up["D"], "R": holders.count("R") + not_up["R"],
                     "other": sum(1 for h in holders if h not in ("D", "R"))},
        )
    out = dict(run_date=today.isoformat(), days_to_election=dte, generic=gb, national_sigma=sig_nat,
               races={r["race_id"]: r for r in results}, chambers=chambers, n_sims=n_sims, demographics=bool(demo),
               ai_applied=ai_applied, national=national)
    _persist(con, out)
    log_run(con, "model", started, True, json.dumps({k: round(v["p_dem"], 3) for k, v in chambers.items()}))
    if verbose:
        if use_ai:
            print(f"  decisions applied to {ai_applied} races; national shift {nat_shift:+.1f}, uncertainty x{nat_mult:.2f}")
        for k, v in chambers.items():
            print(f"  {k:9s} P(D control)={v['p_dem']:.3f}  D seats mean={v['dem_seats']['mean']:.1f} [{v['dem_seats']['p10']}-{v['dem_seats']['p90']}]  exp flips D={v['expected_flips']['D']:.1f} R={v['expected_flips']['R']:.1f}")
    return out


def _pct(a: np.ndarray) -> dict:
    return dict(mean=float(a.mean()), median=float(np.median(a)), p05=float(np.percentile(a, 5)), p10=float(np.percentile(a, 10)),
                p90=float(np.percentile(a, 90)), p95=float(np.percentile(a, 95)))


def _group(rs: list[dict], key: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in rs:
        out.setdefault(r[key], []).append(r)
    return out


def _persist(con, out: dict) -> None:
    run_date = out["run_date"]
    frows = []
    for rid, r in out["races"].items():
        detail = dict(
            prior_margin=r.get("prior_margin"), prior_sd=r.get("prior_sd"), poll_weight=r.get("poll_weight"),
            fund=r.get("fund"), rating=r.get("rating"), sigma_race=r.get("sigma_race"), sigma_total=r.get("sigma_total"),
            poll={k: v for k, v in (r.get("poll") or {}).items() if k != "weights"} if r.get("poll") else None,
            weights=(r.get("poll") or {}).get("weights"), notes=r.get("notes"), uncontested=r.get("uncontested"),
            p_dem_analytic=r.get("p_dem_analytic"), label=r.get("label"), flip_prob=r.get("flip_prob"),
            quant_mu=r.get("quant_mu"), quant_sigma=r.get("quant_sigma"), ai=r.get("ai"),
        )
        frows.append(dict(run_date=run_date, race_id=rid, p_dem=r["p_dem"], margin=r["mu"], sd=r["sigma_total"],
                          poll_margin=(r.get("poll") or {}).get("margin"), n_polls=(r.get("poll") or {}).get("n_polls"),
                          fund_margin=(r.get("fund") or {}).get("margin"), rating_margin=(r.get("rating") or {}).get("margin"),
                          detail=json.dumps(detail, default=float)))
    upsert(con, "forecasts", frows, keys=["run_date", "race_id"])
    crows = [dict(run_date=run_date, chamber=k, p_dem=v["p_dem"], dem_seats_mean=v["dem_seats"]["mean"],
                  dem_seats_p10=v["dem_seats"]["p10"], dem_seats_p90=v["dem_seats"]["p90"],
                  detail=json.dumps(dict(v, national=out.get("national"), ai_applied=out.get("ai_applied")), default=float))
             for k, v in out["chambers"].items()]
    upsert(con, "chamber_forecasts", crows, keys=["run_date", "chamber"])
    con.commit()
