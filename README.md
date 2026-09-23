# Midterm Model 2026

A self-updating forecast of **every 2026 U.S. midterm race**: all 435 House seats, the 35 Senate
seats (including the Ohio and Florida specials) and the 36 governorships. A Python pipeline pulls
polls, expert ratings, fundraising, prediction-market odds and news, runs a simulation-based
forecast, and writes static JSON that a dependency-free website renders.

```
sources ──▶ SQLite (data/elections.db) ──▶ model ──▶ site/data/*.json ──▶ static site (site/)
```

## Quick start

```bash
uv sync                                   # Python 3.14 environment (uses uv)
uv run electionpredictions run            # ingest everything, run the model, export the site data (~10 min first time)
uv run electionpredictions serve          # http://localhost:8000
```

Individual stages:

```bash
uv run electionpredictions ingest                       # all sources
uv run electionpredictions ingest --only polls,markets  # some sources (races,ratings,generic,polls,fec,wiki_fundraising,followthemoney,census,markets,news,ai)
uv run electionpredictions model --sims 20000           # simulation on the decided numbers (stores a dated snapshot)
uv run electionpredictions model --baseline-only        # pure quantitative forecast, ignoring the decision layer
uv run electionpredictions export                       # write site/data/
uv run electionpredictions status                       # what's in the database
uv run pytest                                           # tests
```

Every source is cached on disk under `data/cache/` (Wikipedia 6 h, markets 1 h, news 3 h, FEC 24 h),
so re-runs are fast and polite to the upstream sites.

## What goes in

| Input | Source | Notes |
|---|---|---|
| Race universe, candidates, incumbents, 2026 Cook PVI | Wikipedia's 2026 House/Senate/gubernatorial election articles | Reflects mid-decade redistricting (TX, CA, FL, MO, NC, OH, UT, AL, LA…) |
| Expert ratings (Cook, Inside Elections, Sabato, DDHQ, Silver Bulletin, Split Ticket, Economist, FiftyPlusOne, Fox, RCP) | Wikipedia's ratings aggregation tables | ~1,900 ratings, refreshed daily |
| General-election polls | Each race's Wikipedia article (which aggregates published polls) | ~1,150 polls across 145 races; ranked-choice rounds and hypothetical matchups handled |
| Generic congressional ballot | Aggregator averages (DDHQ, FiftyPlusOne, RCP, Silver Bulletin) | Drives the national environment |
| Fundraising | FEC bulk "all candidates" summary file; Wikipedia "Fundraising" tables as backfill | Governors file with state agencies, so their money comes from the Wikipedia tables (state-filing figures) |
| Prediction markets | Polymarket, PredictIt, Kalshi | Shown for comparison only — **not** a model input |
| News | Google News RSS, per race | Headlines for context; not a model input |
| Poll-closing times & call-time history | The Green Papers (2026 closing times); AP race-call timing 2018–2024 | `src/electionpredictions/schedule.py`, exported to `site/data/schedule.json` |

## How the forecast is decided

1. **Evidence**: every source above is ingested into SQLite.
2. **Baseline**: the quantitative model (below) turns the evidence into a margin and uncertainty per race.
3. **Decisions**: an LLM (Meta Muse Spark 1.3 via OpenCode Zen, `OPENCODE_API_KEY`) reviews each
   race's full dossier (candidates, money and outside spending, ratings, polls, markets, headlines, the baseline)
   and returns a strict-JSON decision: final margin, uncertainty, label, key factors, rationale, what to watch,
   and a two-paragraph overview. A national review sets a shared environment adjustment and the scale of the
   national error term. Decisions are cached by an evidence hash, so a daily run re-decides only races whose
   data changed (`AI_MAX_CALLS` caps a run, default 700).
4. **Guardrails** (`model/forecast.py`): a decision may move a race at most 10 points from the baseline, its
   uncertainty is kept between 2.5 and 12 points, malformed replies are rejected, and a race with no valid
   decision keeps the baseline. Uncontested races are fixed.
5. **Simulation**: 20,000 correlated Monte Carlo draws on the decided numbers produce the probabilities, seat
   totals and control odds the site shows, so everything stays coherent.

The site itself does not label any of this; it presents the forecast. `uv run electionpredictions model
--baseline-only` reproduces the pure quantitative forecast for comparison.

## How the model works (short version)

For every race the model builds a **prior** from fundamentals (partisan lean + national environment
+ incumbency + fundraising) blended 40/60 with the expert-rating consensus, then updates it with a
recency/sample/quality-weighted **polling average** using inverse-variance weighting. 20,000 Monte
Carlo simulations add a shared national swing, regional and state swings, and a fat-tailed
race-specific error, which is what makes seat totals and control probabilities honest about
correlated polling misses. The full write-up is in `site/methodology.html`; the implementation is
`src/electionpredictions/model/`.

## Entering election results (admin page)

`site/admin.html` is a password-gated results-entry page for every race, grouped by state with each
state's official results link and a live poll-closing countdown. Entries autosave in the browser;
**Publish** commits `site/data/results.json` to the repo with your own GitHub token (a fine-grained
personal access token with *Contents: read and write* on this repo, stored only in your browser), and
`.github/workflows/deploy-site.yml` redeploys the site. The results page and race pages then show the
entered numbers.

- Set or change the password: `uv run electionpredictions set-admin-password` (writes a PBKDF2 hash
  to `site/admin-config.json`; use a long passphrase, the hash is public).
- The gate is client-side, as on any static site: it keeps casual visitors out of the UI, but the
  thing that actually protects the live site is the GitHub token, which never leaves your browser.
- Export/Import JSON and "Load published" let you move drafts between devices.

## Keeping it updated

The forecast is meant to be re-run daily. Three options:

**1. GitHub Actions (recommended).** `.github/workflows/update.yml` runs the pipeline every day,
commits `site/data/` and deploys `site/` to GitHub Pages. Enable Pages (Settings → Pages → Source:
GitHub Actions) and optionally add an `FEC_API_KEY` repository secret.

**2. cron.** Run at 07:15 local time:

```
15 7 * * * cd /path/to/electionpredictions && uv run electionpredictions run >> data/run.log 2>&1
```

**3. launchd (macOS).** See `docs/SCHEDULING.md`.

Because the exporter merges each run's history into the published JSON, trend lines survive even if
the SQLite database is rebuilt from scratch.

## Deploying the site

`site/` is plain HTML/CSS/JS with no build step. Publish that directory anywhere static files are
served: GitHub Pages (the workflow does this), Netlify (`publish = "site"`), Vercel, S3, or
`python3 -m http.server --directory site`.

## API keys (all optional, all free)

Put keys in a `.env` file at the repo root (see `.env.example`; git-ignored) for local runs, and as
repository secrets with the same names for the GitHub Actions workflow. Each one unlocks a source:

| Key | Get it | What it adds |
|---|---|---|
| `FEC_API_KEY` | https://api.data.gov/signup (instant, 1,000 req/hour) | Fresh candidate totals layered over the weekly bulk file, plus **outside spending** (independent expenditures for/against every federal principal candidate) which feeds the money term |
| `FOLLOWTHEMONEY_API_KEY` | free account at https://www.followthemoney.org | **Governor fundraising** from state campaign-finance filings for the candidates Wikipedia doesn't cover |
| `CENSUS_API_KEY` | https://api.census.gov/data/key_signup.html (instant) | **District and state demographics** (college share, white non-Hispanic share); the simulation then moves demographically similar races together when it draws errors |
| `OPENCODE_API_KEY` | https://opencode.ai/auth (OpenCode Zen, billing required) | The decision layer: per-race forecast decisions, overviews and the national review by Meta's Muse Spark 1.3 (paid tier, about $1.25/M input and $4.25/M output tokens; a full 506-race pass is roughly $3-4, a typical daily refresh about $2). OpenCode's free `-contributor-free` tier only works inside the OpenCode client. Without a key the quantitative baseline stands. |

Without keys the pipeline runs exactly as before. States that redrew maps for 2026 use statewide demographics because ACS district data predates the new lines.

## Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `FEC_API_KEY` | `DEMO_KEY` | Real key enables API refresh + outside spending (DEMO_KEY is limited to ~40 requests/hour) |
| `FOLLOWTHEMONEY_API_KEY`, `CENSUS_API_KEY` | unset | Enable the `followthemoney` and `census` stages |
| `EP_TTL_WIKI`, `EP_TTL_MARKETS`, `EP_TTL_NEWS`, `EP_TTL_FEC` | 6h / 1h / 3h / 24h | Cache lifetimes in seconds |
| `EP_USER_AGENT` | project string | Sent with every request |
| `OPENCODE_API_KEY` | unset | Enables the decision layer (`ingest --only ai`); `AI_MODEL`, `AI_BASE_URL`, `AI_MAX_CALLS` tune it |

## Project layout

```
src/electionpredictions/
  config.py            constants (election date, seat math, regions, cache TTLs)
  db.py                SQLite schema + helpers
  util.py              parsers (PVI, percentages, poll dates, candidate strings, ratings)
  sources/
    wikipedia.py       cached page fetch + table extraction with section paths
    races.py           race universe & candidates (Senate, governors, all 435 House seats)
    ratings.py         expert ratings
    generic_ballot.py  national environment
    polls.py           per-race polls (incl. ranked-choice rounds, hypothetical matchups)
    fec.py             fundraising (bulk file, API fallback)
    wiki_fundraising.py  fundraising backfill from race articles (governors, unmatched candidates)
    followthemoney.py  governor fundraising from state filings (needs key)
    census.py          ACS demographics for correlated simulation errors (needs key)
    markets.py         Polymarket / PredictIt / Kalshi
    news.py            Google News RSS
  model/
    pollavg.py         weighted polling average
    fundamentals.py    lean + environment + incumbency + money; rating consensus
    forecast.py        combination, Monte Carlo simulation, chamber math
  schedule.py          poll-closing times per race + expected AP call windows (Election Results page)
  export.py            site/data JSON (schema in docs/DATA_CONTRACT.md)
  cli.py               command-line interface
site/                  the website (index.html, results.html, admin.html, race.html, methodology.html, *.js, styles.css, data/)
tests/                 pytest suite
```

## Known limitations

- Wikipedia's poll tables can lag or contain transcription errors; polls get pollster quality tiers
  and a partisan-sponsor adjustment but no per-pollster house-effect estimate.
- District-level House polling is sparse, so most House seats lean on fundamentals and ratings.
- After mid-decade redistricting some incumbents' "last result" and district history are not
  comparable; the model uses the new-district PVI.
- Independents are mapped onto a Democratic or Republican "side" for the two-party framing; a
  non-caucusing independent (Nebraska) counts as neither party for Senate control.
- Louisiana's new closed primaries, California's top-two and Alaska's ranked-choice generals are
  handled with simple rules described in the methodology.
