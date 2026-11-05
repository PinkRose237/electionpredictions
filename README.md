# Presidential Model 2028

A forecast of the **2028 U.S. presidential election** (November 7, 2028) for all 56 Electoral College
contests: the 50 states, the District of Columbia, and the congressional districts of Maine and Nebraska.
A Python pipeline gathers polls, primary polling, the candidate fields, presidential approval, the economy,
expert ratings, fundraising, prediction markets and news; a simulation turns them into probabilities; static
JSON feeds a dependency-free website.

What sets it apart: **the model rebuilds itself at every update.** Its specification (nomination odds,
candidate strength, home states, the weight on polls versus fundamentals, the size and shape of the
uncertainty, state-specific adjustments) is recalibrated from the data and then revised against the full body
of evidence by an LLM reviewer, inside hard guardrails. Every revision is stored as a numbered version with a
changelog and published on the site's Model log.

```
sources ─▶ SQLite (data/president2028.db) ─▶ calibrate ─▶ baseline run ─▶ revise ─▶ guardrails ─▶ spec vN
                                                                                                    │
                    static site (site/) ◀── site/data/*.json ◀── export ◀── summaries ◀── final run ◀┘
```

The retired **2026 midterm** site (results, race calls, scorecard, the frozen final forecast, the
corrections desk) lives in `site/archive/2026/`, reachable only after signing in on `admin.html`.

## Quick start

```bash
uv sync                                   # Python 3.14 environment
uv run electionpredictions run            # ingest, rebuild the model, export site/data (~1 minute)
uv run electionpredictions serve          # http://localhost:8000
uv run pytest -q                          # tests
```

Commands:

```bash
uv run electionpredictions ingest [--only polls,primaries]   # stages: polls, primaries, approval, economy, ratings, money, markets, news
uv run electionpredictions model [--no-revision] [--no-narrative] [--sims 20000]   # calibrate, revise, run, store a new spec version
uv run electionpredictions export                            # write site/data
uv run electionpredictions run [--skip news,revision]        # all of the above
uv run electionpredictions status                            # database contents and the latest model versions
uv run electionpredictions ai-probe                          # one tiny request to the AI gateway (diagnostics)
uv run electionpredictions set-admin-password                # the admin page / archive password (PBKDF2 hash, public)
uv run electionpredictions results [--watch 120 --push]      # archived 2026 site: results and race-call snapshots
```

All HTTP is cached under `data/cache/` (Wikipedia 6 h, markets 1 h, news 3 h, FEC 24 h, BLS 12 h).

## What goes in

| Input | Source | Used for |
|---|---|---|
| 2020 and 2024 results by state and district | Wikipedia "Results by state" tables, frozen in `history.py` | Each contest's partisan lean |
| General-election trial heats (national and state) | Wikipedia's 2028 election article, one table per matchup | National environment, candidate strength, state leans |
| Primary polls, aggregator averages, declared candidates | Wikipedia's 2028 primaries and primary-polling articles | The candidate fields and nomination odds |
| Presidential approval | Wikipedia's aggregator table ("Opinion polling on the second Trump presidency") | Fundamentals |
| Inflation, unemployment, real wages | Bureau of Labor Statistics public API | Fundamentals |
| Expert ratings | Wikipedia "Predictions" table, once raters publish | Pull on state margins |
| Fundraising | FEC API (office P) | Context for the revision step and the site |
| Prediction markets | Polymarket, Kalshi | **Comparison only**: never a model input, never shown to the reviewer |
| News | Google News RSS (race, both primaries, leading candidates, closest states) | Context for the revision step and the site |

## How the forecast works

For every contest the expected Democratic-minus-Republican margin is

```
lean (2020/2024 vs nation, updated by state polls) + national environment
  + D nominee strength − R nominee strength + home-state effects + state adjustment + rating pull
```

- **National environment**: a weighted ridge regression over every national trial heat separates the overall
  environment from each candidate's strength; it is blended with a fundamentals estimate (presidential net
  approval and an economic index) with a weight on polls that grows toward Election Day.
- **Unknown nominees**: each of 20,000 simulations draws a Democratic and a Republican nominee from the
  nomination odds (including "someone else").
- **Correlated error**: national (fat-tailed, shrinking as the election nears), regional, along the
  2020-to-2024 realignment axis, state (fat-tailed), plus district noise.
- **Outputs**: chance of winning, electoral-vote distribution, popular vote, Electoral College/popular-vote
  split, tipping-point odds, each contest's odds and range, and the same outcomes for each possible nominee and
  each of the likeliest matchups.

Code: `src/electionpredictions/model/` (`spec.py` the specification and its guardrails, `calibrate.py`,
`evidence.py`, `contests.py`, `engine.py`, `store.py`). The full write-up is `site/methodology.html`.

## The self-rebuilding loop

`pipeline.rebuild` runs on every update:

1. **Calibrate** (`model/calibrate.py`): re-derive the data-driven parts of the latest spec: nomination odds
   from primary polling (blended 50/50 with the previous odds), candidate strength from the trial-heat
   regression, new candidates as they appear, home states.
2. **Baseline**: simulate the calibrated proposal.
3. **Revise** (`revision.py`): the reviewer (GLM 5.3 Flash through the OpenCode Go gateway, `OPENCODE_API_KEY`)
   receives the current spec, the proposal, every parameter's bounds and meaning, the evidence (polls,
   regression, primaries, the field, approval, economy, ratings, fundraising, headlines; never markets), the
   proposal's diagnostics and the recent revision history, and returns a complete spec with a title, a
   summary and a reason per change.
4. **Guardrails** (`spec.validate`): hard bounds and a maximum step per revision for every parameter, ±5 for
   candidate strength, ±4 and at most 12 state adjustments, normalised nomination odds with at most 12 named
   candidates per party. Anything outside is limited (and the changelog says so); a failed or malformed
   revision leaves the calibrated spec in place.
5. **Version**: if the spec changed, it is stored as the next version in `model_specs` with its changelog.
6. **Final run + summaries** (`narrative.py`): 20,000 simulations on the new spec, then the national overview
   and competitive-state summaries, cached by input hash.

Without `OPENCODE_API_KEY` steps 3 and 6 are skipped and the model still recalibrates itself every run.
The site presents all of this as the forecast's own model log; it never refers to AI.

## Keeping it updated

`.github/workflows/update.yml` runs the full pipeline twice a day (11:17 and 23:17 UTC), commits `site/data`
and deploys `site/` to GitHub Pages. Repository secrets: `OPENCODE_API_KEY` (revision + summaries) and
optionally `FEC_API_KEY`. Run it by hand from the Actions tab; tick **dry_run** to run without committing
or deploying (the exported data is attached as an artifact). The exporter merges each run's history into the
published JSON, so trend lines survive a rebuilt database.

`.github/workflows/results.yml` keeps the archived 2026 results and race calls fresh through November;
`deploy-site.yml` redeploys on any push under `site/`; `probe.yml` checks the AI gateway.

## The site

| Page | What it shows |
|---|---|
| `index.html` | Chance of winning, electoral votes, trend, road to 270, map, overview, nominations, likeliest matchups, environment, tipping points, closest contests, latest model revision, markets comparison |
| `map.html` | Electoral College map, overall or for any likely matchup, with a detail panel and EVs by category |
| `states.html` / `state.html?id=PA` | All 56 contests; one contest's odds, margin breakdown, matchups, trend, polls, past results, coverage |
| `field.html` | Both nomination contests: candidates, primary polling, nomination odds, strength, fundraising, markets |
| `polls.html` | Trial heats with their weights, candidate polling strength, approval, the economy |
| `model.html` | The current specification, every setting with its bounds, and every revision with its reasons |
| `methodology.html` | How it works |
| `admin.html` | Sign-in; links to the 2026 archive; pipeline log and raw model data |

Plain HTML/CSS/JS modules, no build step: publish `site/` anywhere static files are served.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `OPENCODE_API_KEY` | unset | Enables the revision step and the summaries |
| `AI_MODEL`, `AI_BASE_URL` | `glm-5.3-flash`, `https://opencode.ai/zen/go/v1` | Model and gateway (pay-as-you-go Zen: `/zen/v1`) |
| `FEC_API_KEY` | `DEMO_KEY` | FEC API (the demo key allows ~10 requests/hour; the stage makes one or two) |
| `EP_TTL_WIKI`, `EP_TTL_MARKETS`, `EP_TTL_NEWS`, `EP_TTL_FEC`, `EP_TTL_ECON` | 6h / 1h / 3h / 24h / 12h | Cache lifetimes (seconds) |

## Project layout

```
src/electionpredictions/
  config.py        constants: election date, 56 contests and their electoral votes, regions, keys, TTLs
  history.py       certified 2020/2024 results by state and district (frozen)
  db.py            SQLite schema and helpers
  sources/         polls, primaries, approval, economy, ratings, money, markets, news (+ wikipedia/http helpers)
  model/           spec (+guardrails), calibrate, evidence, contests, engine (simulation), store (versions)
  llm.py           OpenCode gateway client
  revision.py      the model-revision step
  narrative.py     national and state summaries
  pipeline.py      ingest + rebuild orchestration
  export.py        site/data JSON (schema: docs/DATA_CONTRACT.md)
  archive2026/     results and race-call snapshots for the archived 2026 site
  cli.py, admin.py
site/              the 2028 site; site/archive/2026/ the retired midterm site (admin-only)
tests/             pytest suite (offline; the revision step is tested with a mocked LLM)
tvos/              Apple TV results board for the 2026 election night (reads the archive's data)
```

## Known limitations

- Two years out, hypothetical trial heats have a poor record; the forecast leans on fundamentals and keeps
  wide ranges on purpose.
- Third-party candidates are folded into the two-party margin; polls including them are down-weighted.
- Candidate strength and home-state effects are rough; early state polling is sparse.
- The admin gate is client-side (the archive's files are public if you know the URL); publishing corrections
  still requires the admin's own GitHub token.
