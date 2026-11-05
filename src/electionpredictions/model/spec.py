"""The model specification: every tunable choice the forecast makes, as one JSON document.

The forecast engine (engine.py) is a fixed machine; *what* it computes is decided by the spec. The spec is
re-derived on every run (calibrate.py), may then be revised against the latest evidence (revision.py), and is
stored as a new numbered version whenever it changes, with a changelog. That is how the model rebuilds itself
as the campaign develops: weights, uncertainty, the candidate field, candidate strength and state-specific
adjustments all move with the evidence, inside the guardrails defined here.

Guardrails:
- every numeric parameter has hard bounds (BOUNDS) and a largest step one revision may take (relative to the
  previous published version), so a single run cannot swing the model wildly;
- nominee probabilities are re-normalised and capped at MAX_NOMINEES per party (the rest is pooled as "Other");
- candidate effects are bounded at +/-5 points, state adjustments at +/-4 points, at most MAX_STATE_ADJ of them.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from typing import Any, Optional

from ..config import CONTEST_EVS, STATES

SCHEMA = 1
MAX_NOMINEES = 12
MAX_STATE_ADJ = 12
OTHER = "Other"

# path: (low, high, largest change per revision)
BOUNDS: dict[str, tuple[float, float, float]] = {
    "lean.weight_2024": (0.5, 1.0, 0.15),
    "lean.trend": (0.0, 0.5, 0.15),
    "national.poll_trust": (0.25, 2.0, 0.5),
    "national.adjustment": (-3.0, 3.0, 1.5),
    "fundamentals.intercept": (-4.0, 2.0, 1.0),
    "fundamentals.approval_coef": (0.0, 0.3, 0.06),
    "fundamentals.econ_coef": (0.0, 2.0, 0.5),
    "polls.half_life_days": (14.0, 180.0, 45.0),
    "polls.state_weight": (0.25, 2.0, 0.5),
    "polls.candidate_prior_sd": (0.5, 5.0, 1.5),
    "polls.third_party_weight": (0.0, 1.0, 0.3),
    "ratings.weight": (0.0, 0.6, 0.2),
    "uncertainty.national_mult": (0.6, 1.6, 0.3),
    "uncertainty.state_mult": (0.6, 1.6, 0.3),
    "uncertainty.region_sd": (0.5, 3.0, 0.75),
    "uncertainty.trend_sd": (0.0, 3.0, 0.75),
    "uncertainty.tail_df": (3.0, 30.0, 10.0),
    "candidates.home_state_bonus": (0.0, 4.0, 1.0),
}
INT_PATHS = {"polls.half_life_days", "uncertainty.tail_df"}
EFFECT_BOUNDS, EFFECT_STEP = (-5.0, 5.0), 2.0
STATE_ADJ_BOUNDS, STATE_ADJ_STEP = (-4.0, 4.0), 2.0

# Plain-language descriptions (used on the site's model page and in the revision prompt).
DESCRIPTIONS = {
    "lean.weight_2024": "Weight on 2024 (vs 2020) when measuring each state's lean relative to the nation",
    "lean.trend": "How much of each state's 2020-to-2024 relative shift is projected forward",
    "national.poll_trust": "Trust in national trial-heat polls relative to the time-to-election default",
    "national.adjustment": "Judgment shift to the national environment, points (Democratic-positive)",
    "fundamentals.intercept": "Baseline margin for the White House party in an open-seat race, points",
    "fundamentals.approval_coef": "Points of White House-party margin per point of presidential net approval",
    "fundamentals.econ_coef": "Weight of the economic index (inflation, unemployment trend, real wages)",
    "polls.half_life_days": "Half-life of a poll's weight, days",
    "polls.state_weight": "Weight of state polls when estimating a state's lean relative to the nation",
    "polls.candidate_prior_sd": "How far polling may pull a candidate's strength from zero (prior s.d., points)",
    "polls.third_party_weight": "Weight of polls that include an independent candidate",
    "ratings.weight": "Weight of published expert ratings on a state's margin",
    "uncertainty.national_mult": "Scale of the shared national error relative to the time-to-election default",
    "uncertainty.state_mult": "Scale of state-specific error relative to the time-to-election default",
    "uncertainty.region_sd": "Shared regional error, points",
    "uncertainty.trend_sd": "Error shared by states along the 2020-to-2024 realignment axis, points",
    "uncertainty.tail_df": "Degrees of freedom of the fat-tailed error (lower = fatter tails)",
    "candidates.home_state_bonus": "Home-state advantage for a nominee, points",
}


def seed() -> dict:
    """Version 1: the hand-built starting point before any data is seen."""
    return dict(
        schema=SCHEMA,
        lean=dict(weight_2024=0.75, trend=0.0),
        national=dict(poll_trust=1.0, adjustment=0.0),
        fundamentals=dict(intercept=-1.0, approval_coef=0.15, econ_coef=1.0),
        polls=dict(half_life_days=60, state_weight=1.0, candidate_prior_sd=2.0, third_party_weight=0.5),
        ratings=dict(weight=0.3),
        uncertainty=dict(national_mult=1.0, state_mult=1.0, region_sd=1.5, trend_sd=1.5, tail_df=6),
        candidates=dict(home_state_bonus=2.0),
        nominees={"D": [dict(name=OTHER, p=1.0, effect=0.0, home_state=None)],
                  "R": [dict(name=OTHER, p=1.0, effect=0.0, home_state=None)]},
        state_adjustments={},
    )


def get(spec: dict, path: str) -> Any:
    cur = spec
    for k in path.split("."):
        cur = cur[k]
    return cur


def put(spec: dict, path: str, value) -> None:
    keys = path.split(".")
    cur = spec
    for k in keys[:-1]:
        cur = cur.setdefault(k, {})
    cur[keys[-1]] = value


def _num(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _clamp(v: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, v))


def validate(candidate: dict, previous: dict, notes: Optional[list[str]] = None) -> dict:
    """Return a clean spec built from `candidate`, falling back to `previous` for anything missing or invalid,
    with every guardrail applied. `notes` collects what was clamped or rejected."""
    notes = notes if notes is not None else []
    out = copy.deepcopy(previous)
    out["schema"] = SCHEMA
    for path, (lo, hi, step) in BOUNDS.items():
        try:
            raw = get(candidate, path)
        except (KeyError, TypeError):
            continue
        v = _num(raw)
        if v is None:
            notes.append(f"{path}: not a number, kept {get(previous, path)}")
            continue
        prev = _num(get(previous, path))
        target = _clamp(v, lo, hi)
        if prev is not None:
            target = _clamp(target, prev - step, prev + step)
        if abs(target - v) > 1e-9:
            notes.append(f"{path}: {v:g} limited to {target:g}")
        put(out, path, int(round(target)) if path in INT_PATHS else round(target, 4))

    # nominees
    for party in ("D", "R"):
        prev_by = {c["name"]: c for c in previous["nominees"][party]}
        cand_list = (candidate.get("nominees") or {}).get(party) if isinstance(candidate.get("nominees"), dict) else None
        if not isinstance(cand_list, list) or not cand_list:
            continue
        clean_list, seen = [], set()
        for c in cand_list:
            if not isinstance(c, dict):
                continue
            name = str(c.get("name") or "").strip()
            p = _num(c.get("p"))
            if not name or p is None or p < 0 or name in seen:
                continue
            seen.add(name)
            eff = _num(c.get("effect"))
            prev_eff = (prev_by.get(name) or {}).get("effect")
            eff = 0.0 if eff is None else _clamp(eff, *EFFECT_BOUNDS)
            if prev_eff is not None:
                lim = _clamp(eff, prev_eff - EFFECT_STEP, prev_eff + EFFECT_STEP)
                if abs(lim - eff) > 1e-9:
                    notes.append(f"nominees.{party}.{name}.effect: {eff:+.1f} limited to {lim:+.1f}")
                eff = lim
            home = c.get("home_state")
            home = home if home in STATES else (prev_by.get(name) or {}).get("home_state")
            if name == OTHER:
                eff, home = 0.0, None
            clean_list.append(dict(name=name, p=p, effect=round(eff, 2), home_state=home))
        if not clean_list:
            continue
        clean_list.sort(key=lambda c: -c["p"])
        keep = [c for c in clean_list if c["name"] != OTHER][:MAX_NOMINEES]
        rest = sum(c["p"] for c in clean_list if c not in keep)
        total = sum(c["p"] for c in keep) + rest
        if total <= 0:
            notes.append(f"nominees.{party}: probabilities sum to zero, kept previous")
            continue
        keep = [dict(c, p=round(c["p"] / total, 4)) for c in keep]
        if rest / total >= 0.0005:
            keep.append(dict(name=OTHER, p=round(rest / total, 4), effect=0.0, home_state=None))
        out["nominees"][party] = keep

    # state adjustments
    sa = candidate.get("state_adjustments")
    if isinstance(sa, dict):
        new = {}
        prev_sa = previous.get("state_adjustments") or {}
        for cid, v in sa.items():
            if cid not in CONTEST_EVS:
                notes.append(f"state_adjustments.{cid}: unknown contest, dropped")
                continue
            shift = _num(v.get("shift") if isinstance(v, dict) else v)
            if shift is None or abs(shift) < 0.05:
                continue
            shift = _clamp(shift, *STATE_ADJ_BOUNDS)
            ps = (prev_sa.get(cid) or {}).get("shift", 0.0)
            lim = _clamp(shift, ps - STATE_ADJ_STEP, ps + STATE_ADJ_STEP)
            if abs(lim - shift) > 1e-9:
                notes.append(f"state_adjustments.{cid}: {shift:+.1f} limited to {lim:+.1f}")
            reason = str(v.get("reason") or "").strip()[:240] if isinstance(v, dict) else ""
            new[cid] = dict(shift=round(lim, 2), reason=reason or (prev_sa.get(cid) or {}).get("reason", ""))
        if len(new) > MAX_STATE_ADJ:
            notes.append(f"state_adjustments: {len(new)} given, kept the {MAX_STATE_ADJ} largest")
            new = dict(sorted(new.items(), key=lambda kv: -abs(kv[1]["shift"]))[:MAX_STATE_ADJ])
        out["state_adjustments"] = new
    return out


def flatten(spec: dict) -> dict[str, Any]:
    """Scalar view of a spec (for diffs and hashing)."""
    out = {p: get(spec, p) for p in BOUNDS}
    for party in ("D", "R"):
        for c in spec["nominees"][party]:
            out[f"nominees.{party}.{c['name']}.p"] = c["p"]
            if c["name"] != OTHER:
                out[f"nominees.{party}.{c['name']}.effect"] = c["effect"]
    for cid, v in (spec.get("state_adjustments") or {}).items():
        out[f"state_adjustments.{cid}"] = v["shift"]
    return out


def diff(old: Optional[dict], new: dict, min_p: float = 0.005) -> list[dict]:
    """List of {path, from, to}; small nominee-probability wiggles (< min_p) are ignored."""
    a = flatten(old) if old else {}
    b = flatten(new)
    out = []
    for k in sorted(set(a) | set(b)):
        x, y = a.get(k), b.get(k)
        if x == y:
            continue
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            tol = min_p if k.endswith(".p") else 1e-6
            if abs(x - y) < tol:
                continue
        elif k.endswith(".p") and (x or 0) < min_p and (y or 0) < min_p:
            continue
        out.append({"path": k, "from": x, "to": y})
    return out


def fingerprint(spec: dict) -> str:
    """Stable hash of a spec, rounded so float noise does not create new versions."""
    flat = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in flatten(spec).items()}
    homes = {f"{p}:{c['name']}": c.get("home_state") for p in ("D", "R") for c in spec["nominees"][p]}
    return hashlib.sha1(json.dumps([flat, homes], sort_keys=True, default=str).encode()).hexdigest()[:16]
