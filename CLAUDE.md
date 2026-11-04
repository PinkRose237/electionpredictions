# electionpredictions — notes for Claude Code

2026 U.S. midterm forecast: Python pipeline (uv, Python 3.14) → SQLite → static JSON → dependency-free site.

- Run everything: `uv run electionpredictions run`; serve: `uv run electionpredictions serve`; tests: `uv run pytest -q`.
- Stages can be run alone: `uv run electionpredictions ingest --only polls,markets` (stages: races, ratings, generic, polls, fec, markets, news, analysis).
- All HTTP is cached under `data/cache/` (TTLs in `config.py`); delete a subfolder to force a refresh.
- `site/data/` is generated — never hand-edit it; change `src/electionpredictions/export.py` (schema in `docs/DATA_CONTRACT.md`).
- Margins are always Democratic minus Republican in points; probabilities are 0–1.
- Markets and news are context only; the model (`src/electionpredictions/model/`) must not use them.
- The decision layer (`sources/ai.py`) uses the OpenCode Go gateway (`https://opencode.ai/zen/go/v1`, OpenAI-compatible, `OPENCODE_API_KEY`), model `glm-5.3-flash` by default; pay-as-you-go Zen is `/zen/v1`; pipeline order is ingest -> model --baseline-only -> ai -> model -> export. The site must never mention AI.
- The FEC API `DEMO_KEY` is limited to ~10 requests/hour; fundraising comes from the bulk `weball26.zip` file.
- Wikipedia is fetched one whole page at a time; tables are located by heading path (`sources/wikipedia.py`).
- Election-night results: the site pulls the NYT (AP) results JSON, with CNN as backup, live in the browser (`site/live.js`); `uv run electionpredictions results [--watch 120 --push]` snapshots the same feeds to `site/data/results-auto.json` (`sources/live_results.py`, keep it in step with live.js). `results.json` holds only the admin page's manual overrides.
- Race Calls page (`site/calls.html`): `sources/race_calls.py` reads CNN, NBC, Bloomberg and AP(NYT) call feeds (Fox News was dropped on Nov 4) into `site/data/calls.json` (same `results` command). Lean labels are AllSides ratings; keep them sourced, never our own judgment.
- A race counts as called everywhere (site and Apple TV) only once 2 of the 4 outlets in calls.json agree and no other side has as many (a 2–2 split stays unconfirmed): `applyConsensus` in `site/live.js` and its twin in `tvos/ElectionNight/Models.swift`; without calls.json the AP feed's calls stand; manual results.json overrides still win.
