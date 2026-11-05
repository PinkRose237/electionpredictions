"""Prediction-market prices for 2028 (Polymarket, Kalshi): winning party, each party's nominee, the winner.

Context only: markets are published next to the forecast for comparison and are never a model input
(nor shown to the model-revision step), so the comparison stays independent."""
from __future__ import annotations

import json
from typing import Optional

from ..config import TTL_MARKETS
from ..db import log_run, now_iso, upsert
from .http import get
from .primaries import canonical

GAMMA = "https://gamma-api.polymarket.com"
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
POLY_EVENTS = {
    "party": "which-party-wins-2028-us-presidential-election",
    "nominee_D": "democratic-presidential-nominee-2028",
    "nominee_R": "republican-presidential-nominee-2028",
    "winner": "presidential-election-winner-2028",
}
KALSHI_EVENTS = {"party": "KXPRESPARTY-2028", "nominee_D": "KXPRESNOMD-28", "nominee_R": "KXPRESNOMR-28"}
MIN_VOLUME = 5_000      # ignore thin or placeholder outcomes
MIN_P = 0.005


def _outcome(kind: str, label: str) -> str:
    if kind == "party":
        low = label.lower()
        return "D" if low.startswith("democrat") else "R" if low.startswith("republican") else label
    return canonical(label)


def polymarket() -> list[dict]:
    out = []
    for kind, slug in POLY_EVENTS.items():
        evs = get(f"{GAMMA}/events", {"slug": slug}, kind="polymarket", ttl=TTL_MARKETS) or []
        if not evs:
            continue
        ev = evs[0]
        for m in ev.get("markets") or []:
            if m.get("closed"):
                continue
            try:
                p = float(json.loads(m.get("outcomePrices") or "[]")[0])
            except (ValueError, IndexError, TypeError):
                continue
            vol = float(m.get("volume") or 0)
            label = m.get("groupItemTitle") or m.get("question") or ""
            if vol < MIN_VOLUME or p < MIN_P or not label or label.lower().startswith(("party ", "other")):
                continue
            out.append(dict(market_key=f"polymarket:{kind}:{m.get('id')}", kind=kind, contest_id=None, outcome=_outcome(kind, label),
                            p=p, volume=vol, platform="polymarket", title=ev.get("title"),
                            url=f"https://polymarket.com/event/{slug}", fetched_at=now_iso()))
    return out


def _price(m: dict) -> Optional[float]:
    for k in ("last_price_dollars", "yes_bid_dollars"):
        try:
            v = float(m.get(k))
            if v > 0:
                return v
        except (TypeError, ValueError):
            continue
    return None


def kalshi() -> list[dict]:
    out = []
    for kind, ev in KALSHI_EVENTS.items():
        d = get(f"{KALSHI}/markets", {"event_ticker": ev, "limit": 200}, kind="kalshi", ttl=TTL_MARKETS) or {}
        for m in d.get("markets") or []:
            p = _price(m)
            label = m.get("yes_sub_title") or m.get("subtitle") or ""
            if p is None or p < MIN_P or not label:
                continue
            out.append(dict(market_key=f"kalshi:{m.get('ticker')}", kind=kind, contest_id=None, outcome=_outcome(kind, label.replace(" party", "")),
                            p=p, volume=float(m.get("volume") or 0), platform="kalshi", title=label,
                            url=f"https://kalshi.com/markets/{ev.split('-')[0].lower()}", fetched_at=now_iso()))
    return out


def load(con, verbose: bool = False) -> dict:
    started = now_iso()
    res, all_rows = {}, []
    for name, fn in (("polymarket", polymarket), ("kalshi", kalshi)):
        try:
            got = fn()
        except Exception as e:  # noqa: BLE001 - one platform failing must not lose the other
            print(f"  ! {name}: {e!r}")
            got = []
        res[name] = len(got)
        all_rows.extend(got)
    if all_rows:
        con.execute("DELETE FROM markets")
        upsert(con, "markets", all_rows, keys=["market_key"])
        con.commit()
    log_run(con, "markets", started, bool(all_rows), json.dumps(res))
    return res
