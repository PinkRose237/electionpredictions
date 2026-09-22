"""SQLite storage. One file, a handful of tables, no ORM."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterable

from .config import DB_PATH, DATA_DIR

SCHEMA = """
CREATE TABLE IF NOT EXISTS races (
    race_id TEXT PRIMARY KEY,
    chamber TEXT NOT NULL,             -- house | senate | governor
    state TEXT NOT NULL,
    district INTEGER,                  -- house only (0 = at-large)
    special INTEGER NOT NULL DEFAULT 0,
    name TEXT NOT NULL,
    incumbent TEXT,
    incumbent_party TEXT,
    incumbent_running INTEGER,         -- 1 if the incumbent is on the general ballot
    holder_party TEXT,                 -- party currently holding the seat
    pvi REAL,                          -- D-positive margin
    last_result TEXT,
    status TEXT,
    wiki_title TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS candidates (
    race_id TEXT NOT NULL,
    name TEXT NOT NULL,
    party TEXT NOT NULL,
    is_incumbent INTEGER NOT NULL DEFAULT 0,
    major INTEGER NOT NULL DEFAULT 0,  -- 1 for the D-side / R-side principal candidate
    fec_id TEXT,
    receipts REAL, disbursements REAL, cash_on_hand REAL, coverage_end TEXT,
    money_source TEXT,
    PRIMARY KEY (race_id, name)
);
CREATE TABLE IF NOT EXISTS ratings (
    race_id TEXT NOT NULL,
    rater TEXT NOT NULL,
    rating TEXT NOT NULL,
    party TEXT, level INTEGER, flip INTEGER,
    as_of TEXT,
    PRIMARY KEY (race_id, rater)
);
CREATE TABLE IF NOT EXISTS polls (
    poll_id TEXT PRIMARY KEY,
    race_id TEXT NOT NULL,
    pollster TEXT, sponsor_lean TEXT,
    start_date TEXT, end_date TEXT,
    sample_size INTEGER, population TEXT, moe REAL,
    dem_name TEXT, rep_name TEXT,
    dem_pct REAL, rep_pct REAL, other_pct REAL, und_pct REAL,
    matchup TEXT,                      -- json list of [name, party, pct]
    hypothetical INTEGER NOT NULL DEFAULT 0,
    source TEXT
);
CREATE INDEX IF NOT EXISTS polls_race ON polls(race_id, end_date);
CREATE TABLE IF NOT EXISTS poll_aggregates (
    race_id TEXT NOT NULL,
    source TEXT NOT NULL,
    as_of TEXT,
    dem REAL, rep REAL, margin REAL,
    PRIMARY KEY (race_id, source)
);
CREATE TABLE IF NOT EXISTS generic_ballot (
    source TEXT NOT NULL,
    as_of TEXT NOT NULL,
    dem REAL, rep REAL, margin REAL,
    PRIMARY KEY (source, as_of)
);
CREATE TABLE IF NOT EXISTS markets (
    race_id TEXT NOT NULL,
    platform TEXT NOT NULL,            -- polymarket | predictit | kalshi
    market_key TEXT NOT NULL,
    title TEXT,
    p_dem REAL, p_rep REAL, p_other REAL,
    volume REAL,
    fetched_at TEXT,
    url TEXT,
    PRIMARY KEY (race_id, platform, market_key)
);
CREATE TABLE IF NOT EXISTS news (
    race_id TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT, source TEXT, published TEXT,
    fetched_at TEXT,
    PRIMARY KEY (race_id, url)
);
CREATE TABLE IF NOT EXISTS forecasts (
    run_date TEXT NOT NULL,
    race_id TEXT NOT NULL,
    p_dem REAL, margin REAL, sd REAL,
    poll_margin REAL, n_polls INTEGER, fund_margin REAL, rating_margin REAL,
    detail TEXT,                       -- json blob with model components
    PRIMARY KEY (run_date, race_id)
);
CREATE TABLE IF NOT EXISTS chamber_forecasts (
    run_date TEXT NOT NULL,
    chamber TEXT NOT NULL,
    p_dem REAL, dem_seats_mean REAL, dem_seats_p10 REAL, dem_seats_p90 REAL,
    detail TEXT,
    PRIMARY KEY (run_date, chamber)
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
    con.execute("PRAGMA foreign_keys=ON")
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
        updates = ",".join(f"{c}=excluded.{c}" for c in cols if c not in keys)
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
