"""Project-wide configuration and constants for the 2028 presidential model."""
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
DB_PATH = DATA_DIR / "president2028.db"
SITE_DIR = ROOT / "site"
SITE_DATA_DIR = SITE_DIR / "data"
# The retired 2026 midterm site (admin-only): frozen pages + data, still fed by the results snapshot tools.
ARCHIVE_2026_DIR = SITE_DIR / "archive" / "2026"
ARCHIVE_2026_DATA_DIR = ARCHIVE_2026_DIR / "data"

CYCLE = 2028
ELECTION_DATE = date(2028, 11, 7)
INCUMBENT_PARTY = "R"          # party holding the White House going into 2028 (open seat: Trump is term-limited)

USER_AGENT = os.environ.get(
    "EP_USER_AGENT",
    "electionpredictions/0.2 (open-source presidential forecast; https://github.com/PinkRose237/electionpredictions)",
)
FEC_API_KEY = os.environ.get("FEC_API_KEY", "DEMO_KEY")
# Model-revision layer via OpenCode (OpenAI-compatible). Default: the OpenCode Go subscription gateway with Z.AI
# GLM 5.3 Flash. Pay-as-you-go Zen is https://opencode.ai/zen/v1 (needs credit).
OPENCODE_API_KEY = os.environ.get("OPENCODE_API_KEY") or os.environ.get("OPENCODE_ZEN_API_KEY", "")
AI_MODEL = os.environ.get("AI_MODEL") or "glm-5.3-flash"
AI_BASE_URL = os.environ.get("AI_BASE_URL") or "https://opencode.ai/zen/go/v1"

# Cache TTLs in seconds
TTL_WIKI = int(os.environ.get("EP_TTL_WIKI", 6 * 3600))
TTL_MARKETS = int(os.environ.get("EP_TTL_MARKETS", 1 * 3600))
TTL_FEC = int(os.environ.get("EP_TTL_FEC", 24 * 3600))
TTL_NEWS = int(os.environ.get("EP_TTL_NEWS", 3 * 3600))
TTL_ECON = int(os.environ.get("EP_TTL_ECON", 12 * 3600))

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
    "DC": "District of Columbia",
}
STATE_BY_NAME = {v: k for k, v in STATES.items()}
DC_NAME = "District of Columbia"

# Census regions, used for correlated regional error in the simulation.
REGIONS = {
    "Northeast": ["CT", "ME", "MA", "NH", "RI", "VT", "NJ", "NY", "PA"],
    "Midwest": ["IL", "IN", "MI", "OH", "WI", "IA", "KS", "MN", "MO", "NE", "ND", "SD"],
    "South": ["DE", "FL", "GA", "MD", "NC", "SC", "VA", "WV", "AL", "KY", "MS", "TN", "AR", "LA", "OK", "TX", "DC"],
    "West": ["AZ", "CO", "ID", "MT", "NV", "NM", "UT", "WY", "AK", "CA", "HI", "OR", "WA"],
}
REGION_OF = {st: r for r, sts in REGIONS.items() for st in sts}

# Electoral votes for 2028 (2020 census apportionment). Maine and Nebraska award two electors statewide
# and one per congressional district; every other jurisdiction is winner-take-all. Total 538, 270 to win.
STATE_EVS = {
    "AL": 9, "AK": 3, "AZ": 11, "AR": 6, "CA": 54, "CO": 10, "CT": 7, "DE": 3, "DC": 3,
    "FL": 30, "GA": 16, "HI": 4, "ID": 4, "IL": 19, "IN": 11, "IA": 6, "KS": 6, "KY": 8,
    "LA": 8, "ME": 4, "MD": 10, "MA": 11, "MI": 15, "MN": 10, "MS": 6, "MO": 10, "MT": 4,
    "NE": 5, "NV": 6, "NH": 4, "NJ": 14, "NM": 5, "NY": 28, "NC": 16, "ND": 3, "OH": 17,
    "OK": 7, "OR": 8, "PA": 19, "RI": 4, "SC": 9, "SD": 3, "TN": 11, "TX": 40, "UT": 6,
    "VT": 3, "VA": 13, "WA": 12, "WV": 4, "WI": 10, "WY": 3,
}
SPLIT_STATES = {"ME": ["ME-1", "ME-2"], "NE": ["NE-1", "NE-2", "NE-3"]}
TOTAL_EVS = 538
EVS_TO_WIN = 270


def contest_evs() -> dict[str, int]:
    """Electors per contest: 51 statewide contests (ME and NE carry only their 2 at-large electors) + 5 districts."""
    out = {}
    for st, ev in STATE_EVS.items():
        if st in SPLIT_STATES:
            out[st] = 2
            for d in SPLIT_STATES[st]:
                out[d] = 1
        else:
            out[st] = ev
    return out


CONTEST_EVS = contest_evs()
CONTEST_IDS = sorted(CONTEST_EVS, key=lambda c: (c[:2], c))


def contest_state(cid: str) -> str:
    return cid[:2]


def contest_name(cid: str) -> str:
    st = STATES[cid[:2]]
    if "-" in cid:
        n = cid.split("-")[1]
        return f"{st} {n}{'st' if n == '1' else 'nd' if n == '2' else 'rd'} District"
    return st


def days_to_election(today: date | None = None) -> int:
    today = today or date.today()
    return max(0, (ELECTION_DATE - today).days)
