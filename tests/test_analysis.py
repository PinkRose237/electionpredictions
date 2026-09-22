"""The AI-brief stage, exercised against a fake OpenCode endpoint (no network)."""
from electionpredictions.db import connect, rows
from electionpredictions.sources import analysis


class _Resp:
    def __init__(self, status, payload=None, text=""):
        self.status_code, self._payload, self.text = status, payload, text
        self.ok = 200 <= status < 300

    def json(self):
        return self._payload


def _setup(tmp_path):
    con = connect(tmp_path / "t.db")
    con.execute("INSERT INTO races (race_id, chamber, state, district, special, name, incumbent, incumbent_party, incumbent_running, holder_party, pvi) VALUES ('GA-SEN','senate','GA',NULL,0,'Georgia Senate','Jon Ossoff','D',1,'D',-1)")
    con.execute("INSERT INTO candidates (race_id, name, party, is_incumbent, major) VALUES ('GA-SEN','Jon Ossoff','D',1,1), ('GA-SEN','Mike Collins','R',0,1)")
    con.execute("INSERT INTO forecasts (run_date, race_id, p_dem, margin, sd, detail) VALUES ('2026-09-22','GA-SEN',0.93,8.0,5.0,'{\"label\":\"Likely D\",\"notes\":[]}')")
    con.commit()
    return con


def test_brief_generation_caching_and_endpoint_fallback(tmp_path, monkeypatch):
    con = _setup(tmp_path)
    monkeypatch.setattr(analysis, "OPENCODE_API_KEY", "test-key")
    monkeypatch.setattr(analysis, "AI_MODEL", "muse-spark-1.3-contributor-free")
    calls = []

    def fake_post(path, body, timeout=120):
        calls.append((path, body["model"]))
        if path == "chat/completions":
            return _Resp(404, text="no such endpoint")
        return _Resp(200, {"output": [{"content": [{"type": "output_text", "text": "Paragraph one.\n\nParagraph two."}]}]})

    monkeypatch.setattr(analysis, "_post", fake_post)
    stats = analysis.load(con, verbose=False)
    assert stats["regenerated"] == 1 and stats["model"] == "muse-spark-1.3-contributor-free"
    assert [c[0] for c in calls] == ["chat/completions", "responses"]  # fell back to the responses API
    assert rows(con, "SELECT brief, model FROM briefs")[0]["brief"].startswith("Paragraph one")
    stats = analysis.load(con, verbose=False)  # unchanged inputs -> no new call
    assert stats["regenerated"] == 0 and stats["unchanged"] == 1 and len(calls) == 2


def test_chat_completions_shape_and_bad_key(tmp_path, monkeypatch):
    con = _setup(tmp_path)
    monkeypatch.setattr(analysis, "OPENCODE_API_KEY", "test-key")
    monkeypatch.setattr(analysis, "_post", lambda path, body, timeout=120: _Resp(200, {"choices": [{"message": {"content": "Brief text."}}]}))
    assert analysis.load(con, verbose=False)["regenerated"] == 1
    (tmp_path / "b").mkdir()
    con2 = _setup(tmp_path / "b")
    monkeypatch.setattr(analysis, "_post", lambda path, body, timeout=120: _Resp(401, text="bad key"))
    assert analysis.load(con2, verbose=False)["regenerated"] == 0


def test_skips_without_key(tmp_path, monkeypatch):
    con = _setup(tmp_path)
    monkeypatch.setattr(analysis, "OPENCODE_API_KEY", "")
    assert analysis.load(con, verbose=False) == {"skipped": True}
