"""SQLite storage for the 2028 presidential model. One file, plain tables, no ORM."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterable

from .config import DATA_DIR, DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS polls (            -- general-election trial heats (named matchups)
    poll_id TEXT PRIMARY KEY,
    scope TEXT NOT NULL,                      -- national | state
    contest_id TEXT,                          -- state polls only (PA, ME-2, ...)
    pollster TEXT, sponsor_lean TEXT,
    start_date TEXT, end_date TEXT,
    sample_size INTEGER, population TEXT,
    dem_name TEXT, rep_name TEXT,
    dem_pct REAL, rep_pct REAL, other_pct REAL, und_pct REAL,
    matchup TEXT,                             -- json [[name, party, pct], ...] incl. third candidates
    source TEXT
);
CREATE INDEX IF NOT EXISTS polls_scope ON polls(scope, end_date);
CREATE TABLE IF NOT EXISTS primary_polls (
    poll_id TEXT PRIMARY KEY,
    party TEXT NOT NULL,                      -- D | R
    pollster TEXT, start_date TEXT, end_date TEXT, sample_size INTEGER, population TEXT,
    shares TEXT NOT NULL,                     -- json {candidate: pct}
    source TEXT
);
CREATE TABLE IF NOT EXISTS primary_averages (
    party TEXT NOT NULL, source TEXT NOT NULL, as_of TEXT,
    shares TEXT NOT NULL,
    PRIMARY KEY (party, source)
);
CREATE TABLE IF NOT EXISTS candidates (
    party TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT,                              -- declared | exploratory | potential
    home_state TEXT,
    experience TEXT,
    announced TEXT,
    source TEXT,
    updated_at TEXT,
    PRIMARY KEY (party, name)
);
CREATE TABLE IF NOT EXISTS approval (
    source TEXT NOT NULL, as_of TEXT NOT NULL,
    approve REAL, disapprove REAL, net REAL,
    PRIMARY KEY (source, as_of)
);
CREATE TABLE IF NOT EXISTS economy (
    series TEXT NOT NULL, period TEXT NOT NULL,   -- period = YYYY-MM
    value REAL,
    PRIMARY KEY (series, period)
);
CREATE TABLE IF NOT EXISTS ratings (
    contest_id TEXT NOT NULL, rater TEXT NOT NULL,
    rating TEXT NOT NULL, party TEXT, level INTEGER, as_of TEXT,
    PRIMARY KEY (contest_id, rater)
);
CREATE TABLE IF NOT EXISTS markets (           -- context only, never a model input
    market_key TEXT PRIMARY KEY,
    kind TEXT NOT NULL,                       -- party | nominee_D | nominee_R | winner | state
    contest_id TEXT, outcome TEXT,
    p REAL, volume REAL, platform TEXT, title TEXT, url TEXT, fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS news (              -- context only
    topic TEXT NOT NULL,                      -- NATIONAL | D | R | candidate name | contest id
    url TEXT NOT NULL,
    title TEXT, source TEXT, published TEXT, fetched_at TEXT,
    PRIMARY KEY (topic, url)
);
CREATE TABLE IF NOT EXISTS money (
    name TEXT NOT NULL, party TEXT, candidate_id TEXT,
    receipts REAL, disbursements REAL, cash REAL, coverage_end TEXT, source TEXT,
    PRIMARY KEY (name)
);
CREATE TABLE IF NOT EXISTS model_specs (       -- every revision of the model, newest = highest version
    version INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    run_date TEXT NOT NULL,
    origin TEXT NOT NULL,                     -- seed | calibration | revision
    title TEXT,
    summary TEXT,
    spec TEXT NOT NULL,                       -- json (see model/spec.py)
    changes TEXT,                             -- json [{path, from, to, reason}]
    input_hash TEXT
);
CREATE TABLE IF NOT EXISTS forecasts (
    run_date TEXT NOT NULL,
    contest_id TEXT NOT NULL,
    p_dem REAL, margin REAL, sd REAL,
    detail TEXT,
    PRIMARY KEY (run_date, contest_id)
);
CREATE TABLE IF NOT EXISTS national_forecasts (
    run_date TEXT PRIMARY KEY,
    spec_version INTEGER,
    p_dem REAL, dem_ev_mean REAL, pv_margin REAL,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS narratives (
    key TEXT PRIMARY KEY,                     -- NATIONAL or a contest id
    input_hash TEXT NOT NULL, body TEXT NOT NULL, model TEXT, generated_at TEXT
);
CREATE TABLE IF NOT EXISTS runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    stage TEXT, started_at TEXT, finished_at TEXT, ok INTEGER, note TEXT
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect(path=DB_PATH) -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=60)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    return con


@contextmanager
def tx(con: sqlite3.Connection):
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise


def upsert(con: sqlite3.Connection, table: str, rows: Iterable[dict[str, Any]], keys: list[str] | None = None) -> int:
    rows = list(rows)
    if not rows:
        return 0
    cols = list(rows[0].keys())
    placeholders = ",".join("?" for _ in cols)
    if keys:
        updates = ",".join(f"{c}=excluded.{c}" for c in cols if c not in keys) or f"{keys[0]}=excluded.{keys[0]}"
        sql = f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders}) ON CONFLICT({','.join(keys)}) DO UPDATE SET {updates}"
    else:
        sql = f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({placeholders})"
    con.executemany(sql, [tuple(_j(r.get(c)) for c in cols) for r in rows])
    return len(rows)


def _j(v):
    if isinstance(v, (dict, list)):
        return json.dumps(v)
    return v


def rows(con: sqlite3.Connection, sql: str, params=()) -> list[dict]:
    return [dict(r) for r in con.execute(sql, params).fetchall()]


def log_run(con, stage: str, started: str, ok: bool, note: str = ""):
    con.execute(
        "INSERT INTO runs (stage, started_at, finished_at, ok, note) VALUES (?,?,?,?,?)",
        (stage, started, now_iso(), int(ok), note[:2000]),
    )
    con.commit()
