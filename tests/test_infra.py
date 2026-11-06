"""Database migrations and pruning, and the 2026 midterm reader."""
import json
import sqlite3

from electionpredictions import db as dbmod
from electionpredictions.sources import midterm2026


def test_migration_adds_columns_to_an_old_database(tmp_path):
    p = tmp_path / "old.db"
    con = sqlite3.connect(p)
    con.executescript("CREATE TABLE model_specs (version INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, run_date TEXT NOT NULL, "
                      "origin TEXT NOT NULL, title TEXT, summary TEXT, spec TEXT NOT NULL, changes TEXT, input_hash TEXT);"
                      "CREATE TABLE polls (poll_id TEXT PRIMARY KEY, scope TEXT NOT NULL, end_date TEXT);")
    con.close()
    con = dbmod.connect(p)
    cols = {r[1] for r in con.execute("PRAGMA table_info(model_specs)")}
    assert {"basis", "model"} <= cols and "first_seen" in {r[1] for r in con.execute("PRAGMA table_info(polls)")}
    assert {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")} >= {"run_log", "storylines", "research"}


def test_prune_keeps_recent_and_changelogs(tmp_path):
    con = dbmod.connect(tmp_path / "p.db")
    con.execute("INSERT INTO runs (stage, started_at, finished_at, ok, note) VALUES ('x', '2020-01-01', '2020-01-01T00:00:00+00:00', 1, '')")
    con.execute("INSERT INTO runs (stage, started_at, finished_at, ok, note) VALUES ('y', datetime('now'), datetime('now'), 1, '')")
    for i in range(505):
        con.execute("INSERT INTO model_specs (created_at, run_date, origin, title, summary, spec, changes) VALUES ('t','d','revision','v','s','{\"a\":1}','[]')")
    con.commit()
    out = dbmod.prune(con)
    assert out["runs"] == 1 and out["spec_bodies"] == 5
    assert con.execute("SELECT count(*) FROM model_specs").fetchone()[0] == 505      # every changelog stays
    assert con.execute("SELECT count(*) FROM model_specs WHERE spec <> '{}'").fetchone()[0] == 500


def test_midterm_summary(tmp_path, monkeypatch):
    races = {"PA-01": dict(status="called", winner="dem", votes=dict(dem=600, rep=400, other=0)),
             "PA-02": dict(status="called", winner="rep", votes=dict(dem=300, rep=700, other=0)),
             "PA-SEN": dict(status="called", winner="dem", reporting=99, votes=dict(dem=550, rep=450, other=0)),
             "GA-GOV": dict(status="counting", winner=None, reporting=80, votes=dict(dem=500, rep=480, other=20))}
    (tmp_path / "results-auto.json").write_text(json.dumps(dict(updated_at="2026-11-05T00:00:00Z", races=races)))
    monkeypatch.setattr(midterm2026, "ARCHIVE_2026_DATA_DIR", tmp_path)
    s = midterm2026.summary()
    assert s["house_vote"]["margin"] == -10.0 and s["seats"]["house"] == {"D": 1, "R": 1, "counting": 0}
    assert s["statewide"]["PA"]["senate"]["margin"] == 10.0 and s["statewide"]["PA"]["senate"]["vs_national_house"] == 20.0
    assert s["seats"]["governor"]["counting"] == 1


def test_hourly_caches_expire_on_the_hour_eastern():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from electionpredictions.config import cache_fresh

    et = ZoneInfo("America/New_York")
    ts = lambda h, m: datetime(2026, 11, 6, h, m, tzinfo=et).timestamp()   # noqa: E731
    assert cache_fresh(ts(13, 1), 3600, now=ts(13, 59))          # fetched 1:01 PM, still fresh at 1:59 PM
    assert not cache_fresh(ts(13, 59), 3600, now=ts(14, 0))      # fetched 1:59 PM, stale at 2:00 PM on the dot
    assert cache_fresh(ts(14, 0), 3600, now=ts(14, 45))
    # rolling lifetimes are unchanged
    assert cache_fresh(ts(13, 0), 12 * 3600, now=ts(23, 0)) and not cache_fresh(ts(1, 0), 12 * 3600, now=ts(14, 0))
