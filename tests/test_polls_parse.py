import io

import pandas as pd

from electionpredictions.sources.polls import parse_polling_table
from electionpredictions.sources.wikipedia import WikiTable


def _table(html: str, path):
    df = pd.read_html(io.StringIO(html))[0]
    return WikiTable(path=path, df=df, html=html, index=0)


RACE = dict(race_id="GA-SEN", chamber="senate", state="GA")
CANDS = [dict(name="Jon Ossoff", party="D", major=1, is_incumbent=1), dict(name="Mike Collins", party="R", major=1, is_incumbent=0)]
DEM, REP = CANDS[0], CANDS[1]


def test_parse_basic_poll_table():
    html = """<table class="wikitable"><tr><th>Poll source</th><th>Date(s) administered</th><th>Sample size[b]</th>
    <th>Margin of error</th><th>Jon Ossoff (D)</th><th>Mike Collins (R)</th><th>Other</th><th>Undecided</th></tr>
    <tr><td>Quantus Insights (R)[7]</td><td>September 14–16, 2026</td><td>645 (LV)</td><td>± 4.3%</td><td>48%</td><td>44%</td><td>1%</td><td>7%</td></tr>
    <tr><td>Beacon Research (D)/ Shaw &amp; Co. Research (R)[13]</td><td>June 23–27, 2026</td><td>1,002 (RV)</td><td>± 3.0%</td><td>56%</td><td>43%</td><td>—</td><td>1%</td></tr>
    </table>"""
    polls, aggs = parse_polling_table(_table(html, ["General election", "Polling"]), RACE, CANDS, DEM, REP)
    assert len(polls) == 2 and not aggs
    p = polls[0]
    assert p["pollster"] == "Quantus Insights" and p["sponsor_lean"] == "R"
    assert (p["dem_pct"], p["rep_pct"], p["und_pct"], p["moe"]) == (48, 44, 7, 4.3)
    assert p["end_date"] == "2026-09-16" and p["population"] == "LV" and p["sample_size"] == 645
    assert p["hypothetical"] == 0
    assert polls[1]["sponsor_lean"] is None  # bipartisan sponsor


def test_hypothetical_matchup_flagged():
    html = """<table class="wikitable"><tr><th>Poll source</th><th>Date(s) administered</th><th>Sample size</th>
    <th>Margin of error</th><th>Jon Ossoff (D)</th><th>Brian Kemp (R)</th><th>Undecided</th></tr>
    <tr><td>Emerson College</td><td>March 1–2, 2026</td><td>1,000 (LV)</td><td>± 3.0%</td><td>49%</td><td>41%</td><td>10%</td></tr></table>"""
    polls, _ = parse_polling_table(_table(html, ["General election", "Polling"]), RACE, CANDS, DEM, REP)
    assert polls[0]["hypothetical"] == 1 and polls[0]["rep_pct"] is None


def test_ranked_choice_keeps_final_round():
    html = """<table class="wikitable"><tr><th>Poll source</th><th>Date(s) administered</th><th>Sample size</th>
    <th>Margin of error</th><th>RCV round</th><th>Mike Collins (R)</th><th>Jon Ossoff (D)</th><th>Bob Smith (R)</th></tr>
    <tr><td>Pollster X</td><td>September 8–11, 2026</td><td>800 (LV)</td><td>± 3.5%</td><td>BA</td><td>41%</td><td>45%</td><td>4%</td></tr>
    <tr><td>Pollster X</td><td>September 8–11, 2026</td><td>800 (LV)</td><td>± 3.5%</td><td>1</td><td>43%</td><td>50%</td><td>4%</td></tr>
    <tr><td>Pollster X</td><td>September 8–11, 2026</td><td>790 (LV)</td><td>± 3.5%</td><td>2</td><td>47%</td><td>53%</td><td>–</td></tr></table>"""
    polls, _ = parse_polling_table(_table(html, ["General election", "Polling", "Ranked-choice polls"]), RACE, CANDS, DEM, REP)
    assert len(polls) == 1
    assert (polls[0]["dem_pct"], polls[0]["rep_pct"]) == (53, 47)


def test_aggregator_table():
    html = """<table class="wikitable"><tr><th>Source of poll aggregation</th><th>Dates administered</th><th>Dates updated</th>
    <th>Jon Ossoff (D)</th><th>Mike Collins (R)</th><th>Other/Undecided</th><th>Margin</th></tr>
    <tr><td>RealClearPolitics[5]</td><td>June 23 – September 16, 2026</td><td>September 18, 2026</td><td>50.6%</td><td>43.1%</td><td>6.3%</td><td>Ossoff +7.5%</td></tr></table>"""
    polls, aggs = parse_polling_table(_table(html, ["General election", "Polling"]), RACE, CANDS, DEM, REP)
    assert not polls and aggs[0]["source"] == "RealClearPolitics" and aggs[0]["margin"] == 7.5 and aggs[0]["as_of"] == "2026-09-18"
