"""Project-wide configuration and constants."""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (KEY=value lines; existing environment wins)."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv(ROOT / ".env")
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
DB_PATH = DATA_DIR / "elections.db"
SITE_DIR = ROOT / "site"
SITE_DATA_DIR = SITE_DIR / "data"

ELECTION_DATE = date(2026, 11, 3)
CYCLE = 2026

USER_AGENT = os.environ.get(
    "EP_USER_AGENT",
    "electionpredictions/0.1 (open-source midterm forecast; https://github.com/local/electionpredictions)",
)
FEC_API_KEY = os.environ.get("FEC_API_KEY", "DEMO_KEY")
FOLLOWTHEMONEY_API_KEY = os.environ.get("FOLLOWTHEMONEY_API_KEY", "")
CENSUS_API_KEY = os.environ.get("CENSUS_API_KEY", "")
# Decision layer via OpenCode Zen (OpenAI-compatible). Default model: Meta Muse Spark 1.3 (paid tier;
# OpenCode's free '-contributor-free' tier only works inside the OpenCode client, not over the API).
OPENCODE_API_KEY = os.environ.get("OPENCODE_API_KEY") or os.environ.get("OPENCODE_ZEN_API_KEY", "")
AI_MODEL = os.environ.get("AI_MODEL") or "muse-spark-1.3"
AI_BASE_URL = os.environ.get("AI_BASE_URL") or "https://opencode.ai/zen/v1"

# States that redrew congressional maps for 2026 (mid-decade); ACS district data predates those lines.
REDISTRICTED_2026 = {"TX", "CA", "FL", "MO", "NC", "OH", "UT", "AL", "LA"}

# Cache TTLs in seconds
TTL_WIKI = int(os.environ.get("EP_TTL_WIKI", 6 * 3600))
TTL_MARKETS = int(os.environ.get("EP_TTL_MARKETS", 1 * 3600))
TTL_FEC = int(os.environ.get("EP_TTL_FEC", 24 * 3600))
TTL_NEWS = int(os.environ.get("EP_TTL_NEWS", 3 * 3600))

# Senate seats NOT up in 2026, by caucus. 100 seats total; 35 are up (33 regular + OH/FL specials).
# Current Senate: 53 R / 45 D / 2 I (both caucus with D). Up in 2026: 22 R-held, 13 D-held.
SENATE_NOT_UP = {"D": 34, "R": 31}
# Governors not up in 2026 (14 states): AK... computed from seed; overridden here as a constant.
# 50 governors: 27 R, 23 D. Up in 2026: 36 (20 R-held, 16 D-held). Not up: 7 R, 7 D.
GOVERNORS_NOT_UP = {"D": 7, "R": 7}

STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri",
    "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}
STATE_BY_NAME = {v: k for k, v in STATES.items()}

# Census regions, used for correlated regional error in the simulation.
REGIONS = {
    "Northeast": ["CT", "ME", "MA", "NH", "RI", "VT", "NJ", "NY", "PA"],
    "Midwest": ["IL", "IN", "MI", "OH", "WI", "IA", "KS", "MN", "MO", "NE", "ND", "SD"],
    "South": ["DE", "FL", "GA", "MD", "NC", "SC", "VA", "WV", "AL", "KY", "MS", "TN", "AR", "LA", "OK", "TX"],
    "West": ["AZ", "CO", "ID", "MT", "NV", "NM", "UT", "WY", "AK", "CA", "HI", "OR", "WA"],
}
REGION_OF = {st: r for r, sts in REGIONS.items() for st in sts}


def days_to_election(today: date | None = None) -> int:
    today = today or date.today()
    return max(0, (ELECTION_DATE - today).days)
