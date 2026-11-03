"""Live election-night results: a saved snapshot of the public results feeds (site/data/results-auto.json).

The site pulls these same feeds in the browser (site/live.js) every minute; this snapshot is the fallback
when a visitor's browser can't reach them, and it keeps the results after the feeds go offline. Keep the
two in step: same feeds, same race resolution, same candidate-to-side matching.

Primary: The New York Times' results JSON (AP vote counts and AP calls; "reporting" is AP's estimated share
of the expected vote). Backup: CNN's national-races JSON, used only for races the primary did not supply.
Entries follow results.json (docs/DATA_CONTRACT.md): status, reporting, votes {dem, rep, other}, winner.
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import requests

from ..config import SITE_DATA_DIR, USER_AGENT

NYT_URL = "https://static01.nyt.com/elections-assets/pages/data/2026-11-03/results-{office}.json"
CNN_URL = "https://politics.api.cnn.io/results/national-races/2026-{code}.json"
SNAPSHOT_PATH = SITE_DATA_DIR / "results-auto.json"

_SUFFIX = re.compile(r"^(jr|sr|ii|iii|iv)$")


def name_tokens(s: Optional[str]) -> list[str]:
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"[^a-z\s-]", " ", s)
    return [t for t in re.split(r"[\s-]+", s) if t and not _SUFFIX.match(t)]


def make_resolver(ids) -> Callable[[str, str, object, bool], Optional[str]]:
    ids = set(ids)

    def resolve(st: str, chamber: str, district, special: bool) -> Optional[str]:
        if chamber == "governor":
            return f"{st}-GOV" if f"{st}-GOV" in ids else None
        if chamber == "senate":
            order = [f"{st}-SEN-SP", f"{st}-SEN"] if special else [f"{st}-SEN", f"{st}-SEN-SP"]
            return next((i for i in order if i in ids), None)
        if chamber == "house":
            try:
                d = int(district)
            except (TypeError, ValueError):
                return None
            if f"{st}-{d:02d}" in ids:
                return f"{st}-{d:02d}"
            if d <= 1 and f"{st}-00" in ids:
                return f"{st}-00"
        return None

    return resolve


def _side_name(c) -> str:
    return (c.get("name") if isinstance(c, dict) else c) or ""


def _fit(our_name: str, cand: dict, side: str) -> float:
    toks = name_tokens(our_name)
    last = name_tokens(cand.get("last"))
    s = 0.0
    if toks and last and all(t in toks for t in last):
        s += 2
        first = name_tokens(cand.get("first"))
        if first and toks[0] == first[0]:
            s += 1
    if (side == "dem" and cand.get("party") == "DEM") or (side == "rep" and cand.get("party") == "REP"):
        s += 0.5
    return s


def assign_sides(race: dict, cands: list[dict]) -> tuple[dict, dict]:
    """Votes per side and the index of the candidate on each side (name matches beat party matches)."""
    pairs = []
    for i, c in enumerate(cands):
        for side in ("dem", "rep"):
            sc = _fit(_side_name(race.get(side)), c, side)
            if sc >= 0.5:
                pairs.append((sc, c.get("votes") or 0, side, i))
    pairs.sort(key=lambda p: (-p[0], -p[1]))
    pick, used = {"dem": -1, "rep": -1}, set()
    for _, _, side, i in pairs:
        if pick[side] != -1 or i in used:
            continue
        pick[side] = i
        used.add(i)
    votes = {"dem": None, "rep": None, "other": 0}
    for i, c in enumerate(cands):
        v = c.get("votes") or 0
        if i == pick["dem"]:
            votes["dem"] = v
        elif i == pick["rep"]:
            votes["rep"] = v
        else:
            votes["other"] += v
    return votes, pick


def entry_from(race: dict, cands: list[dict], winner_idx=(), runoff=False, final=False, reporting=None, updated_at=None) -> dict:
    votes, pick = assign_sides(race, cands)
    total = (votes["dem"] or 0) + (votes["rep"] or 0) + (votes["other"] or 0)
    winner = None
    if winner_idx:
        w = winner_idx[0]
        winner = "dem" if w == pick["dem"] else "rep" if w == pick["rep"] else "other"
    if final and winner:
        status = "final"
    elif winner:
        status = "called"
    elif runoff:
        status = "runoff"
    elif total > 0 or (reporting or 0) > 0:
        status = "counting"
    else:
        status = "pending"
    if not votes["other"] and not total:
        votes["other"] = None
    return dict(status=status, winner=winner, reporting=round(float(reporting), 1) if reporting is not None else None,
                votes=votes, updated_at=updated_at)


def _get(url: str, timeout: int = 60):
    r = requests.get(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}, timeout=timeout)
    r.raise_for_status()
    return r.json()


def parse_nyt(data: dict, by_id: dict, resolve) -> dict:
    out = {}
    chamber_of = {"S": "senate", "H": "house", "G": "governor"}
    for race in data.get("races") or []:
        ru = race.get("top_reporting_unit") or {}
        if ru.get("level") != "state":
            continue
        special = race.get("race_type_id") == "W" or "special" in (race.get("type") or "").lower()
        rid = resolve(ru.get("state_postal"), chamber_of.get(race.get("office_id")), race.get("seat_number"), special)
        if not rid or rid in out:
            continue
        meta = race.get("candidate_metadata") or {}
        cands = []
        for c in ru.get("candidates") or []:
            m = meta.get(c.get("nyt_id")) or {}
            party = (m.get("party") or {}).get("nyt_id") or ""
            cands.append(dict(key=c.get("nyt_id"), first=m.get("first_name") or "", last=m.get("last_name") or "",
                              party="REP" if party == "GOP" else party, votes=(c.get("votes") or {}).get("total") or 0))
        outcome = race.get("outcome") or {}
        won = [i for k in outcome.get("won") or [] for i, c in enumerate(cands) if c["key"] == k]
        out[rid] = entry_from(by_id[rid], cands, winner_idx=won, runoff=bool(outcome.get("advanced_to_runoff")),
                              final=bool(race.get("certified")), reporting=ru.get("eevp"),
                              updated_at=ru.get("provider_updated_at") or race.get("updated_at"))
    return out


def parse_cnn(data: list, by_id: dict, resolve) -> dict:
    out = {}
    chamber_of = {"S": "senate", "H": "house", "G": "governor"}
    for race in data or []:
        if race.get("contestType") == "HQ":  # unexpired-term specials; we track the full-term race
            continue
        chamber = chamber_of.get(race.get("raceType"))
        district = str(race.get("ecKey") or "").split("-")[-1] if chamber == "house" else None
        rid = resolve(race.get("stateAbbreviation"), chamber, district, race.get("contestType") == "SP")
        if not rid or rid in out:
            continue
        cands = [dict(first=c.get("firstName") or "", last=c.get("lastName") or "", party=c.get("majorParty") or "",
                      votes=c.get("voteNum") or 0, winner=bool(c.get("winner")), runoff=bool(c.get("runoffCandidate")))
                 for c in race.get("candidates") or []]
        at = race.get("extractedAt")
        if at and not re.search(r"(Z|[+-]\d\d:?\d\d)$", at):
            at += "Z"
        out[rid] = entry_from(by_id[rid], cands, winner_idx=[i for i, c in enumerate(cands) if c["winner"]],
                              runoff=any(c["runoff"] for c in cands), reporting=race.get("percentReporting"), updated_at=at)
    return out


def fetch_nyt(by_id, resolve, errors: list) -> dict:
    out = {}
    for office in ("senate", "house", "governor"):
        try:
            out.update(parse_nyt(_get(NYT_URL.format(office=office)), by_id, resolve))
        except (requests.RequestException, ValueError) as e:
            errors.append(f"nyt {office}: {e}")
    return out


def fetch_cnn(by_id, resolve, errors: list) -> dict:
    out = {}
    for code in ("SG", "HG", "GG"):
        try:
            out.update(parse_cnn(_get(CNN_URL.format(code=code)), by_id, resolve))
        except (requests.RequestException, ValueError) as e:
            errors.append(f"cnn {code}: {e}")
    return out


FEEDS = {"nyt": fetch_nyt, "cnn": fetch_cnn}


def fetch_live(races: list[dict], order=("nyt", "cnn")) -> dict:
    by_id = {r["race_id"]: r for r in races}
    resolve = make_resolver(by_id)
    merged, by, errors, used = {}, {}, [], []
    for name in order:
        if len(merged) >= len(by_id):
            break
        got = FEEDS[name](by_id, resolve, errors)
        added = 0
        for rid, e in got.items():
            if rid not in merged:
                merged[rid], by[rid] = e, name
                added += 1
        if added:
            used.append(name)
    return dict(races=merged, by=by, sources=used, errors=errors)


def snapshot(out_path: Path = SNAPSHOT_PATH, verbose: bool = True) -> dict:
    """Pull the feeds and write results-auto.json. Leaves the old file alone if every feed fails."""
    races = json.loads((SITE_DATA_DIR / "races.json").read_text())
    res = fetch_live(races)
    if not res["races"]:
        if verbose:
            print(f"[results] no feed data; keeping {out_path.name} as it was ({'; '.join(res['errors'])})")
        return dict(written=False, **{k: res[k] for k in ("sources", "errors")})
    payload = dict(updated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), sources=res["sources"],
                   races=res["races"], by=res["by"])
    out_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    called = sum(1 for e in res["races"].values() if e["status"] in ("called", "final"))
    counting = sum(1 for e in res["races"].values() if e["status"] == "counting")
    if verbose:
        print(f"[results] {len(res['races'])} races from {'+'.join(res['sources'])}: {counting} counting, {called} called"
              + (f" (errors: {'; '.join(res['errors'])})" if res["errors"] else ""))
    return dict(written=True, races=len(res["races"]), called=called, counting=counting, sources=res["sources"], errors=res["errors"])
