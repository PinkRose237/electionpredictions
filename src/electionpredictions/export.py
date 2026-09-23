"""Write the static JSON the website reads (schema: docs/DATA_CONTRACT.md)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .config import DC_NAME, ELECTION_DATE, ELECTORAL_VOTES_2028, PRESIDENT_2024_WINNER, SITE_DATA_DIR, STATES, days_to_election
from .db import now_iso, rows
from .model.forecast import _sides
from .schedule import build_schedule
from .util import ordinal

VERSION = "0.1.0"
CHAMBER_LABEL = {"house": "House", "senate": "Senate", "governor": "Governors", "president": "President"}
LABELS = ["Safe D", "Likely D", "Lean D", "Tossup", "Lean R", "Likely R", "Safe R"]


def _group(rs, key):
    out = {}
    for r in rs:
        out.setdefault(r[key], []).append(r)
    return out


def _pvi_label(pvi: Optional[float]) -> Optional[str]:
    if pvi is None:
        return None
    if abs(pvi) < 0.5:
        return "EVEN"
    return f"{'D' if pvi > 0 else 'R'}+{abs(pvi):g}"


def _short(race: dict) -> str:
    if race["chamber"] == "house":
        return f"{race['state']}-{race['district']:02d}" if race["district"] else f"{race['state']}-AL"
    if race["chamber"] == "senate":
        return f"{race['state']}-Sen" + (" (special)" if race["special"] else "")
    if race["chamber"] == "president":
        return f"{race['state']}-Pres"
    return f"{race['state']}-Gov"


def _cand(c: Optional[dict]) -> Optional[dict]:
    if not c:
        return None
    return dict(name=c["name"], party=c["party"], incumbent=bool(c["is_incumbent"]),
                receipts=c["receipts"], cash=c["cash_on_hand"])


def _market_dem_side(m: dict, dem_party: str) -> Optional[float]:
    """D-side win probability implied by one market row, normalised against the R side."""
    d = m["p_dem"] or 0.0
    if dem_party == "I" and m["p_other"] is not None:
        d = d + m["p_other"]
    r = m["p_rep"]
    if r is None and m["p_dem"] is None:
        return None
    if r is None:
        return d
    tot = d + r
    return d / tot if tot > 0 else None


def _merge_history(new: list[dict], path: Path) -> list[dict]:
    """Union of the freshly computed history with whatever is already published, keyed by date."""
    old: list[dict] = []
    if path.exists():
        try:
            old = json.loads(path.read_text()).get("history") or []
        except (json.JSONDecodeError, AttributeError):
            old = []
    merged = {h["date"]: h for h in old}
    merged.update({h["date"]: h for h in new})
    return [merged[d] for d in sorted(merged)]


def export(con, out_dir: Path = SITE_DATA_DIR, verbose: bool = True) -> dict:
    out_dir = Path(out_dir)
    (out_dir / "races").mkdir(parents=True, exist_ok=True)
    latest = rows(con, "SELECT max(run_date) d FROM forecasts")[0]["d"]
    if not latest:
        raise SystemExit("No forecast in the database yet; run `electionpredictions model` first.")
    fc = {r["race_id"]: r for r in rows(con, "SELECT * FROM forecasts WHERE run_date=?", (latest,))}
    cf = {r["chamber"]: r for r in rows(con, "SELECT * FROM chamber_forecasts WHERE run_date=?", (latest,))}
    races = rows(con, "SELECT * FROM races ORDER BY chamber, state, district, special")
    cands_by = _group(rows(con, "SELECT * FROM candidates ORDER BY major DESC, is_incumbent DESC, coalesce(receipts,0) DESC, name"), "race_id")
    ratings_by = _group(rows(con, "SELECT * FROM ratings ORDER BY rater"), "race_id")
    polls_by = _group(rows(con, "SELECT * FROM polls ORDER BY end_date DESC, pollster"), "race_id")
    aggs_by = _group(rows(con, "SELECT * FROM poll_aggregates ORDER BY source"), "race_id")
    markets_by = _group(rows(con, "SELECT * FROM markets ORDER BY platform"), "race_id")
    news_by = _group(rows(con, "SELECT * FROM news ORDER BY published DESC"), "race_id")
    hist_by = _group(rows(con, "SELECT run_date, race_id, p_dem, margin FROM forecasts ORDER BY run_date"), "race_id")
    try:
        outside = {(o["race_id"], o["name"]): o for o in rows(con, "SELECT * FROM outside_spending")}
    except Exception:  # noqa: BLE001
        outside = {}
    try:
        national = json.loads(rows(con, "SELECT detail FROM chamber_forecasts WHERE run_date=? LIMIT 1", (latest,))[0]["detail"]).get("national")
    except Exception:  # noqa: BLE001
        national = None
    gb_rows = rows(con, "SELECT * FROM generic_ballot ORDER BY as_of DESC")

    summaries, label_counts = [], {c: {lab: 0 for lab in LABELS} for c in CHAMBER_LABEL}
    for race in races:
        rid = race["race_id"]
        f = fc.get(rid)
        if not f:
            continue
        detail = json.loads(f["detail"])
        cands = cands_by.get(rid, [])
        dem, rep = _sides(cands)
        dem_party = dem["party"] if dem else "D"
        rating = detail.get("rating")
        poll = detail.get("poll")
        mk = markets_by.get(rid, [])
        mk_probs = [p for p in (_market_dem_side(m, dem_party) for m in mk) if p is not None]
        label = detail.get("label")
        label_counts[race["chamber"]][label] += 1
        s = dict(
            race_id=rid, chamber=race["chamber"], state=race["state"], state_name=STATES.get(race["state"], DC_NAME),
            district=race["district"] if race["chamber"] == "house" else None, special=bool(race["special"]),
            name=race["name"], short=_short(race),
            incumbent=race["incumbent"], incumbent_party=race["incumbent_party"], incumbent_running=bool(race["incumbent_running"]),
            holder_party=race["holder_party"], open_seat=not bool(race["incumbent_running"]),
            pvi=race["pvi"], pvi_label=_pvi_label(race["pvi"]),
            dem=_cand(dem), rep=_cand(rep),
            p_dem=round(f["p_dem"], 4), margin=round(f["margin"], 2) if not detail.get("uncontested") else None,
            sd=round(f["sd"], 2) if not detail.get("uncontested") else None, label=label,
            rating=dict(label=rating["label"], score=round(rating["score"], 2), n=rating["n"]) if rating else None,
            polls=dict(margin=round(poll["margin"], 2), n=poll["n_polls"], n_eff=round(poll["n_eff"], 2), last=poll["last_poll"]) if poll else None,
            fundamentals=round(detail["fund"]["margin"], 2) if detail.get("fund") else None,
            markets=dict(p_dem=round(sum(mk_probs) / len(mk_probs), 4), n=len(mk_probs)) if mk_probs else None,
            flip_prob=round(detail["flip_prob"], 4) if detail.get("flip_prob") is not None else None,
            uncontested=bool(detail.get("uncontested")),
            news_count=len(news_by.get(rid, [])),
        )
        if race["chamber"] == "president":
            s["evs"] = ELECTORAL_VOTES_2028[race["state"]]
            s["prev"] = PRESIDENT_2024_WINNER[race["state"]]
        summaries.append(s)
        weights = detail.get("weights") or {}
        poll_list = []
        for p in polls_by.get(rid, []):
            matchup = json.loads(p["matchup"]) if p["matchup"] else []
            poll_list.append(dict(
                pollster=p["pollster"], sponsor_lean=p["sponsor_lean"], start_date=p["start_date"], end_date=p["end_date"],
                sample_size=p["sample_size"], population=p["population"], moe=p["moe"],
                dem_pct=p["dem_pct"], rep_pct=p["rep_pct"], und_pct=p["und_pct"],
                margin=round(p["dem_pct"] - p["rep_pct"], 1) if p["dem_pct"] is not None and p["rep_pct"] is not None else None,
                hypothetical=bool(p["hypothetical"]), weight=weights.get(p["poll_id"], 0.0), matchup=matchup,
            ))
        fund = detail.get("fund") or {}
        det = dict(
            s,
            candidates=[dict(name=c["name"], party=c["party"], incumbent=bool(c["is_incumbent"]), major=bool(c["major"]),
                             receipts=c["receipts"], disbursements=c["disbursements"], cash=c["cash_on_hand"], coverage_end=c["coverage_end"],
                             money_source=c.get("money_source") or ("fec" if c["receipts"] is not None else None),
                             outside_support=(outside.get((rid, c["name"])) or {}).get("support"),
                             outside_oppose=(outside.get((rid, c["name"])) or {}).get("oppose"))
                        for c in cands],
            ratings=[dict(rater=r["rater"], rating=r["rating"], as_of=r["as_of"]) for r in ratings_by.get(rid, [])],
            poll_list=poll_list,
            poll_aggregates=[dict(source=a["source"], as_of=a["as_of"], dem=a["dem"], rep=a["rep"], margin=a["margin"]) for a in aggs_by.get(rid, [])],
            market_list=[dict(platform=m["platform"], title=m["title"], p_dem=m["p_dem"], p_rep=m["p_rep"], p_other=m["p_other"],
                              volume=m["volume"], url=m["url"], fetched_at=m["fetched_at"]) for m in mk],
            news=[dict(title=n["title"], source=n["source"], published=n["published"], url=n["url"]) for n in news_by.get(rid, [])[:20]],
            model=dict(
                prior_margin=_r(detail.get("prior_margin")), prior_sd=_r(detail.get("prior_sd")),
                poll_margin=_r(poll["margin"]) if poll else None, poll_sd=_r(poll["poll_sd"]) if poll else None,
                poll_weight=_r(detail.get("poll_weight")),
                fundamentals=dict(margin=_r(fund.get("margin")), lean=_r(fund.get("lean")), environment=_r(fund.get("environment")),
                                  incumbency=_r(fund.get("incumbency")), money=_r(fund.get("money"))) if fund else None,
                rating_margin=_r(rating["margin"]) if rating else None,
                sigma_race=_r(detail.get("sigma_race")), sigma_total=_r(detail.get("sigma_total")),
                baseline_margin=_r(detail.get("quant_mu")) if detail.get("ai") else None,
                analyst_adjustment=_r(f["margin"] - detail["quant_mu"]) if detail.get("ai") and detail.get("quant_mu") is not None else None,
                key_factors=(detail.get("ai") or {}).get("key_factors") or [],
                rationale=(detail.get("ai") or {}).get("rationale") or None,
                watch=(detail.get("ai") or {}).get("watch") or None,
                confidence=(detail.get("ai") or {}).get("confidence") or None,
                notes=detail.get("notes") or [],
            ),
            overview=((detail.get("ai") or {}).get("overview") or None),
            history=_merge_history([dict(date=h["run_date"], p_dem=round(h["p_dem"], 4), margin=_r(h["margin"])) for h in hist_by.get(rid, [])],
                                   out_dir / "races" / f"{rid}.json"),
        )
        (out_dir / "races" / f"{rid}.json").write_text(json.dumps(det, ensure_ascii=False))
    (out_dir / "races.json").write_text(json.dumps(summaries, ensure_ascii=False))
    (out_dir / "schedule.json").write_text(json.dumps(build_schedule(summaries, now_iso()), ensure_ascii=False))

    # ---- summary
    latest_gb = [g for g in gb_rows if g["as_of"] == gb_rows[0]["as_of"]] if gb_rows else []
    avg = next((g for g in latest_gb if g["source"].lower() == "average"), None)
    generic = dict(
        margin=avg["margin"] if avg else (round(sum(g["margin"] for g in latest_gb) / len(latest_gb), 2) if latest_gb else None),
        dem=avg["dem"] if avg else None, rep=avg["rep"] if avg else None,
        sources=[dict(source=g["source"], as_of=g["as_of"], dem=g["dem"], rep=g["rep"], margin=g["margin"]) for g in latest_gb if g["source"].lower() != "average"],
    )
    control_mk = {"senate": markets_by.get("SENATE-CONTROL", []), "house": markets_by.get("HOUSE-CONTROL", []),
                  "governor": [], "president": markets_by.get("PRESIDENT-CONTROL", [])}
    chambers = {}
    for ch, row in cf.items():
        d = json.loads(row["detail"])
        chambers[ch] = dict(
            label=CHAMBER_LABEL[ch], total=d["total"], seats_up=d["seats_up"], needed=d["needed"], not_up=d["not_up"], current=d["current"],
            p_dem=round(d["p_dem"], 4), p_rep=round(d["p_rep"], 4), p_neither=round(d["p_neither"], 4),
            dem_seats={k: round(v, 1) for k, v in d["dem_seats"].items()}, rep_seats={k: round(v, 1) for k, v in d["rep_seats"].items()},
            histogram=[dict(seats=h["seats"], p=round(h["p"], 5)) for h in d["histogram"]],
            markets=[dict(platform=m["platform"], p_dem=m["p_dem"], p_rep=m["p_rep"], url=m["url"]) for m in control_mk.get(ch, [])],
            rating_counts=label_counts[ch], expected_flips={k: round(v, 1) for k, v in d["expected_flips"].items()},
        )
    history = []
    for rd in sorted({r["run_date"] for r in rows(con, "SELECT DISTINCT run_date FROM chamber_forecasts")}):
        h = {"date": rd}
        gbh = next((g["margin"] for g in gb_rows if g["source"].lower() == "average" and (g["as_of"] or "") <= rd), None)
        h["generic"] = gbh if gbh is not None else generic["margin"]
        for r in rows(con, "SELECT * FROM chamber_forecasts WHERE run_date=?", (rd,)):
            h[r["chamber"]] = dict(p_dem=round(r["p_dem"], 4), dem_seats=round(r["dem_seats_mean"], 1))
        history.append(h)
    contested = [s for s in summaries if not s["uncontested"]]
    closest = [s["race_id"] for s in sorted(contested, key=lambda s: abs(s["p_dem"] - 0.5))[:25]]
    counts = dict(
        polls=rows(con, "SELECT count(*) n FROM polls")[0]["n"], ratings=rows(con, "SELECT count(*) n FROM ratings")[0]["n"],
        markets=rows(con, "SELECT count(*) n FROM markets")[0]["n"], news=rows(con, "SELECT count(*) n FROM news")[0]["n"],
        fec_candidates=rows(con, "SELECT count(*) n FROM candidates WHERE receipts IS NOT NULL")[0]["n"],
    )
    history = _merge_history(history, out_dir / "summary.json")
    summary = dict(generated_at=now_iso(), election_date=ELECTION_DATE.isoformat(), days_to_election=days_to_election(),
                   run_date=latest, generic_ballot=generic, chambers=chambers, history=history, closest=closest, sources=counts,
                   overview=(dict(summary=national.get("summary"), key_factors=national.get("key_factors") or [], chambers=national.get("chambers") or {},
                                  environment_adjustment=national.get("environment_adjustment"), uncertainty_multiplier=national.get("uncertainty_multiplier"))
                             if national and national.get("summary") else None))
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False))
    runs = rows(con, "SELECT stage, started_at, finished_at, ok, note FROM runs ORDER BY run_id DESC LIMIT 30")
    (out_dir / "meta.json").write_text(json.dumps(dict(generated_at=summary["generated_at"], version=VERSION,
                                                       runs=[dict(r, ok=bool(r["ok"])) for r in runs]), ensure_ascii=False))
    if verbose:
        print(f"  exported {len(summaries)} races to {out_dir}")
    return summary


def _r(v, nd=2):
    return None if v is None else round(float(v), nd)
