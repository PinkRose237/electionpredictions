"""Cached, throttled HTTP helpers shared by the non-Wikipedia sources."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit

import requests

from ..config import CACHE_DIR, USER_AGENT

_session = requests.Session()
_session.headers["User-Agent"] = USER_AGENT
_last: dict[str, float] = {}
MIN_INTERVAL = {"api.open.fec.gov": 0.6, "news.google.com": 0.5, "gamma-api.polymarket.com": 0.15,
                "api.elections.kalshi.com": 0.2, "www.predictit.org": 1.0}


def _cache_path(kind: str, key: str) -> Path:
    d = CACHE_DIR / kind
    d.mkdir(parents=True, exist_ok=True)
    return d / (hashlib.sha1(key.encode()).hexdigest()[:20] + ".json")


def _throttle(host: str):
    gap = MIN_INTERVAL.get(host, 0.3)
    wait = gap - (time.time() - _last.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    _last[host] = time.time()


def get(url: str, params: dict | None = None, *, kind: str = "http", ttl: int = 3600,
        headers: dict | None = None, retries: int = 3, as_json: bool = True) -> Optional[Any]:
    """GET with an on-disk cache. Returns parsed JSON (or text). None on persistent failure / 404."""
    params = params or {}
    key = url + "?" + json.dumps(params, sort_keys=True)
    p = _cache_path(kind, key)
    if p.exists() and (time.time() - p.stat().st_mtime) < ttl:
        try:
            payload = json.loads(p.read_text())
            return payload.get("data")
        except json.JSONDecodeError:
            pass
    host = urlsplit(url).netloc
    last_err = None
    for attempt in range(retries):
        _throttle(host)
        try:
            r = _session.get(url, params=params, headers=headers, timeout=60)
            if r.status_code == 404:
                p.write_text(json.dumps({"data": None}))
                return None
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(3 * (attempt + 1))
                last_err = f"HTTP {r.status_code}"
                continue
            r.raise_for_status()
            data = r.json() if as_json else r.text
            p.write_text(json.dumps({"data": data}))
            return data
        except (requests.RequestException, ValueError) as e:  # noqa: PERF203
            last_err = e
            time.sleep(2 * (attempt + 1))
    print(f"  ! GET failed {url} {params}: {last_err}")
    return None
