"""The presidential engine, its evidence layer, calibration and the historical baseline."""
from datetime import date

from electionpredictions.config import CONTEST_EVS, CONTEST_IDS, EVS_TO_WIN, TOTAL_EVS
from electionpredictions.history import RESULTS
from electionpredictions.model import engine, evidence as ev
from electionpredictions.model.calibrate import calibrate
from electionpredictions.model.contests import contests
from electionpredictions.model.spec import seed

TODAY = date(2026, 11, 5)


def test_contests_and_electoral_votes():
    assert sum(CONTEST_EVS.values()) == TOTAL_EVS == 538
    assert len(CONTEST_IDS) == 56 and set(CONTEST_IDS) == set(RESULTS)
    assert CONTEST_EVS["ME"] == 2 and CONTEST_EVS["NE-2"] == 1 and CONTEST_EVS["CA"] == 54


def test_history_reproduces_2024_and_2020_electoral_votes():
    cs = contests(seed())
    d24 = sum(c["evs"] for c in cs if c["winner24"] == "D")
    d20 = sum(c["evs"] for c in cs if c["winner20"] == "D")
    assert (d24, TOTAL_EVS - d24) == (226, 312)   # Harris 226 (incl. NE-2), Trump 312 (incl. ME-2)
    assert (d20, TOTAL_EVS - d20) == (303, 235)   # Biden states on the 2020-census map (306 under the old apportionment)


def test_lean_is_relative_to_nation():
    by = {c["contest_id"]: c for c in contests(seed())}
    assert -3 < by["PA"]["lean"] < 0 and by["WY"]["lean"] < -40 and by["DC"]["lean"] > 80
    assert by["NE-2"]["lean"] > 3 and by["ME-2"]["lean"] < -5


def test_national_poll_regression_separates_candidates(db):
    from electionpredictions.db import rows

    nat = ev.national_poll_model(rows(db, "SELECT * FROM polls WHERE scope='national'"), TODAY, seed())
    assert nat and nat["n_polls"] == 5
    s = nat["strengths"]
    assert s["Kamala Harris"]["strength"] > s["Gavin Newsom"]["strength"]   # Harris polls better than Newsom vs the same opponents
    assert s["Marco Rubio"]["strength"] > s["JD Vance"]["strength"]         # Rubio runs stronger than Vance
    assert 0 < nat["g"] < 4


def test_state_poll_reads_relative_to_national(db):
    from electionpredictions.db import rows

    nat = ev.national_poll_model(rows(db, "SELECT * FROM polls WHERE scope='national'"), TODAY, seed())
    leans = {c["contest_id"]: c["lean"] for c in contests(seed())}
    upd = ev.state_lean_updates(rows(db, "SELECT * FROM polls WHERE scope='state'"), leans, nat, 0.0, TODAY, seed())
    assert set(upd) == {"NV"}
    assert upd["NV"]["shift"] < 0 and 0 < upd["NV"]["poll_weight"] < 0.5   # a weak R-leaning read moves the lean a little


def test_fundamentals_direction():
    sp = seed()
    bad = ev.fundamentals(dict(net=-30.0), dict(inflation=6.0, unemployment_change=1.0, real_wage_growth=-2.0), sp)
    good = ev.fundamentals(dict(net=15.0), dict(inflation=2.0, unemployment_change=-0.3, real_wage_growth=1.5), sp)
    assert bad["dem_environment"] > 5 > good["dem_environment"]   # the White House party (R) is punished for a bad record


def test_implied_nominee_odds():
    odds = ev.implied_nominee_odds({"A": 30, "B": 15, "C": 0.5}, dte=700, extra_names=["D"])
    assert abs(sum(odds.values()) - 1) < 1e-9 and odds["A"] > odds["B"] > odds["D"] and "C" not in odds
    assert odds["Other"] > ev.implied_nominee_odds({"A": 30}, dte=10)["Other"]


def test_calibrate_builds_field(db):
    prop, nomev, _ = calibrate(db, seed(), TODAY)
    d = {c["name"]: c for c in prop["nominees"]["D"]}
    r = {c["name"]: c for c in prop["nominees"]["R"]}
    assert d["Kamala Harris"]["p"] > d["Gavin Newsom"]["p"] > d["Pete Buttigieg"]["p"]
    assert "Royce White" in r and r["Royce White"]["home_state"] == "MN"   # declared candidates join the field
    assert abs(sum(c["p"] for c in prop["nominees"]["D"]) - 1) < 1e-3
    assert d["Kamala Harris"]["home_state"] == "CA"


def test_engine_is_coherent(db):
    prop, _, _ = calibrate(db, seed(), TODAY)
    out = engine.run(db, prop, spec_version=1, today=TODAY, n_sims=3000, seed=7, verbose=False)
    ec = out["ec"]
    assert abs(ec["p_dem"] + ec["p_rep"] + ec["p_tie"] - 1) < 1e-9
    assert abs(ec["dem_ev"]["mean"] + ec["rep_ev"]["mean"] - TOTAL_EVS) < 1e-6
    assert abs(sum(b["p"] for b in ec["histogram"]) - 1) < 1e-9
    per = {c["contest_id"]: c for c in out["contests"]}
    assert len(per) == 56
    assert per["DC"]["p_dem"] > 0.99 and per["WY"]["p_dem"] < 0.01
    assert per["ME-1"]["p_dem"] > per["ME"]["p_dem"] > per["ME-2"]["p_dem"]
    assert abs(sum(c["tip"] for c in out["contests"]) - 1) < 1e-6
    # each matchup's odds are consistent with the candidate strengths
    sc = out["scenarios"]
    assert sc and all(0 <= s["p_dem"] <= 1 for s in sc) and sc[0]["p"] >= sc[-1]["p"]
    cond = {c["name"]: c for c in out["conditional"]["R"]}
    assert cond["Marco Rubio"]["p_win_if_nominee"] > cond["JD Vance"]["p_win_if_nominee"]
    # persisted
    from electionpredictions.db import rows

    assert rows(db, "SELECT count(*) n FROM forecasts")[0]["n"] == 56
    assert rows(db, "SELECT spec_version FROM national_forecasts")[0]["spec_version"] == 1


def test_wider_uncertainty_pulls_toward_even(db):
    prop, _, _ = calibrate(db, seed(), TODAY)
    narrow = dict(prop, uncertainty=dict(prop["uncertainty"], national_mult=0.6, state_mult=0.6))
    wide = dict(prop, uncertainty=dict(prop["uncertainty"], national_mult=1.6, state_mult=1.6))
    a = engine.run(db, narrow, today=TODAY, n_sims=3000, seed=3, persist=False, verbose=False)["ec"]["p_dem"]
    b = engine.run(db, wide, today=TODAY, n_sims=3000, seed=3, persist=False, verbose=False)["ec"]["p_dem"]
    assert abs(b - 0.5) < abs(a - 0.5)
    assert EVS_TO_WIN == 270


def test_house_effects_absorb_a_leaning_pollster():
    import copy as _copy

    polls = []
    for i in range(12):
        lean = 4.0 if i % 2 else 0.0                       # "Tilted Co." always 4 points more Democratic
        firm = "Tilted Co." if i % 2 else f"Neutral {i}"
        polls.append(dict(poll_id=f"h{i}", pollster=firm, sponsor_lean=None, end_date="2026-10-20", sample_size=1000, population="LV",
                          dem_name="A Dem", rep_name="A Rep", dem_pct=46 + lean / 2, rep_pct=46 - lean / 2, other_pct=None))
    sp = seed()
    with_h = ev.national_poll_model(polls, TODAY, sp)
    no_h = _copy.deepcopy(sp)
    no_h["polls"]["house_effect_sd"] = 0.0
    without = ev.national_poll_model(polls, TODAY, no_h)
    assert with_h["house_effects"]["Tilted Co."]["effect"] > 0.8 and "Neutral 1" not in with_h["house_effects"]
    assert abs(with_h["g"]) < abs(without["g"])            # the tilt no longer drags the environment
    assert without["house_effects"] == {}


def test_independent_candidate_and_determinism(db):
    prop, _, _ = calibrate(db, seed(), TODAY)
    base = engine.run(db, prop, today=TODAY, n_sims=4000, persist=False, verbose=False)
    again = engine.run(db, prop, today=TODAY, n_sims=4000, persist=False, verbose=False)
    assert base["ec"]["p_dem"] == again["ec"]["p_dem"]      # inputs fully determine the numbers
    spoiler = dict(prop, third_party=dict(p_run=0.8, net_effect=-4.0, effect_sd=0.5))   # a bid that costs Democrats
    hurt = engine.run(db, spoiler, today=TODAY, n_sims=4000, persist=False, verbose=False)
    assert hurt["ec"]["p_dem"] < base["ec"]["p_dem"] - 0.05
    assert hurt["uncertainty"]["third_party_p"] == 0.8


def test_spec_upgrade_fills_new_settings():
    from electionpredictions.model.spec import upgrade, validate

    old = seed()
    del old["third_party"]
    del old["polls"]["house_effect_sd"]
    up = upgrade(old)
    assert up["third_party"]["p_run"] == seed()["third_party"]["p_run"] and up["polls"]["house_effect_sd"] == 2.0
    assert validate(up, old)["third_party"] == up["third_party"]
