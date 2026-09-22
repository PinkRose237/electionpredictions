"""Fetch Wikipedia pages (cached) and extract every wikitable together with its section path.

We fetch the whole rendered page once (one request per page) and walk the HTML in document
order, tracking the heading hierarchy, so each table can be located as e.g.
['General election', 'Polling'] or ['District 1', 'General election', 'Polling'].
"""
from __future__ import annotations

import hashlib
import io
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
from lxml import html as lxml_html

from ..config import CACHE_DIR, TTL_WIKI, USER_AGENT
from ..util import clean

API = "https://en.wikipedia.org/w/api.php"
_session = requests.Session()
_session.headers["User-Agent"] = USER_AGENT
_last_request = 0.0
MIN_INTERVAL = 0.25  # seconds between live requests


def _cache_path(kind: str, key: str) -> Path:
    h = hashlib.sha1(key.encode()).hexdigest()[:16]
    d = CACHE_DIR / kind
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{h}.json"


def _get_cached(kind: str, key: str, ttl: int) -> Optional[dict]:
    p = _cache_path(kind, key)
    if p.exists() and (time.time() - p.stat().st_mtime) < ttl:
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            return None
    return None


def _put_cached(kind: str, key: str, payload: dict) -> None:
    _cache_path(kind, key).write_text(json.dumps(payload))


def _throttle():
    global _last_request
    wait = MIN_INTERVAL - (time.time() - _last_request)
    if wait > 0:
        time.sleep(wait)
    _last_request = time.time()


def api(params: dict, kind: str = "wiki", ttl: int = TTL_WIKI, retries: int = 3) -> dict:
    params = {"format": "json", "formatversion": "2", **params}
    key = json.dumps(params, sort_keys=True)
    cached = _get_cached(kind, key, ttl)
    if cached is not None:
        return cached
    last_err = None
    for attempt in range(retries):
        _throttle()
        try:
            r = _session.get(API, params=params, timeout=60)
            if r.status_code == 429:
                time.sleep(5 * (attempt + 1))
                continue
            r.raise_for_status()
            data = r.json()
            _put_cached(kind, key, data)
            return data
        except (requests.RequestException, ValueError) as e:  # noqa: PERF203
            last_err = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Wikipedia API failed for {params}: {last_err}")


def page_exists(title: str) -> bool:
    d = api({"action": "query", "titles": title, "redirects": 1})
    pages = d.get("query", {}).get("pages", [])
    return bool(pages) and not pages[0].get("missing", False)


def resolve_title(candidates: list[str]) -> Optional[str]:
    """Return the first title in the list that exists (following redirects)."""
    for t in candidates:
        d = api({"action": "query", "titles": t, "redirects": 1})
        pages = d.get("query", {}).get("pages", [])
        if pages and not pages[0].get("missing", False):
            return pages[0].get("title", t)
    return None


def page_html(title: str) -> Optional[str]:
    d = api({"action": "parse", "page": title, "prop": "text", "redirects": 1, "disablelimitreport": 1})
    if "error" in d:
        return None
    return d["parse"]["text"]


@dataclass
class WikiTable:
    path: list[str]          # heading path, e.g. ['General election', 'Polling']
    df: pd.DataFrame
    html: str
    index: int               # order within the page

    @property
    def columns(self) -> list[str]:
        out = []
        for c in self.df.columns:
            if isinstance(c, tuple):
                parts = [clean(x) for x in c if not str(x).startswith("Unnamed")]
                # collapse duplicated multi-index levels like ('Ratings','Cook ...') -> 'Cook ...'
                out.append(parts[-1] if parts else "")
            else:
                out.append(clean(c))
        return out

    def flat(self) -> pd.DataFrame:
        df = self.df.copy()
        df.columns = self.columns
        return df


def _heading_text(el) -> str:
    # drop [edit] links and footnotes
    for bad in el.xpath('.//span[contains(@class,"mw-editsection")] | .//sup'):
        bad.getparent().remove(bad)
    return clean(el.text_content())


def extract_tables(html: str) -> list[WikiTable]:
    """Walk the page in document order; return all wikitables with their heading path."""
    doc = lxml_html.fromstring(html)
    stack: list[tuple[int, str]] = []
    tables: list[WikiTable] = []
    idx = 0
    for el in doc.iter():
        tag = el.tag if isinstance(el.tag, str) else ""
        if tag in ("h2", "h3", "h4", "h5", "h6"):
            level = int(tag[1])
            text = _heading_text(el)
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, text))
        elif tag == "table":
            cls = el.get("class", "")
            if "wikitable" not in cls:
                continue
            # skip tables nested inside another wikitable (already covered)
            parent = el.getparent()
            nested = False
            while parent is not None:
                if parent.tag == "table" and "wikitable" in (parent.get("class") or ""):
                    nested = True
                    break
                parent = parent.getparent()
            if nested:
                continue
            outer = lxml_html.tostring(el, encoding="unicode")
            try:
                dfs = pd.read_html(io.StringIO(outer))
            except ValueError:
                continue
            if not dfs:
                continue
            tables.append(WikiTable(path=[t for _, t in stack], df=dfs[0], html=outer, index=idx))
            idx += 1
    return tables


def find_tables(tables: list[WikiTable], *, endswith: list[str] | None = None, contains: list[str] | None = None,
                columns_any: list[str] | None = None) -> list[WikiTable]:
    """Filter tables by heading path suffix / membership and by column names."""
    out = []
    for t in tables:
        path_l = [p.lower() for p in t.path]
        if endswith:
            suffix = [e.lower() for e in endswith]
            if path_l[-len(suffix):] != suffix:
                continue
        if contains and not all(any(c.lower() in p for p in path_l) for c in contains):
            continue
        if columns_any:
            cols = " | ".join(t.columns).lower()
            if not any(c.lower() in cols for c in columns_any):
                continue
        out.append(t)
    return out


def section_list(title: str) -> list[dict]:
    d = api({"action": "parse", "page": title, "prop": "sections", "redirects": 1})
    return d.get("parse", {}).get("sections", [])


def link_map(table_html: str) -> dict[str, str]:
    """{anchor text: href} for every real article link in a table (redlinks excluded)."""
    out: dict[str, str] = {}
    doc = lxml_html.fromstring(table_html)
    for a in doc.iter("a"):
        href = a.get("href") or ""
        if not href.startswith("/wiki/") or "new" in (a.get("class") or ""):
            continue
        text = clean(a.text_content())
        if text and text not in out:
            out[text] = href.split("#")[0]
    return out
