from datetime import date

from electionpredictions.util import (parse_date_range, parse_pct, parse_pvi, parse_rating, parse_sample, prob_label,
                                      race_id, rating_label, split_candidates, state_abbr)


def test_parse_pvi():
    assert parse_pvi("R+15") == -15
    assert parse_pvi("D+6") == 6
    assert parse_pvi("EVEN") == 0
    assert parse_pvi("") is None


def test_parse_pct():
    assert parse_pct("48%") == 48
    assert parse_pct("49%[c]") == 49
    assert parse_pct("—") is None
    assert parse_pct("<1%") == 0.5
    assert parse_pct("± 4.3%") == 4.3


def test_parse_sample():
    assert parse_sample("1,019 (LV)") == (1019, "LV")
    assert parse_sample("645 (RV)") == (645, "RV")
    assert parse_sample("—") == (None, None)


def test_parse_date_range():
    assert parse_date_range("September 14–16, 2026") == (date(2026, 9, 14), date(2026, 9, 16))
    assert parse_date_range("February 28 – March 2, 2026") == (date(2026, 2, 28), date(2026, 3, 2))
    assert parse_date_range("September 14, 2026") == (date(2026, 9, 14), date(2026, 9, 14))
    assert parse_date_range("Dec 30, 2025 – Jan 2, 2026") == (date(2025, 12, 30), date(2026, 1, 2))
    assert parse_date_range("July 28 – August 1, 2025") == (date(2025, 7, 28), date(2025, 8, 1))


def test_split_candidates():
    assert split_candidates("▌Mike Collins (Republican)[11] ▌Jon Ossoff (Democratic)[11]") == [("Mike Collins", "R"), ("Jon Ossoff", "D")]
    assert split_candidates("▌Dan Osborn (Independent) ▌Pete Ricketts (Republican)") == [("Dan Osborn", "I"), ("Pete Ricketts", "R")]


def test_ratings():
    assert parse_rating("Lean D (flip)") == ("D", 2, True)
    assert parse_rating("Tossup") == ("T", 0, False)
    assert parse_rating("Solid R") == ("R", 4, False)
    assert rating_label(2.7) == "Likely D"
    assert rating_label(-0.2) == "Tossup"


def test_prob_label_and_ids():
    assert prob_label(0.5) == "Tossup"
    assert prob_label(0.9) == "Likely D"
    assert prob_label(0.01) == "Safe R"
    assert race_id("house", "AZ", 1) == "AZ-01"
    assert race_id("senate", "OH", special=True) == "OH-SEN-SP"
    assert state_abbr("Florida (special)") == "FL"
