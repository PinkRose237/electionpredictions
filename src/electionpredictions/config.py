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

# Cycle switch: EP_CYCLE=2028 runs the presidential pipeline (separate DB + site data dir)
# while the 2026 midterm pipeline stays untouched.
CYCLE = int(os.environ.get("EP_CYCLE", "2026") or 2026)
ELECTION_DATES = {2026: date(2026, 11, 3), 2028: date(2028, 11, 7)}
ELECTION_DATE = ELECTION_DATES.get(CYCLE, ELECTION_DATES[2026])

DB_PATH = DATA_DIR / ("elections.db" if CYCLE == 2026 else f"elections{CYCLE}.db")
SITE_DIR = ROOT / "site"
SITE_DATA_DIR = SITE_DIR / ("data" if CYCLE == 2026 else f"data{CYCLE}")

USER_AGENT = os.environ.get(
    "EP_USER_AGENT",
    "electionpredictions/0.1 (open-source midterm forecast; https://github.com/local/electionpredictions)",
)
FEC_API_KEY = os.environ.get("FEC_API_KEY", "DEMO_KEY")
FOLLOWTHEMONEY_API_KEY = os.environ.get("FOLLOWTHEMONEY_API_KEY", "")
CENSUS_API_KEY = os.environ.get("CENSUS_API_KEY", "")
# Decision layer via OpenCode (OpenAI-compatible). Default: the OpenCode Go subscription gateway with Z.AI GLM 5.3
# Flash. Pay-as-you-go Zen is https://opencode.ai/zen/v1 (needs credit); the '-free' tiers only work inside the client.
OPENCODE_API_KEY = os.environ.get("OPENCODE_API_KEY") or os.environ.get("OPENCODE_ZEN_API_KEY", "")
AI_MODEL = os.environ.get("AI_MODEL") or "glm-5.3-flash"
AI_BASE_URL = os.environ.get("AI_BASE_URL") or "https://opencode.ai/zen/go/v1"

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
    "South": ["DE", "FL", "GA", "MD", "NC", "SC", "VA", "WV", "AL", "KY", "MS", "TN", "AR", "LA", "OK", "TX", "DC"],
    "West": ["AZ", "CO", "ID", "MT", "NV", "NM", "UT", "WY", "AK", "CA", "HI", "OR", "WA"],
}
REGION_OF = {st: r for r, sts in REGIONS.items() for st in sts}

DC_NAME = "District of Columbia"

# Electoral votes for the 2028 presidential election (2020 census apportionment; same map as 2024).
# Winner-take-all per jurisdiction (Maine/Nebraska district splits are folded into the statewide
# winner as a documented simplification). Total: 538, needed to win: 270.
ELECTORAL_VOTES_2028 = {
    "AL": 9, "AK": 3, "AZ": 11, "AR": 6, "CA": 54, "CO": 10, "CT": 7, "DE": 3, "DC": 3,
    "FL": 30, "GA": 16, "HI": 4, "ID": 4, "IL": 19, "IN": 11, "IA": 6, "KS": 6, "KY": 8,
    "LA": 8, "ME": 4, "MD": 10, "MA": 11, "MI": 15, "MN": 10, "MS": 6, "MO": 10, "MT": 4,
    "NE": 5, "NV": 6, "NH": 4, "NJ": 14, "NM": 5, "NY": 28, "NC": 16, "ND": 3, "OH": 17,
    "OK": 7, "OR": 8, "PA": 19, "RI": 4, "SC": 9, "SD": 3, "TN": 11, "TX": 40, "UT": 6,
    "VT": 3, "VA": 13, "WA": 12, "WV": 4, "WI": 10, "WY": 3,
}
EVS_TO_WIN_2028 = 270
PRESIDENT_JURISDICTIONS = [*STATES, "DC"]

# State lean for the 2028 presidential model: 2026 Cook PVI (based on 2020+2024 results, weighted
# to 2024), Democratic-positive points. Source: Wikipedia "Cook Partisan Voting Index", Sept 2026.
PRESIDENT_PVI_2028 = {
    "AL": -15, "AK": -6, "AZ": -2, "AR": -15, "CA": 12, "CO": 6, "CT": 8, "DE": 8, "DC": 44,
    "FL": -5, "GA": -1, "HI": 13, "ID": -18, "IL": 6, "IN": -9, "IA": -6, "KS": -8, "KY": -15,
    "LA": -11, "ME": 4, "MD": 15, "MA": 14, "MI": 0, "MN": 3, "MS": -11, "MO": -9, "MT": -10,
    "NE": -10, "NV": -1, "NH": 2, "NJ": 4, "NM": 4, "NY": 8, "NC": -1, "ND": -18, "OH": -5,
    "OK": -17, "OR": 8, "PA": -1, "RI": 8, "SC": -8, "SD": -15, "TN": -14, "TX": -6, "UT": -11,
    "VT": 17, "VA": 3, "WA": 10, "WV": -21, "WI": 0, "WY": -23,
}

# Winner of each jurisdiction in the 2024 presidential election ("D" Harris / "R" Trump).
# Used for expected-flip math and as the reference ("current") electoral split.
PRESIDENT_2024_WINNER = {
    "AL": "R", "AK": "R", "AZ": "R", "AR": "R", "CA": "D", "CO": "D", "CT": "D", "DE": "D", "DC": "D",
    "FL": "R", "GA": "R", "HI": "D", "ID": "R", "IL": "D", "IN": "R", "IA": "R", "KS": "R", "KY": "R",
    "LA": "R", "ME": "D", "MD": "D", "MA": "D", "MI": "R", "MN": "D", "MS": "R", "MO": "R", "MT": "R",
    "NE": "R", "NV": "R", "NH": "D", "NJ": "D", "NM": "D", "NY": "D", "NC": "R", "ND": "R", "OH": "R",
    "OK": "R", "OR": "D", "PA": "R", "RI": "D", "SC": "R", "SD": "R", "TN": "R", "TX": "R", "UT": "R",
    "VT": "D", "VA": "D", "WA": "D", "WV": "R", "WI": "R", "WY": "R",
}


def days_to_election(today: date | None = None) -> int:
    today = today or date.today()
    return max(0, (ELECTION_DATE - today).days)
