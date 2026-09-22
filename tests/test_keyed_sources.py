import numpy as np

from electionpredictions.model.forecast import demographic_z, simulate
from electionpredictions.model.fundamentals import fundamentals
from electionpredictions.sources.census import parse_table
from electionpredictions.sources.followthemoney import parse_records


def test_census_parse_table():
    table = [["NAME", "B01003_001E", "B15003_001E", "B15003_022E", "B15003_023E", "B15003_024E", "B15003_025E",
              "B03002_001E", "B03002_003E", "B03002_004E", "B03002_012E", "state", "congressional district"],
             ["Congressional District 1 (119th Congress), Arizona", "800000", "500000", "100000", "50000", "10000", "5000",
              "800000", "500000", "40000", "200000", "04", "01"],
             ["Congressional District (not defined), Arizona", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "04", "ZZ"]]
    rows_ = parse_table(table, district=True)
    assert len(rows_) == 1 and rows_[0]["state"] == "AZ" and rows_[0]["district"] == 1
    assert abs(rows_[0]["pct_college"] - 33.0) < 0.01 and abs(rows_[0]["pct_white_nh"] - 62.5) < 0.01


def test_followthemoney_parse_records():
    payload = {"records": [{"Candidate": {"token": "c-t-id", "id": "1", "Candidate": "INSLEE, JAY ROBERT"},
                            "General_Party": {"General_Party": "Democratic"}, "Office_Sought": {"Office_Sought": "GOVERNOR"},
                            "Total_$": {"Total_$": "1,234,567.89"}}]}
    recs = parse_records(payload)
    assert recs[0]["name"] == "Jay Robert Inslee" and recs[0]["total"] == 1234567.89 and recs[0]["party"] == "Democratic"


def _race():
    return dict(race_id="XX-SEN", chamber="senate", state="XX", pvi=0.0, incumbent=None, incumbent_party=None,
                incumbent_running=0, holder_party="D", special=0, district=None)


def test_outside_spending_shifts_money_term():
    dem = dict(name="D", party="D", is_incumbent=0, major=1, receipts=1e6)
    rep = dict(name="R", party="R", is_incumbent=0, major=1, receipts=1e6)
    base = fundamentals(_race(), dem, rep, 0.0)["money"]
    rep2 = dict(rep, ie_oppose=5e6)  # heavy attacks on the Republican help the Democrat
    assert fundamentals(_race(), dem, rep2, 0.0)["money"] > base


def test_demographic_correlation_in_simulation():
    results = [dict(mu=0.0, sigma_race=3.0, env_w=1.0, state="GA", district=None, chamber="senate", uncontested=False),
               dict(mu=0.0, sigma_race=3.0, env_w=1.0, state="WI", district=None, chamber="senate", uncontested=False)]
    demo = {("GA", None): dict(pct_college=40.0, pct_white_nh=50.0), ("WI", None): dict(pct_college=40.0, pct_white_nh=50.0)}
    z = demographic_z(results, demo)
    assert z.shape == (2, 2)
    wins = simulate(results, dte=42, n_sims=4000, seed=3, demo=demo)
    assert wins.shape == (4000, 2)
    assert simulate(results, dte=42, n_sims=100, seed=3, demo=None).shape == (100, 2)
