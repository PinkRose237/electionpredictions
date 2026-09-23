"""Tests for the 2028 presidential (Electoral College) model."""
import json
import sqlite3
import tempfile
from pathlib import Path

from electionpredictions import export as _export
from electionpredictions.config import (
    ELECTORAL_VOTES_2028,
    PRESIDENT_2024_WINNER,
    PRESIDENT_JURISDICTIONS,
    PRESIDENT_PVI_2028,
)
from electionpredictions.db import connect, upsert
from electionpredictions.model import forecast
from electionpredictions.model.fundamentals import PARAMS
from electionpredictions.sources.races import build_president
from electionpredictions.util import race_id


def test_electoral_votes_sum_to_538():
    assert sum(ELECTORAL_VOTES_2028.values()) == 538
    assert len(ELECTORAL_VOTES_2028) == 51
    assert set(ELECTORAL_VOTES_2028) == set(PRESIDENT_JURISDICTIONS) == set(PRESIDENT_PVI_2028) == set(PRESIDENT_2024_WINNER)


def test_2024_reference_split_matches_history():
    d = sum(ev for st, ev in ELECTORAL_VOTES_2028.items() if PRESIDENT_2024_WINNER[st] == "D")
    r = sum(ev for st, ev in ELECTORAL_VOTES_2028.items() if PRESIDENT_2024_WINNER[st] == "R")
    assert (d, r) == (226, 312)  # Harris 226, Trump 312


def test_president_race_ids():
    assert race_id("president", "PA") == "PA-PRES"
    assert race_id("president", "DC") == "DC-PRES"


def test_build_president_universe():
    races, cands = build_president()
    assert len(races) == 51 and len(cands) == 102
    by_id = {r["race_id"]: r for r in races}
    pa = by_id["PA-PRES"]
    assert pa["chamber"] == "president" and pa["pvi"] == -1 and pa["holder_party"] == "R"
    assert pa["incumbent_running"] == 0
    dc = by_id["DC-PRES"]
    assert dc["pvi"] == 44 and "Columbia" in dc["name"]
    for c in cands:
        assert c["major"] == 1 and c["party"] in ("D", "R")
    assert "president" in PARAMS


def _pres_db():
    tmp = Path(tempfile.mkdtemp()) / "pres.db"
    con = connect(tmp)
    races, cands = build_president()
    upsert(con, "races", races, keys=["race_id"])
    for c in cands:
        con.execute("INSERT INTO candidates (race_id,name,party,is_incumbent,major) VALUES (?,?,?,?,?)",
                    (c["race_id"], c["name"], c["party"], c["is_incumbent"], c["major"]))
    con.commit()
    return con


def test_president_simulation_is_coherent():
    con = _pres_db()
    out = forecast.run(con, n_sims=500, seed=11, verbose=False, use_ai=False)
    assert set(out["chambers"]) == {"president"}
    p = out["chambers"]["president"]
    assert p["total"] == 538 and p["needed"] == 270
    assert 0 < p["p_dem"] < 1 and 0 < p["p_rep"] < 1
    assert abs(p["p_dem"] + p["p_rep"] + p["p_neither"] - 1) < 1e-9
    assert abs(p["dem_seats"]["mean"] + p["rep_seats"]["mean"] - 538) < 5  # rounding + ties
    assert p["current"] == {"D": 226, "R": 312, "other": 0}
    assert p["expected_flips"]["D"] >= 0 and p["expected_flips"]["R"] >= 0
    # fundamentals-only: PA (R+1 lean) leans R, CA (D+12) is safe D
    rp = out["races"]
    assert rp["PA-PRES"]["p_dem"] < 0.5 < rp["CA-PRES"]["p_dem"]
    assert rp["DC-PRES"]["p_dem"] > 0.95


def test_president_export_shape():
    con = _pres_db()
    forecast.run(con, n_sims=500, seed=11, verbose=False, use_ai=False)
    outdir = Path(tempfile.mkdtemp())
    s = _export.export(con, out_dir=outdir, verbose=False)
    p = s["chambers"]["president"]
    assert (p["label"], p["total"], p["seats_up"], p["needed"]) == ("President", 538, 51, 270)
    summaries = json.loads((outdir / "races.json").read_text())
    assert len(summaries) == 51
    pa = next(r for r in summaries if r["race_id"] == "PA-PRES")
    assert pa["evs"] == 19 and pa["prev"] == "R" and pa["short"] == "PA-Pres"
    assert len(list((outdir / "races").glob("*.json"))) == 51
    assert s["history"] and "president" in s["history"][-1]
    con.close()
    sqlite3.connect(":memory:").close()
