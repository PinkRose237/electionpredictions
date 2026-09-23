"""The AI decision layer, exercised against a fake OpenCode endpoint (no network)."""
import json

from electionpredictions.db import connect, rows
from electionpredictions.sources import ai


class _Resp:
    def __init__(self, status, payload=None, text=""):
        self.status_code, self._payload, self.text = status, payload, text
        self.ok = 200 <= status < 300

    def json(self):
        return self._payload


def _setup(tmp_path):
    con = connect(tmp_path / "t.db")
    con.execute("INSERT INTO races (race_id, chamber, state, district, special, name, incumbent, incumbent_party, incumbent_running, holder_party, pvi) VALUES ('GA-SEN','senate','GA',NULL,0,'Georgia Senate','Jon Ossoff','D',1,'D',-1)")
    con.execute("INSERT INTO candidates (race_id, name, party, is_incumbent, major, receipts) VALUES ('GA-SEN','Jon Ossoff','D',1,1,7.7e7), ('GA-SEN','Mike Collins','R',0,1,7.4e6)")
    con.execute("INSERT INTO forecasts (run_date, race_id, p_dem, margin, sd, detail) VALUES ('2026-09-22','GA-SEN',0.93,8.0,5.3,?)",
                (json.dumps({"label": "Likely D", "notes": [], "p_dem_analytic": 0.93, "sigma_total": 5.3, "fund": {"margin": 10.5}, "poll": {"margin": 7.1, "n_polls": 7}, "rating": {"label": "Likely D", "margin": 9.0, "n": 10}}),))
    con.execute("INSERT INTO chamber_forecasts (run_date, chamber, p_dem, dem_seats_mean, dem_seats_p10, dem_seats_p90, detail) VALUES ('2026-09-22','senate',0.68,51.5,48,54,'{}')")
    con.commit()
    return con


RACE_JSON = {"margin": 7.5, "sd": 5, "p_dem": 0.92, "label": "Likely D", "confidence": "medium",
             "key_factors": ["Ossoff leads every public poll", "10-to-1 money edge"], "rationale": "Polls and money favour the incumbent.",
             "watch": "A late tightening in suburban Atlanta.", "overview": "Para one.\n\nPara two."}
NAT_JSON = {"environment_adjustment": -0.5, "uncertainty_multiplier": 1.1, "summary": "S1.\n\nS2.", "key_factors": ["Generic ballot D+8"],
            "chambers": {"house": "h", "senate": "s", "governor": "g"}}


def test_parse_json_tolerates_fences_and_preamble():
    assert ai.parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert ai.parse_json('Sure, here it is: {"a": {"b": 2}} thanks') == {"a": {"b": 2}}


def test_validation_clamps_and_fills():
    d = ai.validate_race_decision({"margin": 4, "sd": 50, "p_dem": 0.7, "label": "Weird", "key_factors": "x"}, 3.0)
    assert d["sd"] == 12.0 and d["label"] == "Lean D" and d["key_factors"] == [] and d["baseline_margin"] == 3.0
    n = ai.validate_national_decision({"environment_adjustment": 9, "uncertainty_multiplier": 0.1})
    assert n["environment_adjustment"] == 3.0 and n["uncertainty_multiplier"] == 0.7


def test_decisions_cached_by_evidence_hash(tmp_path, monkeypatch):
    con = _setup(tmp_path)
    monkeypatch.setattr(ai, "OPENCODE_API_KEY", "k")
    calls = []

    def fake_post(path, body, timeout=180):
        calls.append(path)
        sys_prompt = body["messages"][0]["content"] if "messages" in body else body["instructions"]
        payload = NAT_JSON if "national picture" in sys_prompt else RACE_JSON
        return _Resp(200, {"choices": [{"message": {"content": "```json\n" + json.dumps(payload) + "\n```"}}]})

    monkeypatch.setattr(ai, "_post", fake_post)
    stats = ai.load(con, verbose=False)
    assert stats["decided"] == 1 and stats["national"] and stats["errors"] == 0 and len(calls) == 2
    per_race, nat = ai.decisions(con)
    assert per_race["GA-SEN"]["margin"] == 7.5 and per_race["GA-SEN"]["baseline_margin"] == 8.0
    assert nat["environment_adjustment"] == -0.5 and nat["uncertainty_multiplier"] == 1.1
    stats = ai.load(con, verbose=False)  # nothing changed -> no new calls
    assert stats["decided"] == 0 and len(calls) == 2


def test_bad_key_and_missing_key(tmp_path, monkeypatch):
    con = _setup(tmp_path)
    monkeypatch.setattr(ai, "OPENCODE_API_KEY", "")
    assert ai.load(con, verbose=False) == {"skipped": True}
    monkeypatch.setattr(ai, "OPENCODE_API_KEY", "bad")
    monkeypatch.setattr(ai, "_post", lambda path, body, timeout=180: _Resp(401, text="nope"))
    assert ai.load(con, verbose=False)["decided"] == 0
    calls = []
    monkeypatch.setattr(ai, "_post", lambda path, body, timeout=180: (calls.append(path), _Resp(402, text="Insufficient account funds"))[1])
    stats = ai.load(con, verbose=False)   # no credit: fail fast after the probe call, no per-race churn
    assert stats["decided"] == 0 and stats["errors"] == 0 and len(calls) == 1
    assert rows(con, "SELECT count(*) n FROM ai_decisions")[0]["n"] == 0
