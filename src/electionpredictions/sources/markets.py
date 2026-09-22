"""Prediction-market odds from Polymarket, PredictIt and Kalshi, mapped onto our race ids.

Markets are stored for comparison with the model; they are not a model input."""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Optional

from ..config import STATES, TTL_MARKETS
from ..db import log_run, now_iso, rows, upsert
from ..util import last_name, slug, state_abbr
from .http import get
from .races import same_person

GAMMA = "https://gamma-api.polymarket.com"
PREDICTIT = "https://www.predictit.org/api/marketdata/all/"
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
CONTROL_IDS = {"senate": "SENATE-CONTROL", "house": "HOUSE-CONTROL"}


def _party_from_text(q: str) -> Optional[str]:
    q = (q or "").lower()
    if "democrat" in q:
        return "D"
    if "republican" in q:
        return "R"
    if "independent" in q or "third party" in q or "other" in q:
        return "I"
    return None


def _cand_party(text: str, cands: list[dict]) -> Optional[str]:
    p = _party_from_text(text)
    if p:
        return p
    for c in cands:
        if same_person(text, c["name"]) or last_name(c["name"]).lower() == text.strip().lower():
            return "D" if c["party"] == "D" else "R" if c["party"] == "R" else "I"
    return None


# ------------------------------------------------------------------ Polymarket
def poly_slugs(race: dict) -> list[str]:
    st = race["state"]
    s = slug(STATES[st])
    if race["chamber"] == "senate":
        if race["special"]:
            return [f"{s}-senate-special-election-winner", f"{s}-special-senate-election-winner", f"{s}-senate-election-winner"]
        return [f"{s}-senate-election-winner", f"{s}-senate-election-winner-2026", f"{s}-senate-winner-2026"]
    if race["chamber"] == "governor":
        return [f"{s}-governor-winner-2026", f"{s}-governor-election-winner", f"{s}-governor-election-winner-2026"]
    dd = f"{race['district']:02d}" if race["district"] else "al"
    return [f"{st.lower()}-{dd}-house-election-winner"]


def poly_event(slug_: str) -> Optional[dict]:
    d = get(f"{GAMMA}/events", {"slug": slug_}, kind="polymarket", ttl=TTL_MARKETS)
    return d[0] if d else None


def poly_search(q: str, title_re: str) -> Optional[dict]:
    d = get(f"{GAMMA}/public-search", {"q": q, "limit_per_type": 10}, kind="polymarket", ttl=TTL_MARKETS)
    for e in (d or {}).get("events", []):
        if not e.get("closed") and re.search(title_re, e.get("title", ""), re.I):
            return e
    return None


def poly_parse(event: dict, cands: list[dict]) -> Optional[dict]:
    p: dict[str, Optional[float]] = {"D": None, "R": None, "I": None}
    for m in event.get("markets", []):
        if m.get("closed"):
            continue
        q = m.get("question") or m.get("groupItemTitle") or ""
        party = _cand_party(q, cands)
        if not party:
            continue
        try:
            outcomes = json.loads(m.get("outcomes") or "[]")
            prices = json.loads(m.get("outcomePrices") or "[]")
            yes = float(prices[outcomes.index("Yes")]) if "Yes" in outcomes else float(prices[0])
        except (ValueError, IndexError, TypeError):
            continue
        p[party] = yes if p[party] is None else max(p[party], yes)
    if p["D"] is None and p["R"] is None:
        return None
    return dict(market_key=event.get("slug"), title=event.get("title"), p_dem=p["D"], p_rep=p["R"], p_other=p["I"],
                volume=float(event.get("volume") or 0), url=f"https://polymarket.com/event/{event.get('slug')}")


def load_polymarket(con, races: list[dict], cands_by_race: dict) -> int:
    out = []
    for race in races:
        ev = None
        for s in poly_slugs(race):
            ev = poly_event(s)
            if ev:
                break
        if ev is None and race["chamber"] in ("senate", "governor"):
            kind = "Senate" if race["chamber"] == "senate" else "Governor"
            ev = poly_search(f"{STATES[race['state']]} {kind}", rf"^{STATES[race['state']]} {kind}.*(winner|election)")
        if not ev:
            continue
        rec = poly_parse(ev, cands_by_race.get(race["race_id"], []))
        if rec:
            out.append(dict(race_id=race["race_id"], platform="polymarket", fetched_at=now_iso(), **rec))
    for chamber, slug_ in (("senate", "which-party-will-win-the-senate-in-2026"), ("house", "which-party-will-win-the-house-in-2026")):
        ev = poly_event(slug_)
        rec = poly_parse(ev, []) if ev else None
        if rec:
            out.append(dict(race_id=CONTROL_IDS[chamber], platform="polymarket", fetched_at=now_iso(), **rec))
    con.execute("DELETE FROM markets WHERE platform='polymarket'")
    return upsert(con, "markets", out, keys=["race_id", "platform", "market_key"])


# ------------------------------------------------------------------ PredictIt
def load_predictit(con, race_ids: set[str], cands_by_race: dict) -> int:
    d = get(PREDICTIT, kind="predictit", ttl=TTL_MARKETS)
    out = []
    for m in (d or {}).get("markets", []):
        sn, name = m.get("shortName", ""), m.get("name", "")
        rid = None
        mm = re.match(r"^(.*?) Senate (party )?winner\?$", sn, re.I)
        if mm:
            st = state_abbr(mm.group(1))
            if st:
                rid = f"{st}-SEN" + ("-SP" if "special" in name.lower() else "")
                if rid not in race_ids and f"{st}-SEN-SP" in race_ids:
                    rid = f"{st}-SEN-SP"
        mm = mm or re.match(r"^([A-Z]{2})-(\d{2}) House race winner\?$", sn)
        if rid is None and mm and mm.re.pattern.startswith("^([A-Z]{2})"):
            rid = f"{mm.group(1)}-{mm.group(2)}"
        if rid is None:
            mm = re.match(r"^(.*?) governor (party )?winner\?$", sn, re.I)
            if mm:
                st = state_abbr(mm.group(1))
                rid = f"{st}-GOV" if st else None
        if rid is None:
            if re.search(r"control the Senate after 2026|win the Senate in 2026", sn, re.I):
                rid = CONTROL_IDS["senate"]
            elif re.search(r"win the House in 2026|control the House after 2026", sn, re.I):
                rid = CONTROL_IDS["house"]
        if rid is None or (rid not in race_ids and rid not in CONTROL_IDS.values()):
            continue
        p: dict[str, Optional[float]] = {"D": None, "R": None, "I": None}
        for c in m.get("contracts", []):
            party = _cand_party(c.get("shortName", ""), cands_by_race.get(rid, []))
            price = c.get("lastTradePrice")
            if party and price is not None:
                p[party] = price if p[party] is None else max(p[party], price)
        if p["D"] is None and p["R"] is None:
            continue
        out.append(dict(race_id=rid, platform="predictit", market_key=str(m.get("id")), title=name, p_dem=p["D"], p_rep=p["R"],
                        p_other=p["I"], volume=None, fetched_at=now_iso(), url=m.get("url")))
    con.execute("DELETE FROM markets WHERE platform='predictit'")
    return upsert(con, "markets", out, keys=["race_id", "platform", "market_key"])


# ------------------------------------------------------------------ Kalshi
SEN_RE = re.compile(r"^(?:KX)?SENATE(?:PARTY)?-?([A-Z]{2})(S)?$")
GOV_RE = re.compile(r"^(?:KX)?GOV(?:PARTY)?-?([A-Z]{2})$")
HOUSE_RE = re.compile(r"^(?:KX)?HOUSE(?:PARTY)?-?([A-Z]{2})(\d{1,2})$")


def kalshi_series() -> list[dict]:
    out, cursor = [], None
    for _ in range(20):
        params = {"category": "Elections", "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        d = get(f"{KALSHI}/series", params, kind="kalshi", ttl=TTL_MARKETS)
        if not d:
            break
        out.extend(d.get("series", []))
        cursor = d.get("cursor")
        if not cursor:
            break
    return out


def _dollars(m: dict, key: str) -> Optional[float]:
    v = m.get(key + "_dollars")
    if v in (None, ""):
        v = m.get(key)
        if v is None:
            return None
        try:
            return float(v) / 100.0
        except (TypeError, ValueError):
            return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _kalshi_price(m: dict) -> Optional[float]:
    bid, ask, last = _dollars(m, "yes_bid"), _dollars(m, "yes_ask"), _dollars(m, "last_price")
    if bid and ask and bid > 0 and ask > 0:
        return (bid + ask) / 2
    return last if last is not None else bid or ask


def kalshi_race_odds(series_ticker: str, cands: list[dict]) -> Optional[dict]:
    d = get(f"{KALSHI}/events", {"series_ticker": series_ticker, "with_nested_markets": "true", "limit": 50}, kind="kalshi", ttl=TTL_MARKETS)
    best = None
    for ev in (d or {}).get("events", []):
        markets = ev.get("markets", [])
        if not markets:
            continue
        close = markets[0].get("close_time") or markets[0].get("expiration_time") or ""
        if not ("2026-11" <= close[:7] <= "2027-12"):
            continue
        p: dict[str, Optional[float]] = {"D": None, "R": None, "I": None}
        vol = 0.0
        for m in markets:
            if m.get("status") not in (None, "active", "open", "initialized"):
                continue
            t = m.get("ticker", "")
            party = None
            mm = re.search(r"-(D|R|I|IND|DEM|REP|OTH)$", t)
            if mm:
                party = {"D": "D", "DEM": "D", "R": "R", "REP": "R", "I": "I", "IND": "I", "OTH": "I"}[mm.group(1)]
            party = party or _cand_party(m.get("subtitle") or m.get("yes_sub_title") or "", cands)
            price = _kalshi_price(m)
            if party and price is not None:
                p[party] = price if p[party] is None else max(p[party], price)
            try:
                vol += float(m.get("volume_fp") or m.get("volume") or 0)
            except (TypeError, ValueError):
                pass
        if p["D"] is None and p["R"] is None:
            continue
        rec = dict(market_key=ev.get("event_ticker"), title=ev.get("title"), p_dem=p["D"], p_rep=p["R"], p_other=p["I"], volume=vol,
                   url=f"https://kalshi.com/markets/{series_ticker.lower()}")
        if best is None or vol > (best["volume"] or 0):
            best = rec
    return best


def load_kalshi(con, race_ids: set[str], cands_by_race: dict) -> int:
    series = kalshi_series()
    targets: dict[str, list[str]] = {}
    for s in series:
        t = s.get("ticker", "")
        rid = None
        if (m := SEN_RE.match(t)):
            st = m.group(1)
            if st in STATES:
                rid = f"{st}-SEN-SP" if (m.group(2) and f"{st}-SEN-SP" in race_ids) else f"{st}-SEN"
                if rid not in race_ids and f"{st}-SEN-SP" in race_ids:
                    rid = f"{st}-SEN-SP"
        elif (m := GOV_RE.match(t)):
            rid = f"{m.group(1)}-GOV"
        elif (m := HOUSE_RE.match(t)):
            rid = f"{m.group(1)}-{int(m.group(2)):02d}"
        if rid and rid in race_ids:
            targets.setdefault(rid, []).append(t)
    out = []
    for rid, tickers in targets.items():
        best = None
        for t in tickers:
            rec = kalshi_race_odds(t, cands_by_race.get(rid, []))
            if rec and (best is None or (rec["volume"] or 0) > (best["volume"] or 0)):
                best = rec
        if best:
            out.append(dict(race_id=rid, platform="kalshi", fetched_at=now_iso(), **best))
    for chamber, ticker in (("senate", "KXSENATE"), ("house", "KXHOUSE")):
        rec = kalshi_race_odds(ticker, [])
        if rec:
            out.append(dict(race_id=CONTROL_IDS[chamber], platform="kalshi", fetched_at=now_iso(), **rec))
    con.execute("DELETE FROM markets WHERE platform='kalshi'")
    return upsert(con, "markets", out, keys=["race_id", "platform", "market_key"])


def load(con, verbose=True) -> dict:
    started = now_iso()
    races = rows(con, "SELECT * FROM races ORDER BY chamber, state, district")
    race_ids = {r["race_id"] for r in races}
    cands_by_race: dict[str, list[dict]] = {}
    for c in rows(con, "SELECT * FROM candidates"):
        cands_by_race.setdefault(c["race_id"], []).append(c)
    stats = {}
    for name, fn in (("polymarket", lambda: load_polymarket(con, races, cands_by_race)),
                     ("predictit", lambda: load_predictit(con, race_ids, cands_by_race)),
                     ("kalshi", lambda: load_kalshi(con, race_ids, cands_by_race))):
        try:
            stats[name] = fn()
        except Exception as e:  # noqa: BLE001
            print(f"  ! {name} failed: {e}")
            stats[name] = f"error: {e}"
        con.commit()
        if verbose:
            print(f"  markets/{name}: {stats[name]}")
    log_run(con, "markets", started, True, json.dumps(stats))
    return stats
