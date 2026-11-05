"""Shared fixtures: a small, fully offline database with polls, primaries, approval and economy rows."""
import json

import pytest

from electionpredictions.db import connect, upsert


def _poll(i, scope, dem, rep, d, r, end, contest=None, n=1000):
    return dict(poll_id=f"p{i}", scope=scope, contest_id=contest, pollster=f"Pollster {i % 4}", sponsor_lean=None, start_date=end, end_date=end,
                sample_size=n, population="LV", dem_name=dem, rep_name=rep, dem_pct=d, rep_pct=r, other_pct=None, und_pct=None,
                matchup=json.dumps([[dem, "D", d], [rep, "R", r]]), source="test")


@pytest.fixture
def db(tmp_path):
    con = connect(tmp_path / "t.db")
    polls = [
        _poll(1, "national", "Gavin Newsom", "JD Vance", 47, 44, "2026-10-01"),
        _poll(2, "national", "Gavin Newsom", "JD Vance", 46, 45, "2026-09-15"),
        _poll(3, "national", "Kamala Harris", "JD Vance", 48, 44, "2026-09-20"),
        _poll(4, "national", "Gavin Newsom", "Marco Rubio", 44, 45, "2026-10-05"),
        _poll(5, "national", "Kamala Harris", "Marco Rubio", 45, 45, "2026-08-01"),
        _poll(6, "state", "Gavin Newsom", "JD Vance", 43, 47, "2026-06-24", contest="NV", n=550),
    ]
    upsert(con, "polls", polls, keys=["poll_id"])
    upsert(con, "primary_polls", [
        dict(poll_id="d1", party="D", pollster="YouGov", start_date="2026-10-20", end_date="2026-10-22", sample_size=800, population="RV",
             shares=json.dumps({"Kamala Harris": 25, "Gavin Newsom": 20, "Pete Buttigieg": 10}), source="t"),
        dict(poll_id="r1", party="R", pollster="YouGov", start_date="2026-10-20", end_date="2026-10-22", sample_size=800, population="RV",
             shares=json.dumps({"JD Vance": 40, "Marco Rubio": 20}), source="t"),
    ], keys=["poll_id"])
    upsert(con, "candidates", [
        dict(party="D", name="Kamala Harris", status="potential", home_state="CA", experience=None, announced=None, source="t", updated_at="x"),
        dict(party="D", name="Gavin Newsom", status="potential", home_state="CA", experience=None, announced=None, source="t", updated_at="x"),
        dict(party="D", name="Pete Buttigieg", status="potential", home_state="MI", experience=None, announced=None, source="t", updated_at="x"),
        dict(party="R", name="JD Vance", status="potential", home_state="OH", experience=None, announced=None, source="t", updated_at="x"),
        dict(party="R", name="Marco Rubio", status="potential", home_state="FL", experience=None, announced=None, source="t", updated_at="x"),
        dict(party="R", name="Royce White", status="declared", home_state="MN", experience=None, announced=None, source="t", updated_at="x"),
    ], keys=["party", "name"])
    upsert(con, "approval", [dict(source="Average", as_of="2026-11-01", approve=37.0, disapprove=60.0, net=-23.0)], keys=["source", "as_of"])
    upsert(con, "economy", [
        dict(series="unemployment", period="2026-09", value=4.2), dict(series="unemployment", period="2025-09", value=4.4),
        dict(series="cpi", period="2026-09", value=103.7), dict(series="cpi", period="2025-09", value=100.0),
        dict(series="real_wages", period="2026-09", value=11.2), dict(series="real_wages", period="2025-09", value=11.3),
    ], keys=["series", "period"])
    con.commit()
    yield con
    con.close()
