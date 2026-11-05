"""The 56 Electoral College contests and their partisan lean from the 2020 and 2024 results."""
from __future__ import annotations

import numpy as np

from ..config import CONTEST_EVS, CONTEST_IDS, REGION_OF, contest_name
from ..history import NATIONAL, RESULTS


def relative_margins(cid: str) -> tuple[float, float]:
    """(2020, 2024) margin relative to the national margin, Democratic-positive points."""
    out = []
    for yr in (2020, 2024):
        d, r, _ = RESULTS[cid][yr]
        nd, nr = NATIONAL[yr]
        out.append((d - r) - (nd - nr))
    return out[0], out[1]


def winner(cid: str, yr: int) -> str:
    d, r, _ = RESULTS[cid][yr]
    return "D" if d > r else "R"


def contests(spec: dict) -> list[dict]:
    w24 = float(spec["lean"]["weight_2024"])
    trend = float(spec["lean"]["trend"])
    out = []
    for cid in CONTEST_IDS:
        r20, r24 = relative_margins(cid)
        lean = w24 * r24 + (1 - w24) * r20 + trend * (r24 - r20)
        out.append(dict(contest_id=cid, state=cid[:2], district=int(cid.split("-")[1]) if "-" in cid else None,
                        name=contest_name(cid), evs=CONTEST_EVS[cid], region=REGION_OF[cid[:2]],
                        rel20=round(r20, 2), rel24=round(r24, 2), shift=round(r24 - r20, 2), lean=round(lean, 2),
                        margin20=round(RESULTS[cid][2020][0] - RESULTS[cid][2020][1], 2),
                        margin24=round(RESULTS[cid][2024][0] - RESULTS[cid][2024][1], 2),
                        winner20=winner(cid, 2020), winner24=winner(cid, 2024), votes24=RESULTS[cid][2024][2]))
    return out


def trend_loadings(cs: list[dict]) -> np.ndarray:
    """Standardised 2020-to-2024 relative shift: states that moved together are likely to move together again."""
    s = np.array([c["shift"] for c in cs], dtype=float)
    return (s - s.mean()) / (s.std() or 1.0)
