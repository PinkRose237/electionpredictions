# Site data contract — 2028 presidential model

`src/electionpredictions/export.py` writes these files into `site/data/`; the site reads only them (plus
`site/geo/us-maps.json`). Probabilities are 0–1. Margins are **Democratic minus Republican, in points**.
Contest ids: two-letter state codes (`PA`, `DC`) and `ME-1`, `ME-2`, `NE-1`, `NE-2`, `NE-3`; `ME` and `NE`
are the statewide contests (2 electors each). The 2026 midterm archive keeps its own frozen files in
`site/archive/2026/data/` (see `DATA_CONTRACT_2026.md`).

## `summary.json`
```json
{
  "generated_at": "2026-11-05T18:39:00+00:00", "election_date": "2028-11-07", "days_to_election": 733, "run_date": "2026-11-05",
  "model": {"version": 7, "latest_version": 7, "origin": "revision", "updated": "…", "title": "…", "summary": "…", "n_changes": 4, "n_sims": 20000},
  "ec": {"p_dem": 0.73, "p_rep": 0.27, "p_tie": 0.004,
         "dem_ev": {"mean": 307, "median": 307, "p05": 190, "p10": 226, "p25": 268, "p75": 348, "p90": 393, "p95": 420},
         "rep_ev": {"…": "same keys"}, "histogram": [{"ev": 270, "p": 0.006}]},
  "popular": {"margin": 4.9, "sd": 6.4, "p_dem": 0.8, "p10": -2.8, "p90": 12.5},
  "splits": {"dem_ec_rep_pv": 0.016, "rep_ec_dem_pv": 0.084},
  "environment": {"polls": 1.5, "fundamentals": 5.9, "poll_weight": 0.25, "adjustment": 0.0, "environment": 4.8,
                  "approval": {"net": -23.7, "approve": 36.8, "disapprove": 60.5, "as_of": "2026-11-01", "sources": 9},
                  "economy": {"as_of": "2026-09", "unemployment": 4.2, "unemployment_change": -0.2, "inflation": 3.7, "real_wage_growth": -0.7},
                  "econ_index": -1.3, "incumbent_party_margin": -5.9,
                  "national_polls": {"n": 58, "n_eff": 26.5, "average": 1.7, "last": "2026-10-14", "g_sd": 2.0}},
  "uncertainty": {"national_sd": 6.25, "state_sd": 3.9, "region_sd": 1.5, "trend_sd": 1.5, "tail_df": 6, "district_sd": 2.0},
  "nominees": {"D": [{"name": "Gavin Newsom", "p": 0.14, "effect": 0.35, "home_state": "CA", "p_win_if_nominee": 0.75, "dem_ev": 310, "pv_margin": 5.4}],
               "R": ["… (p_win_if_nominee is the Republican chance)"]},
  "scenarios": [{"dem": "Kamala Harris", "rep": "JD Vance", "p": 0.118, "p_dem": 0.76, "p_rep": 0.24, "dem_ev": 311, "pv_margin": 5.5}],
  "tipping": [{"id": "PA", "name": "Pennsylvania", "p": 0.21, "p_dem": 0.72, "evs": 19}],
  "closest": ["AZ", "NC"],
  "overview": {"summary": "…", "key_factors": ["…"], "nominations": {"D": "…", "R": "…"}, "watch": "…", "generated_at": "…"},
  "markets": {"party": [{"platform": "kalshi", "outcome": "D", "p": 0.66, "volume": 0, "url": "…"}], "party_dem": 0.67,
              "nominee_D": ["…"], "nominee_R": ["…"], "winner": ["…"]},
  "history": [{"date": "2026-11-05", "version": 7, "p_dem": 0.73, "p_rep": 0.27, "dem_ev": 307, "dem_ev_p10": 226, "dem_ev_p90": 393, "pv": 4.9, "env": 4.8}],
  "counts": {"national_polls": 63, "state_polls": 1, "primary_polls": 250, "ratings": 0, "markets": 106, "news": 57, "candidates": 22, "model_versions": 7}
}
```
`overview` is null when no summary has been written. `markets` are comparison only.

## `states.json`
One row per contest:
```json
{"id": "PA", "state": "PA", "district": null, "name": "Pennsylvania", "state_name": "Pennsylvania", "evs": 19,
 "lean": -1.0, "lean_label": "R+1.0", "hist_lean": -1.0, "p_dem": 0.72, "margin": 4.05, "sd": 7.6, "p10": -5.1, "p90": 13.2,
 "label": "Lean D", "tip": 0.21, "margin20": 1.16, "margin24": -1.71, "winner20": "D", "winner24": "R", "flip": 0.72,
 "n_polls": 0, "adjustment": null, "rating": null}
```
`lean` is the (poll-updated) margin relative to the nation; `hist_lean` the 2020/2024 record alone;
`tip` the chance the contest casts the 270th electoral vote; `flip` the chance it votes differently from 2024;
`rating` `{label, n}` once experts publish.

## `states/<id>.json`
The row above plus: `breakdown` (`historical_lean`, `rel20`, `rel24`, `poll_shift`, `environment`,
`nominee_effects`, `home_effect`, `adjustment`, `adjustment_reason`, `rating_pull`: they add up to `margin`),
`poll_update` (state-poll posterior), `polls` (each with `weight`), `ratings`, `matchups`
(`[{dem, rep, p, p_dem}]`, the contest's odds under each likely pairing), `news`, `overview`
(`{overview, key_factors, watch}` or null) and `history` (`[{date, p_dem, margin}]`).

## `scenarios.json`
The likeliest matchups (top 12) as in `summary.scenarios`, each with `states: {id: p_dem}`.

## `field.json`
`{parties: {D|R: {candidates: [...], other, average, n_polls, aggregates, polls, news, markets, narrative}}, scenarios, winner_markets}`.
A candidate: `name, party, status (declared|exploratory|potential), home_state, experience, announced,
primary_share, p_nominee, effect, p_win_if_nominee, dem_ev, poll_strength {strength, sd, n_polls},
receipts, cash, coverage_end, news`.

## `polls.json`
`national` and `state` trial heats (`id, pollster, sponsor, start, end, n, pop, dem, rep, dem_pct, rep_pct,
other_pct, und_pct, margin, contest, matchup, weight`), `strengths` (candidate polling strength from the
regression), `environment`, `approval` (latest aggregator rows), `approval_history`, `economy`
(`indicators`, `index`, `series`), `state_updates`.

## `model.json`
`current`: `version`, `origin` (`seed|calibration|revision`), `spec` (the full specification),
`parameters` (`[{path, value, low, high, max_step, description}]`), `effective` (`national_sd`, `state_sd`,
`default_poll_weight`, `poll_weight`, `days_to_election`). `versions`: newest first,
`[{version, created_at, run_date, origin, title, summary, changes: [{path, from, to, reason, label}]}]`.

## `meta.json`
`{generated_at, version, runs: [{stage, started_at, finished_at, ok, note}]}` (last 40 pipeline stages).
