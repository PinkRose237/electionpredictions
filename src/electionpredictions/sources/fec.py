"""Candidate fundraising from the FEC.

Primary source: the FEC bulk 'All candidates' summary file (weballYY.zip), one download and no API key.
Fallback: the candidates/totals API endpoint (needs FEC_API_KEY; DEMO_KEY is limited to ~10 requests/hour).
"""
from __future__ import annotations

import io
import json
import re
import time
import unicodedata
import zipfile
from datetime import datetime
from typing import Optional

import requests

from ..config import CACHE_DIR, CYCLE, FEC_API_KEY, STATES, TTL_FEC, USER_AGENT
from ..db import log_run, now_iso, rows
from .http import get

BASE = "https://api.open.fec.gov/v1"
BULK_URL = f"https://www.fec.gov/files/bulk-downloads/{CYCLE}/weball{str(CYCLE)[2:]}.zip"
BULK_COLS = ["CAND_ID", "CAND_NAME", "CAND_ICI", "PTY_CD", "CAND_PTY_AFFILIATION", "TTL_RECEIPTS", "TRANS_FROM_AUTH",
             "TTL_DISB", "TRANS_TO_AUTH", "COH_BOP", "COH_COP", "CAND_CONTRIB", "CAND_LOANS", "OTHER_LOANS",
             "CAND_LOAN_REPAY", "OTHER_LOAN_REPAY", "DEBTS_OWED_BY", "TTL_INDIV_CONTRIB", "CAND_OFFICE_ST",
             "CAND_OFFICE_DISTRICT", "SPEC_ELECTION", "PRIM_ELECTION", "RUN_ELECTION", "GEN_ELECTION",
             "GEN_ELECTION_PRECENT", "OTHER_POL_CMTE_CONTRIB", "POL_PTY_CONTRIB", "CVG_END_DT", "INDIV_REFUNDS", "CMTE_REFUNDS"]
PARTY_MAP = {"DEM": "D", "DFL": "D", "REP": "R", "IND": "I", "NPA": "I", "NNE": "I", "UNK": "?", "LIB": "L", "GRE": "G"}


def _ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().upper()


def fetch_bulk() -> list[dict]:
    """Download (cached) and parse the all-candidates summary file into API-shaped rows."""
    d = CACHE_DIR / "fec"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"weball{str(CYCLE)[2:]}.zip"
    if not p.exists() or (time.time() - p.stat().st_mtime) > TTL_FEC:
        r = requests.get(BULK_URL, headers={"User-Agent": USER_AGENT}, timeout=120)
        r.raise_for_status()
        p.write_bytes(r.content)
    out = []
    with zipfile.ZipFile(io.BytesIO(p.read_bytes())) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(".txt"))
        for line in z.read(name).decode("latin-1").splitlines():
            parts = line.split("|")
            if len(parts) < len(BULK_COLS):
                continue
            rec = dict(zip(BULK_COLS, parts))
            cid = rec["CAND_ID"]
            cvg = rec.get("CVG_END_DT") or ""
            try:
                cvg_iso = datetime.strptime(cvg, "%m/%d/%Y").date().isoformat() if cvg else None
            except ValueError:
                cvg_iso = None
            out.append(dict(
                candidate_id=cid, name=rec["CAND_NAME"], party=rec["CAND_PTY_AFFILIATION"],
                office=cid[:1], state=rec["CAND_OFFICE_ST"], district=rec["CAND_OFFICE_DISTRICT"] or "00",
                incumbent_challenge=rec["CAND_ICI"],
                receipts=_f(rec["TTL_RECEIPTS"]), disbursements=_f(rec["TTL_DISB"]),
                cash_on_hand_end_period=_f(rec["COH_COP"]), coverage_end_date=cvg_iso,
            ))
    return out


def _f(s) -> Optional[float]:
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def fetch_totals_api(office: str, state: Optional[str] = None, max_pages: int = 10) -> list[dict]:
    out, page = [], 1
    while page <= max_pages:
        params = dict(api_key=FEC_API_KEY, cycle=CYCLE, election_year=CYCLE, office=office, per_page=100, page=page,
                      is_active_candidate="true", election_full="false", sort="-receipts")
        if state:
            params["state"] = state
        d = get(f"{BASE}/candidates/totals/", params, kind="fec", ttl=TTL_FEC, retries=1)
        if not d:
            break
        out.extend(d.get("results", []))
        if page >= d.get("pagination", {}).get("pages", 1):
            break
        page += 1
    return out


def _fec_last(name: str) -> str:
    return _ascii(name.split(",")[0]).strip()


def _wiki_last(name: str) -> str:
    n = re.sub(r"\s+(Jr\.?|Sr\.?|II|III|IV)$", "", name.strip())
    return _ascii(n.split()[-1]) if n else ""


def _match(cand: dict, fec_rows: list[dict]) -> Optional[dict]:
    wl = _wiki_last(cand["name"])
    wfull = _ascii(cand["name"])
    if not wl:
        return None
    hits = []
    for f in fec_rows:
        fl = _fec_last(f["name"])
        fl_tokens = re.split(r"[\s\-]+", fl)
        if not (fl == wl or fl_tokens[-1] == wl or wl in fl_tokens):
            continue
        fp = PARTY_MAP.get(f.get("party") or "", "O")
        if cand["party"] in ("D", "R") and fp in ("D", "R") and fp != cand["party"]:
            continue
        hits.append(f)
    if not hits:
        # fallback: surname appears anywhere in the FEC name (e.g. 'ARENHOLZ, ASHLEY HINSON' for Ashley Hinson)
        loose = []
        for f in fec_rows:
            toks = re.split(r"[\s,\-]+", _ascii(f["name"]))
            fp = PARTY_MAP.get(f.get("party") or "", "O")
            if wl in toks and not (cand["party"] in ("D", "R") and fp in ("D", "R") and fp != cand["party"]):
                loose.append(f)
        if len(loose) == 1:
            return loose[0]
        return None
    first = wfull.split()[0][:1] if wfull else ""
    hits.sort(key=lambda f: (_ascii(f["name"].split(",")[-1]).strip()[:1] == first, f.get("receipts") or 0), reverse=True)
    return hits[0]


def load(con, verbose=True, use_api_fallback=False) -> dict:
    started = now_iso()
    stats = {"source": "bulk", "fec_rows": 0, "matched": 0, "unmatched_major": 0}
    try:
        allrows = fetch_bulk()
    except Exception as e:  # noqa: BLE001
        print(f"  ! FEC bulk download failed: {e}")
        allrows = []
        if use_api_fallback:
            stats["source"] = "api"
            allrows = fetch_totals_api("S") + [r for st in STATES for r in fetch_totals_api("H", st)]
    stats["fec_rows"] = len(allrows)
    by_key: dict[tuple, list[dict]] = {}
    for f in allrows:
        if f["office"] not in ("S", "H"):
            continue
        by_key.setdefault((f["office"], f["state"], f["district"] if f["office"] == "H" else "00"), []).append(f)
    unmatched = []
    races = rows(con, "SELECT * FROM races WHERE chamber IN ('senate','house')")
    for race in races:
        key = ("S", race["state"], "00") if race["chamber"] == "senate" else ("H", race["state"], f"{race['district']:02d}")
        pool = by_key.get(key, [])
        for c in rows(con, "SELECT * FROM candidates WHERE race_id=?", (race["race_id"],)):
            f = _match(c, pool)
            if f is None:
                if c["major"]:
                    unmatched.append(f"{race['race_id']}:{c['name']}")
                continue
            stats["matched"] += 1
            con.execute(
                "UPDATE candidates SET fec_id=?, receipts=?, disbursements=?, cash_on_hand=?, coverage_end=? WHERE race_id=? AND name=?",
                (f.get("candidate_id"), f.get("receipts"), f.get("disbursements"), f.get("cash_on_hand_end_period"),
                 f.get("coverage_end_date"), race["race_id"], c["name"]),
            )
    con.commit()
    stats["majors_repicked"] = refresh_majors(con)
    stats["unmatched_major"] = len(unmatched)
    if verbose:
        print(f"  FEC ({stats['source']}): {stats['fec_rows']} rows; matched {stats['matched']} candidates; {len(unmatched)} major candidates unmatched, e.g. {unmatched[:20]}")
    log_run(con, "fec", started, True, json.dumps(stats))
    return stats


def refresh_majors(con) -> int:
    """Where several same-party candidates are listed and none is the incumbent, make the top
    fundraiser the principal candidate (e.g. states whose nominee is not yet marked on Wikipedia)."""
    changed = 0
    for race in rows(con, "SELECT race_id FROM races"):
        cands = rows(con, "SELECT * FROM candidates WHERE race_id=?", (race["race_id"],))
        for party in ("D", "R"):
            same = [c for c in cands if c["party"] == party]
            if len(same) < 2 or any(c["is_incumbent"] for c in same):
                continue
            with_money = [c for c in same if c["receipts"]]
            if not with_money:
                continue
            top = max(with_money, key=lambda c: c["receipts"])
            cur = [c for c in same if c["major"]]
            if cur and cur[0]["name"] == top["name"]:
                continue
            for c in same:
                con.execute("UPDATE candidates SET major=? WHERE race_id=? AND name=?", (int(c["name"] == top["name"]), race["race_id"], c["name"]))
            changed += 1
    con.commit()
    return changed
