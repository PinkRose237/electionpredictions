"""Small parsing helpers shared by the sources and the model."""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional

from dateutil import parser as dtparser

from .config import STATES, STATE_BY_NAME

REF_RE = re.compile(r"\[[^\]]*\]")  # [1], [a], [note 2]
WS_RE = re.compile(r"\s+")


def clean(s) -> str:
    """Strip footnote markers and normalise whitespace."""
    if s is None:
        return ""
    s = str(s)
    if s.lower() == "nan":
        return ""
    s = REF_RE.sub("", s)
    s = s.replace(" ", " ").replace("\xa0", " ").replace("​", "")
    return WS_RE.sub(" ", s).strip()


def parse_pvi(s) -> Optional[float]:
    """'R+15' -> -15, 'D+6' -> 6, 'EVEN' -> 0. Democratic-positive."""
    s = clean(s).upper().replace("–", "-").replace("−", "-")
    if not s:
        return None
    if s.startswith("EVEN"):
        return 0.0
    m = re.match(r"([DR])\s*\+?\s*(\d+(?:\.\d+)?)", s)
    if not m:
        return None
    v = float(m.group(2))
    return v if m.group(1) == "D" else -v


def parse_pct(s) -> Optional[float]:
    """'48%' -> 48.0, '49%[c]' -> 49.0, '—' -> None, '<1%' -> 0.5"""
    s = clean(s).replace("%", "").replace("−", "-").replace("–", "-").replace("±", "").replace("+", "").strip()
    if not s or s in {"-", "—", "N/A", "n/a", "TBD"}:
        return None
    if s.startswith("<"):
        try:
            return float(s[1:]) / 2
        except ValueError:
            return None
    m = re.match(r"-?\d+(?:\.\d+)?", s)
    return float(m.group(0)) if m else None


def parse_sample(s) -> tuple[Optional[int], Optional[str]]:
    """'1,019 (LV)' -> (1019, 'LV'); '645 (RV)' -> (645, 'RV'); '—' -> (None, None)"""
    s = clean(s)
    n = None
    m = re.search(r"(\d[\d,]*)", s)
    if m:
        try:
            n = int(m.group(1).replace(",", ""))
        except ValueError:
            n = None
    pop = None
    m2 = re.search(r"\((LV|RV|A|V)\)", s.upper())
    if m2:
        pop = m2.group(1)
    return n, pop


MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"


def parse_date_range(s, default_year: int | None = None) -> tuple[Optional[date], Optional[date]]:
    """Parse Wikipedia poll date strings into (start, end).

    Handles 'September 14–16, 2026', 'February 28 – March 2, 2026', 'September 14, 2026',
    'July 28 – August 1, 2025', 'Dec 30, 2025 – Jan 2, 2026'.
    """
    s = clean(s).replace("–", "-").replace("—", "-").replace("−", "-")
    if not s:
        return None, None
    years = re.findall(r"(20\d\d)", s)
    end_year = int(years[-1]) if years else default_year
    if end_year is None:
        return None, None
    parts = [p.strip() for p in s.split("-")]
    try:
        if len(parts) == 1:
            d = dtparser.parse(parts[0], default=datetime(end_year, 1, 1)).date()
            return d, d
        left, right = parts[0], parts[-1]
        # right side: may be '16, 2026' or 'March 2, 2026'
        m_right = re.match(rf"^\s*({MONTHS})\b", right)
        if m_right:
            end = dtparser.parse(right, default=datetime(end_year, 1, 1)).date()
        else:
            # right is a day (and maybe year); month comes from left
            m_left = re.match(rf"^\s*({MONTHS})\b", left)
            month = m_left.group(1) if m_left else ""
            end = dtparser.parse(f"{month} {right}", default=datetime(end_year, 1, 1)).date()
        # start
        m_left = re.match(rf"^\s*({MONTHS})\b", left)
        if m_left:
            has_year = bool(re.search(r"20\d\d", left))
            start_year = end_year if not has_year else None
            start = dtparser.parse(left, default=datetime(start_year or end_year, 1, 1)).date()
            if start > end and not has_year:
                start = start.replace(year=end.year - 1)
        else:
            start = end
        return start, end
    except (ValueError, OverflowError):
        return None, None


PARTY_WORDS = {
    "democratic": "D", "democrat": "D", "dfl": "D", "democratic-farmer-labor": "D",
    "republican": "R", "gop": "R",
    "independent": "I", "libertarian": "L", "green": "G", "no labels": "NL",
    "working families": "WF", "constitution": "C", "forward": "F", "independence": "I",
    "alaska independence": "I", "nonpartisan": "I", "write-in": "W",
}


def party_code(s) -> str:
    s = clean(s).lower()
    if not s:
        return "?"
    if s in {"d", "r", "i", "l", "g"}:
        return s.upper()
    for k, v in PARTY_WORDS.items():
        if s.startswith(k):
            return v
    return "O"


def state_abbr(name_or_abbr: str) -> Optional[str]:
    s = clean(name_or_abbr)
    if s.upper() in STATES:
        return s.upper()
    s2 = re.sub(r"\s*\(.*?\)\s*", "", s).strip()
    if s2 in STATE_BY_NAME:
        return STATE_BY_NAME[s2]
    for name, ab in STATE_BY_NAME.items():
        if s2.startswith(name):
            return ab
    return None


def ordinal(n: int) -> str:
    return "%d%s" % (n, "tsnrhtdd"[(n // 10 % 10 != 1) * (n % 10 < 4) * n % 10 :: 4])


def race_id(chamber: str, state: str, district: int | None = None, special: bool = False) -> str:
    if chamber == "house":
        return f"{state}-{district:02d}"
    if chamber == "senate":
        return f"{state}-SEN" + ("-SP" if special else "")
    if chamber == "president":
        return f"{state}-PRES"
    return f"{state}-GOV"


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", clean(s).lower()).strip("-")


def split_candidates(cell: str) -> list[tuple[str, str]]:
    """'▌Mike Collins (Republican)[11] ▌Jon Ossoff (Democratic)[11]' -> [(name, party_code), ...]"""
    cell = REF_RE.sub("", str(cell)) if cell is not None else ""
    out = []
    for chunk in re.split(r"[▌•\n]|(?<=\))\s+(?=[A-Z])", cell):
        chunk = clean(chunk)
        if not chunk:
            continue
        m = re.match(r"(.+?)\s*\(([^)]+)\)\s*$", chunk)
        if m:
            out.append((m.group(1).strip(), party_code(m.group(2))))
        else:
            out.append((chunk, "?"))
    return out


def last_name(full: str) -> str:
    full = clean(full)
    full = re.sub(r"\s+(Jr\.?|Sr\.?|II|III|IV)$", "", full)
    return full.split()[-1] if full else ""


def parse_rating(s) -> Optional[tuple[str, int, bool]]:
    """'Lean D (flip)' -> ('D', 2, True); 'Tossup' -> ('T', 0, False); 'Safe R' -> ('R', 4, False)"""
    s = clean(s)
    if not s:
        return None
    low = s.lower()
    flip = "flip" in low
    if low.startswith(("toss", "tilt-up", "toss-up")):
        return ("T", 0, flip)
    m = re.match(r"(safe|solid|likely|lean|tilt)\s*([DRI])", s, re.I)
    if not m:
        return None
    level = {"safe": 4, "solid": 4, "likely": 3, "lean": 2, "tilt": 1}[m.group(1).lower()]
    return (m.group(2).upper(), level, flip)


def rating_label(score: float) -> str:
    """Map a signed consensus score (D-positive, -4..4) to a label."""
    a = abs(score)
    if a < 0.5:
        return "Tossup"
    party = "D" if score > 0 else "R"
    if a < 1.5:
        return f"Tilt {party}"
    if a < 2.5:
        return f"Lean {party}"
    if a < 3.5:
        return f"Likely {party}"
    return f"Safe {party}"


def prob_label(p_dem: float) -> str:
    """Bucket a Democratic win probability into a rating-like label."""
    if p_dem >= 0.97:
        return "Safe D"
    if p_dem >= 0.85:
        return "Likely D"
    if p_dem >= 0.65:
        return "Lean D"
    if p_dem > 0.35:
        return "Tossup"
    if p_dem > 0.15:
        return "Lean R"
    if p_dem > 0.03:
        return "Likely R"
    return "Safe R"
