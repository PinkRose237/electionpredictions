"""Race calls from several news organisations, side by side (site/data/calls.json, the Race Calls page).

Each outlet's own results feed is read and every call is mapped onto our races and our Democratic /
Republican sides (same matching as live_results.py, so an independent standing in for a party lands on
that side). Senate, House and governor races.

Sources, with AllSides Media Bias Ratings (online news; checked 2026-11-03) and who makes the calls:
  CNN          Lean Left   CNN Decision Desk          politics.api.cnn.io national-races JSON
  NBC News     Lean Left   NBC News Decision Desk     nbcnews.com firecracker national-results JSON
  Bloomberg    Center      AP (its `network` column)  bloomberg.com election-data calls.tsv + candidates.tsv
  AP (wire)    Lean Left   AP                         The New York Times' results JSON, which carries AP calls
All are public, undocumented endpoints the outlets use for their own pages; any of them can change.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import requests

from ..config import ARCHIVE_2026_DATA_DIR as SITE_DATA_DIR, USER_AGENT
from . import live_results as lr

CALLS_PATH = SITE_DATA_DIR / "calls.json"
ALLSIDES = "https://www.allsides.com/media-bias/ratings"

SOURCES = [
    dict(id="cnn", name="CNN", lean="Lean Left", desk="CNN Decision Desk",
         url="https://www.cnn.com/election/2026/results", rating_url="https://www.allsides.com/news-sources/cnn-media-bias"),
    dict(id="nbc", name="NBC News", lean="Lean Left", desk="NBC News Decision Desk",
         url="https://www.nbcnews.com/politics/2026-elections/senate-results", rating_url="https://www.allsides.com/news-sources/nbc-news-media-bias"),
    dict(id="bloomberg", name="Bloomberg", lean="Center", desk="AP (as published by Bloomberg)",
         url="https://www.bloomberg.com/graphics/2026-us-election-results/", rating_url="https://www.allsides.com/news-sources/bloomberg-media-bias"),
    dict(id="ap", name="AP", lean="Lean Left", desk="The Associated Press (wire; via The New York Times)", wire=True,
         url="https://www.nytimes.com/interactive/2026/11/03/us/elections/results-senate.html", rating_url="https://www.allsides.com/news-sources/associated-press-media-bias"),
]

FIPS = {"01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO", "09": "CT", "10": "DE", "12": "FL",
        "13": "GA", "15": "HI", "16": "ID", "17": "IL", "18": "IN", "19": "IA", "20": "KS", "21": "KY", "22": "LA",
        "23": "ME", "24": "MD", "25": "MA", "26": "MI", "27": "MN", "28": "MS", "29": "MO", "30": "MT", "31": "NE",
        "32": "NV", "33": "NH", "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND", "39": "OH", "40": "OK",
        "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD", "47": "TN", "48": "TX", "49": "UT", "50": "VT",
        "51": "VA", "53": "WA", "54": "WV", "55": "WI", "56": "WY"}
PARTY = {"D": "DEM", "DEM": "DEM", "Dem": "DEM", "R": "REP", "REP": "REP", "Rep": "REP", "GOP": "REP"}

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json, text/plain, */*"})


def _get(url: str, *, text: bool = False):
    r = _session.get(url, timeout=60)
    r.raise_for_status()
    return r.text if text else r.json()


class Collector:
    """Accumulates one source's calls: feed race -> our race_id -> {winner, status, at}."""

    def __init__(self, by_id: dict, resolve: Callable):
        self.by_id, self.resolve = by_id, resolve
        self.calls: dict[str, dict] = {}
        self.seen: set[str] = set()

    def add(self, st, chamber, district, special, cands: list[dict], at=None):
        rid = self.resolve(st, chamber, district, special)
        if not rid or rid in self.seen:  # first listing wins (NBC lists FL/OH specials twice)
            return
        self.seen.add(rid)
        won = [i for i, c in enumerate(cands) if c.get("winner")]
        runoff = any(c.get("runoff") for c in cands)
        e = lr.entry_from(self.by_id[rid], cands, winner_idx=won, runoff=runoff)
        if e["status"] in ("called", "final", "runoff"):
            self.calls[rid] = {"winner": e["winner"], "status": e["status"], "at": at}


# --- CNN -------------------------------------------------------------------------------------------
def fetch_cnn(col: Collector, errors: list):
    chamber_of = {"S": "senate", "H": "house", "G": "governor"}
    for code in ("SG", "HG", "GG"):
        try:
            data = _get(lr.CNN_URL.format(code=code))
        except (requests.RequestException, ValueError) as e:
            errors.append(f"{code}: {e}")
            continue
        for r in data or []:
            if r.get("contestType") == "HQ":
                continue
            chamber = chamber_of.get(r.get("raceType"))
            district = str(r.get("ecKey") or "").split("-")[-1] if chamber == "house" else None
            cands = [dict(first=c.get("firstName") or "", last=c.get("lastName") or "", party=c.get("majorParty") or "",
                          votes=c.get("voteNum") or 0, winner=bool(c.get("winner")), runoff=bool(c.get("runoffCandidate")))
                     for c in r.get("candidates") or []]
            col.add(r.get("stateAbbreviation"), chamber, district, r.get("contestType") == "SP", cands)


# --- NBC -------------------------------------------------------------------------------------------
NBC_URL = "https://www.nbcnews.com/firecracker/api/v2/national-results/2026-elections/{office}-results"


def fetch_nbc(col: Collector, errors: list):
    for office, chamber in (("senate", "senate"), ("house", "house"), ("governor", "governor")):
        try:
            data = _get(NBC_URL.format(office=office))
        except (requests.RequestException, ValueError) as e:
            errors.append(f"{office}: {e}")
            continue
        for key, v in (data.get("mapData") or {}).items():
            t = (v or {}).get("tooltip") if isinstance(v, dict) else None
            if not t or not t.get("candidates"):
                continue
            special = key.endswith("~P")
            key = key.split("~")[0]
            if chamber == "house":
                st, district = FIPS.get(key[:2]), key[2:]
            else:
                st, district = key, None
            if not st:
                continue
            cands = [dict(first=c.get("firstName") or "", last=c.get("lastName") or "", party=PARTY.get(c.get("party"), c.get("party") or ""),
                          votes=c.get("votes") or c.get("vote") or 0, winner=bool(c.get("isWinner")),
                          runoff=str(c.get("callStatus") or "").lower().startswith("runoff"))
                     for c in t["candidates"]]
            col.add(st, chamber, district, special, cands)


# --- Bloomberg -------------------------------------------------------------------------------------
BBG_CANDS = "https://www.bloomberg.com/graphics/2026-us-election-results/api/election/2026/candidates.tsv"
BBG_CALLS = "https://www.bloomberg.com/bbg-gfx/election-data/usa/2026-11-03/calls.tsv"


def _bbg_race(key: str):
    """'SGA' / 'HCA12' / 'GAZ' -> (state, chamber, district)."""
    kind, st, rest = key[:1], key[1:3], key[3:]
    chamber = {"S": "senate", "H": "house", "G": "governor"}.get(kind)
    return st, chamber, (rest or None)


BBG_EPOCH = datetime(2026, 11, 3, tzinfo=timezone.utc)


def _bbg_time(v: float) -> str:
    """Bloomberg's callDateTime_epoch counts seconds from midnight UTC on election day (86400 = 7 pm ET)."""
    if v > 1e12:          # milliseconds since 1970, should they switch
        t = datetime.fromtimestamp(v / 1000, timezone.utc)
    elif v > 1e9:         # seconds since 1970
        t = datetime.fromtimestamp(v, timezone.utc)
    else:
        t = BBG_EPOCH + timedelta(seconds=v)
    return t.isoformat(timespec="seconds")


def _bbg_runoff(row) -> bool:
    return (row.get("callType") or "").strip().lower() in ("r", "runoff")


def fetch_bloomberg(col: Collector, errors: list):
    try:
        cand_rows = list(csv.DictReader(io.StringIO(_get(BBG_CANDS, text=True)), delimiter="\t"))
        call_text = _get(BBG_CALLS, text=True)
    except requests.RequestException as e:
        errors.append(str(e))
        return
    races: dict[str, list[dict]] = {}
    current = ""
    for row in cand_rows:  # the race key is only on a race's first candidate row
        current = row.get("raceKey") or current
        races.setdefault(current, []).append(row)
    calls = {}
    for row in csv.DictReader(io.StringIO(call_text), delimiter="\t"):
        calls.setdefault(row.get("raceKey"), []).append(row)
    for key, rows in races.items():
        st, chamber, district = _bbg_race(key)
        if not chamber:
            continue
        mine = calls.get(key, [])
        winners = {c.get("winnerCandidateID") for c in mine if not _bbg_runoff(c)}
        runoffs = {c.get("winnerCandidateID") for c in mine if _bbg_runoff(c)}
        cands = [dict(first=r.get("first") or "", last=r.get("last") or "", party=PARTY.get(r.get("partyCode"), r.get("partyCode") or ""),
                      votes=0, winner=r.get("candidateID") in winners, runoff=r.get("candidateID") in runoffs) for r in rows]
        at = None
        if mine and mine[0].get("callDateTime_epoch"):
            try:
                at = _bbg_time(float(mine[0]["callDateTime_epoch"]))
            except ValueError:
                at = None
        col.add(st, chamber, district, False, cands, at=at)  # the resolver falls back to the special when that's all a state has


# --- AP via the NYT --------------------------------------------------------------------------------
def fetch_ap(col: Collector, errors: list):
    chamber_of = {"S": "senate", "H": "house", "G": "governor"}
    for office in ("senate", "house", "governor"):
        try:
            data = _get(lr.NYT_URL.format(office=office))
        except (requests.RequestException, ValueError) as e:
            errors.append(f"{office}: {e}")
            continue
        for race in data.get("races") or []:
            ru = race.get("top_reporting_unit") or {}
            if ru.get("level") != "state":
                continue
            meta = race.get("candidate_metadata") or {}
            outcome = race.get("outcome") or {}
            won, runoff = set(outcome.get("won") or []), set(outcome.get("advanced_to_runoff") or [])
            cands = []
            for c in ru.get("candidates") or []:
                m = meta.get(c.get("nyt_id")) or {}
                p = (m.get("party") or {}).get("nyt_id") or ""
                cands.append(dict(first=m.get("first_name") or "", last=m.get("last_name") or "", party=PARTY.get(p, p),
                                  votes=(c.get("votes") or {}).get("total") or 0, winner=c.get("nyt_id") in won,
                                  runoff=c.get("nyt_id") in runoff))
            special = race.get("race_type_id") == "W" or "special" in (race.get("type") or "").lower()
            col.add(ru.get("state_postal"), chamber_of.get(race.get("office_id")), race.get("seat_number"), special, cands)


FETCHERS = {"cnn": fetch_cnn, "nbc": fetch_nbc, "bloomberg": fetch_bloomberg, "ap": fetch_ap}


def collect(races: list[dict]) -> dict:
    by_id = {r["race_id"]: r for r in races}
    resolve = lr.make_resolver(by_id)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    sources, merged = [], {}
    for s in SOURCES:
        col, errors = Collector(by_id, resolve), []
        try:
            FETCHERS[s["id"]](col, errors)
        except Exception as e:  # noqa: BLE001 - one broken feed must not sink the others
            errors.append(repr(e))
        for rid, call in col.calls.items():
            merged.setdefault(rid, {})[s["id"]] = call
        sources.append({**s, "races_seen": len(col.seen), "calls": len(col.calls), "ok": bool(col.seen),
                        "errors": errors[:5], "checked_at": now})
    return {"updated_at": now, "ratings_source": ALLSIDES, "sources": sources, "races": merged}


def stamp_call_times(payload: dict, old: dict):
    """Give every call a time: the outlet's own when it publishes one (Bloomberg), otherwise when we first
    saw that call, carried over from the previous file for as long as the call stays the same."""
    for rid, calls in payload["races"].items():
        for sid, call in calls.items():
            prev = ((old.get("races") or {}).get(rid) or {}).get(sid)
            same = prev and prev.get("winner") == call.get("winner") and prev.get("status") == call.get("status")
            if not call.get("at"):
                call["at"] = prev.get("at") if same and prev.get("at") else payload["updated_at"]


def write_calls(out_path: Path = CALLS_PATH, verbose: bool = True) -> dict:
    races = json.loads((SITE_DATA_DIR / "races.json").read_text())
    payload = collect(races)
    if not any(s["ok"] for s in payload["sources"]):
        if verbose:
            print(f"[calls] no source responded; keeping {out_path.name} as it was")
        return dict(written=False)
    old = {}
    if out_path.exists():
        try:
            old = json.loads(out_path.read_text())
        except (json.JSONDecodeError, OSError):
            old = {}
    # Keep a source's previous calls when only that source failed this time.
    for s in payload["sources"]:
        if not s["ok"]:
            for rid, calls in (old.get("races") or {}).items():
                if s["id"] in calls:
                    payload["races"].setdefault(rid, {})[s["id"]] = calls[s["id"]]
            prev = next((p for p in old.get("sources", []) if p.get("id") == s["id"]), None)
            s["checked_at"] = prev.get("checked_at") if prev else None
    stamp_call_times(payload, old)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    if verbose:
        print("[calls] " + ", ".join(f"{s['name']}: {s['calls']} calls/{s['races_seen']} races" + ("" if s["ok"] else " (FAILED)")
                                     for s in payload["sources"]))
    return dict(written=True, sources={s["id"]: s["calls"] for s in payload["sources"]})
