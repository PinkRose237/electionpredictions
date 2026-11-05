"""Offline parsing of the 2028 sources (Wikipedia table shapes as seen in November 2026)."""
import json

import pandas as pd

from electionpredictions.sources import approval, polls, primaries, ratings
from electionpredictions.sources.wikipedia import WikiTable


def test_heading_names_and_surnames():
    names = polls.heading_names("JD Vance vs. Gavin Newsom vs. Aaron Rodgers as an Independent")
    assert names == ["JD Vance", "Gavin Newsom", "Aaron Rodgers"]
    assert polls._full_name("Ocasio-Cortez", ["JD Vance", "Alexandria Ocasio-Cortez"]) == "Alexandria Ocasio-Cortez"


def test_parse_matchup_table():
    df = pd.DataFrame({"Poll source": ["Emerson College", "Zogby", "Average"], "Date(s) administered": ["August 16–17, 2026", "July 1–4, 2026", "x"],
                       "Sample size": ["1,000 (LV)", "1,003 (LV)", ""], "Vance (R)": ["45%", "43%", "44%"], "Harris (D)": ["49%", "48%", "48%"],
                       "Undecided": ["6%", "9%", ""]})
    t = WikiTable(path=["Opinion polling", "General election", "Nationwide", "JD Vance vs. Kamala Harris"], df=df, html="", index=0)
    rs = polls.parse_matchup_table(t, "national", None)
    assert len(rs) == 2
    p = rs[0]
    assert (p["dem_name"], p["rep_name"], p["dem_pct"], p["rep_pct"], p["sample_size"], p["population"], p["end_date"]) == \
        ("Kamala Harris", "JD Vance", 49.0, 45.0, 1000, "LV", "2026-08-17")


def test_state_contest_from_path():
    assert polls._contest_for(["Opinion polling", "General election", "Statewide", "Nevada", "JD Vance vs. Gavin Newsom"]) == "NV"
    assert polls._contest_for(["Statewide", "Maine", "Maine's 2nd congressional district", "A vs. B"]) == "ME-2"


def test_primary_tables_and_ineligible():
    df = pd.DataFrame({"Poll source": ["Echelon Insights"], "Date(s) administered": ["October 15–19, 2026"], "Sample size": ["522 (LV)"],
                       "Donald Trump": ["30%"], "JD Vance": ["38%"], "Marco Rubio": ["20%"], "Other": ["5%"], "Undecided": ["7%"]})
    rs = primaries.parse_poll_table(df, "R", 2026)
    shares = json.loads(rs[0]["shares"])
    assert shares == {"JD Vance": 38.0, "Marco Rubio": 20.0}   # Trump is term-limited: never a nominee
    agg = pd.DataFrame({"Aggregator": ["270toWin[1]", "Aggregate"], "Updated": ["August 28, 2026", "Aggregate"],
                        "Kamala Harris": ["25.0%", "26.3%"], "Gavin Newsom": ["14.0%", "15.2%"], "Other": ["14.5%", "—"], "Lead": ["Harris +11", "Harris +11.1"]})
    a = primaries.parse_aggregates(agg, "D")
    assert [x["source"] for x in a] == ["270toWin", "Average"] and a[0]["as_of"] == "2026-08-28"
    assert primaries.canonical("J.D. Vance") == "JD Vance"


def test_approval_aggregates():
    df = pd.DataFrame({"Aggregator": ["Silver Bulletin", "Average"], "Updated": ["November 1, 2026", "November 1, 2026"],
                       "Approve": ["37.3%", "36.8%"], "Disapprove": ["59.9%", "60.5%"], "Unsure/Other": ["2.8%", "2.7%"], "Lead": ["−22.6%", "−23.7%"]})
    rs = approval.parse(df)
    assert rs[1] == dict(source="Average", as_of="2026-11-01", approve=36.8, disapprove=60.5, net=-23.7)


def test_ratings_helpers():
    assert ratings.rater_header("Cook Sep. 11, 2027") == ("Cook Political Report", "2027-09-11")
    assert ratings.rater_header("EVs") is None
    assert ratings.contest_of("Maine's 2nd congressional district") == "ME-2"
    assert ratings.contest_of("NE–2") == "NE-2"
    assert ratings.contest_of("Pennsylvania") == "PA" and ratings.contest_of("D.C.") == "DC"
