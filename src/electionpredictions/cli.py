"""Command-line entry point: ingest -> model -> export -> serve."""
from __future__ import annotations

import argparse
import functools
import http.server
import json
import sys
import time

from .config import SITE_DIR, days_to_election
from .db import connect, log_run, now_iso, rows

STAGES = ["races", "ratings", "generic", "polls", "fec", "wiki_fundraising", "followthemoney", "census", "markets", "news", "analysis"]


def ingest(con, only=None, skip=()):
    import os

    from .sources import analysis, census, fec, followthemoney, generic_ballot, markets, news, polls, races, ratings, wiki_fundraising

    fns = {
        "races": lambda: races.load_all(con),
        "ratings": lambda: ratings.load_all(con),
        "generic": lambda: generic_ballot.load(con),
        "polls": lambda: polls.load(con, verbose=False),
        "fec": lambda: fec.load(con, verbose=False),
        "wiki_fundraising": lambda: wiki_fundraising.load(con, verbose=False),
        "followthemoney": lambda: followthemoney.load(con, verbose=True),
        "census": lambda: census.load(con, verbose=True),
        "markets": lambda: markets.load(con, verbose=False),
        "news": lambda: news.load(con, verbose=False),
        "analysis": lambda: analysis.load(con, verbose=True),
    }
    has_creds = bool(os.environ.get("OPENCODE_API_KEY") or os.environ.get("OPENCODE_ZEN_API_KEY"))
    for stage in STAGES:
        if (only and stage not in only) or stage in skip:
            continue
        if stage == "analysis" and not only and not has_creds:
            print("[analysis] skipped (no OPENCODE_API_KEY; run `ingest --only analysis` to try anyway)")
            continue
        t0, started = time.time(), now_iso()
        print(f"[{stage}] ...", flush=True)
        try:
            res = fns[stage]()
            print(f"[{stage}] done in {time.time() - t0:.0f}s: {res}")
        except Exception as e:  # noqa: BLE001
            print(f"[{stage}] FAILED: {e!r}", file=sys.stderr)
            log_run(con, stage, started, False, repr(e))


def model(con, sims=20000, seed=None):
    from .model import forecast

    print(f"[model] {sims} simulations, {days_to_election()} days to the election")
    return forecast.run(con, n_sims=sims, seed=seed)


def export(con):
    from .export import export as _export

    print("[export]")
    return _export(con)


def status(con):
    print("Races:", rows(con, "SELECT chamber, count(*) n FROM races GROUP BY chamber"))
    print("Polls:", rows(con, "SELECT count(*) n, count(distinct race_id) races, max(end_date) newest FROM polls")[0])
    print("Ratings:", rows(con, "SELECT count(*) n, max(as_of) newest FROM ratings")[0])
    print("Generic ballot:", rows(con, "SELECT source, as_of, margin FROM generic_ballot ORDER BY as_of DESC LIMIT 5"))
    print("Markets:", rows(con, "SELECT platform, count(*) n, max(fetched_at) fetched FROM markets GROUP BY platform"))
    print("News:", rows(con, "SELECT count(*) n, count(distinct race_id) races FROM news")[0])
    print("FEC:", rows(con, "SELECT count(*) n, max(coverage_end) newest FROM candidates WHERE receipts IS NOT NULL")[0])
    print("Forecast runs:", rows(con, "SELECT run_date, chamber, round(p_dem,3) p_dem, round(dem_seats_mean,1) seats FROM chamber_forecasts ORDER BY run_date DESC LIMIT 9"))
    print("Recent stages:", [f"{r['stage']}@{r['finished_at']} ok={r['ok']}" for r in rows(con, "SELECT * FROM runs ORDER BY run_id DESC LIMIT 8")])


class _NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):  # quieter
        pass


def serve(port=8000):
    handler = functools.partial(_NoCacheHandler, directory=str(SITE_DIR))
    print(f"Serving {SITE_DIR} at http://localhost:{port}/ (Ctrl-C to stop)")
    http.server.ThreadingHTTPServer(("", port), handler).serve_forever()


def main(argv=None):
    p = argparse.ArgumentParser(prog="electionpredictions", description="2026 midterm forecast pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("ingest", help="fetch all data sources into the database")
    a.add_argument("--only", help="comma-separated stages: " + ",".join(STAGES))
    a.add_argument("--skip", default="", help="comma-separated stages to skip")
    m = sub.add_parser("model", help="run the forecast model")
    m.add_argument("--sims", type=int, default=20000)
    m.add_argument("--seed", type=int)
    sub.add_parser("export", help="write site/data JSON")
    r = sub.add_parser("run", help="ingest + model + export")
    r.add_argument("--skip", default="")
    r.add_argument("--sims", type=int, default=20000)
    s = sub.add_parser("serve", help="serve the site locally")
    s.add_argument("--port", type=int, default=8000)
    sub.add_parser("status", help="show what is in the database")
    ap = sub.add_parser("set-admin-password", help="set the password for the site's admin page")
    ap.add_argument("--password", help="omit to be prompted")
    ap.add_argument("--repo", help="GitHub owner/name the admin page publishes to (default: origin remote)")
    args = p.parse_args(argv)
    if args.cmd == "set-admin-password":
        import getpass

        from .admin import CONFIG_PATH, write_config

        pw = args.password or getpass.getpass("New admin password: ")
        if len(pw) < 8:
            raise SystemExit("Use at least 8 characters (a long passphrase is best: the hash is public).")
        cfg = write_config(pw, repo=args.repo)
        print(f"Wrote {CONFIG_PATH} (publishes to {cfg['repo'] or '<set --repo>'} on {cfg['branch']}: {cfg['path']})")
        return
    con = connect()
    if args.cmd == "ingest":
        ingest(con, only=args.only.split(",") if args.only else None, skip=tuple(filter(None, args.skip.split(","))))
    elif args.cmd == "model":
        model(con, sims=args.sims, seed=args.seed)
    elif args.cmd == "export":
        export(con)
    elif args.cmd == "run":
        ingest(con, skip=tuple(filter(None, args.skip.split(","))))
        model(con, sims=args.sims)
        export(con)
    elif args.cmd == "serve":
        serve(args.port)
    elif args.cmd == "status":
        status(con)


if __name__ == "__main__":
    main()
