"""Non-poll inputs: partisan lean + national environment + incumbency + money, and expert ratings."""
from __future__ import annotations

import math
from statistics import mean
from typing import Optional

from ..util import rating_label

PARAMS = {
    "house": dict(env_w=1.0, inc_adv=2.0, lean_w=1.0, money_w=1.0, prior_sd=7.0, floor=3.0),
    "senate": dict(env_w=0.9, inc_adv=3.0, lean_w=1.0, money_w=1.0, prior_sd=6.5, floor=2.5),
    "governor": dict(env_w=0.5, inc_adv=4.0, lean_w=0.75, money_w=0.8, prior_sd=8.0, floor=3.0),
}
RATING_MARGIN = {0: 0.0, 1: 2.5, 2: 5.0, 3: 9.0, 4: 16.0}
RATING_SD = 6.3              # implied by historical accuracy of Lean/Likely/Safe calls
IMPLICIT_SAFE_MARGIN = 20.0  # seats no rater bothers to list
RATING_WEIGHT = 0.6          # share of the prior taken from expert ratings when they exist


def fundamentals(race: dict, dem: Optional[dict], rep: Optional[dict], generic_margin: float) -> dict:
    P = PARAMS[race["chamber"]]
    lean = race["pvi"] if race["pvi"] is not None else 0.0
    env = P["env_w"] * generic_margin
    inc = 0.0
    if race["incumbent_running"]:
        if dem and dem["is_incumbent"]:
            inc = P["inc_adv"]
        elif rep and rep["is_incumbent"]:
            inc = -P["inc_adv"]
    money = 0.0
    d_r = (dem or {}).get("receipts") or 0.0
    r_r = (rep or {}).get("receipts") or 0.0
    # outside spending (independent expenditures) counts for the side it helps: support for me + attacks on my opponent
    d_r += ((dem or {}).get("ie_support") or 0.0) + ((rep or {}).get("ie_oppose") or 0.0)
    r_r += ((rep or {}).get("ie_support") or 0.0) + ((dem or {}).get("ie_oppose") or 0.0)
    if dem and rep and (d_r + r_r) > 200_000:
        money = P["money_w"] * max(-3.0, min(3.0, 1.5 * math.log10(max(d_r, 25_000) / max(r_r, 25_000))))
    margin = P["lean_w"] * lean + env + inc + money
    return dict(margin=margin, lean=P["lean_w"] * lean, environment=env, incumbency=inc, money=money,
                sd=P["prior_sd"], floor=P["floor"])


def rating_summary(ratings: list[dict], holder_party: Optional[str], dem_side_party: str = "D",
                   fund_margin: Optional[float] = None) -> Optional[dict]:
    """Average the expert ratings into a D-positive score (-4..4) and implied margin.

    Seats no rater lists are implicitly safe. Usually that means safe for the holder, but after
    mid-decade redistricting a seat can be safe for the *other* party (e.g. CA-01, LA-06), so when
    the fundamentals point strongly the other way we follow the fundamentals instead."""
    if not ratings:
        fund_sign = 0 if fund_margin is None or abs(fund_margin) < 5 else (1 if fund_margin > 0 else -1)
        holder_sign = 1 if holder_party == "D" else -1 if holder_party == "R" else 0
        if fund_sign and holder_sign and fund_sign != holder_sign:
            s, mag, why = fund_sign, IMPLICIT_SAFE_MARGIN, "fundamentals"
        elif holder_sign:
            s, mag, why = holder_sign, (IMPLICIT_SAFE_MARGIN if fund_sign == holder_sign else 12.0), "holder"
        elif fund_sign:
            s, mag, why = fund_sign, IMPLICIT_SAFE_MARGIN, "fundamentals"
        else:
            return None
        party = "D" if s > 0 else "R"
        return dict(margin=s * mag, score=4.0 * s, n=0, implicit=True, label=f"Safe {party}", basis=why)
    ms, scores = [], []
    for r in ratings:
        party = r["party"]
        if party == "I":
            party = "D" if dem_side_party == "I" else "R"
        sign = 1 if party == "D" else -1 if party == "R" else 0
        ms.append(sign * RATING_MARGIN.get(r["level"], 0.0))
        scores.append(sign * r["level"])
    score = mean(scores)
    return dict(margin=mean(ms), score=score, n=len(ratings), implicit=False, label=rating_label(score))
