"""The rebuild loop: calibrate -> research + revise (mocked LLM) -> guardrails -> versioned spec -> final run -> export."""
import copy
import json
from datetime import date

import pytest

from electionpredictions import llm, narrative, pipeline, revision
from electionpredictions.db import rows
from electionpredictions.export import export
from electionpredictions.model import store
from electionpredictions.sources import news

TODAY = date(2026, 11, 5)


@pytest.fixture(autouse=True)
def offline_news(monkeypatch):
    monkeypatch.setattr(news, "fetch", lambda q, limit=12: [dict(url=f"https://example.org/{abs(hash(q))}", title=f"Headline about {q}",
                                                                 source="Example", published="2026-11-04T12:00:00+00:00")])


def _fake(calls, harris_p=0.05):
    def ask_json_with(system, user, models, max_tokens=4000, timeout=300):
        calls.append(system[:40])
        d = json.loads(user.split("\n", 1)[1])
        if system.startswith("You are preparing the next update"):
            return dict(searches=[dict(query="Kamala Harris 2028 decision", why="She leads primary polls"), dict(query="  <script> ", why="junk")]), "m-research"
        if "chief modeler" in system:
            assert d["evidence"]["research"][0]["results"], "research results reach the decision"
            assert "new_polls_vs_expectations" in d and "midterm_2026" in d["evidence"]
            spec = copy.deepcopy(d["proposal"])
            spec["national"]["adjustment"] = 9.0                       # beyond bounds and step: must be limited
            spec["state_adjustments"] = {"NV": {"shift": -1.0, "reason": "Consistent Republican-leaning state polling."}}
            spec["third_party"]["p_run"] = 0.3
            for c in spec["nominees"]["D"]:
                if c["name"] == "Kamala Harris":
                    c["p"] = harris_p                                   # e.g. headlines say she ruled out a run
            return dict(title="Harris odds cut after she rules out a run", summary="The model lowers Harris's odds. I am an AI.",
                        reasons={"nominees.D": "Harris said she will not run.", "state_adjustments.NV": "State polling."},
                        storylines=[dict(title="Harris steps back", detail="Harris said she will not run in 2028.", leans="neutral", importance=3, since="2026-11-04"),
                                    dict(title="Midterm wave", detail="Democrats won the 2026 House vote.", leans="D", importance=2, since="2099-01-01"),
                                    "junk"],
                        spec=spec), "m-decide"
        if "national overview" in system:
            return dict(summary="Para one.\n\nPara two.", key_factors=["Approval"], nominations={"D": "Open.", "R": "Vance leads."}, watch="Polls."), "m-narr"
        return dict(overview="State text.", key_factors=["Lean"], watch="Polls."), "m-narr"
    return ask_json_with


def test_rebuild_without_key_calibrates(db, monkeypatch):
    monkeypatch.setattr(llm, "available", lambda: False)
    final = pipeline.rebuild(db, today=TODAY, n_sims=2000, seed=1, verbose=False)
    hist = store.history(db)
    assert [h["origin"] for h in hist] == ["calibration", "seed"]
    assert final["spec_version"] == hist[0]["version"]
    assert store.latest_basis(db)["implied"]["D"]        # the evidence the version was built on is stored
    # a second identical run creates no new version, and identical inputs give identical numbers
    again = pipeline.rebuild(db, today=TODAY, n_sims=2000, verbose=False)
    third = pipeline.rebuild(db, today=TODAY, n_sims=2000, verbose=False)
    assert len(store.history(db)) == 2
    assert again["ec"]["p_dem"] == third["ec"]["p_dem"]
    assert rows(db, "SELECT count(*) n FROM run_log")[0]["n"] >= 1


def test_rebuild_with_revision_applies_guardrails_and_logs(db, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "ask_json_with", _fake(calls))
    final = pipeline.rebuild(db, today=TODAY, n_sims=2000, seed=1, verbose=False)
    v, spec, origin = store.latest(db)
    assert origin == "revision" and final["spec_version"] == v
    assert spec["national"]["adjustment"] == 1.5                      # limited to the per-revision step
    assert spec["state_adjustments"]["NV"]["shift"] == -1.0
    assert spec["third_party"]["p_run"] == 0.3
    harris = next(c for c in spec["nominees"]["D"] if c["name"] == "Kamala Harris")
    assert harris["p"] < 0.1
    log = store.history(db)[0]
    assert log["title"].startswith("Harris odds cut") and "Guardrails limited" in log["summary"]
    assert "AI" not in log["summary"]                                 # self-references are scrubbed from published text
    assert log["model"] == "m-decide"
    reasons = {c["path"]: c["reason"] for c in log["changes"]}
    assert reasons["state_adjustments.NV"] == "State polling." and reasons["nominees.D.Kamala Harris.p"] == "Harris said she will not run."
    # research: the junk query is dropped, the real one stored with its results
    res = rows(db, "SELECT query, results FROM research")
    assert [r["query"] for r in res] == ["Kamala Harris 2028 decision"] and json.loads(res[0]["results"])
    # storylines: cleaned (junk dropped, future date fixed), most important first
    sl = revision.current_storylines(db)
    assert [s["title"] for s in sl] == ["Harris steps back", "Midterm wave"] and sl[1]["since"] == TODAY.isoformat()
    # narratives were written for the nation and competitive contests
    nar = narrative.load(db)
    assert nar["NATIONAL"]["nominations"]["R"] == "Vance leads." and any(k != "NATIONAL" for k in nar)

    # the same evidence again: no new revision call, no new version, and the revision's judgment persists
    n_decide = sum(1 for c in calls if "chief modeler" in c)
    pipeline.rebuild(db, today=TODAY, n_sims=2000, seed=1, verbose=False)
    assert sum(1 for c in calls if "chief modeler" in c) == n_decide
    v2, spec2, _ = store.latest(db)
    assert v2 == v and next(c for c in spec2["nominees"]["D"] if c["name"] == "Kamala Harris")["p"] < 0.1

    # export writes every file the site reads
    s = export(db, out_dir=tmp_path / "site", verbose=False)
    for f in ("summary.json", "states.json", "scenarios.json", "field.json", "polls.json", "model.json", "meta.json", "hegseth.json"):
        assert (tmp_path / "site" / f).exists(), f
    assert len(list((tmp_path / "site" / "states").glob("*.json"))) == 56
    assert s["model"]["origin"] == "revision" and s["overview"]["summary"].startswith("Para one")
    assert [x["title"] for x in s["storylines"]] == ["Harris steps back", "Midterm wave"]
    assert s["recent"] and s["revisions"][0]["version"] == v
    m = json.loads((tmp_path / "site" / "model.json").read_text())
    assert m["versions"][0]["changes"] and all("label" in c for c in m["versions"][0]["changes"])
    nv = json.loads((tmp_path / "site" / "states" / "NV.json").read_text())
    assert nv["adjustment"] == -1.0 and nv["breakdown"]["adjustment_reason"]


def test_new_evidence_moves_a_revised_spec_by_the_delta(db, monkeypatch):
    calls = []
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "ask_json_with", _fake(calls, harris_p=0.04))
    pipeline.rebuild(db, today=TODAY, n_sims=2000, seed=1, narrate=False, verbose=False)
    before = {c["name"]: c["p"] for c in store.latest(db)[1]["nominees"]["D"]}
    # a new primary poll where Buttigieg surges; no key now, so only calibration runs
    db.execute("INSERT INTO primary_polls (poll_id, party, pollster, start_date, end_date, sample_size, population, shares, source) VALUES "
               "('d2','D','Marist','2026-11-03','2026-11-04',1200,'RV',?, 't')", (json.dumps({"Kamala Harris": 20, "Gavin Newsom": 18, "Pete Buttigieg": 30}),))
    db.commit()
    monkeypatch.setattr(llm, "available", lambda: False)
    pipeline.rebuild(db, today=TODAY, n_sims=2000, seed=1, narrate=False, verbose=False)
    after = {c["name"]: c["p"] for c in store.latest(db)[1]["nominees"]["D"]}
    assert after["Pete Buttigieg"] > before["Pete Buttigieg"]          # the new evidence moves the field...
    assert after["Kamala Harris"] < 0.1                                # ...without undoing the revision's judgment


def test_revision_failure_falls_back(db, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("gateway down")
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "ask_json_with", boom)
    pipeline.rebuild(db, today=TODAY, n_sims=2000, seed=1, narrate=False, verbose=False)
    assert store.latest(db)[2] == "calibration"
    assert rows(db, "SELECT ok FROM runs WHERE stage='revision'")[0]["ok"] == 0


def test_model_chain_falls_through(monkeypatch):
    tried = []

    def complete(system, user, model, **k):
        tried.append(model)
        if model == "bad":
            raise llm.ModelError("bad: HTTP 403")
        if model == "garbled":
            return "no json here"
        return '{"ok": true}'
    monkeypatch.setattr(llm, "complete", complete)
    out, model = llm.ask_json_with("s", "u", ["bad", "garbled", "good"])
    assert out == {"ok": True} and model == "good" and tried == ["bad", "garbled", "garbled", "good"]


def test_prompts_forbid_mentioning_ai():
    for text in (revision.SYSTEM, revision.RESEARCH_SYSTEM + revision.VOICE, narrative.VOICE):
        assert "artificial intelligence" in text or "Never mention" in text
    assert revision.scrub("Newsom leads. As an AI, I think so.", 100) == "Newsom leads."
