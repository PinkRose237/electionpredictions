"""Write the static JSON the website reads (schema: docs/DATA_CONTRACT.md).

site/data/
  summary.json        headline numbers, environment, nominees, matchups, tipping points, overview, history
  states.json         one row per contest (50 states, DC, ME-1/ME-2, NE-1/NE-2/NE-3)
  states/<id>.json    a contest's page: breakdown, results history, polls, ratings, coverage, trend
  scenarios.json      the most likely nominee matchups with every contest's odds under each (map picker)
  field.json          both nomination contests: candidates, primary polling, odds, strength, fundraising
  polls.json          national and state trial heats, approval, economy
  model.json          the current model specification and every revision with its changelog
  meta.json           pipeline stage log
"""
from __future__ import annotations

import json
from pathlib import Path

from .config import ELECTION_DATE, SITE_DATA_DIR, STATES, contest_name, days_to_election
from .db import now_iso, rows
from .model import store
from .model.contests import contests as contest_list
from .model.evidence import national_sd_curve, poll_trust_curve, state_sd_curve
from .model.spec import BOUNDS, DESCRIPTIONS, OTHER, get
from .narrative import load as load_narratives
from .revision import current_storylines
from .sources import midterm2026

VERSION = "2.0.0"


def _r(v, nd=2):
    return None if v is None else round(float(v), nd)


def lean_label(v) -> str:
    if v is None:
        return ""
    if abs(v) < 0.5:
        return "EVEN"
    return f"{'D' if v > 0 else 'R'}+{abs(v):.1f}"


def _merge_history(new: list[dict], path: Path) -> list[dict]:
    old: list[dict] = []
    if path.exists():
        try:
            old = json.loads(path.read_text()).get("history") or []
        except (json.JSONDecodeError, AttributeError):
            old = []
    merged = {h["date"]: h for h in old}
    merged.update({h["date"]: h for h in new})
    return [merged[d] for d in sorted(merged)]


def _write(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))


def _news(con, topic: str, n: int) -> list[dict]:
    return [dict(title=r["title"], source=r["source"], published=r["published"], url=r["url"])
            for r in rows(con, "SELECT * FROM news WHERE topic=? ORDER BY published DESC LIMIT ?", (topic, n))]


def _poll_out(p: dict, weight=None) -> dict:
    return dict(id=p["poll_id"], pollster=p["pollster"], sponsor=p["sponsor_lean"], start=p["start_date"], end=p["end_date"],
                n=p["sample_size"], pop=p["population"], dem=p["dem_name"], rep=p["rep_name"], dem_pct=p["dem_pct"], rep_pct=p["rep_pct"],
                other_pct=p["other_pct"], und_pct=p["und_pct"], margin=_r(p["dem_pct"] - p["rep_pct"], 1), contest=p["contest_id"],
                matchup=json.loads(p["matchup"] or "[]"), weight=_r(weight, 4) if weight is not None else None)


def markets_summary(con) -> dict:
    out: dict = {}
    for r in rows(con, "SELECT * FROM markets ORDER BY p DESC"):
        out.setdefault(r["kind"], []).append(dict(platform=r["platform"], outcome=r["outcome"], p=_r(r["p"], 4), volume=_r(r["volume"], 0), url=r["url"]))
    party = out.get("party") or []
    d = [m["p"] for m in party if m["outcome"] == "D"]
    r_ = [m["p"] for m in party if m["outcome"] == "R"]
    if d and r_:
        out["party_dem"] = _r(sum(d) / len(d) / (sum(d) / len(d) + sum(r_) / len(r_)), 4)
    for k in ("nominee_D", "nominee_R", "winner"):
        if k in out:
            out[k] = out[k][:24]
    return out


def export(con, out_dir: Path = SITE_DATA_DIR, verbose: bool = True) -> dict:
    out_dir = Path(out_dir)
    (out_dir / "states").mkdir(parents=True, exist_ok=True)
    nf = rows(con, "SELECT * FROM national_forecasts ORDER BY run_date DESC LIMIT 1")
    if not nf:
        raise SystemExit("No forecast in the database yet; run `electionpredictions model` first.")
    nf = nf[0]
    run_date = nf["run_date"]
    N = json.loads(nf["detail"])
    E = N["evidence"]
    fc = {r["contest_id"]: json.loads(r["detail"]) for r in rows(con, "SELECT * FROM forecasts WHERE run_date=?", (run_date,))}
    version, spec, origin = store.latest(con)
    versions = store.history(con)
    vrow = next((v for v in versions if v["version"] == N.get("spec_version")), versions[0] if versions else None)
    narr = load_narratives(con)
    mk = markets_summary(con)
    cs = {c["contest_id"]: c for c in contest_list(spec)}
    hist_by: dict[str, list] = {}
    for h in rows(con, "SELECT run_date, contest_id, p_dem, margin FROM forecasts ORDER BY run_date"):
        hist_by.setdefault(h["contest_id"], []).append(dict(date=h["run_date"], p_dem=_r(h["p_dem"], 4), margin=_r(h["margin"], 2)))
    state_polls: dict[str, list] = {}
    for p in rows(con, "SELECT * FROM polls WHERE scope='state' ORDER BY end_date DESC"):
        state_polls.setdefault(p["contest_id"], []).append(p)
    ratings: dict[str, list] = {}
    for r in rows(con, "SELECT * FROM ratings ORDER BY rater"):
        ratings.setdefault(r["contest_id"], []).append(dict(rater=r["rater"], rating=r["rating"], as_of=r["as_of"]))
    upd = E.get("state_updates") or {}
    mid = midterm2026.summary()
    mid_states = (mid or {}).get("statewide", {})
    scen_states = {f"{s['dem']}|{s['rep']}": s.get("states") or {} for s in N.get("scenarios", [])}

    # ---- contests
    table = []
    for cid, c in cs.items():
        f = fc.get(cid)
        if not f:
            continue
        sp = state_polls.get(cid, [])
        adj = spec["state_adjustments"].get(cid)
        row = dict(
            id=cid, state=c["state"], district=c["district"], name=c["name"], state_name=STATES[c["state"]], evs=c["evs"],
            lean=_r(f["lean"], 1), lean_label=lean_label(f["lean"]), hist_lean=_r(c["lean"], 1),
            p_dem=_r(f["p_dem"], 4), margin=_r(f["margin"], 2), sd=_r(f["sd"], 2), p10=_r(f["p10"], 1), p90=_r(f["p90"], 1),
            label=f["label"], tip=_r(f["tip"], 4), margin20=c["margin20"], margin24=c["margin24"], winner20=c["winner20"], winner24=c["winner24"],
            flip=_r(f["flip_vs_2024"], 4), n_polls=len(sp), adjustment=_r(adj["shift"], 1) if adj else None,
            rating=_rating_consensus(ratings.get(cid, [])),
        )
        table.append(row)
        detail = dict(
            row,
            breakdown=dict(historical_lean=_r(c["lean"], 2), rel20=c["rel20"], rel24=c["rel24"], poll_shift=_r(f["poll_shift"], 2),
                           environment=_r(E["environment"]["environment"], 2), nominee_effects=_r(f["margin"] - f["lean"] - f["adjustment"] - f["rating_pull"] - f["home_effect"] - E["environment"]["environment"], 2),
                           adjustment=_r(f["adjustment"], 2), adjustment_reason=(adj or {}).get("reason") or None, rating_pull=_r(f["rating_pull"], 2),
                           home_effect=_r(f["home_effect"], 2)),
            poll_update=upd.get(cid),
            polls=[_poll_out(p, (upd.get(cid) or {}).get("weights", {}).get(p["poll_id"])) for p in sp],
            ratings=ratings.get(cid, []),
            matchups=[dict(dem=s["dem"], rep=s["rep"], p=_r(s["p"], 4), p_dem=_r((scen_states.get(f"{s['dem']}|{s['rep']}") or {}).get(cid), 3))
                      for s in N.get("scenarios", [])],
            news=_news(con, cid, 12),
            midterm_2026=(mid_states.get(c["state"]) if not c["district"] else None),
            overview=narr.get(cid),
            history=_merge_history(hist_by.get(cid, []), out_dir / "states" / f"{cid}.json"),
        )
        _write(out_dir / "states" / f"{cid}.json", detail)
    _write(out_dir / "states.json", table)

    # ---- nominees (spec + conditional outcomes)
    cond = {p: {x["name"]: x for x in N["conditional"][p]} for p in ("D", "R")}
    nominees = {p: [dict(name=c["name"], p=_r(c["p"], 4), effect=_r(c["effect"], 2), home_state=c.get("home_state"),
                         p_win_if_nominee=_r((cond[p].get(c["name"]) or {}).get("p_win_if_nominee"), 4),
                         dem_ev=_r((cond[p].get(c["name"]) or {}).get("dem_ev"), 1), pv_margin=_r((cond[p].get(c["name"]) or {}).get("pv_margin"), 2))
                    for c in spec["nominees"][p]] for p in ("D", "R")}

    # ---- summary
    nh = rows(con, "SELECT * FROM national_forecasts ORDER BY run_date")
    history = []
    for h in nh:
        d = json.loads(h["detail"])
        history.append(dict(date=h["run_date"], version=h["spec_version"], p_dem=_r(d["ec"]["p_dem"], 4), p_rep=_r(d["ec"]["p_rep"], 4),
                            dem_ev=_r(d["ec"]["dem_ev"]["mean"], 1), dem_ev_p10=d["ec"]["dem_ev"]["p10"], dem_ev_p90=d["ec"]["dem_ev"]["p90"],
                            pv=_r(d["popular"]["margin"], 2), env=_r(d["evidence"]["environment"]["environment"], 2)))
    history = _merge_history(history, out_dir / "summary.json")
    tips = sorted(table, key=lambda r: -(r["tip"] or 0))[:10]
    closest = [r["id"] for r in sorted(table, key=lambda r: abs(r["p_dem"] - 0.5))[:10]]
    nat_polls = E.get("national_polls") or {}
    counts = dict(
        national_polls=rows(con, "SELECT count(*) n FROM polls WHERE scope='national'")[0]["n"],
        state_polls=rows(con, "SELECT count(*) n FROM polls WHERE scope='state'")[0]["n"],
        primary_polls=rows(con, "SELECT count(*) n FROM primary_polls")[0]["n"],
        ratings=rows(con, "SELECT count(*) n FROM ratings")[0]["n"], markets=rows(con, "SELECT count(*) n FROM markets")[0]["n"],
        news=rows(con, "SELECT count(*) n FROM news")[0]["n"], candidates=rows(con, "SELECT count(*) n FROM candidates")[0]["n"],
        model_versions=len(versions),
    )
    summary = dict(
        generated_at=now_iso(), election_date=ELECTION_DATE.isoformat(), days_to_election=days_to_election(), run_date=run_date,
        model=dict(version=N.get("spec_version"), latest_version=version, origin=(vrow or {}).get("origin"), updated=(vrow or {}).get("created_at"),
                   title=(vrow or {}).get("title"), summary=(vrow or {}).get("summary"), n_changes=len((vrow or {}).get("changes") or []),
                   n_sims=N.get("n_sims")),
        ec=_round_tree(N["ec"]), popular=_round_tree(N["popular"]), splits=_round_tree(N["splits"]),
        environment=dict(_round_tree(E["environment"]), approval=E.get("approval"), economy=E.get("economy"),
                         econ_index=E["fundamentals"].get("econ_index"), incumbent_party_margin=E["fundamentals"].get("incumbent_party_margin"),
                         national_polls=dict(n=nat_polls.get("n_polls"), n_eff=nat_polls.get("n_eff"), average=nat_polls.get("simple_average"),
                                             last=nat_polls.get("last_poll"), g_sd=nat_polls.get("g_sd")) if nat_polls else None),
        uncertainty=_round_tree(N["uncertainty"]), nominees=nominees,
        scenarios=[{k: (_r(v, 4) if isinstance(v, float) else v) for k, v in s.items() if k != "states"} for s in N.get("scenarios", [])],
        tipping=[dict(id=r["id"], name=r["name"], p=r["tip"], p_dem=r["p_dem"], evs=r["evs"]) for r in tips],
        closest=closest, overview=narr.get("NATIONAL"), markets=mk, history=history, counts=counts,
        storylines=current_storylines(con),
        revisions=[dict(version=v["version"], created_at=v["created_at"], origin=v["origin"], title=v["title"], summary=v["summary"],
                        n_changes=len(v["changes"])) for v in versions[:6]],
        recent=_recent(con),
        midterm_2026=mid and dict(as_of=mid["as_of"], house_vote=mid["house_vote"], seats=mid["seats"]),
    )
    _write(out_dir / "summary.json", summary)
    _write(out_dir / "scenarios.json", [dict({k: (_r(v, 4) if isinstance(v, float) else v) for k, v in s.items()}) for s in N.get("scenarios", [])])

    # ---- field
    from .model.evidence import primary_average
    from datetime import date as _date

    today = _date.fromisoformat(run_date)
    money = {m["name"]: m for m in rows(con, "SELECT * FROM money")}
    strengths = nat_polls.get("strengths") or {}
    field = {}
    for party in ("D", "R"):
        avg = primary_average(con, party, today)
        spec_by = {c["name"]: c for c in nominees[party]}
        people = []
        for c in rows(con, "SELECT * FROM candidates WHERE party=?", (party,)):
            people.append(_person(con, c["name"], party, c, spec_by, avg, strengths, money))
        for name in spec_by:
            if name != OTHER and name not in {x["name"] for x in people}:
                people.append(_person(con, name, party, None, spec_by, avg, strengths, money))
        people.sort(key=lambda x: (-(x["p_nominee"] or 0), -(x["primary_share"] or 0), x["name"]))
        field[party] = dict(
            candidates=people, other=spec_by.get(OTHER), average=avg.get("shares"), n_polls=avg.get("n_polls"), aggregates=avg.get("aggregates") or [],
            polls=[dict(pollster=r["pollster"], end=r["end_date"], start=r["start_date"], n=r["sample_size"], pop=r["population"], shares=json.loads(r["shares"]))
                   for r in rows(con, "SELECT * FROM primary_polls WHERE party=? ORDER BY end_date DESC LIMIT 60", (party,))],
            news=_news(con, party, 10),
            markets=[m for m in mk.get(f"nominee_{party}", [])],
            narrative=((narr.get("NATIONAL") or {}).get("nominations") or {}).get(party),
        )
    _write(out_dir / "field.json", dict(generated_at=summary["generated_at"], run_date=run_date, parties=field,
                                        scenarios=summary["scenarios"], winner_markets=mk.get("winner", [])))

    # ---- polls
    weights = nat_polls.get("weights") or {}
    econ_series = {}
    for r in rows(con, "SELECT * FROM economy ORDER BY period"):
        econ_series.setdefault(r["series"], []).append(dict(period=r["period"], value=r["value"]))
    _write(out_dir / "polls.json", dict(
        generated_at=summary["generated_at"], run_date=run_date,
        national=[_poll_out(p, weights.get(p["poll_id"])) for p in rows(con, "SELECT * FROM polls WHERE scope='national' ORDER BY end_date DESC")],
        state=[_poll_out(p, (upd.get(p["contest_id"]) or {}).get("weights", {}).get(p["poll_id"])) for p in rows(con, "SELECT * FROM polls WHERE scope='state' ORDER BY end_date DESC")],
        strengths=strengths, environment=summary["environment"], house_effects=nat_polls.get("house_effects") or {},
        midterm_2026=mid,
        approval=[dict(source=r["source"], as_of=r["as_of"], approve=r["approve"], disapprove=r["disapprove"], net=r["net"])
                  for r in rows(con, "SELECT * FROM approval WHERE as_of=(SELECT max(as_of) FROM approval) ORDER BY source")],
        approval_history=[dict(as_of=r["as_of"], net=r["net"]) for r in rows(con, "SELECT as_of, net FROM approval WHERE source='Average' ORDER BY as_of")],
        economy=dict(indicators=E.get("economy"), index=E["fundamentals"].get("econ_index"),
                     series={k: v[-30:] for k, v in econ_series.items()}),
        state_updates={k: {kk: vv for kk, vv in v.items() if kk != "weights"} for k, v in upd.items()},
    ))

    # ---- model
    dte = N.get("days_to_election", days_to_election())
    params = [dict(path=p, value=get(spec, p), low=lo, high=hi, max_step=st, description=DESCRIPTIONS.get(p)) for p, (lo, hi, st) in BOUNDS.items()]
    _write(out_dir / "model.json", dict(
        generated_at=summary["generated_at"],
        current=dict(version=version, origin=origin, spec=spec, parameters=params,
                     effective=dict(national_sd=_r(national_sd_curve(dte) * spec["uncertainty"]["national_mult"], 2),
                                    state_sd=_r(state_sd_curve(dte) * spec["uncertainty"]["state_mult"], 2),
                                    default_poll_weight=_r(poll_trust_curve(dte), 3), poll_weight=E["environment"].get("poll_weight"),
                                    days_to_election=dte)),
        versions=[dict(v, changes=[_label_change(c) for c in v["changes"]]) for v in versions[:200]],
        total_versions=store.count(con), storylines=current_storylines(con),
    ))
    runs = rows(con, "SELECT stage, started_at, finished_at, ok, note FROM runs ORDER BY run_id DESC LIMIT 40")
    research = [dict(r, results=json.loads(r["results"] or "[]")) for r in rows(con, "SELECT created_at, query, why, results FROM research ORDER BY id DESC LIMIT 24")]
    _write(out_dir / "meta.json", dict(generated_at=summary["generated_at"], version=VERSION, runs=[dict(r, ok=bool(r["ok"])) for r in runs],
                                       research=research))
    from . import hegseth

    hegseth.export(con, out_dir)
    if verbose:
        ec = summary["ec"]
        print(f"  exported {len(table)} contests to {out_dir} (spec v{N.get('spec_version')}; P(D)={ec['p_dem']:.3f})")
    return summary


def _recent(con, days: int = 7, max_points: int = 240) -> list[dict]:
    """Every update's headline numbers over the last week (thinned to at most max_points)."""
    rs = rows(con, "SELECT * FROM run_log WHERE ts >= datetime('now', ?) ORDER BY ts", (f"-{days} days",))
    step = max(1, len(rs) // max_points)
    pts = rs[::step]
    if rs and pts[-1] is not rs[-1]:
        pts.append(rs[-1])
    return [dict(ts=r["ts"], v=r["spec_version"], p_dem=_r(r["p_dem"], 4), p_rep=_r(r["p_rep"], 4), dem_ev=_r(r["dem_ev"], 1), pv=_r(r["pv"], 2)) for r in pts]


def _person(con, name, party, row, spec_by, avg, strengths, money) -> dict:
    s = spec_by.get(name) or {}
    st = strengths.get(name) if (strengths.get(name) or {}).get("party") == party else None
    m = money.get(name) or {}
    return dict(name=name, party=party, status=(row or {}).get("status") or ("potential" if name in spec_by else None),
                home_state=s.get("home_state") or (row or {}).get("home_state"), experience=(row or {}).get("experience"),
                announced=(row or {}).get("announced"), primary_share=(avg.get("shares") or {}).get(name),
                p_nominee=s.get("p"), effect=s.get("effect"), p_win_if_nominee=s.get("p_win_if_nominee"), dem_ev=s.get("dem_ev"),
                poll_strength=st and dict(strength=st["strength"], sd=st["sd"], n_polls=st["n_polls"]),
                receipts=m.get("receipts"), cash=m.get("cash"), coverage_end=m.get("coverage_end"), news=_news(con, name, 4))


def _rating_consensus(rs: list[dict]):
    if not rs:
        return None
    from .util import parse_rating, rating_label

    scores = []
    for r in rs:
        pr = parse_rating(r["rating"])
        if pr:
            scores.append((1 if pr[0] == "D" else -1 if pr[0] == "R" else 0) * pr[1])
    if not scores:
        return None
    return dict(label=rating_label(sum(scores) / len(scores)), n=len(scores))


def _label_change(c: dict) -> dict:
    path = c["path"]
    parts = path.split(".")
    if parts[0] == "nominees":
        label = f"{parts[2]}: {'nomination odds' if parts[-1] == 'p' else 'candidate strength'} ({'Democratic' if parts[1] == 'D' else 'Republican'})"
    elif parts[0] == "state_adjustments":
        label = f"{contest_name(parts[1])} adjustment"
    else:
        label = DESCRIPTIONS.get(path, path)
    return dict(c, label=label)


def _round_tree(o, nd=4):
    if isinstance(o, float):
        return round(o, nd)
    if isinstance(o, dict):
        return {k: _round_tree(v, nd) for k, v in o.items()}
    if isinstance(o, list):
        return [_round_tree(v, nd) for v in o]
    return o
