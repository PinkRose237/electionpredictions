from datetime import datetime, timezone

from electionpredictions.config import STATES
from electionpredictions.schedule import STATEWIDE_CLOSE_ET, build_schedule, call_estimate, close_datetime, race_close


def _race(rid, chamber, state, district=None, label="Tossup", p=0.5, unc=False):
    return dict(race_id=rid, short=rid, name=rid, chamber=chamber, state=state, district=district, label=label, p_dem=p,
                dem={"name": "D"}, rep={"name": "R"}, uncontested=unc)


def test_every_state_has_a_close_time():
    assert set(STATEWIDE_CLOSE_ET) == set(STATES)


def test_close_times_and_utc_conversion():
    assert close_datetime("19:00").astimezone(timezone.utc) == datetime(2026, 11, 4, 0, 0, tzinfo=timezone.utc)
    assert close_datetime("25:00").astimezone(timezone.utc) == datetime(2026, 11, 4, 6, 0, tzinfo=timezone.utc)


def test_split_zone_assignment():
    assert race_close(_race("FL-05", "house", "FL", 5))[0] == "19:00"
    assert race_close(_race("FL-01", "house", "FL", 1))[0] == "20:00"
    assert race_close(_race("FL-GOV", "governor", "FL"))[0] == "20:00"
    assert race_close(_race("TX-16", "house", "TX", 16))[0] == "21:00"
    assert race_close(_race("TX-07", "house", "TX", 7))[0] == "20:00"
    assert race_close(_race("KY-06", "house", "KY", 6))[0] == "18:00"
    assert race_close(_race("KY-SEN", "senate", "KY"))[0] == "19:00"
    assert race_close(_race("NE-SEN", "senate", "NE"))[0] == "21:00"
    assert race_close(_race("AK-00", "house", "AK", 0))[0] == "25:00"


def test_call_estimate_orders_by_competitiveness():
    close = close_datetime("19:00")
    safe = call_estimate(_race("GA-05", "house", "GA", 5, "Safe D", 0.99), close)
    tossup = call_estimate(_race("GA-GOV", "governor", "GA", label="Tossup", p=0.5), close)
    assert safe["typical"] < tossup["typical"] and safe["earliest"] == close
    assert tossup["typical"] > close and "runoff" in tossup["summary"]
    ak = call_estimate(_race("AK-SEN", "senate", "AK", label="Tossup"), close_datetime("25:00"))
    assert ak["typical"].month == 11 and ak["typical"].day >= 18
    unc = call_estimate(_race("CA-40", "house", "CA", 40, "Safe R", 0.0, unc=True), close)
    assert unc["tier"] == "uncontested"


def test_build_schedule_groups_by_state_and_time():
    races = [_race("FL-01", "house", "FL", 1), _race("FL-05", "house", "FL", 5), _race("FL-GOV", "governor", "FL"),
             _race("GA-SEN", "senate", "GA", label="Likely D", p=0.95)]
    sched = build_schedule(races, "now")
    keys = [(g["state"], g["close_et"]) for g in sched["groups"]]
    assert keys == [("Georgia", "7 pm ET"), ("Florida", "7 pm ET"), ("Florida", "8 pm ET")] or \
           keys == [("FL", "7 pm ET"), ("GA", "7 pm ET"), ("FL", "8 pm ET")]
    fl8 = next(g for g in sched["groups"] if g["state"] == "FL" and g["close_et"] == "8 pm ET")
    assert {r["race_id"] for r in fl8["races"]} == {"FL-01", "FL-GOV"}
    assert sched["first_close_utc"] <= sched["last_close_utc"]
