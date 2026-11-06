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


def rebuild(con, today: Optional[date] = None, n_sims: int = 50000, revise: bool = True, seed: Optional[int] = None,
            narrate: bool = True, verbose: bool = True) -> dict:
    """Re-derive the spec, revise it against the evidence, store a new version if it changed meaningfully, run the
    final model, write the summaries."""
    from . import narrative, revision
    from .db import prune
    from .model import engine, store
    from .model.calibrate import basis_of, calibrate

    today = today or date.today()
    store.ensure_seed(con)
    prev_v, prev, _ = store.latest(con)
    print(f"[rebuild] from spec v{prev_v}")
    proposal, nomev, _ = calibrate(con, prev, today, basis=store.latest_basis(con))
    baseline = engine.run(con, proposal, spec_version=None, today=today, n_sims=max(5000, n_sims // 4), seed=seed, persist=False, verbose=verbose)
    rev = revision.revise(con, prev, proposal, nomev, baseline, today, verbose=verbose) if revise else None
    model = None
    if rev and not rev["reused"]:
        spec, origin, model = rev["spec"], "revision", rev.get("model")
        title = rev["title"] or "Model revised"
        summary = rev["summary"] or ""
        reasons = dict(rev["reasons"])
        if rev["notes"]:
            summary = (summary + " " if summary else "") + f"Guardrails limited {len(rev['notes'])} requested change(s)."
    elif rev:
        spec, origin, title, summary, reasons = rev["spec"], "revision", "", "", {}
    else:
        spec, origin = proposal, "calibration"
        title = "Updated with the latest polling"
        summary = "Nomination odds and candidate strengths moved with new primary and general-election polling."
        reasons = {"nominees": "Moved by the change in primary polling and in the national trial-heat regression since the last version."}
    if store.changed(prev, spec):
        version = store.save(con, prev, spec, origin, title, summary, reasons, today, input_hash=(rev or {}).get("input_hash"),
                             basis=basis_of(nomev), model=model)
        print(f"[rebuild] stored spec v{version} ({origin}): {title}")
    else:
        version = prev_v
        spec = prev
        print(f"[rebuild] no meaningful change (v{version})")
    final = engine.run(con, spec, spec_version=version, today=today, n_sims=n_sims, seed=seed, persist=True, verbose=verbose)
    if narrate:
        narrative.write(con, final, spec, verbose=verbose)
        narrative.stale_keys(con, final)
    pr = prune(con)
    if verbose and any(pr.values()):
        print(f"  pruned: {pr}")
    return final
