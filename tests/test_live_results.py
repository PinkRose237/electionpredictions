from electionpredictions.archive2026 import live_results as lr

RACES = [
    {"race_id": "NE-SEN", "dem": {"name": "Dan Osborn", "party": "I"}, "rep": {"name": "Pete Ricketts", "party": "R"}},
    {"race_id": "AK-SEN", "dem": {"name": "Mary Peltola", "party": "D"}, "rep": {"name": "Dan Sullivan", "party": "R"}},
    {"race_id": "AK-00", "dem": {"name": "Ann Doe", "party": "D"}, "rep": {"name": "Bob Roe", "party": "R"}},
    {"race_id": "OH-SEN-SP", "dem": {"name": "Sherrod Brown", "party": "D"}, "rep": {"name": "Jon Husted", "party": "R"}},
    {"race_id": "KY-03", "dem": {"name": "Morgan McGarvey", "party": "D"}, "rep": {"name": "Maria Rodriquez", "party": "R"}},
]
BY_ID = {r["race_id"]: r for r in RACES}
RESOLVE = lr.make_resolver(BY_ID)


def nyt_race(st, office, seat, cands, won=(), race_type="G", eevp=50):
    meta = {k: {"first_name": f, "last_name": l, "party": {"nyt_id": p}} for k, f, l, p, _ in cands}
    return {"office_id": office, "seat_number": seat, "race_type_id": race_type, "type": "General", "certified": False,
            "outcome": {"won": list(won), "advanced_to_runoff": []}, "candidate_metadata": meta,
            "top_reporting_unit": {"level": "state", "state_postal": st, "eevp": eevp, "provider_updated_at": "t",
                                   "candidates": [{"nyt_id": k, "votes": {"total": v}} for k, _, _, _, v in cands]}}


def test_resolver_handles_at_large_and_specials():
    assert RESOLVE("AK", "house", "1", False) == "AK-00"
    assert RESOLVE("OH", "senate", None, True) == "OH-SEN-SP"
    assert RESOLVE("OH", "senate", None, False) == "OH-SEN-SP"  # only the special is up
    assert RESOLVE("TX", "house", "18", False) is None


def test_independent_on_dem_side_and_call():
    data = {"races": [nyt_race("NE", "S", "2", [("r", "Pete", "Ricketts", "GOP", 400), ("o", "Dan", "Osborn", "IND", 500),
                                                 ("x", "Mike", "Marvin", "IND", 20)], won=["o"])]}
    e = lr.parse_nyt(data, BY_ID, RESOLVE)["NE-SEN"]
    assert e["votes"] == {"dem": 500, "rep": 400, "other": 20}
    assert e["winner"] == "dem" and e["status"] == "called" and e["reporting"] == 50.0


def test_same_surname_uses_first_name():
    data = {"races": [nyt_race("AK", "S", "2", [("a", "Daniel", "Sullivan", "IND", 999), ("b", "Dan", "Sullivan", "GOP", 100),
                                                 ("c", "Mary", "Peltola", "DEM", 120)])]}
    e = lr.parse_nyt(data, BY_ID, RESOLVE)["AK-SEN"]
    assert e["votes"] == {"dem": 120, "rep": 100, "other": 999} and e["status"] == "counting"


def test_misspelled_name_falls_back_to_party_cnn():
    data = [{"contestType": "HG", "raceType": "H", "ecKey": "2026-HG-KY-3", "stateAbbreviation": "KY", "percentReporting": 0,
             "extractedAt": "2026-11-03T19:10:09.277394",
             "candidates": [{"firstName": "Morgan", "lastName": "McGarvey", "majorParty": "DEM", "voteNum": 0, "winner": False},
                            {"firstName": "Maria", "lastName": "Rodriguez", "majorParty": "REP", "voteNum": 0, "winner": False}]}]
    e = lr.parse_cnn(data, BY_ID, RESOLVE)["KY-03"]
    assert e["status"] == "pending" and e["votes"] == {"dem": 0, "rep": 0, "other": None}
    assert e["updated_at"].endswith("Z")


def test_fetch_live_fills_gaps_from_backup(monkeypatch):
    monkeypatch.setitem(lr.FEEDS, "nyt", lambda by_id, resolve, errors: {"NE-SEN": {"status": "pending"}})
    monkeypatch.setitem(lr.FEEDS, "cnn", lambda by_id, resolve, errors: {"NE-SEN": {"status": "x"}, "AK-00": {"status": "counting"}})
    res = lr.fetch_live(RACES)
    assert res["races"]["NE-SEN"] == {"status": "pending"} and res["by"] == {"NE-SEN": "nyt", "AK-00": "cnn"}
    assert res["sources"] == ["nyt", "cnn"]
