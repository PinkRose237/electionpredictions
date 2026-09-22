"""The optional AI-brief stage, exercised with a fake Anthropic client (no network)."""
import types

from electionpredictions.db import connect, rows
from electionpredictions.sources import analysis


class _Block:
    def __init__(self, text):
        self.type, self.text = "text", text


class _Resp:
    stop_reason = "end_turn"
    stop_details = None
    content = [_Block("Paragraph one.\n\nParagraph two.")]


class _Msgs:
    calls = 0

    def create(self, **kw):
        _Msgs.calls += 1
        assert kw["model"] == analysis.MODEL and kw["fallbacks"] == "default"
        return _Resp()


class _FakeClient:
    def __init__(self, **kw):
        self.beta = types.SimpleNamespace(messages=_Msgs())


def test_brief_generation_and_caching(tmp_path, monkeypatch):
    con = connect(tmp_path / "t.db")
    con.execute("INSERT INTO races (race_id, chamber, state, district, special, name, incumbent, incumbent_party, incumbent_running, holder_party, pvi) VALUES ('GA-SEN','senate','GA',NULL,0,'Georgia Senate','Jon Ossoff','D',1,'D',-1)")
    con.execute("INSERT INTO candidates (race_id, name, party, is_incumbent, major) VALUES ('GA-SEN','Jon Ossoff','D',1,1), ('GA-SEN','Mike Collins','R',0,1)")
    con.execute("INSERT INTO forecasts (run_date, race_id, p_dem, margin, sd, detail) VALUES ('2026-09-22','GA-SEN',0.93,8.0,5.0,'{\"label\":\"Likely D\",\"notes\":[]}')")
    con.commit()
    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", _FakeClient)
    stats = analysis.load(con, verbose=False)
    assert stats["regenerated"] == 1 and _Msgs.calls == 1
    assert rows(con, "SELECT brief FROM briefs")[0]["brief"].startswith("Paragraph one")
    # unchanged inputs -> no new API call
    stats = analysis.load(con, verbose=False)
    assert stats["regenerated"] == 0 and stats["unchanged"] == 1 and _Msgs.calls == 1
