from electionpredictions.sources import live_results as lr
from electionpredictions.sources import race_calls as rc

RACES = [
    {"race_id": "NE-SEN", "dem": {"name": "Dan Osborn", "party": "I"}, "rep": {"name": "Pete Ricketts", "party": "R"}},
    {"race_id": "FL-SEN-SP", "dem": {"name": "Angie Nixon", "party": "D"}, "rep": {"name": "Ashley Moody", "party": "R"}},
    {"race_id": "DE-00", "dem": {"name": "Sarah McBride", "party": "D"}, "rep": {"name": "John Doe", "party": "R"}},
    {"race_id": "CA-12", "dem": {"name": "Lateefah Simon", "party": "D"}, "rep": {"name": "Jane Roe", "party": "R"}},
]
BY_ID = {r["race_id"]: r for r in RACES}


def collector():
    return rc.Collector(BY_ID, lr.make_resolver(BY_ID))


def test_nbc_house_key_and_duplicate_special(monkeypatch):
    def tip(names, winner):
        return {"tooltip": {"candidates": [{"firstName": f, "lastName": l, "party": p, "isWinner": l == winner, "votes": 1}
                                           for f, l, p in names]}}
    pages = {
        "senate": {"mapData": {"FL": tip([("Ashley", "Moody", "Rep"), ("Angie", "Nixon", "Dem")], "Moody"),
                               "FL~P": tip([("Ashley", "Moody", "Rep"), ("Angie", "Nixon", "Dem")], "Nixon")}},
        "house": {"mapData": {"1001": tip([("Sarah", "McBride", "Dem"), ("John", "Doe", "Rep")], "McBride"),
                              "0612": tip([("Lateefah", "Simon", "Dem"), ("Jane", "Roe", "Rep")], "")}},
        "governor": {"mapData": {}},
    }
    monkeypatch.setattr(rc, "_get", lambda url, text=False: next(v for k, v in pages.items() if f"/{k}-results" in url))
    col, errors = collector(), []
    rc.fetch_nbc(col, errors)
    assert col.calls["FL-SEN-SP"]["winner"] == "rep"          # first listing wins
    assert col.calls["DE-00"]["winner"] == "dem"              # FIPS 10 + district 01 -> at-large
    assert "CA-12" not in col.calls and "CA-12" in col.seen   # seen but not called


def test_bloomberg_tsv_forward_fills_race_keys(monkeypatch):
    cands = "raceKey\tcandidateID\tpartyCode\tfirst\tlast\nHCA12\t1\tDem\tLateefah\tSimon\n\t2\tRep\tJane\tRoe\nSNE\t3\tRep\tPete\tRicketts\n\t4\tInd\tDan\tOsborn\n"
    calls = "raceKey\twinnerCandidateID\tcallDateTime_epoch\tnetwork\tcallType\nSNE\t4\t86400\tAP\tX\n"
    monkeypatch.setattr(rc, "_get", lambda url, text=False: cands if "candidates" in url else calls)
    col, errors = collector(), []
    rc.fetch_bloomberg(col, errors)
    assert col.calls["NE-SEN"]["winner"] == "dem" and col.calls["NE-SEN"]["at"] == "2026-11-04T00:00:00+00:00"  # 7 pm ET
    assert col.seen == {"CA-12", "NE-SEN"}


def test_bbg_race_keys():
    assert rc._bbg_race("SGA") == ("GA", "senate", None)
    assert rc._bbg_race("HCA12") == ("CA", "house", "12")
    assert rc._bbg_race("GAZ") == ("AZ", "governor", None)


def test_call_times_carry_over_and_reset_when_the_call_changes():
    old = {"races": {"GA-SEN": {"cnn2": {"winner": "dem", "status": "called", "at": "2026-11-04T00:10:00+00:00"},
                                "cnn": {"winner": "rep", "status": "called", "at": "2026-11-04T00:12:00+00:00"}}}}
    payload = {"updated_at": "2026-11-04T01:00:00+00:00", "races": {"GA-SEN": {
        "cnn2": {"winner": "dem", "status": "called", "at": None},            # unchanged -> keeps its first-seen time
        "cnn": {"winner": "dem", "status": "called", "at": None},            # changed its call -> new time
        "nbc": {"winner": "dem", "status": "called", "at": None},            # new call -> now
        "bloomberg": {"winner": "dem", "status": "called", "at": "2026-11-04T00:05:00+00:00"}}}}  # outlet's own time
    rc.stamp_call_times(payload, old)
    got = {k: v["at"] for k, v in payload["races"]["GA-SEN"].items()}
    assert got == {"cnn2": "2026-11-04T00:10:00+00:00", "cnn": "2026-11-04T01:00:00+00:00",
                   "nbc": "2026-11-04T01:00:00+00:00", "bloomberg": "2026-11-04T00:05:00+00:00"}
