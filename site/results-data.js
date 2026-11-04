/**
 * results-data.js — the 2026 results as every post-election page sees them.
 *
 * Races and the final forecast come from data/races.json and summary.json (frozen at the last pre-election
 * run). Results: the live AP feed pulled in the browser (live.js) when it answers, otherwise the saved
 * snapshot (results-auto.json); a race counts as called once 2 of the 4 news outlets in calls.json agree
 * (applyConsensus); the editor's corrections (results.json) go on top.
 */
import { loadJSON, isNum, DATA_BASE } from './common.js';
import { fetchLive, mergeResults, applyConsensus, shares, isCalled } from './live.js';

export { shares, isCalled };
export const REFRESH_MS = 5 * 60e3;
export const FORECAST_PUBLISHED = '2026-11-03T18:46:56Z';

async function fresh(name) {
  try {
    const r = await fetch(`${DATA_BASE}/${name}?t=${Date.now()}`, { cache: 'no-store' });
    return r.ok ? await r.json() : null;
  } catch (e) { return null; }
}

/** Load everything once. `live: false` skips the in-browser feed pull (snapshot only). */
export async function loadResults({ live = true } = {}) {
  const [races, summary, snapshot, manual, calls] = await Promise.all([
    loadJSON('races.json'), loadJSON('summary.json').catch(() => null),
    fresh('results-auto.json'), fresh('results.json'), fresh('calls.json')]);
  const S = { races, byId: new Map(races.map((r) => [r.race_id, r])), summary, snapshot, manual, calls, feed: null, results: {}, updatedAt: null, source: null };
  if (live) await pullFeed(S);
  merge(S);
  return S;
}

async function pullFeed(S) {
  const res = await fetchLive(S.races).catch(() => null);
  if (res && Object.keys(res.races).length) { S.feed = res; S.source = 'live'; S.updatedAt = res.fetched_at; }
}

function merge(S) {
  const base = S.feed || (S.snapshot ? { races: S.snapshot.races || {}, by: S.snapshot.by || {} } : { races: {}, by: {} });
  if (!S.feed && S.snapshot) { S.source = 'snapshot'; S.updatedAt = S.snapshot.updated_at; }
  S.results = mergeResults(applyConsensus(base.races, S.calls), base.by, S.manual && S.manual.races);
}

/** Re-pull everything every REFRESH_MS while the tab is visible; calls onUpdate(S) after each. */
export function keepFresh(S, onUpdate, { live = true } = {}) {
  setInterval(async () => {
    if (document.hidden) return;
    const [snapshot, manual, calls] = await Promise.all([fresh('results-auto.json'), fresh('results.json'), fresh('calls.json')]);
    if (snapshot) S.snapshot = snapshot;
    if (manual) S.manual = manual;
    if (calls) S.calls = calls;
    if (live) await pullFeed(S);
    merge(S);
    onUpdate(S);
  }, REFRESH_MS);
}

// ---------------------------------------------------------------------------
// Race helpers
// ---------------------------------------------------------------------------
export const sideParty = (race, side) => (side === 'other' ? 'O' : (race && race[side] && race[side].party) || (side === 'dem' ? 'D' : 'R'));
export const heldBy = (race) => race.holder_party || race.incumbent_party || null;

function ordinal(n) {
  const v = n % 100;
  return n + (v >= 11 && v <= 13 ? 'th' : ['th', 'st', 'nd', 'rd'][n % 10] || 'th');
}
export function displayName(race) {
  if (race.chamber === 'house' && race.state_name && race.district != null) {
    return race.district === 0 ? `${race.state_name} at-large` : `${race.state_name} ${ordinal(race.district)} District`;
  }
  return race.name || race.race_id;
}

/** Where a race stands: { kind: called | runoff | counting | waiting, winner, party, flip, sh, e }. */
export function standing(S, race) {
  const e = S.results[race.race_id];
  const sh = shares(e);
  if (isCalled(e)) {
    const party = sideParty(race, e.winner);
    return { kind: 'called', e, sh, winner: e.winner, party, flip: !!heldBy(race) && party !== heldBy(race) };
  }
  if (e && e.status === 'runoff') return { kind: 'runoff', e, sh };
  if (sh) {
    const lead = sh.margin > 0 ? 'dem' : sh.margin < 0 ? 'rep' : null;
    return { kind: 'counting', e, sh, leader: lead, party: lead ? sideParty(race, lead) : null };
  }
  return { kind: 'waiting', e, sh };
}

/** Seats per party in a chamber: won (incl. seats not up), leading, uncalled, flips, control. */
export function tally(S, chamber) {
  const c = S.summary && S.summary.chambers && S.summary.chambers[chamber];
  const t = { dWon: c ? c.not_up.D : 0, rWon: c ? c.not_up.R : 0, oWon: 0, dLead: 0, rLead: 0, open: 0, called: 0, up: 0,
    total: c ? c.total : 0, needed: c ? c.needed : 0, flips: [], uncalled: [], forecast: c };
  for (const race of S.races) {
    if (race.chamber !== chamber) continue;
    t.up += 1;
    const st = standing(S, race);
    if (st.kind === 'called') {
      t.called += 1;
      if (st.winner === 'dem') t.dWon += 1; else if (st.winner === 'rep') t.rWon += 1; else t.oWon += 1;
      if (st.flip) t.flips.push({ race, from: heldBy(race), to: st.party });
    } else {
      t.uncalled.push({ race, st });
      if (st.kind === 'counting' && st.sh.margin > 0) t.dLead += 1;
      else if (st.kind === 'counting' && st.sh.margin < 0) t.rLead += 1;
      else t.open += 1;
    }
  }
  t.control = t.dWon >= t.needed ? 'dem' : t.rWon >= t.needed ? 'rep' : null;
  t.projected = { d: t.dWon + t.dLead, r: t.rWon + t.rLead };
  t.uncalled.sort((a, b) => closeness(a.st) - closeness(b.st));
  return t;
}
const closeness = (st) => (st.sh ? Math.abs(st.sh.margin) : 999);

/** Newest calls first: the time the race was confirmed (the 2nd agreeing outlet), with who called first. */
export function latestCalls(S) {
  if (!S.calls || !S.calls.races) return [];
  const names = Object.fromEntries((S.calls.sources || []).map((s) => [s.id, s.name]));
  const out = [];
  for (const [rid, byOutlet] of Object.entries(S.calls.races)) {
    const race = S.byId.get(rid);
    const st = race && standing(S, race);
    if (!st || st.kind !== 'called') continue;
    const agreeing = Object.entries(byOutlet).filter(([, c]) => c.status !== 'runoff' && c.winner === st.winner && c.at)
      .sort((a, b) => a[1].at.localeCompare(b[1].at));
    if (!agreeing.length) continue;
    const confirmedAt = (agreeing[1] || agreeing[0])[1].at;
    out.push({ race, st, at: confirmedAt, first: names[agreeing[0][0]] || agreeing[0][0], n: agreeing.length });
  }
  return out.sort((a, b) => b.at.localeCompare(a.at));
}

// ---------------------------------------------------------------------------
// Forecast scorecard
// ---------------------------------------------------------------------------
/**
 * How the final forecast did on the races called so far: favourites' record, Brier score, results by
 * rating, calibration bins, and margin error where at least 95% of the expected vote is in.
 */
export function scorecard(S) {
  const called = [];
  const margins = [];
  for (const race of S.races) {
    if (!isNum(race.p_dem) || race.uncontested) continue;
    const st = standing(S, race);
    if (st.kind === 'called' && (st.winner === 'dem' || st.winner === 'rep')) {
      const demWon = st.winner === 'dem';
      called.push({ race, demWon, fav: race.p_dem >= 0.5 ? 'dem' : 'rep', hit: (race.p_dem >= 0.5) === demWon, conf: Math.max(race.p_dem, 1 - race.p_dem) });
    }
    if (st.sh && isNum(race.margin) && isNum(st.e.reporting) && st.e.reporting >= 95) {
      margins.push({ race, model: race.margin, actual: st.sh.margin, err: st.sh.margin - race.margin, kind: st.kind });
    }
  }
  const n = called.length;
  const hits = called.filter((c) => c.hit).length;
  const brier = n ? called.reduce((s, c) => s + (c.race.p_dem - (c.demWon ? 1 : 0)) ** 2, 0) / n : null;
  const byLabel = {};
  for (const c of called) {
    const l = c.race.label || 'Unrated';
    byLabel[l] = byLabel[l] || { n: 0, hits: 0 };
    byLabel[l].n += 1; if (c.hit) byLabel[l].hits += 1;
  }
  const bins = Array.from({ length: 10 }, (_, i) => ({ lo: i / 10, hi: (i + 1) / 10, n: 0, dem: 0, pSum: 0 }));
  for (const c of called) {
    const b = bins[Math.min(9, Math.floor(c.race.p_dem * 10))];
    b.n += 1; b.pSum += c.race.p_dem; if (c.demWon) b.dem += 1;
  }
  const errs = margins.map((m) => m.err).sort((a, b) => a - b);
  const median = errs.length ? errs[Math.floor(errs.length / 2)] : null;
  const mae = errs.length ? errs.reduce((s, x) => s + Math.abs(x), 0) / errs.length : null;
  const upsets = called.filter((c) => !c.hit).sort((a, b) => b.conf - a.conf);
  return { n, hits, brier, byLabel, bins, margins, median, mae, upsets };
}

export const LABEL_ORDER = ['Safe D', 'Likely D', 'Lean D', 'Tossup', 'Lean R', 'Likely R', 'Safe R'];
