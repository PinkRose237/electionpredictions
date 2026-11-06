# electionpredictions — notes for Claude Code

2028 U.S. presidential forecast ("Presidential Model 2028"): Python pipeline (uv, Python 3.14) → SQLite
(`data/president2028.db`) → static JSON (`site/data/`) → dependency-free site (`site/`).

- Run everything: `uv run electionpredictions run`; serve: `uv run electionpredictions serve`; tests: `uv run pytest -q`.
- Ingest stages can run alone: `uv run electionpredictions ingest --only polls,primaries` (polls, primaries, approval, economy, ratings, money, markets, news).
- All HTTP is cached under `data/cache/` (TTLs in `config.py`); delete a subfolder to force a refresh.
- `site/data/` is generated — never hand-edit it; change `src/electionpredictions/export.py` (schema in `docs/DATA_CONTRACT.md`).
- Margins are always Democratic minus Republican in points; probabilities are 0–1. 56 contests: 50 states, DC, ME-1/ME-2, NE-1/NE-2/NE-3 (ME and NE statewide carry 2 electors each); 538 total, 270 to win.
- The model rebuilds itself every run (`pipeline.rebuild`): calibrate (`model/calibrate.py`) → baseline run → revision (`revision.py`, LLM) → guardrails (`model/spec.py: validate`) → new spec version in `model_specs` if it changed → final run (`model/engine.py`) → summaries (`narrative.py`) → export. New tunable settings go in `spec.BOUNDS` + `DESCRIPTIONS` (with a max step) so the revision step and the Model log page pick them up.
- Markets are context only: never a model input and never shown to the revision step. News informs the revision step but never enters the simulation directly.
- The LLM layer (`llm.py`) uses the OpenCode Go gateway (`https://opencode.ai/zen/go/v1`, OpenAI-compatible, `OPENCODE_API_KEY`), model `glm-5.3-flash`; pay-as-you-go Zen is `/zen/v1`. Without a key the model still recalibrates every run. The site must never mention AI (the revision log is presented as the model's own revisions).
- Lean comes from real 2020/2024 results in `history.py` (margin scale, relative to the national margin), not Cook PVI (PVI is a share scale, half the size).
- Wikipedia is fetched one whole page at a time; tables are located by heading path (`sources/wikipedia.py`). Trial-heat tables live under "Opinion polling > General election > Nationwide/Statewide > <A vs. B>"; Donald Trump is term-limited and is filtered out of primary polls (`primaries.INELIGIBLE`).
- The FEC `DEMO_KEY` is limited to ~10 requests/hour; the money stage makes one or two.
- Retired 2026 midterm site: `site/archive/2026/` (frozen pages, JS, CSS and data; every page loads `archive-gate.js`, which requires the admin sign-in from `site/admin.html`, same `admin-ok` storage key). Never re-run or re-export the 2026 forecast. `uv run electionpredictions results` (code in `archive2026/`) still snapshots results/race calls into `site/archive/2026/data/` through November (`results.yml`); the archived corrections desk publishes `site/archive/2026/data/results.json`. The 2-of-4 outlet consensus rule (`applyConsensus` in `archive/2026/live.js` and `tvos/ElectionNight/Models.swift`) is unchanged; tvOS reads `/archive/2026/data/`.
- `update.yml` runs the 2028 pipeline at 2:00 AM and 2:00 PM Eastern (UTC crons for EDT and EST plus a `gate` job) and deploys; `workflow_dispatch` with `dry_run` runs it without committing.
