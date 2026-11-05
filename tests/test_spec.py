"""Guardrails of the self-revising model specification."""
import copy

from electionpredictions.model import spec as S


def test_seed_is_valid_and_stable():
    s = S.seed()
    assert S.validate(s, s) == s
    assert S.diff(s, s) == []
    assert S.fingerprint(s) == S.fingerprint(copy.deepcopy(s))


def test_bounds_and_step_limits():
    prev = S.seed()
    cand = copy.deepcopy(prev)
    cand["national"]["poll_trust"] = 99          # out of range and far beyond the step
    cand["uncertainty"]["tail_df"] = 2.2          # below range
    cand["lean"]["weight_2024"] = "nonsense"     # rejected
    notes = []
    out = S.validate(cand, prev, notes)
    assert out["national"]["poll_trust"] == prev["national"]["poll_trust"] + S.BOUNDS["national.poll_trust"][2]
    assert out["uncertainty"]["tail_df"] == 3 and isinstance(out["uncertainty"]["tail_df"], int)
    assert out["lean"]["weight_2024"] == prev["lean"]["weight_2024"]
    assert len(notes) == 3


def test_nominees_normalised_capped_and_pooled():
    prev = S.seed()
    names = [f"Person {i}" for i in range(15)]
    cand = copy.deepcopy(prev)
    cand["nominees"]["D"] = [dict(name=n, p=1.0, effect=9.0, home_state="PA") for n in names] + [dict(name="Other", p=5.0, effect=3, home_state="CA")]
    cand["nominees"]["R"] = [dict(name="Bad", p=-1), "junk", dict(name="Solo", p=0.5, effect=-1.0, home_state="ZZ")]
    out = S.validate(cand, prev)
    d = out["nominees"]["D"]
    assert len([c for c in d if c["name"] != "Other"]) == S.MAX_NOMINEES
    assert abs(sum(c["p"] for c in d) - 1) < 1e-3
    other = next(c for c in d if c["name"] == "Other")
    assert other["effect"] == 0 and other["home_state"] is None
    assert all(c["effect"] == S.EFFECT_BOUNDS[1] for c in d if c["name"] != "Other")   # new names: bound only
    r = out["nominees"]["R"]
    assert [c["name"] for c in r] == ["Solo"] and r[0]["p"] == 1.0 and r[0]["home_state"] is None


def test_effect_step_limit_against_previous():
    prev = S.seed()
    prev["nominees"]["D"] = [dict(name="A", p=0.6, effect=0.0, home_state=None), dict(name="Other", p=0.4, effect=0.0, home_state=None)]
    cand = copy.deepcopy(prev)
    cand["nominees"]["D"][0]["effect"] = 4.5
    out = S.validate(cand, prev)
    assert out["nominees"]["D"][0]["effect"] == S.EFFECT_STEP


def test_state_adjustments_guarded():
    prev = S.seed()
    cand = copy.deepcopy(prev)
    cand["state_adjustments"] = {"PA": {"shift": 9, "reason": "x"}, "XX": {"shift": 1}, "ME-2": -1.5}
    for i, st in enumerate(["AZ", "GA", "MI", "NV", "NC", "WI", "TX", "FL", "OH", "IA", "NH", "MN", "VA"]):
        cand["state_adjustments"][st] = {"shift": 0.1 + i * 0.1, "reason": "r"}
    notes = []
    out = S.validate(cand, prev, notes)
    sa = out["state_adjustments"]
    assert "XX" not in sa and len(sa) == S.MAX_STATE_ADJ
    assert sa["PA"]["shift"] == S.STATE_ADJ_STEP          # 9 -> bound 4 -> step 2 from 0
    assert any("unknown contest" in n for n in notes)


def test_diff_labels_changes():
    a = S.seed()
    b = copy.deepcopy(a)
    b["national"]["adjustment"] = 1.0
    b["nominees"]["R"] = [dict(name="X", p=0.7, effect=1.0, home_state="OH"), dict(name="Other", p=0.3, effect=0.0, home_state=None)]
    paths = {c["path"] for c in S.diff(a, b)}
    assert {"national.adjustment", "nominees.R.X.p", "nominees.R.X.effect", "nominees.R.Other.p"} <= paths
    assert S.fingerprint(a) != S.fingerprint(b)
