"""Command-line entry point for the 2028 presidential model: ingest -> rebuild -> export -> serve."""
from __future__ import annotations

import argparse
import functools
import http.server
import json
import sys
import time

from .config import SITE_DIR, days_to_election
from .db import connect, now_iso, rows
from .pipeline import STAGES, ingest, rebuild


def export(con):
    from .export import export as _export

    print("[export]")
    return _export(con)


def status(con):
    print("Polls:", rows(con, "SELECT scope, count(*) n, max(end_date) newest FROM polls GROUP BY scope"))
    print("Primary polls:", rows(con, "SELECT party, count(*) n, max(end_date) newest FROM primary_polls GROUP BY party"))
    print("Candidates:", rows(con, "SELECT party, status, count(*) n FROM candidates GROUP BY party, status"))
    print("Approval:", rows(con, "SELECT source, as_of, net FROM approval WHERE source='Average' ORDER BY as_of DESC LIMIT 3"))
    print("Economy:", rows(con, "SELECT series, max(period) latest FROM economy GROUP BY series"))
    print("Ratings:", rows(con, "SELECT count(*) n FROM ratings")[0])
    print("Markets:", rows(con, "SELECT platform, kind, count(*) n FROM markets GROUP BY platform, kind"))
    print("News:", rows(con, "SELECT count(*) n, count(distinct topic) topics FROM news")[0])
    print("Model versions:", [f"v{r['version']} {r['run_date']} {r['origin']}: {r['title']}" for r in
                              rows(con, "SELECT * FROM model_specs ORDER BY version DESC LIMIT 6")])
    print("Forecasts:", rows(con, "SELECT run_date, spec_version, round(p_dem,3) p_dem, round(dem_ev_mean,1) dem_ev FROM national_forecasts ORDER BY run_date DESC LIMIT 5"))
    print("Recent stages:", [f"{r['stage']}@{r['finished_at']} ok={r['ok']}" for r in rows(con, "SELECT * FROM runs ORDER BY run_id DESC LIMIT 10")])


def results(watch: int = 0, push: bool = False):
    """Archived 2026 midterm site: snapshot the live results feeds and outlets' race calls."""
    import subprocess

    from .archive2026.live_results import SNAPSHOT_PATH, snapshot
    from .archive2026.race_calls import CALLS_PATH, write_calls

    rels = [str(p.relative_to(SITE_DIR.parent)) for p in (SNAPSHOT_PATH, CALLS_PATH)]
    git = lambda *a: subprocess.run(["git", *a], cwd=SITE_DIR.parent, capture_output=True, text=True)  # noqa: E731
    while True:
        try:
            res = snapshot()
            calls = write_calls()
            if push and (res.get("written") or calls.get("written")):
                _push_snapshot(git, rels)
        except Exception as e:  # noqa: BLE001 - a bad cycle must not stop a watch
            print(f"[results] cycle failed: {e!r}", file=sys.stderr)
            res = {}
        if not watch:
            return res
        time.sleep(watch)


def _push_snapshot(git, rels):
    git_dir = SITE_DIR.parent / ".git"
    if (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists() or (git_dir / "MERGE_HEAD").exists():
        print("[results] a rebase or merge is in progress in this checkout; not pushing until it's finished")
        return
    git("add", *rels)
    if not git("diff", "--cached", "--quiet", "--", *rels).returncode:
        print("[results] unchanged; nothing to push")
        return
    git("commit", "-m", f"Results snapshot {now_iso()}", "--", *rels)
    pulled = git("pull", "--rebase", "-X", "theirs", "--autostash", "origin", "main")
    if pulled.returncode != 0:
        git("rebase", "--abort")
        print(f"[results] pull failed, will retry next cycle: {pulled.stderr.strip()[:300]}")
        return
    pushed = git("push", "origin", "HEAD:main")
    print("[results] pushed" if pushed.returncode == 0 else f"[results] push failed, will retry: {pushed.stderr.strip()[:300]}")


class _NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        pass


def serve(port=8000):
    handler = functools.partial(_NoCacheHandler, directory=str(SITE_DIR))
    print(f"Serving {SITE_DIR} at http://localhost:{port}/ (Ctrl-C to stop)")
    http.server.ThreadingHTTPServer(("", port), handler).serve_forever()


def main(argv=None):
    p = argparse.ArgumentParser(prog="electionpredictions", description="2028 presidential election model")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("ingest", help="fetch the data sources into the database")
    a.add_argument("--only", help="comma-separated stages: " + ",".join(STAGES))
    a.add_argument("--skip", default="", help="comma-separated stages to skip")
    m = sub.add_parser("model", help="rebuild the model spec (calibrate + revise) and run the forecast")
    m.add_argument("--sims", type=int, default=20000)
    m.add_argument("--seed", type=int)
    m.add_argument("--no-revision", action="store_true", help="calibrate only; do not call the revision step")
    m.add_argument("--no-narrative", action="store_true", help="skip the written summaries")
    sub.add_parser("export", help="write site/data JSON")
    r = sub.add_parser("run", help="ingest + model + export (one full update)")
    r.add_argument("--skip", default="", help="comma-separated stages to skip (ingest stages, or 'revision', 'narrative')")
    r.add_argument("--sims", type=int, default=20000)
    s = sub.add_parser("serve", help="serve the site locally")
    s.add_argument("--port", type=int, default=8000)
    sub.add_parser("status", help="show what is in the database")
    sub.add_parser("ai-probe", help="make one tiny request to the AI provider and print what it answers (diagnostics)")
    bm = sub.add_parser("ai-benchmark", help="time candidate models on a small spec-revision task")
    bm.add_argument("--models", default="", help="comma-separated model ids (default: the gateway's strong candidates)")
    rs = sub.add_parser("results", help="archived 2026 site: snapshot results feeds and race calls")
    rs.add_argument("--watch", type=int, default=0, metavar="SECONDS")
    rs.add_argument("--push", action="store_true")
    ap = sub.add_parser("set-admin-password", help="set the password for the site's admin page")
    ap.add_argument("--password", help="omit to be prompted")
    ap.add_argument("--repo", help="GitHub owner/name the archived corrections desk publishes to (default: origin remote)")
    args = p.parse_args(argv)
    if args.cmd == "ai-probe":
        from .llm import probe

        print(json.dumps(probe(), indent=2))
        return
    if args.cmd == "ai-benchmark":
        from .config import AI_MODELS_NARRATIVE, AI_MODELS_REVISION
        from .llm import benchmark

        extra = ["gpt-6-luna", "gemini-4-argon", "kimi-k3.1-pro", "kimi-k3", "qwen3.8-max", "deepseek-v4-pro", "glm-5.3", "grok-4.7",
                 "claude-haiku-5-5", "mimo-v2.6-pro", "hy4", "minimax-m3", "gpt-5.6-luna", "glm-5.3-flash", "qwen3.8-flash", "deepseek-v4.1-flash"]
        models = [m for m in args.models.split(",") if m] or list(dict.fromkeys(AI_MODELS_REVISION + AI_MODELS_NARRATIVE + extra))
        rows = benchmark(models)
        good = sorted((r for r in rows if r.get("ok")), key=lambda r: r["seconds"])
        print("usable, fastest first:", [f"{r['model']} {r['seconds']}s" for r in good])
        return
    if args.cmd == "results":
        results(watch=args.watch, push=args.push)
        return
    if args.cmd == "set-admin-password":
        import getpass

        from .admin import CONFIG_PATHS, write_config

        pw = args.password or getpass.getpass("New admin password: ")
        if len(pw) < 8:
            raise SystemExit("Use at least 8 characters (a long passphrase is best: the hash is public).")
        write_config(pw, repo=args.repo)
        print("Wrote " + ", ".join(str(p) for p in CONFIG_PATHS))
        return
    con = connect()
    print(f"2028 presidential model · {days_to_election()} days to the election")
    if args.cmd == "ingest":
        ingest(con, only=args.only.split(",") if args.only else None, skip=tuple(filter(None, args.skip.split(","))))
    elif args.cmd == "model":
        rebuild(con, n_sims=args.sims, seed=args.seed, revise=not args.no_revision, narrate=not args.no_narrative)
    elif args.cmd == "export":
        export(con)
    elif args.cmd == "run":
        skip = tuple(filter(None, args.skip.split(",")))
        ingest(con, skip=skip)
        rebuild(con, n_sims=args.sims, revise="revision" not in skip, narrate="narrative" not in skip)
        export(con)
    elif args.cmd == "serve":
        serve(args.port)
    elif args.cmd == "status":
        status(con)


if __name__ == "__main__":
    main()
