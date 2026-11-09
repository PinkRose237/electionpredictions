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
Also: `storylines` (`[{title, detail, leans: D|R|neutral, importance: 1-3, since}]`, the developments the
forecast tracks), `revisions` (the latest six versions: `{version, created_at, origin, title, summary, n_changes}`),
`recent` (every update's numbers over the last week, thinned: `[{ts, v, p_dem, p_rep, dem_ev, pv}]`) and
`midterm_2026` (`{as_of, house_vote: {dem, rep, other, margin, dem_pct, rep_pct}, seats: {house|senate|governor: {D, R, counting}}}`).
`overview` is null when no summary has been written. `markets` are comparison only. `generated_at` changes on
every run (about every 15 minutes); the pages watch it and offer a refresh.

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
(`{overview, key_factors, watch}` or null), `midterm_2026` (the state's 2026 Senate/governor results:
`{senate|senate_special|governor: {margin, reporting, status, vs_national_house}}`, statewide contests only) and
`history` (`[{date, p_dem, margin}]`).

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
regression), `house_effects` (`{pollster: {effect, sd, n_polls}}`), `midterm_2026` (as in summary, plus
`statewide`), `environment`, `approval` (latest aggregator rows), `approval_history`, `economy`
(`indicators`, `index`, `series`), `state_updates`.

## `model.json`
`current`: `version`, `origin` (`seed|calibration|revision`), `spec` (the full specification),
`parameters` (`[{path, value, low, high, max_step, description}]`), `effective` (`national_sd`, `state_sd`,
`default_poll_weight`, `poll_weight`, `days_to_election`). `versions`: newest first,
`[{version, created_at, run_date, origin, title, summary, model, changes: [{path, from, to, reason, label}]}]`
(the latest 200; `total_versions` counts all), and `storylines`.

## `meta.json`
`{generated_at, version, runs: [{stage, started_at, finished_at, ok, note}], research: [{created_at, query, why, results}]}`
(last 40 pipeline stages; the latest research searches, shown on the admin page).

## `hegseth.json`

Independent event forecast; all probabilities are 0–1. No election or market inputs.
`available` is false before tracking begins (November 9, 2026), with a `message` for the page.
Otherwise:

- `generated_at`, `as_of`, `term_end` (exclusive January 20, 2029 deadline).
- `status`: `{state, was_impeached, verified_on, url}`. A manually verified state, separate from forecasts.
- `reviewed_at`, `initial_assumptions`, `review_stale` (review older than two days), `model_version`, `summary`.
- `rates`, `background`: `{firing, resignation, impeachment, conviction}` conditional daily hazards,
  not horizon probabilities. `bounds` has `[low, high]` for each reviewed rate. `elevated_until` is the
  original review date plus 90 days; afterward background rates apply.
- `horizons`: `[{id: "30d"|"90d"|"term", label, deadline, days, probabilities, sensitivity}]`.
  Deadlines are capped at the term end. Each `probabilities` object has `forced_exit`, `fired`,
  `impeached`, `removed`, `resigned`, `any_exit`, `still_serving`.
  `forced_exit = fired + removed`; `any_exit = forced_exit + resigned = 1 - still_serving`;
  `removed <= impeached`. Impeachment overlaps departure outcomes and must not be added to them.
  `sensitivity` maps each metric to `[low, high]` across assumption scenarios, **not a confidence interval**.
- `sources`: `[{date|null, source, title, detail, url}]` supporting the initial assessment and process.
- `news`: `[{title, source, published, url}]` (last 30 days, maximum 24); `news_fetched_at` is the last
  successful collection time, not the assumption review time. `last_update` is `{finished_at, ok, note}`
  or null; `note` is JSON with collection/review status and warnings.
- `reviews`: latest 40, newest first: `[{id, date, initial, summary, reasons}]`.
  `reasons` maps a changed rate to `{before, after, reason, urls}`.
- `history`: `[{date, horizons}]`, one actual saved observation per day, same horizon schema.
  No backfill. The 30/90-day histories have rolling deadlines; the end-of-term deadline is fixed.

The tracker reads only this file and works without `summary.json`. The page polls its own
`generated_at` for updates. Its SQLite tables are `hegseth_news`, `hegseth_reviews`, `hegseth_history`.
