"""The forecast engine: executes a model spec on the evidence and simulates the Electoral College.

For each of the 56 contests (50 states, DC, and the Maine and Nebraska congressional districts):

    margin = lean (2020/2024 record, updated by state polls)
           + national environment (national trial heats blended with approval and economic fundamentals)
           + D nominee strength - R nominee strength      (drawn per simulation from the nomination odds)
           + home-state effect for either nominee
           + state adjustment (from the spec)  + expert-rating pull (when ratings exist)
           + correlated error: national (fat-tailed) + regional + realignment axis + state (fat-tailed)

Margins are Democratic minus Republican, in points. All probabilities, electoral-vote totals, the popular vote,
tipping-point odds and per-matchup outcomes come from the same simulation, so they are mutually consistent.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date
from typing import Optional

import numpy as np

from ..config import EVS_TO_WIN, REGIONS, TOTAL_EVS, days_to_election
from ..db import log_run, now_iso, rows, upsert
from ..sources.economy import indicators
from ..util import prob_label
from . import evidence as ev
from .contests import contests, trend_loadings
from .spec import OTHER

DISTRICT_SD = 2.0
RATING_MARGIN = {0: 0.0, 1: 3.0, 2: 6.0, 3: 12.0, 4: 24.0}
TOP_SCENARIOS = 12


def _t(rng, df, size):
    """Unit-variance Student-t draws."""
    return rng.standard_t(df, size=size) / math.sqrt(df / (df - 2))


def gather(con, spec: dict, today: date) -> dict:
    """Everything the engine needs from the database, evaluated under `spec`."""
    dte = days_to_election(today)
    nat_polls = rows(con, "SELECT * FROM polls WHERE scope='national'")
    state_polls = rows(con, "SELECT * FROM polls WHERE scope='state'")
    nat = ev.national_poll_model(nat_polls, today, spec)
    appr = ev.approval(con)
    econ = indicators(con)
    fund = ev.fundamentals(appr, econ, spec)
    env = ev.environment(nat, fund, spec, dte)
    cs = contests(spec)
    leans = {c["contest_id"]: c["lean"] for c in cs}
    upd = ev.state_lean_updates(state_polls, leans, nat, env["environment"], today, spec)
    ratings: dict[str, list] = {}
    for r in rows(con, "SELECT * FROM ratings"):
        ratings.setdefault(r["contest_id"], []).append(r)
    return dict(today=today, dte=dte, nat=nat, approval=appr, economy=econ, fundamentals=fund, env=env, contests=cs,
                state_updates=upd, ratings=ratings, n_state_polls=len(state_polls), n_national_polls=len(nat_polls))


def rating_margin(rs: list[dict]) -> Optional[float]:
    vals = []
    for r in rs:
        sign = 1 if r["party"] == "D" else -1 if r["party"] == "R" else 0
        vals.append(sign * RATING_MARGIN.get(r["level"], 0.0))
    return sum(vals) / len(vals) if vals else None


def simulate(spec: dict, E: dict, n_sims: int = 20000, seed: Optional[int] = None) -> dict:
    rng = np.random.default_rng(seed)
    cs = E["contests"]
    n = len(cs)
    ids = [c["contest_id"] for c in cs]
    evs = np.array([c["evs"] for c in cs])
    st_codes = sorted({c["state"] for c in cs})
    st_idx = np.array([st_codes.index(c["state"]) for c in cs])
    regions = sorted(REGIONS)
    reg_idx = np.array([regions.index(c["region"]) for c in cs])
    is_district = np.array([c["district"] is not None for c in cs])
    statewide = ~is_district
    votes = np.array([c["votes24"] for c in cs], dtype=float) * statewide
    wv = votes / votes.sum()

    # ---- means
    upd = E["state_updates"]
    lean = np.array([upd[c["contest_id"]]["posterior_lean"] if c["contest_id"] in upd else c["lean"] for c in cs])
    adj = np.array([float((spec["state_adjustments"].get(c["contest_id"]) or {}).get("shift", 0.0)) for c in cs])
    env = E["env"]["environment"]
    bonus = float(spec["candidates"]["home_state_bonus"])
    noms = {p: spec["nominees"][p] for p in ("D", "R")}
    pD = np.array([c["p"] for c in noms["D"]]); pD = pD / pD.sum()
    pR = np.array([c["p"] for c in noms["R"]]); pR = pR / pR.sum()
    effD = np.array([c["effect"] for c in noms["D"]])
    effR = np.array([c["effect"] for c in noms["R"]])
    homeD = np.array([[bonus if c.get("home_state") == x["state"] else 0.0 for x in cs] for c in noms["D"]])
    homeR = np.array([[bonus if c.get("home_state") == x["state"] else 0.0 for x in cs] for c in noms["R"]])
    base = lean + adj
    mean_all = base + env + pD @ effD - pR @ effR + pD @ homeD - pR @ homeR
    rw = float(spec["ratings"]["weight"])
    rpull = np.zeros(n)
    for i, c in enumerate(cs):
        rm = rating_margin(E["ratings"].get(c["contest_id"], []))
        if rm is not None and rw > 0:
            rpull[i] = rw * (rm - mean_all[i])
    base = base + rpull

    # ---- errors (common random numbers, reused by every conditional run below)
    U = spec["uncertainty"]
    df = float(U["tail_df"])
    nat_sd = ev.national_sd_curve(E["dte"]) * float(U["national_mult"])
    state_sd = ev.state_sd_curve(E["dte"]) * float(U["state_mult"])
    load = trend_loadings(cs)
    err = (nat_sd * _t(rng, df, (n_sims, 1))
           + rng.normal(0, float(U["region_sd"]), (n_sims, len(regions)))[:, reg_idx]
           + rng.normal(0, float(U["trend_sd"]), (n_sims, 1)) * load
           + state_sd * _t(rng, df, (n_sims, len(st_codes)))[:, st_idx]
           + is_district * rng.normal(0, DISTRICT_SD, (n_sims, n)))
    # a significant independent / third-party candidate: on the ballot in some simulations, shifting the margin
    TP = spec.get("third_party") or {}
    tp_on = rng.random((n_sims, 1)) < float(TP.get("p_run", 0.0))
    tp_shift = tp_on * rng.normal(float(TP.get("net_effect", 0.0)), max(1e-9, float(TP.get("effect_sd", 0.0))), (n_sims, 1))
    err = err + tp_shift
    iD = rng.choice(len(pD), size=n_sims, p=pD)
    iR = rng.choice(len(pR), size=n_sims, p=pR)

    def run(dsel, rsel):
        """Margins (n_sims, n) with the D/R nominee indices per simulation (arrays) or fixed (ints)."""
        dshift = (effD[dsel] if np.ndim(dsel) == 0 else effD[dsel][:, None]) + homeD[dsel]
        rshift = (effR[rsel] if np.ndim(rsel) == 0 else effR[rsel][:, None]) + homeR[rsel]
        return base + env + dshift - rshift + err

    def outcome(m):
        wins = m > 0
        ev_d = wins.astype(int) @ evs
        pv = m @ wv
        return wins, ev_d, pv

    M = run(iD, iR)
    wins, ev_d, pv = outcome(M)
    p_dem, p_rep = float((ev_d >= EVS_TO_WIN).mean()), float((ev_d <= TOTAL_EVS - EVS_TO_WIN).mean())

    # tipping point: order each simulation's contests from the winner's best to worst, find the 270th elector
    dwin = ev_d >= EVS_TO_WIN
    rwin = ev_d <= TOTAL_EVS - EVS_TO_WIN
    order = np.argsort(np.where(dwin[:, None], -M, M), axis=1)
    cum = np.cumsum(evs[order], axis=1)
    tip_pos = (cum >= EVS_TO_WIN).argmax(axis=1)
    tip = order[np.arange(n_sims), tip_pos]
    decided = dwin | rwin
    tip_p = np.bincount(tip[decided], minlength=n) / max(1, decided.sum())

    per = []
    for i, c in enumerate(cs):
        col = M[:, i]
        p = float(wins[:, i].mean())
        per.append(dict(contest_id=c["contest_id"], p_dem=p, margin=float(col.mean()), sd=float(col.std()),
                        p10=float(np.percentile(col, 10)), p90=float(np.percentile(col, 90)), tip=float(tip_p[i]), label=prob_label(p),
                        lean=float(lean[i]), hist_lean=c["lean"], poll_shift=float(lean[i] - c["lean"]), adjustment=float(adj[i]),
                        rating_pull=float(rpull[i]), home_effect=float(pD @ homeD[:, i] - pR @ homeR[:, i]),
                        flip_vs_2024=(p if c["winner24"] == "R" else 1 - p)))

    # conditional outcomes for each possible nominee (the other party's nominee still drawn at random)
    cond = {"D": [], "R": []}
    for j, c in enumerate(noms["D"]):
        _, e, v = outcome(run(j, iR))
        cond["D"].append(dict(name=c["name"], p_nominee=float(pD[j]), p_win_if_nominee=float((e >= EVS_TO_WIN).mean()),
                              dem_ev=float(e.mean()), pv_margin=float(v.mean())))
    for j, c in enumerate(noms["R"]):
        _, e, v = outcome(run(iD, j))
        cond["R"].append(dict(name=c["name"], p_nominee=float(pR[j]), p_win_if_nominee=float((e <= TOTAL_EVS - EVS_TO_WIN).mean()),
                              dem_ev=float(e.mean()), pv_margin=float(v.mean())))

    # head-to-head matchups, most likely first
    pairs = sorted(((pD[a] * pR[b], a, b) for a in range(len(pD)) for b in range(len(pR))), reverse=True)
    named = [x for x in pairs if noms["D"][x[1]]["name"] != OTHER and noms["R"][x[2]]["name"] != OTHER][:TOP_SCENARIOS]
    scenarios = []
    for prob, a, b in named:
        w_, e, v = outcome(run(a, b))
        scenarios.append(dict(dem=noms["D"][a]["name"], rep=noms["R"][b]["name"], p=float(prob),
                              p_dem=float((e >= EVS_TO_WIN).mean()), p_rep=float((e <= TOTAL_EVS - EVS_TO_WIN).mean()),
                              dem_ev=float(e.mean()), pv_margin=float(v.mean()),
                              states={ids[i]: round(float(w_[:, i].mean()), 3) for i in range(n)}))

    hist = np.bincount(ev_d, minlength=TOTAL_EVS + 1) / n_sims
    return dict(
        contests=per,
        ec=dict(p_dem=p_dem, p_rep=p_rep, p_tie=max(0.0, 1 - p_dem - p_rep), dem_ev=_pct(ev_d), rep_ev=_pct(TOTAL_EVS - ev_d),
                histogram=[dict(ev=int(k), p=float(v)) for k, v in enumerate(hist) if v > 0]),
        popular=dict(margin=float(pv.mean()), sd=float(pv.std()), p_dem=float((pv > 0).mean()),
                     p10=float(np.percentile(pv, 10)), p90=float(np.percentile(pv, 90))),
        splits=dict(dem_ec_rep_pv=float((dwin & (pv < 0)).mean()), rep_ec_dem_pv=float((rwin & (pv > 0)).mean())),
        conditional=cond, scenarios=scenarios,
        uncertainty=dict(national_sd=nat_sd, state_sd=state_sd, region_sd=float(U["region_sd"]), trend_sd=float(U["trend_sd"]),
                         tail_df=df, district_sd=DISTRICT_SD, third_party_p=float(TP.get("p_run", 0.0)),
                         third_party_effect=float(TP.get("net_effect", 0.0))),
        n_sims=n_sims,
    )


def _pct(a: np.ndarray) -> dict:
    return dict(mean=float(a.mean()), median=float(np.median(a)), p05=float(np.percentile(a, 5)), p10=float(np.percentile(a, 10)),
                p25=float(np.percentile(a, 25)), p75=float(np.percentile(a, 75)), p90=float(np.percentile(a, 90)),
                p95=float(np.percentile(a, 95)))


def input_seed(spec: dict, E: dict) -> int:
    """Seed derived from everything the run depends on: identical inputs give identical numbers, so frequent
    updates move only when the evidence or the model does (not with Monte Carlo noise)."""
    from .spec import fingerprint

    ev_sum = _evidence_summary(E)
    payload = dict(spec=fingerprint(spec), nominees=spec.get("nominees"), adj=spec.get("state_adjustments"),
                   env=ev_sum["environment"], polls=sorted((ev_sum.get("national_polls") or {}).get("weights", {}).items()),
                   states={k: v.get("posterior_lean") for k, v in ev_sum["state_updates"].items()}, ratings=ev_sum["ratings"],
                   dte=E["dte"])
    return int(hashlib.sha1(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:12], 16)


def run(con, spec: dict, spec_version: Optional[int] = None, today: Optional[date] = None, n_sims: int = 50000,
        seed: Optional[int] = None, persist: bool = True, verbose: bool = True) -> dict:
    started = now_iso()
    today = today or date.today()
    E = gather(con, spec, today)
    S = simulate(spec, E, n_sims=n_sims, seed=seed if seed is not None else input_seed(spec, E))
    out = dict(run_date=today.isoformat(), days_to_election=E["dte"], spec_version=spec_version, evidence=_evidence_summary(E), **S)
    if persist:
        _persist(con, out)
        log_run(con, "model", started, True, json.dumps(dict(version=spec_version, p_dem=round(S["ec"]["p_dem"], 3),
                                                              dem_ev=round(S["ec"]["dem_ev"]["mean"], 1))))
    if verbose:
        ec = S["ec"]
        print(f"  spec v{spec_version}: P(D)={ec['p_dem']:.3f} P(R)={ec['p_rep']:.3f} tie={ec['p_tie']:.3f}  "
              f"D EVs {ec['dem_ev']['mean']:.0f} [{ec['dem_ev']['p10']:.0f}-{ec['dem_ev']['p90']:.0f}]  "
              f"PV {S['popular']['margin']:+.1f}  env {E['env']['environment']:+.1f}")
    return out


def _evidence_summary(E: dict) -> dict:
    nat = E["nat"]
    return dict(
        national_polls=None if not nat else dict(g=round(nat["g"], 2), g_sd=round(nat["g_sd"], 2), n_polls=nat["n_polls"], n_eff=nat["n_eff"],
                                                 last_poll=nat["last_poll"], simple_average=nat["simple_average"], strengths=nat["strengths"],
                                                 house_effects=nat.get("house_effects", {}), residuals=nat.get("residuals", {}),
                                                 weights=nat["weights"]),
        approval=E["approval"], economy=E["economy"], fundamentals=E["fundamentals"], environment=E["env"],
        state_updates=E["state_updates"], n_state_polls=E["n_state_polls"], n_national_polls=E["n_national_polls"],
        ratings={k: [dict(rater=r["rater"], rating=r["rating"]) for r in v] for k, v in E["ratings"].items()},
    )


def _persist(con, out: dict) -> None:
    rd = out["run_date"]
    upsert(con, "forecasts", [dict(run_date=rd, contest_id=c["contest_id"], p_dem=c["p_dem"], margin=c["margin"], sd=c["sd"],
                                   detail=json.dumps(c)) for c in out["contests"]], keys=["run_date", "contest_id"])
    upsert(con, "national_forecasts", [dict(run_date=rd, spec_version=out["spec_version"], p_dem=out["ec"]["p_dem"],
                                            dem_ev_mean=out["ec"]["dem_ev"]["mean"], pv_margin=out["popular"]["margin"],
                                            detail=json.dumps({k: v for k, v in out.items() if k != "contests"}, default=float))],
           keys=["run_date"])
    con.execute("INSERT OR REPLACE INTO run_log (ts, run_date, spec_version, p_dem, p_rep, dem_ev, pv, env) VALUES (?,?,?,?,?,?,?,?)",
                (now_iso(), rd, out["spec_version"], out["ec"]["p_dem"], out["ec"]["p_rep"], out["ec"]["dem_ev"]["mean"],
                 out["popular"]["margin"], out["evidence"]["environment"]["environment"]))
    con.commit()
