"""Election-night schedule: when polls close for every race, and when a call can be expected.

Poll-closing times: The Green Papers, "2026 Poll Closing Times for Statewide offices and Congress"
(https://www.thegreenpapers.com/G26/closing.phtml). Nov 3, 2026 is after the end of daylight time, so
Eastern = UTC-5. A race cannot be called before the LAST polls in its jurisdiction close, so statewide
races in split-time-zone states use the later time, and House districts are assigned to the zone they sit in.

Call-time estimates are heuristics fitted to how long the AP took to call races in 2018-2024, per state:
e.g. Arizona Senate 2018/2022/2024 took 6/3/6 days, Nevada Senate 2022/2024 four days each, Pennsylvania
Senate 2024 two days, Michigan and Wisconsin Senate 2024 the next afternoon, Alaska's ranked-choice
tabulation 15 days after the election (Nov 23 2022, Nov 20 2024), Maine's 2nd district RCV runoff
Nov 15 2024, California's closest House seats about four weeks (Dec 3 2022, Dec 3 2024). Uncompetitive
races are called at poll close. The window widens with the model's uncertainty about the race.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from .config import DC_NAME, ELECTION_DATE, STATES

ET = timezone(timedelta(hours=-5))  # Eastern Standard Time on election day 2026

# Statewide (last) poll-closing time in Eastern time, as "HH:MM" on election day; 24:00+ = Nov 4.
STATEWIDE_CLOSE_ET: dict[str, str] = {
    "IN": "19:00", "KY": "19:00",
    "GA": "19:00", "SC": "19:00", "VT": "19:00", "VA": "19:00",
    "NC": "19:30", "OH": "19:30", "WV": "19:30",
    "AL": "20:00", "CT": "20:00", "DC": "20:00", "DE": "20:00", "FL": "20:00", "IL": "20:00", "ME": "20:00", "MD": "20:00",
    "MA": "20:00", "MS": "20:00", "MO": "20:00", "NH": "20:00", "NJ": "20:00", "OK": "20:00", "PA": "20:00",
    "RI": "20:00", "TN": "20:00",
    "AR": "20:30",
    "AZ": "21:00", "CO": "21:00", "IA": "21:00", "KS": "21:00", "LA": "21:00", "MI": "21:00", "MN": "21:00",
    "NE": "21:00", "NM": "21:00", "NY": "21:00", "SD": "21:00", "TX": "21:00", "WI": "21:00", "WY": "21:00",
    "MT": "22:00", "NV": "22:00", "UT": "22:00",
    "CA": "23:00", "ID": "23:00", "ND": "23:00", "OR": "23:00", "WA": "23:00",
    "HI": "24:00",
    "AK": "25:00",
}

# Earlier closing time that applies to MOST of a split-time-zone state, and the House districts that
# actually close at that earlier time. Anything not listed here closes at the statewide time above.
EARLY_ZONE: dict[str, dict] = {
    "IN": {"et": "18:00", "local": "6:00 pm ET (6:00 pm CT in the northwest and southwest corners)",
           "districts_late": {1, 8}, "note": "IN-1 and IN-8 include Central-time counties that close at 7 pm ET."},
    "KY": {"et": "18:00", "local": "6:00 pm ET (6:00 pm CT in western Kentucky)",
           "districts_late": {1, 2}, "note": "Western Kentucky (KY-1, KY-2) is on Central time and closes at 7 pm ET; statewide races wait for it."},
    "FL": {"et": "19:00", "local": "7:00 pm ET (7:00 pm CT in the panhandle)",
           "districts_late": {1, 2}, "note": "The Central-time panhandle (FL-1, FL-2) closes at 8 pm ET; statewide races wait for it."},
    "MI": {"et": "20:00", "local": "8:00 pm ET (8:00 pm CT in four Upper Peninsula counties)",
           "districts_late": {1}, "note": "Four western U.P. counties in MI-1 are on Central time and close at 9 pm ET; statewide races wait for them."},
    "TX": {"et": "20:00", "local": "7:00 pm CT (7:00 pm MT in El Paso and Hudspeth counties)",
           "districts_late": {16, 23}, "note": "El Paso and Hudspeth counties (TX-16, TX-23) are on Mountain time and close at 9 pm ET; statewide races wait for them."},
    "KS": {"et": "20:00", "local": "7:00 pm CT (7:00 pm MT in four western counties)",
           "districts_late": {1}, "note": "Four far-western counties in KS-1 are on Mountain time and close at 9 pm ET; statewide races wait for them."},
    "ID": {"et": "22:00", "local": "8:00 pm MT (8:00 pm PT in the northern panhandle)",
           "districts_late": {1}, "note": "The Pacific-time panhandle (ID-1) closes at 11 pm ET; statewide races wait for it."},
    "ND": {"et": "22:00", "local": "polls close between 7 and 9 pm local time (9 pm CT / 9 pm MT at the latest)",
           "districts_late": {0}, "note": "Most North Dakota polls close by 8 pm CT; the last (Mountain-time) polls close at 11 pm ET."},
}

# Single-time states that deserve a note.
CLOSE_NOTES: dict[str, str] = {
    "NE": "Nebraska closes both time zones at the same moment (8 pm CT / 7 pm MT).",
    "TN": "Tennessee closes both time zones at the same moment (8 pm ET / 7 pm CT).",
    "SD": "7 pm local time; the Mountain-time west closes an hour after the east (9 pm ET).",
    "OR": "Vote by mail; ballots must be in a drop box by 8 pm PT (Malheur County, on Mountain time, closes an hour earlier).",
    "AK": "Most Alaska polls close at midnight ET (8 pm AKST); the Aleutians west of Umnak close at 1 am ET.",
    "HI": "7 pm HST; almost entirely vote by mail.",
    "NH": "Most towns close at 7 pm ET, but 13 cities may stay open until 8 pm, so calls wait until 8 pm ET.",
    "NV": "Vote by mail; ballots postmarked by election day count if received within four days.",
    "WA": "Vote by mail; ballots must be postmarked by election day, so counting continues for days.",
    "CA": "Ballots postmarked by election day count if they arrive within seven days; counting takes weeks.",
    "AZ": "Roughly 80% vote by mail; ballots dropped off on election day are verified over the following days.",
    "GA": "If no candidate reaches 50% the race goes to a December 1 runoff.",
    "ME": "Ranked-choice tabulation is run only if no candidate wins a majority of first choices.",
}

# Where each state posts election-night results (verified Sept 2026). 'kind' summarises the feed.
RESULTS_SOURCES: dict[str, list[dict]] = {
    "AL": [{"label": "Alabama Votes election night", "url": "https://www.sos.alabama.gov/alabama-votes/voter/enr-current-list", "kind": "state site"}],
    "AK": [{"label": "Alaska Division of Elections results", "url": "https://www.elections.alaska.gov/results/", "kind": "state site; RCV tabulation ~15 days later"}],
    "AZ": [{"label": "results.arizona.vote", "url": "https://results.arizona.vote/", "kind": "state site; media XML by arrangement"}],
    "AR": [{"label": "Arkansas ENR (Clarity)", "url": "https://results.enr.clarityelections.com/AR/", "kind": "Clarity JSON/CSV"}],
    "CA": [{"label": "California SoS election results", "url": "https://electionresults.sos.ca.gov/", "kind": "state site; XLS/CSV/XML downloads"}],
    "CO": [{"label": "Colorado ENR (Clarity)", "url": "https://results.enr.clarityelections.com/CO/", "kind": "Clarity JSON/CSV"}],
    "CT": [{"label": "electionresults.ct.gov", "url": "https://electionresults.ct.gov/", "kind": "state site"}],
    "DE": [{"label": "Delaware election results", "url": "https://elections.delaware.gov/results/", "kind": "state site"}],
    "FL": [{"label": "Florida Division of Elections results", "url": "https://results.elections.myflorida.com/", "kind": "state site; tab-delimited download"}],
    "GA": [{"label": "Georgia ENR (Clarity)", "url": "https://results.enr.clarityelections.com/GA/", "kind": "Clarity JSON/CSV"}],
    "HI": [{"label": "Hawaii Office of Elections results", "url": "https://elections.hawaii.gov/election-results/", "kind": "PDF/text printouts at set times"}],
    "ID": [{"label": "results.voteidaho.gov", "url": "https://results.voteidaho.gov/results/public/id", "kind": "Enhanced Voting; media export"}],
    "IL": [{"label": "Illinois SBE results (post-election)", "url": "https://www.elections.il.gov/ElectionOperations/ElectionResults.aspx", "kind": "no live state feed"},
           {"label": "Cook County Clerk results", "url": "https://www.cookcountyclerkil.gov/elections/results", "kind": "county"},
           {"label": "Chicago Board of Elections results", "url": "https://chicagoelections.gov/elections/results", "kind": "city"}],
    "IN": [{"label": "Indiana ENR", "url": "https://enr.indianavoters.in.gov/", "kind": "state site"}],
    "IA": [{"label": "Iowa ENR (Clarity)", "url": "https://electionresults.iowa.gov/IA/", "kind": "Clarity JSON/CSV"}],
    "KS": [{"label": "Kansas election night results", "url": "https://ent.sos.ks.gov/kssos_ent.html", "kind": "state site"}],
    "KY": [{"label": "Kentucky ENR (Clarity)", "url": "https://results.enr.clarityelections.com/KY/", "kind": "Clarity JSON/CSV"}],
    "LA": [{"label": "Louisiana live results", "url": "https://voterportal.sos.la.gov/graphical", "kind": "state site; media XML feed; CSV after 11 pm"}],
    "ME": [{"label": "Maine SoS elections (tabulation later)", "url": "https://www.maine.gov/sos/elections-voting", "kind": "no live state feed"},
           {"label": "Bangor Daily News live results", "url": "https://www.bangordailynews.com/maine-election-results/", "kind": "media"}],
    "MD": [{"label": "Maryland SBE elections", "url": "https://elections.maryland.gov/elections/", "kind": "state site; CSV files"}],
    "MA": [{"label": "Massachusetts electionstats (certified later)", "url": "https://electionstats.state.ma.us/", "kind": "no election-night state feed"}],
    "MI": [{"label": "Michigan SoS election results", "url": "https://www.michigan.gov/sos/elections/election-results-and-data", "kind": "state; counties post first"}],
    "MN": [{"label": "Minnesota SoS results", "url": "https://electionresults.sos.mn.gov/", "kind": "state site; media text files"}],
    "MS": [{"label": "Mississippi SoS results (post-election)", "url": "https://www.sos.ms.gov/elections-voting/election-results", "kind": "no live state feed; counties"}],
    "MO": [{"label": "Missouri election night results", "url": "https://enr.sos.mo.gov/", "kind": "state site"}],
    "MT": [{"label": "Montana election results", "url": "https://electionresults.mt.gov/", "kind": "state site; ResultsExport.aspx"}],
    "NE": [{"label": "Nebraska election night results", "url": "https://electionresults.nebraska.gov/", "kind": "state site"}],
    "NV": [{"label": "Silver State Election", "url": "https://silverstateelection.nv.gov/", "kind": "state site; XML county files"}],
    "NH": [{"label": "New Hampshire SoS elections", "url": "https://www.sos.nh.gov/elections", "kind": "no live state feed; towns"}],
    "NJ": [{"label": "NJ election night results (county links)", "url": "https://www.nj.gov/state/elections/election-night-results.shtml", "kind": "county sites, mostly Clarity"}],
    "NM": [{"label": "New Mexico election results", "url": "https://electionresults.sos.nm.gov/", "kind": "state site"}],
    "NY": [{"label": "NYS Board of Elections ENR", "url": "https://nyenr.elections.ny.gov/", "kind": "state site (county uploads)"},
           {"label": "NYC Board of Elections ENR", "url": "https://enr.boenyc.gov/", "kind": "city; CSV"}],
    "NC": [{"label": "NC State Board of Elections ENR", "url": "https://er.ncsbe.gov/", "kind": "state site; TSV downloads at dl.ncsbe.gov/ENRS"}],
    "ND": [{"label": "North Dakota SoS election results", "url": "https://www.sos.nd.gov/elections/election-results", "kind": "state site"}],
    "OH": [{"label": "Ohio SoS live results", "url": "https://liveresults.ohiosos.gov/", "kind": "state site"}],
    "OK": [{"label": "Oklahoma election results", "url": "https://results.okelections.gov/OKER/", "kind": "state site; export tab"}],
    "OR": [{"label": "Oregon election results", "url": "https://results.oregonvotes.gov/", "kind": "state site"}],
    "PA": [{"label": "Pennsylvania election returns", "url": "https://www.electionreturns.pa.gov/", "kind": "state site; JSON API + CSV reports"}],
    "RI": [{"label": "Rhode Island Board of Elections", "url": "https://elections.ri.gov/", "kind": "state site"}],
    "SC": [{"label": "SC election night results (Scytl)", "url": "https://www.enr-scvotes.org/", "kind": "Clarity-style JSON/CSV"}],
    "SD": [{"label": "South Dakota election results", "url": "https://electionresults.sd.gov/", "kind": "state site"}],
    "TN": [{"label": "Tennessee election night dashboard", "url": "https://www.elections.tn.gov/", "kind": "state site"}],
    "TX": [{"label": "Texas election night results", "url": "https://results.texas-election.com/", "kind": "state site; JSON behind app"}],
    "UT": [{"label": "Utah election results", "url": "https://electionresults.utah.gov/", "kind": "Enhanced Voting; media export"}],
    "VT": [{"label": "Vermont election night results", "url": "https://vtelectionresults.sec.state.vt.us/", "kind": "state site"}],
    "VA": [{"label": "Virginia ENR", "url": "https://enr.elections.virginia.gov/results/public/virginia", "kind": "Enhanced Voting; JSON file"}],
    "WA": [{"label": "Washington election results", "url": "https://results.vote.wa.gov/", "kind": "state site; CSV/XML/JSON export"}],
    "WV": [{"label": "West Virginia ENR (Clarity)", "url": "https://results.enr.clarityelections.com/WV/", "kind": "Clarity JSON/CSV"}],
    "WI": [{"label": "Wisconsin county election websites", "url": "https://elections.wi.gov/wisconsin-county-election-websites", "kind": "no state feed; 72 county sites"}],
    "WY": [{"label": "Wyoming SoS elections", "url": "https://sos.wyo.gov/Elections/", "kind": "county clerks + SoS files"}],
}

# Counting profile: hours after close until roughly 90% of the vote is reported, and days the AP
# typically needed to call a genuinely close race in 2018-2024.
COUNT_PROFILE: dict[str, dict] = {
    "AK": dict(h90=24, close_days=15, why="Ranked-choice tabulation is run about 15 days after the election (Nov 23 2022, Nov 20 2024); mail ballots arrive for two weeks."),
    "AZ": dict(h90=72, close_days=6, why="Maricopa needs 10-13 days to finish; Senate races were called 6, 3 and 6 days out in 2018, 2022 and 2024."),
    "CA": dict(h90=168, close_days=24, why="Ballots may arrive a week after election day; the closest House seats were called Dec 3 in both 2022 and 2024."),
    "NV": dict(h90=48, close_days=4, why="Mail ballots arrive for four days; the Senate races of 2022 and 2024 were both called on the Saturday after the election."),
    "WA": dict(h90=36, close_days=4, why="All-mail state; close House races in 2022 took about four days."),
    "OR": dict(h90=30, close_days=3, why="All-mail state; close races in 2022 took three to four days."),
    "UT": dict(h90=30, close_days=3, why="Mostly by mail with post-election arrival."),
    "PA": dict(h90=14, close_days=2, why="Mail ballots can't be opened before 7 am on election day; the 2024 Senate race was called two days later."),
    "MI": dict(h90=14, close_days=1.5, why="Big cities finish overnight; the 2024 Senate race was called the next afternoon."),
    "NY": dict(h90=10, close_days=3, why="Absentee ballots are canvassed over several days; several 2022 House seats took days."),
    "MD": dict(h90=12, close_days=3, why="Mail ballots are canvassed over several days after the election."),
    "IL": dict(h90=8, close_days=2, why="Cook County mail ballots arrive for two weeks; close 2022 seats took a couple of days."),
    "NJ": dict(h90=8, close_days=2, why="Mail ballots postmarked by election day count for six days."),
    "ME": dict(h90=6, close_days=9, why="A ranked-choice runoff, if needed, is tabulated about a week after election day (ME-2 was called Nov 15 in 2024)."),
    "WI": dict(h90=6, close_days=1, why="Milwaukee's absentee count lands after midnight; 2022 and 2024 Senate races were called the next day."),
    "MN": dict(h90=5, close_days=1, why="Most of the vote is in by midnight; close races resolve the next morning."),
    "CO": dict(h90=6, close_days=1.5, why="All-mail but fast; 2022's closest House seat took ten days but the norm is one."),
    "GA": dict(h90=4, close_days=1.5, why="Counts quickly; a majority is required, otherwise a Dec 1 runoff."),
    "NC": dict(h90=4, close_days=1, why="Mail ballots must now arrive by election day, so most calls come on election night."),
    "MT": dict(h90=6, close_days=1, why="Rural precincts report overnight; the 2024 Senate race was called by morning."),
    "NM": dict(h90=5, close_days=1, why="Close 2022 House races were called by the next morning."),
    "NH": dict(h90=4, close_days=1, why="Hand-counted towns report through the night."),
    "KS": dict(h90=4, close_days=1, why="Fast count; mail ballots postmarked by election day count for three days."),
    "NE": dict(h90=4, close_days=1, why="Fast count; NE-2 in 2024 was called the next day."),
    "TX": dict(h90=4, close_days=1, why="Large counties finish overnight; statewide races are usually called on election night."),
    "OH": dict(h90=3, close_days=1, why="Fast count; late-arriving mail ballots are few."),
    "IA": dict(h90=3, close_days=1, why="Fast count."),
    "VA": dict(h90=3, close_days=1, why="Fast count."),
    "FL": dict(h90=3, close_days=1, why="Mail ballots are counted before polls close; the 2018 recounts were the exception."),
}
DEFAULT_PROFILE = dict(h90=4, close_days=1, why="Fast-counting state; most results are in within a few hours of poll close.")

LABEL_TIER = {"Safe D": 0, "Safe R": 0, "Likely D": 1, "Likely R": 1, "Lean D": 2, "Lean R": 2, "Tossup": 3}


def close_datetime(hhmm: str) -> datetime:
    """'19:30' -> aware datetime in ET on election day ('25:00' = 1 am the next day)."""
    hh, mm = (int(x) for x in hhmm.split(":"))
    return datetime(ELECTION_DATE.year, ELECTION_DATE.month, ELECTION_DATE.day, tzinfo=ET) + timedelta(hours=hh, minutes=mm)


def _fmt_et(dt: datetime) -> str:
    s = dt.astimezone(ET).strftime("%I:%M %p").lstrip("0").lower().replace(":00", "")
    return s + " ET"


def race_close(race: dict) -> tuple[str, str, Optional[str]]:
    """(close 'HH:MM' ET, human description, note) for one race."""
    st = race["state"]
    late = STATEWIDE_CLOSE_ET[st]
    early = EARLY_ZONE.get(st)
    note = CLOSE_NOTES.get(st)
    if early:
        if race["chamber"] == "house" and race.get("district") not in early["districts_late"]:
            return early["et"], early["local"], early["note"]
        return late, f"{_fmt_et(close_datetime(late))} (last polls in the state)", early["note"]
    return late, _fmt_et(close_datetime(late)), note


def call_estimate(race: dict, close: datetime) -> dict:
    """Expected AP-call window for a race given the model's label and the state's counting profile."""
    prof = COUNT_PROFILE.get(race["state"], DEFAULT_PROFILE)
    h90, cd = prof["h90"], prof["close_days"]
    if race.get("uncontested"):
        return dict(earliest=close, typical=close, late=close, summary="At poll close (uncontested)", tier="uncontested", why=None)
    tier = LABEL_TIER.get(race.get("label") or "Tossup", 3)
    if tier == 0:
        e, t, l = close, close + timedelta(minutes=10), close + timedelta(hours=1)
        summary = "At poll close"
    elif tier == 1:
        e, t, l = close + timedelta(minutes=30), close + timedelta(hours=max(1.0, 0.4 * h90)), close + timedelta(hours=h90)
        summary = "Election night" if h90 <= 8 else "Within a day or two"
    elif tier == 2:
        e, t, l = close + timedelta(hours=0.75 * h90), close + timedelta(hours=max(h90, 12 * cd)), close + timedelta(hours=24 * cd)
        summary = "Late election night or next morning" if 24 * cd <= 30 else f"About {_days(cd)} after the election"
    else:
        e, t, l = close + timedelta(hours=h90), close + timedelta(hours=24 * cd), close + timedelta(hours=36 * cd)
        summary = "Overnight into the next day" if cd <= 1 else f"About {_days(cd)} after the election; could be longer"
    if race["state"] == "AK" and tier >= 2:
        rcv = datetime(ELECTION_DATE.year, 11, 18, 21, 0, tzinfo=ET)  # tabulation scheduled ~15 days out
        t, l = max(t, rcv), max(l, rcv + timedelta(days=2))
        summary = "After ranked-choice tabulation (~Nov 18)"
    if race["state"] == "ME" and tier >= 2:
        summary = "Within a week if a ranked-choice runoff is needed"
    if race["state"] == "GA" and tier >= 2:
        summary += "; Dec 1 runoff if no majority"
    return dict(earliest=e, typical=t, late=l, summary=summary, tier=tier, why=prof["why"])


def _days(d: float) -> str:
    return "a day" if d <= 1 else f"{d:g} days"


def build_schedule(race_summaries: list[dict], generated_at: str) -> dict:
    """Group races by (state, close time) and attach call estimates. Input: exported race summaries."""
    groups: dict[tuple, dict] = {}
    for r in race_summaries:
        et, local_desc, note = race_close(r)
        close = close_datetime(et)
        est = call_estimate(r, close)
        key = (close.isoformat(), r["state"])
        g = groups.setdefault(key, dict(
            state=r["state"], state_name=STATES.get(r["state"], DC_NAME), close_utc=close.astimezone(timezone.utc).isoformat(),
            close_et=_fmt_et(close), local=local_desc, note=note, races=[], sources=RESULTS_SOURCES.get(r["state"], []),
        ))
        g["races"].append(dict(
            race_id=r["race_id"], short=r["short"], name=r["name"], chamber=r["chamber"], label=r["label"], p_dem=r["p_dem"],
            dem=(r["dem"] or {}).get("name"), rep=(r["rep"] or {}).get("name"), uncontested=r["uncontested"],
            call=dict(earliest=est["earliest"].astimezone(timezone.utc).isoformat(), typical=est["typical"].astimezone(timezone.utc).isoformat(),
                      late=est["late"].astimezone(timezone.utc).isoformat(), summary=est["summary"], tier=est["tier"], why=est["why"]),
        ))
    order = {"president": -1, "senate": 0, "governor": 1, "house": 2}
    out = []
    for g in groups.values():
        g["races"].sort(key=lambda x: (order[x["chamber"]], x["short"]))
        g["settled_typical"] = max(x["call"]["typical"] for x in g["races"])
        g["settled_late"] = max(x["call"]["late"] for x in g["races"])
        g["n_competitive"] = sum(1 for x in g["races"] if x["call"]["tier"] in (2, 3))
        out.append(g)
    out.sort(key=lambda g: (g["close_utc"], g["state_name"]))
    first = min(g["close_utc"] for g in out) if out else None
    last = max(g["close_utc"] for g in out) if out else None
    return dict(
        generated_at=generated_at, election_date=ELECTION_DATE.isoformat(), first_close_utc=first, last_close_utc=last,
        groups=out,
        results_sources=RESULTS_SOURCES,
        method=[
            "Poll-closing times come from The Green Papers' 2026 closing-time table; a race is listed at the moment the LAST polls in its jurisdiction close, because the AP does not call a race before then.",
            "Expected call times are estimates, not AP guidance: uncompetitive races (model Safe) are usually called at poll close; Likely races within the state's typical count time; Lean and Tossup races take as long as the state historically needed for close calls (Arizona ~6 days, Nevada ~4, Pennsylvania ~2, Michigan/Wisconsin the next day, California up to a month, Alaska after its ranked-choice tabulation about 15 days out).",
            "History used: AP call timing from the 2018, 2020, 2022 and 2024 general elections. Recounts, runoffs (Georgia) and ranked-choice tabulations (Alaska, Maine) can push calls later.",
        ],
        sources=[
            {"title": "The Green Papers — 2026 Poll Closing Times", "url": "https://www.thegreenpapers.com/G26/closing.phtml?format=ga"},
            {"title": "AP — why AP called the Michigan Senate race (Nov 6, 2024)", "url": "https://www.usnews.com/news/politics/articles/2024-11-06/why-ap-called-the-michigan-senate-race-for-elissa-slotkin"},
            {"title": "AP — why AP called the Wisconsin Senate race (Nov 6, 2024)", "url": "https://abcnews.go.com/US/wireStory/ap-called-wisconsin-senate-race-tammy-baldwin-115575667"},
            {"title": "WHYY — AP calls Pennsylvania Senate race (Nov 7, 2024)", "url": "https://whyy.org/articles/david-mccormick-beats-bob-casey-pennsylvania-senate/"},
            {"title": "NPR — Arizona Senate race called (Nov 11, 2024)", "url": "https://www.npr.org/2024/11/12/g-s1-33813/arizona-senate-gallego-lake"},
            {"title": "CNN — outstanding votes in Nevada and Arizona (Nov 12, 2022)", "url": "https://www.cnn.com/2022/11/12/politics/nevada-arizona-votes-midterms-what-to-know/index.html"},
            {"title": "Alaska Beacon — ranked-choice tabulation results (Nov 20, 2024)", "url": "https://alaskabeacon.com/2024/11/20/alaska-chooses-to-keep-ranked-choice-voting-begich-defeats-peltola-unofficial-results-show/"},
            {"title": "Maine Public — Golden wins ranked-choice runoff (Nov 15, 2024)", "url": "https://www.mainepublic.org/politics/2024-11-15/golden-wins-ranked-choice-runoff-in-maines-2nd-congressional-district"},
            {"title": "The Hill — CA-13, 2024's last uncalled race (Dec 3, 2024)", "url": "https://thehill.com/homenews/campaign/5024007-duarte-concedes-in-last-congressional-race-2024/"},
            {"title": "CBS News — when will we know election results (2024)", "url": "https://www.cbsnews.com/news/when-will-we-know-election-results-2024/"},
        ],
    )
