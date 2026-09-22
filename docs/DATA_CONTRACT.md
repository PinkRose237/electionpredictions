# Site data contract

The Python pipeline writes static JSON into `site/data/`. The website reads only these files.
All probabilities are 0–1 floats. All margins are **Democratic minus Republican, in percentage points**
(positive = D ahead). "dem"/"rep" mean the D-side and R-side principal candidate; an independent can
stand in for a missing major-party nominee (e.g. Nebraska Senate, where `dem.party == "I"`).

## `summary.json`
```json
{
  "generated_at": "2026-09-22T20:15:00+00:00",
  "election_date": "2026-11-03",
  "days_to_election": 42,
  "generic_ballot": {
    "margin": 7.8, "dem": 49.7, "rep": 41.9,
    "sources": [{"source": "Decision Desk HQ", "as_of": "2026-09-21", "dem": 48.1, "rep": 40.5, "margin": 7.6}]
  },
  "chambers": {
    "house": {
      "label": "House", "total": 435, "seats_up": 435, "needed": 218,
      "not_up": {"D": 0, "R": 0},
      "current": {"D": 213, "R": 219, "other": 3},
      "p_dem": 0.93, "p_rep": 0.07, "p_neither": 0.0,
      "dem_seats": {"mean": 232.4, "median": 232, "p05": 220, "p10": 223, "p90": 242, "p95": 245},
      "rep_seats": {"mean": 202.6, "median": 203, "p05": 190, "p10": 193, "p90": 212, "p95": 215},
      "histogram": [{"seats": 215, "p": 0.004}],
      "markets": [{"platform": "polymarket", "p_dem": 0.925, "p_rep": 0.075, "url": "https://..."}],
      "rating_counts": {"Safe D": 160, "Likely D": 20, "Lean D": 15, "Tossup": 25, "Lean R": 15, "Likely R": 25, "Safe R": 175},
      "expected_flips": {"D": 22.3, "R": 3.1}
    },
    "senate": {"...": "same shape; total 100, seats_up 35, needed 51, not_up {D:34,R:31}"},
    "governor": {"...": "same shape; total 50, seats_up 36, needed 26, not_up {D:7,R:7}"}
  },
  "history": [
    {"date": "2026-09-22", "generic": 7.8,
     "house": {"p_dem": 0.93, "dem_seats": 232.4}, "senate": {"p_dem": 0.55, "dem_seats": 50.4}, "governor": {"p_dem": 0.6, "dem_seats": 26.1}}
  ],
  "closest": ["ME-SEN", "NC-01"],
  "sources": {"polls": 1412, "ratings": 1871, "markets": 725, "news": 3433, "fec_candidates": 968}
}
```
Notes: `needed` for the Senate is 51 because the Vice President (R) breaks ties; `p_neither` is the chance
no party reaches control on its own (independents decide). `histogram` lists Democratic seat totals with
nonzero probability, ascending. `rating_counts` are counts of the **model's** labels among races up.

## `races.json` — array with one object per race (506 races)
```json
{
  "race_id": "GA-SEN", "chamber": "senate", "state": "GA", "state_name": "Georgia",
  "district": null, "special": false, "name": "Georgia Senate", "short": "GA-Sen",
  "incumbent": "Jon Ossoff", "incumbent_party": "D", "incumbent_running": true,
  "holder_party": "D", "open_seat": false,
  "pvi": -1.0, "pvi_label": "R+1",
  "dem": {"name": "Jon Ossoff", "party": "D", "incumbent": true, "receipts": 77279766.5, "cash": 42587451.0},
  "rep": {"name": "Mike Collins", "party": "R", "incumbent": false, "receipts": 7409349.6, "cash": 2079981.4},
  "p_dem": 0.936, "margin": 8.1, "sd": 5.3, "label": "Likely D",
  "rating": {"label": "Likely D", "score": 2.7, "n": 10},
  "polls": {"margin": 7.1, "n": 14, "n_eff": 6.2, "last": "2026-09-16"},
  "fundamentals": 10.5,
  "markets": {"p_dem": 0.935, "n": 3},
  "flip_prob": 0.064,
  "uncontested": false,
  "news_count": 15
}
```
`dem`/`rep`/`rating`/`polls`/`markets`/`flip_prob`/`pvi` may be `null`. `label` is one of
`Safe D, Likely D, Lean D, Tossup, Lean R, Likely R, Safe R`. `district` is an integer for House races
(0 = at-large) and null otherwise. `short` looks like `GA-Sen`, `TX-Gov`, `AZ-01`, `OH-Sen (special)`.
`rating.score` is D-positive on a −4..4 scale (−4 = every rater Safe R). `rating.n == 0` means no rater
lists the race and it is treated as safe for the holder.

## `races/{race_id}.json` — everything in the `races.json` object plus:
```json
{
  "candidates": [{"name": "Jon Ossoff", "party": "D", "incumbent": true, "major": true,
                  "receipts": 77279766.5, "disbursements": 59730545.5, "cash": 42587451.0, "coverage_end": "2026-06-30"}],
  "ratings": [{"rater": "Cook Political Report", "rating": "Lean D", "as_of": "2026-09-15"}],
  "poll_list": [{"pollster": "Quantus Insights", "sponsor_lean": "R", "start_date": "2026-09-14", "end_date": "2026-09-16",
                 "sample_size": 645, "population": "LV", "moe": 4.3, "dem_pct": 48.0, "rep_pct": 44.0, "und_pct": 7.0,
                 "margin": 4.0, "hypothetical": false, "weight": 0.83,
                 "matchup": [["Jon Ossoff", "D", 48.0], ["Mike Collins", "R", 44.0]]}],
  "poll_aggregates": [{"source": "RealClearPolitics", "as_of": "2026-09-18", "dem": 50.6, "rep": 43.1, "margin": 7.5}],
  "market_list": [{"platform": "polymarket", "title": "Georgia Senate Election Winner", "p_dem": 0.935, "p_rep": 0.0585,
                   "p_other": null, "volume": 153777.0, "url": "https://polymarket.com/event/...", "fetched_at": "2026-09-22T19:00:00+00:00"}],
  "news": [{"title": "...", "source": "USA Today", "published": "2026-09-22T16:43:59+00:00", "url": "https://..."}],
  "model": {
    "prior_margin": 9.6, "prior_sd": 6.0, "poll_margin": 7.1, "poll_sd": 4.7, "poll_weight": 0.62,
    "fundamentals": {"margin": 10.5, "lean": -1.0, "environment": 7.0, "incumbency": 3.0, "money": 1.5},
    "rating_margin": 9.0, "sigma_race": 4.5, "sigma_total": 5.3,
    "notes": ["Incumbent Jon Ossoff (D) is running."]
  },
  "history": [{"date": "2026-09-22", "p_dem": 0.936, "margin": 8.1}],
  "brief": {"text": "Two short paragraphs...", "generated_at": "2026-09-22T20:00:00+00:00", "model": "claude-opus-5"}
}
```
`brief` is null unless the optional AI analysis stage has run (`ingest --only analysis` with Anthropic credentials).
`poll_list` is sorted newest first; `weight` is the model's weight (0 for polls it ignored, e.g. too old or
a hypothetical matchup when real ones exist). `poll_list[].moe`, `und_pct`, `sample_size` may be null.
`market_list[].p_other` is the independent/third-party price when the platform lists one.

## `meta.json`
```json
{"generated_at": "...", "version": "0.1.0", "runs": [{"stage": "polls", "finished_at": "...", "ok": true, "note": "{...}"}]}
```
