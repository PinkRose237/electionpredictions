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
