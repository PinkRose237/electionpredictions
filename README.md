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
uv run electionpredictions ingest --only polls,markets  # some sources (races,ratings,generic,polls,fec,markets,news)
uv run electionpredictions model --sims 20000           # forecast + simulation (stores a dated snapshot)
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
| Fundraising | FEC bulk "all candidates" summary file | No API key needed; `FEC_API_KEY` enables the API fallback |
| Prediction markets | Polymarket, PredictIt, Kalshi | Shown for comparison only — **not** a model input |
| News | Google News RSS, per race | Headlines for context; not a model input |

## How the model works (short version)

For every race the model builds a **prior** from fundamentals (partisan lean + national environment
+ incumbency + fundraising) blended 40/60 with the expert-rating consensus, then updates it with a
recency/sample/quality-weighted **polling average** using inverse-variance weighting. 20,000 Monte
Carlo simulations add a shared national swing, regional and state swings, and a fat-tailed
race-specific error, which is what makes seat totals and control probabilities honest about
correlated polling misses. The full write-up is in `site/methodology.html`; the implementation is
`src/electionpredictions/model/`.

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

## Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `FEC_API_KEY` | `DEMO_KEY` | Only used by the API fallback (DEMO_KEY allows ~10 requests/hour) |
| `EP_TTL_WIKI`, `EP_TTL_MARKETS`, `EP_TTL_NEWS`, `EP_TTL_FEC` | 6h / 1h / 3h / 24h | Cache lifetimes in seconds |
| `EP_USER_AGENT` | project string | Sent with every request |
| `ANTHROPIC_API_KEY` | unset | Enables the optional AI race briefs (`ingest --only analysis`) |

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
    markets.py         Polymarket / PredictIt / Kalshi
    news.py            Google News RSS
  model/
    pollavg.py         weighted polling average
    fundamentals.py    lean + environment + incumbency + money; rating consensus
    forecast.py        combination, Monte Carlo simulation, chamber math
  export.py            site/data JSON (schema in docs/DATA_CONTRACT.md)
  cli.py               command-line interface
site/                  the website (index.html, race.html, methodology.html, *.js, styles.css, data/)
tests/                 pytest suite
```

## Known limitations

- Wikipedia's poll tables can lag or contain transcription errors; polls are not yet adjusted for
  pollster house effects.
- District-level House polling is sparse, so most House seats lean on fundamentals and ratings.
- After mid-decade redistricting some incumbents' "last result" and district history are not
  comparable; the model uses the new-district PVI.
- Independents are mapped onto a Democratic or Republican "side" for the two-party framing; a
  non-caucusing independent (Nebraska) counts as neither party for Senate control.
- Louisiana's new closed primaries, California's top-two and Alaska's ranked-choice generals are
  handled with simple rules described in the methodology.
