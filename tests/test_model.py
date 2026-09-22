from datetime import date

import numpy as np
import pytest

from electionpredictions.model.forecast import race_forecast, simulate
from electionpredictions.model.fundamentals import fundamentals, rating_summary
from electionpredictions.model.pollavg import average

TODAY = date(2026, 9, 22)


def poll(end, d, r, n=800, pop="LV", lean=None, hyp=0, pollster="A", pid=None):
    return dict(poll_id=pid or f"{pollster}{end}{d}{r}", end_date=end, dem_pct=d, rep_pct=r, sample_size=n,
                population=pop, sponsor_lean=lean, hypothetical=hyp, pollster=pollster)


def cand(name, party, inc=0, receipts=None):
    return dict(name=name, party=party, is_incumbent=inc, major=1, receipts=receipts)


def race(chamber="senate", pvi=0.0, inc="D", running=1, holder="D"):
    return dict(race_id="XX-SEN", chamber=chamber, state="XX", pvi=pvi, incumbent="Inc" if inc else None,
                incumbent_party=inc, incumbent_running=running, holder_party=holder, special=0, district=None)


def test_average_recency_weights_newer_polls_more():
    a = average([poll("2026-09-20", 50, 40, pollster="A"), poll("2026-08-01", 40, 50, pollster="B")], TODAY)
    assert a["margin"] > 0 and a["n_polls"] == 2


def test_average_sponsor_shift_and_weight():
    neutral = average([poll("2026-09-20", 50, 45)], TODAY)
    partisan = average([poll("2026-09-20", 50, 45, lean="D")], TODAY)
    assert partisan["margin"] == pytest.approx(neutral["margin"] - 1.5)
    assert partisan["n_eff"] < neutral["n_eff"]


def test_average_pollster_cap():
    same = [poll("2026-09-20", 60, 40, pollster="A", pid=str(i)) for i in range(5)]
    other = [poll("2026-09-19", 45, 55, pollster="B")]
    a = average(same + other, TODAY)
    # five identical polls from one firm shouldn't swamp one from another
    assert -5 < a["margin"] < 12


def test_average_ignores_stale_polls():
    assert average([poll("2025-12-01", 50, 40)], TODAY) is None


def test_fundamentals_components():
    f = fundamentals(race(pvi=-4, inc="R"), cand("D", "D", receipts=2e6), cand("R", "R", inc=1, receipts=1e6), generic_margin=8.0)
    assert f["lean"] == -4
    assert abs(f["environment"] - 7.2) < 1e-9
    assert f["incumbency"] == -3
    assert f["money"] > 0
    assert abs(f["margin"] - (f["lean"] + f["environment"] + f["incumbency"] + f["money"])) < 1e-9


def test_rating_summary_and_implicit():
    rs = [dict(party="D", level=2), dict(party="R", level=2)]
    s = rating_summary(rs, "D")
    assert s["n"] == 2 and s["label"] == "Tossup" and s["margin"] == 0
    imp = rating_summary([], "R", fund_margin=-12)
    assert imp["implicit"] and imp["label"] == "Safe R"
    # redistricted seat: holder R but fundamentals strongly D -> safe D
    flip = rating_summary([], "R", fund_margin=+13)
    assert flip["label"] == "Safe D" and flip["basis"] == "fundamentals"


def test_race_forecast_polls_pull_toward_polls():
    r = race(pvi=-3, inc="R")
    cands = [cand("D", "D"), cand("R", "R", inc=1)]
    ratings = [dict(party="R", level=2)]
    without = race_forecast(r, cands, ratings, [], 8.0, TODAY)
    with_polls = race_forecast(r, cands, ratings, [poll("2026-09-20", 52, 42, n=1000, pollster=str(i), pid=str(i)) for i in range(4)], 8.0, TODAY)
    assert with_polls["mu"] > without["mu"]
    assert with_polls["poll_weight"] > 0.5


def test_race_forecast_uncontested():
    r = race_forecast(race(), [cand("D", "D")], [], [], 8.0, TODAY)
    assert r["uncontested"] and r["p_dem"] == 1.0


def test_simulate_shape_and_monotone():
    results = [dict(mu=m, sigma_race=4.0, env_w=1.0, state="GA", uncontested=False) for m in (-10, 0, 10)]
    wins = simulate(results, dte=42, n_sims=5000, seed=1)
    assert wins.shape == (5000, 3)
    p = wins.mean(axis=0)
    assert p[0] < 0.1 and 0.4 < p[1] < 0.6 and p[2] > 0.9


def test_simulate_correlation_via_national_swing():
    results = [dict(mu=0.0, sigma_race=3.0, env_w=1.0, state="GA", uncontested=False),
               dict(mu=0.0, sigma_race=3.0, env_w=1.0, state="WI", uncontested=False)]
    wins = simulate(results, dte=42, n_sims=20000, seed=2)
    corr = np.corrcoef(wins[:, 0], wins[:, 1])[0, 1]
    assert corr > 0.1
