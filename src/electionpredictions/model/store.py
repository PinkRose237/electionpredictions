"""Versioned storage of model specs (table model_specs).

Each version stores the specification, a changelog, and its *basis*: the evidence-derived quantities
(poll-implied nomination odds, polling strengths) it was built on. Calibration later moves the spec by how much
that evidence has changed since (see calibrate.py), so judgments made in a revision persist until new evidence
arrives instead of being pulled back toward the polls on every run."""
from __future__ import annotations

import json
from datetime import date
from typing import Optional

from ..db import now_iso, rows
from .spec import BOUNDS, OTHER, diff, seed, upgrade

# What counts as a change worth a new version (smaller moves are noise between frequent updates).
MIN_P = 0.005          # nomination odds
MIN_EFFECT = 0.1       # candidate strength, points
MIN_ADJ = 0.1          # state adjustment, points
MIN_PARAM_FRAC = 0.01  # other settings: share of their allowed range


def latest(con) -> tuple[Optional[int], dict, str]:
    r = rows(con, "SELECT version, spec, origin FROM model_specs WHERE spec <> '{}' ORDER BY version DESC LIMIT 1")
    if not r:
        return None, seed(), "seed"
    return r[0]["version"], upgrade(json.loads(r[0]["spec"])), r[0]["origin"]


def latest_basis(con) -> Optional[dict]:
    r = rows(con, "SELECT basis FROM model_specs WHERE spec <> '{}' ORDER BY version DESC LIMIT 1")
    return json.loads(r[0]["basis"]) if r and r[0]["basis"] else None


def history(con, limit: int = 400) -> list[dict]:
    out = []
    for r in rows(con, "SELECT * FROM model_specs ORDER BY version DESC LIMIT ?", (limit,)):
        out.append(dict(version=r["version"], created_at=r["created_at"], run_date=r["run_date"], origin=r["origin"],
                        title=r["title"], summary=r["summary"], changes=json.loads(r["changes"] or "[]"), model=r.get("model")))
    return out


def count(con) -> int:
    return rows(con, "SELECT count(*) n FROM model_specs")[0]["n"]


def ensure_seed(con) -> int:
    v, _, _ = latest(con)
    if v is not None:
        return v
    return save(con, None, seed(), "seed", "Initial model", "The starting specification, before any evidence is applied.", [], date.today())


def save(con, prev: Optional[dict], new: dict, origin: str, title: str, summary: str, reasons: dict | list,
         run_date: date, input_hash: str | None = None, basis: Optional[dict] = None, model: Optional[str] = None) -> int:
    """Store `new` as the next version; `reasons` maps change paths (or prefixes) to a sentence."""
    changes = significant_changes(prev, new) if prev else diff(prev, new)
    rmap = reasons if isinstance(reasons, dict) else {}
    for c in changes:
        c["reason"] = _reason_for(c["path"], rmap)
    cur = con.execute("INSERT INTO model_specs (created_at, run_date, origin, title, summary, spec, changes, input_hash, basis, model) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (now_iso(), run_date.isoformat(), origin, title, summary, json.dumps(new), json.dumps(changes), input_hash,
                       json.dumps(basis) if basis is not None else None, model))
    con.commit()
    return int(cur.lastrowid)


def _reason_for(path: str, rmap: dict) -> Optional[str]:
    best = None
    for k, v in rmap.items():
        if path == k or path.startswith(k + "."):
            if best is None or len(k) > len(best[0]):
                best = (k, v)
    return best[1] if best else None


def significant_changes(prev: Optional[dict], new: dict) -> list[dict]:
    """The diff, keeping only changes large enough to matter (and any added/removed name or home state)."""
    out = []
    for c in diff(prev, new):
        path, a, b = c["path"], c["from"], c["to"]
        if a is None or b is None:
            if (a or 0) >= MIN_P or (b or 0) >= MIN_P or not path.endswith(".p"):
                out.append(c)
            continue
        if path.endswith(".p"):
            keep = abs(a - b) >= MIN_P
        elif path.endswith(".effect"):
            keep = abs(a - b) >= MIN_EFFECT
        elif path.startswith("state_adjustments."):
            keep = abs(a - b) >= MIN_ADJ
        elif path in BOUNDS:
            lo, hi, _ = BOUNDS[path]
            keep = abs(a - b) >= MIN_PARAM_FRAC * (hi - lo)
        else:
            keep = True
        if keep:
            out.append(c)
    if prev:
        homes = lambda s: {(p, c["name"]): c.get("home_state") for p in ("D", "R") for c in s["nominees"][p] if c["name"] != OTHER}  # noqa: E731
        ha, hb = homes(prev), homes(new)
        for k in ha.keys() & hb.keys():
            if ha[k] != hb[k]:
                out.append({"path": f"nominees.{k[0]}.{k[1]}.home_state", "from": ha[k], "to": hb[k]})
    return out


def changed(prev: dict, new: dict) -> bool:
    return bool(significant_changes(upgrade(prev), upgrade(new)))
