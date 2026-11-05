"""One update of the forecast: ingest -> calibrate -> baseline -> revise -> new spec version -> final run -> write-ups -> export."""
from __future__ import annotations

import sys
import time
from datetime import date
from typing import Optional

from .db import log_run, now_iso

STAGES = ["polls", "primaries", "approval", "economy", "ratings", "money", "markets", "news"]


def ingest(con, only=None, skip=()) -> None:
    from .sources import approval, economy, markets, money, news, polls, primaries, ratings

    fns = {"polls": polls.load, "primaries": primaries.load, "approval": approval.load, "economy": economy.load,
           "ratings": ratings.load, "money": money.load, "markets": markets.load, "news": news.load}
    for stage in STAGES:
        if (only and stage not in only) or stage in skip:
            continue
        t0, started = time.time(), now_iso()
        print(f"[{stage}] ...", flush=True)
        try:
            res = fns[stage](con)
            print(f"[{stage}] done in {time.time() - t0:.0f}s: {res}")
        except Exception as e:  # noqa: BLE001 - a failed source must not stop the update
            print(f"[{stage}] FAILED: {e!r}", file=sys.stderr)
            log_run(con, stage, started, False, repr(e))


def rebuild(con, today: Optional[date] = None, n_sims: int = 20000, revise: bool = True, seed: Optional[int] = None,
            narrate: bool = True, verbose: bool = True) -> dict:
    """Re-derive the spec, revise it against the evidence, store a new version if it changed, run the final model."""
    from . import narrative, revision
    from .model import engine, store
    from .model.calibrate import calibrate

    today = today or date.today()
    store.ensure_seed(con)
    prev_v, prev, _ = store.latest(con)
    print(f"[rebuild] from spec v{prev_v}")
    proposal, nomev, _ = calibrate(con, prev, today)
    baseline = engine.run(con, proposal, spec_version=None, today=today, n_sims=max(4000, n_sims // 4), seed=seed, persist=False, verbose=verbose)
    rev = revision.revise(con, prev, proposal, nomev, baseline, today, verbose=verbose) if revise else None
    if rev and not rev["reused"]:
        spec, origin = rev["spec"], "revision"
        title = rev["title"] or "Model revised"
        summary = rev["summary"] or ""
        reasons = dict(rev["reasons"])
        if rev["notes"]:
            summary = (summary + " " if summary else "") + f"Guardrails limited {len(rev['notes'])} requested change(s)."
    else:
        spec, origin = (rev["spec"], "revision") if rev else (proposal, "calibration")
        title = "Recalibrated to the latest polling"
        summary = "Nomination odds and candidate strengths were re-estimated from the latest primary and general-election polling."
        reasons = {"nominees": "Re-estimated from primary polling (smoothed with the previous odds) and the national trial-heat regression."}
    if store.changed(prev, spec):
        version = store.save(con, prev, spec, origin, title, summary, reasons, today, input_hash=(rev or {}).get("input_hash"))
        print(f"[rebuild] stored spec v{version} ({origin}): {title}")
    else:
        version = prev_v
        print(f"[rebuild] spec unchanged (v{version})")
    final = engine.run(con, spec, spec_version=version, today=today, n_sims=n_sims, seed=seed, persist=True, verbose=verbose)
    if narrate:
        narrative.write(con, final, spec, verbose=verbose)
        narrative.stale_keys(con, final)
    return final
