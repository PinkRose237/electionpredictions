"""Turn the raw evidence in the database into model inputs.

- national_poll_model: a weighted ridge regression over every national trial heat,
      margin = g + strength(D candidate) - strength(R candidate) + error,
  giving the polling environment for an average-strength matchup (g) and each candidate's polling strength.
- state_lean_updates: state polls, read relative to the national polls for the same matchup, update a state's
  lean (so a Newsom-vs-Vance poll of Nevada informs Nevada's lean, whoever the nominees turn out to be).
- primary_average / implied_nominee_odds: the nomination contests.
- fundamentals: presidential approval and the economy -> the national environment they imply.
All margins are Democratic minus Republican, in points.
"""
from __future__ import annotations

import json
import math
from datetime import date
from typing import Optional

import numpy as np

from ..config import INCUMBENT_PARTY, days_to_election
from ..db import rows

POP_WEIGHT = {"LV": 1.0, "RV": 0.9, "V": 0.85, "A": 0.7}
SPONSOR_SHIFT = 1.5
SPONSOR_WEIGHT = 0.6
NAT_POLL_SD = 5.0       # error of one full-weight national trial heat this far out (sampling + house + timing)
STATE_POLL_SD = 5.5     # same for a state poll's reading of the state's relative lean
LEAN_PRIOR_SD = 3.0     # how far a state's true lean may sit from its 2020/2024 record
MAX_AGE = 540

POLLSTER_TIER = {
    1.15: ["new york times", "siena", "marist", "quinnipiac", "fox news", "cnn", "ssrs", "abc news", "washington post", "marquette",
           "selzer", "monmouth", "suffolk", "surveyusa", "emerson", "yougov", "ipsos", "atlasintel", "wall street journal", "nbc news",
           "cbs news", "ap-norc", "pew", "gallup", "beacon research", "shaw & co", "hart research", "public opinion strategies",
           "data for progress", "echelon insights", "morning consult", "harrisx", "impact research", "fabrizio", "cygnal",
           "public policy polling", "university", "college", "umass", "tarrance"],
    0.75: ["rasmussen", "trafalgar", "insideradvantage", "quantus", "big data poll", "patriot polling", "co/efficient", "rmg research",
           "tipp", "tpsi", "victory insights", "spry strategies", "j.l. partners", "redfield", "wilton", "overton insights",
           "napolitan", "zogby", "leger", "atlas", "noble predictive", "bullfinch", "american pulse"],
}


def pollster_weight(name: str) -> float:
    n = (name or "").lower()
    for w, keys in POLLSTER_TIER.items():
        if any(k in n for k in keys):
            return w
    return 1.0


def poll_weight(p: dict, today: date, half_life: float, third_party_weight: float = 0.5) -> tuple[float, float]:
    """(weight, sponsor-corrected margin) for one trial heat."""
    end = date.fromisoformat(p["end_date"])
    age = max(0, (today - end).days)
    if age > MAX_AGE:
        return 0.0, 0.0
    recency = 0.5 ** (age / half_life)
    n = p.get("sample_size") or 600
    size = math.sqrt(min(n, 2500) / 800.0)
    sponsor = SPONSOR_WEIGHT if p.get("sponsor_lean") in ("D", "R") else 1.0
    pop = POP_WEIGHT.get(p.get("population") or "RV", 0.9)
    third = third_party_weight if (p.get("other_pct") or 0) > 0 else 1.0
    m = p["dem_pct"] - p["rep_pct"]
    if p.get("sponsor_lean") == "D":
        m -= SPONSOR_SHIFT
    elif p.get("sponsor_lean") == "R":
        m += SPONSOR_SHIFT
    return recency * size * sponsor * pop * third * pollster_weight(p.get("pollster")), m


def national_poll_model(polls: list[dict], today: date, spec: dict) -> Optional[dict]:
    """Weighted ridge regression over every national trial heat:
        margin = g + strength(D) - strength(R) + house(pollster) + error
    g is the environment for an average-strength matchup; house effects (pollsters with 2+ polls) absorb each
    firm's systematic lean, so a prolific firm cannot tilt the average or a candidate's strength."""
    hl = float(spec["polls"]["half_life_days"])
    tpw = float(spec["polls"]["third_party_weight"])
    tau = float(spec["polls"]["candidate_prior_sd"])
    hsd = float(spec["polls"].get("house_effect_sd", 0.0))
    obs = []
    for p in polls:
        if p.get("dem_pct") is None or p.get("rep_pct") is None or not p.get("end_date"):
            continue
        w, m = poll_weight(p, today, hl, tpw)
        if w > 1e-4:
            obs.append((p, w, m))
    if not obs:
        return None
    dnames = sorted({p["dem_name"] for p, _, _ in obs})
    rnames = sorted({p["rep_name"] for p, _, _ in obs})
    n_by_firm: dict[str, int] = {}
    for p, _, _ in obs:
        n_by_firm[p["pollster"]] = n_by_firm.get(p["pollster"], 0) + 1
    firms = sorted(f for f, n in n_by_firm.items() if n >= 2) if hsd > 0 else []
    nd, nr = len(dnames), len(rnames)
    k = 1 + nd + nr + len(firms)
    X = np.zeros((len(obs), k))
    y = np.array([m for _, _, m in obs])
    w = np.array([w for _, w, _ in obs])
    for i, (p, _, _) in enumerate(obs):
        X[i, 0] = 1.0
        X[i, 1 + dnames.index(p["dem_name"])] = 1.0
        X[i, 1 + nd + rnames.index(p["rep_name"])] = -1.0
        if p["pollster"] in firms:
            X[i, 1 + nd + nr + firms.index(p["pollster"])] = 1.0
    prior_prec = np.array([1 / 10.0 ** 2] + [1 / tau ** 2] * (nd + nr) + [1 / max(hsd, 1e-3) ** 2] * len(firms))
    A = (X.T * w) @ X / NAT_POLL_SD ** 2 + np.diag(prior_prec)
    b = (X.T * w) @ y / NAT_POLL_SD ** 2
    cov = np.linalg.inv(A)
    beta = cov @ b
    sd = np.sqrt(np.diag(cov))
    n_by = {}
    for p, _, _ in obs:
        n_by[("D", p["dem_name"])] = n_by.get(("D", p["dem_name"]), 0) + 1
        n_by[("R", p["rep_name"])] = n_by.get(("R", p["rep_name"]), 0) + 1
    strengths = {}
    for j, nm in enumerate(dnames):
        strengths[nm] = dict(party="D", strength=round(float(beta[1 + j]), 2), sd=round(float(sd[1 + j]), 2), n_polls=n_by[("D", nm)])
    for j, nm in enumerate(rnames):
        strengths[nm] = dict(party="R", strength=round(float(beta[1 + nd + j]), 2), sd=round(float(sd[1 + nd + j]), 2), n_polls=n_by[("R", nm)])
    house = {f: dict(effect=round(float(beta[1 + nd + nr + j]), 2), sd=round(float(sd[1 + nd + nr + j]), 2), n_polls=n_by_firm[f])
             for j, f in enumerate(firms)}
    W = float(w.sum())
    fitted = X @ beta
    return dict(g=float(beta[0]), g_sd=max(1.0, float(sd[0])), strengths=strengths, house_effects=house, n_polls=len(obs),
                n_eff=round(W ** 2 / float((w ** 2).sum()), 2), weight_sum=round(W, 3),
                last_poll=max(p["end_date"] for p, _, _ in obs), weights={p["poll_id"]: round(float(x), 4) for (p, _, _), x in zip(obs, w)},
                residuals={p["poll_id"]: round(float(yy - ff), 2) for (p, _, _), yy, ff in zip(obs, y, fitted)},
                simple_average=round(float((w * y).sum() / W), 2))


def matchup_level(nat: Optional[dict], dem: str, rep: str) -> float:
    """What national polls imply for a specific matchup (environment + both candidates' strengths)."""
    if not nat:
        return 0.0
    s = nat["strengths"]
    return nat["g"] + (s.get(dem) or {}).get("strength", 0.0) - (s.get(rep) or {}).get("strength", 0.0)


def state_lean_updates(state_polls: list[dict], leans: dict[str, float], nat: Optional[dict], env: float, today: date,
                       spec: dict) -> dict[str, dict]:
    """Posterior lean per polled contest: prior = historical lean, data = state polls minus the national level."""
    hl = float(spec["polls"]["half_life_days"])
    tpw = float(spec["polls"]["third_party_weight"])
    sw = float(spec["polls"]["state_weight"])
    by: dict[str, list] = {}
    for p in state_polls:
        cid = p.get("contest_id")
        if cid not in leans or p.get("dem_pct") is None or p.get("rep_pct") is None:
            continue
        w, m = poll_weight(p, today, hl, tpw)
        if w <= 1e-4:
            continue
        level = matchup_level(nat, p["dem_name"], p["rep_name"]) if nat else env
        house = ((nat or {}).get("house_effects", {}).get(p.get("pollster")) or {}).get("effect", 0.0)
        by.setdefault(cid, []).append((p, w * sw, m - house - level, m))
    out = {}
    for cid, obs in by.items():
        prior = leans[cid]
        prec_prior = 1 / LEAN_PRIOR_SD ** 2
        prec_data = sum(w for _, w, _, _ in obs) / STATE_POLL_SD ** 2
        rel = sum(w * r for _, w, r, _ in obs) / sum(w for _, w, _, _ in obs)
        post = (prior * prec_prior + rel * prec_data) / (prec_prior + prec_data)
        out[cid] = dict(prior_lean=round(prior, 2), poll_relative=round(rel, 2), posterior_lean=round(post, 2),
                        shift=round(post - prior, 2), poll_weight=round(prec_data / (prec_prior + prec_data), 3), n_polls=len(obs),
                        last_poll=max(p["end_date"] for p, _, _, _ in obs),
                        weights={p["poll_id"]: round(w, 4) for p, w, _, _ in obs},
                        raw_average=round(sum(w * m for _, w, _, m in obs) / sum(w for _, w, _, _ in obs), 2))
    return out


def primary_average(con, party: str, today: date, half_life: float = 30.0, max_age: int = 150) -> dict:
    """Recency-weighted average of national primary polls; falls back to the aggregators' average."""
    acc: dict[str, float] = {}
    wsum = 0.0
    n = 0
    for p in rows(con, "SELECT * FROM primary_polls WHERE party=?", (party,)):
        age = (today - date.fromisoformat(p["end_date"])).days
        if age < 0 or age > max_age:
            continue
        w = 0.5 ** (age / half_life) * math.sqrt(min(p["sample_size"] or 500, 2000) / 500) * pollster_weight(p["pollster"])
        shares = json.loads(p["shares"])
        for k, v in shares.items():
            acc[k] = acc.get(k, 0.0) + w * v
        wsum += w
        n += 1
    aggs = rows(con, "SELECT * FROM primary_averages WHERE party=? ORDER BY (source='Average') DESC, as_of DESC", (party,))
    if wsum > 0:
        avg = {k: round(v / wsum, 2) for k, v in acc.items()}
        src = "polls"
    elif aggs:
        avg, src = json.loads(aggs[0]["shares"]), "aggregate"
    else:
        return dict(shares={}, n_polls=0, source=None)
    return dict(shares=dict(sorted(avg.items(), key=lambda kv: -kv[1])), n_polls=n, source=src,
                aggregates=[dict(source=a["source"], as_of=a["as_of"], shares=json.loads(a["shares"])) for a in aggs])


def implied_nominee_odds(shares: dict[str, float], dte: int, extra_names: list[str] = (), k: float = 1.3) -> dict[str, float]:
    """Rough nomination odds from primary polling: leaders are favoured, but far from the primaries much of the
    probability belongs to the field (people not yet polled, or not yet running)."""
    raw = {n: max(s, 0.5) ** k for n, s in shares.items() if s and s >= 1.0}
    for n in extra_names:
        raw.setdefault(n, 0.5 ** k)
    tot = sum(raw.values())
    other = 0.03 + 0.25 * min(1.0, dte / 600.0)
    if not tot:
        return {"Other": 1.0}
    out = {n: (1 - other) * v / tot for n, v in raw.items()}
    out["Other"] = other
    return out


def approval(con) -> Optional[dict]:
    rs = rows(con, "SELECT * FROM approval ORDER BY as_of DESC")
    if not rs:
        return None
    latest = rs[0]["as_of"]
    cur = [r for r in rs if r["as_of"] == latest]
    avg = next((r for r in cur if r["source"].lower() == "average"), None)
    if avg:
        return dict(net=avg["net"], approve=avg["approve"], disapprove=avg["disapprove"], as_of=latest, sources=len(cur) - 1)
    return dict(net=round(sum(r["net"] for r in cur) / len(cur), 2), approve=round(sum(r["approve"] for r in cur) / len(cur), 1),
                disapprove=round(sum(r["disapprove"] for r in cur) / len(cur), 1), as_of=latest, sources=len(cur))


def econ_index(ind: dict) -> Optional[float]:
    """Points of White House-party margin implied by the economy (0 = an ordinary economy)."""
    if not ind:
        return None
    parts = []
    if ind.get("inflation") is not None:
        parts.append(-0.6 * (ind["inflation"] - 2.5))
    if ind.get("unemployment_change") is not None:
        parts.append(-1.0 * ind["unemployment_change"])
    if ind.get("real_wage_growth") is not None:
        parts.append(0.5 * (ind["real_wage_growth"] - 0.8))
    if not parts:
        return None
    return max(-5.0, min(5.0, sum(parts)))


def fundamentals(appr: Optional[dict], econ: dict, spec: dict) -> dict:
    f = spec["fundamentals"]
    net = appr["net"] if appr else -10.0
    ei = econ_index(econ)
    inc_margin = f["intercept"] + f["approval_coef"] * net + f["econ_coef"] * (ei or 0.0)
    dem_env = -inc_margin if INCUMBENT_PARTY == "R" else inc_margin
    return dict(net_approval=net, approval_known=bool(appr), econ_index=None if ei is None else round(ei, 2),
                incumbent_party_margin=round(inc_margin, 2), dem_environment=round(dem_env, 2))


def poll_trust_curve(dte: int) -> float:
    """Default weight of national trial heats vs fundamentals: ~0.25 two years out, ~0.55 a year out, 0.85 at the end."""
    return 0.85 - 0.6 * min(1.0, dte / 730.0)


def national_sd_curve(dte: int) -> float:
    return 2.0 + 3.0 * math.sqrt(max(dte, 0) / 365.0)


def state_sd_curve(dte: int) -> float:
    return 2.5 + 1.0 * math.sqrt(max(dte, 0) / 365.0)


def environment(nat: Optional[dict], fund: dict, spec: dict, dte: int) -> dict:
    if nat:
        w = poll_trust_curve(dte) * float(spec["national"]["poll_trust"]) * min(1.0, nat["n_eff"] / 3.0)
        w = max(0.0, min(0.9, w))
        g = nat["g"]
    else:
        w, g = 0.0, 0.0
    adj = float(spec["national"]["adjustment"])
    env = w * g + (1 - w) * fund["dem_environment"] + adj
    return dict(polls=round(g, 2) if nat else None, fundamentals=fund["dem_environment"], poll_weight=round(w, 3),
                adjustment=adj, environment=round(env, 2))


def today_dte(today: Optional[date] = None) -> tuple[date, int]:
    today = today or date.today()
    return today, days_to_election(today)
