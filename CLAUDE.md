# electionpredictions — notes for Claude Code

2026 U.S. midterm forecast: Python pipeline (uv, Python 3.14) → SQLite → static JSON → dependency-free site.

- Run everything: `uv run electionpredictions run`; serve: `uv run electionpredictions serve`; tests: `uv run pytest -q`.
- Stages can be run alone: `uv run electionpredictions ingest --only polls,markets` (stages: races, ratings, generic, polls, fec, markets, news, analysis).
- All HTTP is cached under `data/cache/` (TTLs in `config.py`); delete a subfolder to force a refresh.
- `site/data/` is generated — never hand-edit it; change `src/electionpredictions/export.py` (schema in `docs/DATA_CONTRACT.md`).
- Margins are always Democratic minus Republican in points; probabilities are 0–1.
- Markets and news are context only; the model (`src/electionpredictions/model/`) must not use them.
- AI race briefs use OpenCode Zen (OpenAI-compatible, `OPENCODE_API_KEY`), model `muse-spark-1.3-contributor-free` by default; not the Anthropic SDK.
- The FEC API `DEMO_KEY` is limited to ~10 requests/hour; fundraising comes from the bulk `weball26.zip` file.
- Wikipedia is fetched one whole page at a time; tables are located by heading path (`sources/wikipedia.py`).
