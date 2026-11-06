# Presidential Model 2028

A forecast of the **2028 U.S. presidential election** (November 7, 2028) for all 56 Electoral College
contests: the 50 states, the District of Columbia, and the congressional districts of Maine and Nebraska.
A Python pipeline gathers polls, primary polling, the candidate fields, presidential approval, the economy,
expert ratings, fundraising, prediction markets and news; a simulation turns them into probabilities; static
JSON feeds a dependency-free website.

What sets it apart: **it runs continuously and rebuilds itself.** Every 15 minutes it refreshes the evidence
and reruns. Its specification (nomination odds, candidate strength, home states, the weight on polls versus
fundamentals, pollster house effects, the chance and effect of an independent bid, the size and shape of the
uncertainty, state-specific adjustments) moves with the data, and whenever there is new evidence an LLM
researches what it might be missing (targeted news searches), reviews everything and revises the
specification inside hard guardrails, keeping a running set of storylines as its memory of the race. Every
meaningful revision is stored as a numbered version with a changelog and published on the site's Model log.

```
sources ─▶ SQLite ─▶ calibrate (evidence deltas) ─▶ baseline ─▶ research ─▶ revise + storylines ─▶ guardrails ─▶ spec vN
                                                                                                                  │
  GitHub Pages ◀── site/ + forecast-data branch ◀── export ◀── summaries ◀── final run (50,000 sims, seeded by inputs) ◀┘
```

The retired **2026 midterm** site (results, race calls, scorecard, the frozen final forecast, the
corrections desk) lives in `site/archive/2026/`, reachable only after signing in on `admin.html`.

## Quick start

```bash
uv sync                                   # Python 3.14 environment
uv run electionpredictions sync-state     # optional: download the live model state (database + site/data)
uv run electionpredictions run            # ingest, rebuild the model, export site/data (~1 minute)
uv run electionpredictions serve          # http://localhost:8000
uv run pytest -q                          # tests
```

Commands:

```bash
uv run electionpredictions ingest [--only polls,primaries]   # stages: polls, primaries, approval, economy, ratings, money, markets, news
uv run electionpredictions model [--no-revision] [--no-narrative] [--sims 50000]   # calibrate, revise, run, store a new spec version
uv run electionpredictions export                            # write site/data
uv run electionpredictions run [--skip news,revision]        # all of the above
uv run electionpredictions status                            # database contents and the latest model versions
uv run electionpredictions sync-state                        # replace local database + site/data with the live state
uv run electionpredictions ai-probe                          # one tiny request per model chain + the gateway's model list
uv run electionpredictions ai-benchmark [--models a,b]       # time candidate models on a small spec-revision task
uv run electionpredictions set-admin-password                # the admin page / archive password (PBKDF2 hash, public)
uv run electionpredictions results [--watch 120 --push]      # archived 2026 site: results and race-call snapshots
```

All HTTP is cached under `data/cache/` (Wikipedia 1 h, markets 15 min, news 1 h, FEC 12 h, BLS 12 h).

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
| News | Google News RSS (race, both primaries, independents, calendar, leading candidates, closest states) plus the revision step's own targeted searches | Context for the revision step and the site |
| 2026 midterm results | The archived 2026 site's results (`sources/midterm2026.py`) | National House vote and statewide races: evidence for the revision step |

## How the forecast works

For every contest the expected Democratic-minus-Republican margin is

```
lean (2020/2024 vs nation, updated by state polls) + national environment
  + D nominee strength − R nominee strength + home-state effects + state adjustment + rating pull
```

- **National environment**: a weighted ridge regression over every national trial heat separates the overall
  environment from each candidate's strength and each repeat pollster's house effect; it is blended with a
  fundamentals estimate (presidential net approval and an economic index) with a weight on polls that grows
  toward Election Day.
- **Unknown nominees**: each of 50,000 simulations draws a Democratic and a Republican nominee from the
  nomination odds (including "someone else").
- **Correlated error**: national (fat-tailed, shrinking as the election nears), regional, along the
  2020-to-2024 realignment axis, state (fat-tailed), plus district noise, and in some simulations an independent
  candidate shifting the margin.
- **Deterministic**: the random seed is derived from the inputs, so the forecast moves only when the evidence or
  the model does, never from Monte Carlo noise between frequent runs.
- **Outputs**: chance of winning, electoral-vote distribution, popular vote, Electoral College/popular-vote
  split, tipping-point odds, each contest's odds and range, and the same outcomes for each possible nominee and
  each of the likeliest matchups.

Code: `src/electionpredictions/model/` (`spec.py` the specification and its guardrails, `calibrate.py`,
`evidence.py`, `contests.py`, `engine.py`, `store.py`). The full write-up is `site/methodology.html`.

## The self-rebuilding loop

`pipeline.rebuild` runs on every update:

1. **Calibrate** (`model/calibrate.py`): move the latest spec by how much the evidence changed since it was made
   (each version stores its evidence *basis*): nomination odds by the change in poll-implied odds, candidate
   strength by the change in the trial-heat regression; new candidates join as they appear. A revision's
   judgment therefore persists until new evidence arrives.
2. **Baseline**: simulate the calibrated proposal.
3. **Research + revise** (`revision.py`), whenever the raw evidence changed (and at least every 12 hours): the
   strongest model in `AI_MODELS_REVISION` (OpenCode Go gateway, `OPENCODE_API_KEY`; later models are
   fallbacks) first picks up to 8 targeted news searches, which the pipeline runs; then it receives the current
   spec, the proposal, every parameter's bounds and meaning, the evidence (polls, regression with house
   effects, primaries, the field, approval and its trend, economy, the 2026 midterm results, ratings,
   fundraising, headlines, the research results; never markets), how polls released since the last revision
   compared with the model's expectations, the proposal's diagnostics, the storylines and the recent revision
   history, and returns a complete spec, a title, a summary, a reason per change and the updated storylines.
4. **Guardrails** (`spec.validate`): hard bounds and a maximum step per revision for every parameter, ±5 for
   candidate strength, ±4 and at most 12 state adjustments, normalised nomination odds with at most 12 named
   candidates per party. Anything outside is limited (and the changelog says so); a failed or malformed
   revision leaves the calibrated spec in place.
5. **Version**: if the spec changed meaningfully (thresholds in `model/store.py`), it is stored as the next
   version in `model_specs` with its changelog and evidence basis.
6. **Final run + summaries** (`narrative.py`, `AI_MODELS_NARRATIVE`): 50,000 simulations on the spec, then the
   national overview and competitive-state summaries, rewritten only when their (rounded) inputs change.

Without `OPENCODE_API_KEY` steps 3 and 6 are skipped and the model still recalibrates itself every run.
Published text is scrubbed of self-references; the site presents all of this as the forecast's own model log
and never refers to AI.

## Keeping it updated

`.github/workflows/update.yml` runs the full pipeline and deploys `site/` to GitHub Pages, then **starts the next
run itself** after a pause (the `next` job), so an update lands about every 15 minutes around the clock. GitHub
throttles busy cron schedules (in practice runs were hours apart), so the cron is only a backstop that restarts the
loop if it stops; the workflow's concurrency group keeps exactly one loop. Set the repository variable
`FORECAST_PAUSED=true` to pause it, `FORECAST_INTERVAL_MIN` to change the pause (default 12 minutes).
The model's state (the database with every model version, and the published `site/data`) lives on the
**`forecast-data` branch** as a single commit that each run replaces, so `main` holds only code and the
repository does not grow with every update; `site/data` is git-ignored on main and copied in at deploy time
(`.github/actions/forecast-data`). HTTP responses are cached between runs with `actions/cache`.
Repository secrets: `OPENCODE_API_KEY` (research, revision, summaries) and optionally `FEC_API_KEY`;
repository variables `AI_MODELS_REVISION` / `AI_MODELS_NARRATIVE` override the model chains. Run it by hand
from the Actions tab; tick **dry_run** to run without saving or deploying (the exported data is attached as
an artifact).

`.github/workflows/results.yml` keeps the archived 2026 results and race calls fresh through November;
`deploy-site.yml` redeploys on any push under `site/`; `probe.yml` checks the AI gateway.

## The site

| Page | What it shows |
|---|---|
| `index.html` | Live status, chance of winning and its movement, electoral votes, trend, road to 270, map, storylines, overview, nominations, likeliest matchups, environment (incl. the 2026 midterm vote), tipping points, closest contests, recent model revisions, markets comparison |
| `map.html` | Electoral College map, overall or for any likely matchup, with a detail panel and EVs by category |
| `states.html` / `state.html?id=PA` | All 56 contests; one contest's odds, margin breakdown, matchups, trend, polls, past results, coverage |
| `field.html` | Both nomination contests: candidates, primary polling, nomination odds, strength, fundraising, markets |
| `polls.html` | Trial heats with their weights, candidate polling strength, pollster house effects, approval, the economy, the 2026 midterms |
| `model.html` | The current specification, storylines, every setting with its bounds, and every revision with its reasons |
| `methodology.html` | How it works |
| `admin.html` | Sign-in; links to the 2026 archive; pipeline log, the latest research searches, raw model data |

Plain HTML/CSS/JS modules, no build step: publish `site/` anywhere static files are served.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `OPENCODE_API_KEY` | unset | Enables research, revision and the summaries |
| `AI_MODELS_REVISION`, `AI_MODELS_NARRATIVE` | see `config.py` | Comma-separated model chains (first that answers wins) |
| `AI_MODEL` | unset | A single model put first in both chains |
| `AI_BASE_URL` | `https://opencode.ai/zen/go/v1` | Gateway (pay-as-you-go Zen: `/zen/v1`) |
| `FEC_API_KEY` | `DEMO_KEY` | FEC API (the demo key allows ~10 requests/hour; the stage makes one or two) |
| `EP_TTL_WIKI`, `EP_TTL_MARKETS`, `EP_TTL_NEWS`, `EP_TTL_FEC`, `EP_TTL_ECON` | 1h / 15m / 1h / 12h / 12h | Cache lifetimes (seconds) |

## Project layout

```
src/electionpredictions/
  config.py        constants: election date, 56 contests and their electoral votes, regions, keys, TTLs
  history.py       certified 2020/2024 results by state and district (frozen)
  db.py            SQLite schema and helpers
  sources/         polls, primaries, approval, economy, ratings, money, markets, news, midterm2026 (+ wikipedia/http helpers)
  model/           spec (+guardrails), calibrate, evidence, contests, engine (simulation), store (versions)
  llm.py           OpenCode gateway client (model chains with fallback, benchmark)
  revision.py      research + revision + storylines
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
- Third-party candidates are folded into the two-party margin (a possible independent bid is modelled as a
  shift); polls including them are down-weighted.
- Published text comes from a language model working from headlines (not article text); it is scrubbed of
  self-references and bounded by the guardrails, but it can be wrong in the way any summary can.
- Candidate strength and home-state effects are rough; early state polling is sparse.
- The admin gate is client-side (the archive's files are public if you know the URL); publishing corrections
  still requires the admin's own GitHub token.
