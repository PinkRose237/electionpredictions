"""Versioned storage of model specs (table model_specs)."""
from __future__ import annotations

import json
from datetime import date
from typing import Optional

from ..db import now_iso, rows
from .spec import diff, fingerprint, seed


def latest(con) -> tuple[Optional[int], dict, str]:
    r = rows(con, "SELECT version, spec, origin FROM model_specs ORDER BY version DESC LIMIT 1")
    if not r:
        return None, seed(), "seed"
    return r[0]["version"], json.loads(r[0]["spec"]), r[0]["origin"]


def history(con, limit: int = 400) -> list[dict]:
    out = []
    for r in rows(con, "SELECT * FROM model_specs ORDER BY version DESC LIMIT ?", (limit,)):
        out.append(dict(version=r["version"], created_at=r["created_at"], run_date=r["run_date"], origin=r["origin"],
                        title=r["title"], summary=r["summary"], changes=json.loads(r["changes"] or "[]")))
    return out


def ensure_seed(con) -> int:
    v, _, _ = latest(con)
    if v is not None:
        return v
    return save(con, None, seed(), "seed", "Initial model", "The starting specification, before any evidence is applied.", [], date.today())


def save(con, prev: Optional[dict], new: dict, origin: str, title: str, summary: str, reasons: dict | list,
         run_date: date, input_hash: str | None = None) -> int:
    """Store `new` as the next version; `reasons` maps change paths (or prefixes) to a sentence."""
    changes = diff(prev, new)
    rmap = reasons if isinstance(reasons, dict) else {}
    for c in changes:
        c["reason"] = _reason_for(c["path"], rmap)
    cur = con.execute("INSERT INTO model_specs (created_at, run_date, origin, title, summary, spec, changes, input_hash) VALUES (?,?,?,?,?,?,?,?)",
                      (now_iso(), run_date.isoformat(), origin, title, summary, json.dumps(new), json.dumps(changes), input_hash))
    con.commit()
    return int(cur.lastrowid)


def _reason_for(path: str, rmap: dict) -> Optional[str]:
    best = None
    for k, v in rmap.items():
        if path == k or path.startswith(k + "."):
            if best is None or len(k) > len(best[0]):
                best = (k, v)
    return best[1] if best else None


def changed(prev: dict, new: dict) -> bool:
    return fingerprint(prev) != fingerprint(new)
