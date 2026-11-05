"""The rebuild loop: calibrate -> revise (mocked LLM) -> guardrails -> versioned spec -> final run -> export."""
import copy
import json
from datetime import date

from electionpredictions import llm, narrative, pipeline, revision
from electionpredictions.db import rows
from electionpredictions.export import export
from electionpredictions.model import store

TODAY = date(2026, 11, 5)


def _fake_revision(calls):
    def ask_json(system, user, max_tokens=4000):
        calls.append(system[:40])
        d = json.loads(user.split("\n", 1)[1])
        if "chief modeler" in system:
            spec = copy.deepcopy(d["proposal"])
            spec["national"]["adjustment"] = 9.0                       # beyond bounds and step: must be limited
            spec["state_adjustments"] = {"NV": {"shift": -1.0, "reason": "Consistent Republican-leaning state polling."}}
            for c in spec["nominees"]["D"]:
                if c["name"] == "Kamala Harris":
                    c["p"] = 0.05                                       # e.g. headlines say she ruled out a run
            return dict(title="Harris odds cut after she rules out a run", summary="The model lowers Harris's odds.",
                        reasons={"nominees.D": "Harris said she will not run.", "state_adjustments.NV": "State polling."}, spec=spec)
        if "national overview" in system:
            return dict(summary="Para one.\n\nPara two.", key_factors=["Approval"], nominations={"D": "Open.", "R": "Vance leads."}, watch="Polls.")
        return dict(overview="State text.", key_factors=["Lean"], watch="Polls.")
    return ask_json


def test_rebuild_without_key_calibrates(db, monkeypatch):
    monkeypatch.setattr(llm, "available", lambda: False)
    final = pipeline.rebuild(db, today=TODAY, n_sims=2000, seed=1, verbose=False)
    hist = store.history(db)
    assert [h["origin"] for h in hist] == ["calibration", "seed"]
    assert final["spec_version"] == hist[0]["version"]
    # a second identical run creates no new version
    pipeline.rebuild(db, today=TODAY, n_sims=2000, seed=1, verbose=False)
    assert len(store.history(db)) == 2


def test_rebuild_with_revision_applies_guardrails_and_logs(db, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "ask_json", _fake_revision(calls))
    final = pipeline.rebuild(db, today=TODAY, n_sims=2000, seed=1, verbose=False)
    v, spec, origin = store.latest(db)
    assert origin == "revision" and final["spec_version"] == v
    assert spec["national"]["adjustment"] == 1.5                      # limited to the per-revision step
    assert spec["state_adjustments"]["NV"]["shift"] == -1.0
    harris = next(c for c in spec["nominees"]["D"] if c["name"] == "Kamala Harris")
    assert harris["p"] < 0.1
    log = store.history(db)[0]
    assert log["title"].startswith("Harris odds cut") and "Guardrails limited" in log["summary"]
    reasons = {c["path"]: c["reason"] for c in log["changes"]}
    assert reasons["state_adjustments.NV"] == "State polling." and reasons["nominees.D.Kamala Harris.p"] == "Harris said she will not run."
    # narratives were written for the nation and competitive contests
    nar = narrative.load(db)
    assert nar["NATIONAL"]["nominations"]["R"] == "Vance leads." and any(k != "NATIONAL" for k in nar)
    # the same evidence again: no new revision call, no new version
    n_calls = sum(1 for c in calls if "chief modeler" in c)
    pipeline.rebuild(db, today=TODAY, n_sims=2000, seed=1, verbose=False)
    assert sum(1 for c in calls if "chief modeler" in c) >= n_calls
    # export writes every file the site reads
    s = export(db, out_dir=tmp_path / "site", verbose=False)
    for f in ("summary.json", "states.json", "scenarios.json", "field.json", "polls.json", "model.json", "meta.json"):
        assert (tmp_path / "site" / f).exists(), f
    assert len(list((tmp_path / "site" / "states").glob("*.json"))) == 56
    assert s["model"]["origin"] == "revision" and s["overview"]["summary"].startswith("Para one")
    m = json.loads((tmp_path / "site" / "model.json").read_text())
    assert m["versions"][0]["changes"] and all("label" in c for c in m["versions"][0]["changes"])
    nv = json.loads((tmp_path / "site" / "states" / "NV.json").read_text())
    assert nv["adjustment"] == -1.0 and nv["breakdown"]["adjustment_reason"]


def test_revision_failure_falls_back(db, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("gateway down")
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "ask_json", boom)
    pipeline.rebuild(db, today=TODAY, n_sims=2000, seed=1, narrate=False, verbose=False)
    assert store.latest(db)[2] == "calibration"
    assert rows(db, "SELECT ok FROM runs WHERE stage='revision'")[0]["ok"] == 0


def test_prompt_forbids_mentioning_ai():
    for text in (revision.SYSTEM, narrative.VOICE):
        assert "Never mention" in text and ("artificial intelligence" in text)
