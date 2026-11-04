/**
 * calls.js — "Race Calls" page: each news organization's calls for every race, side by side.
 *
 * Reads data/calls.json (written by `electionpredictions results`, see sources/race_calls.py) and
 * re-reads it every minute. Race names, ratings and sides come from data/races.json.
 */
import {
  CHAMBER_LABEL, DASH, loadJSON, raceHref, h, ratingPill, initChrome, renderUpdated, renderFooterMeta, showError,
  relativeTime, partyClass, lastName, DATA_BASE,
} from './common.js';

const REFRESH_MS = 60e3;
const CH_ORDER = { senate: 0, governor: 1, house: 2 };
const LEAN_CLASS = { Left: 'left', 'Lean Left': 'lean-left', Center: 'center', 'Lean Right': 'lean-right', Right: 'right' };

const state = { chamber: 'all', show: 'default', search: '' };
let calls = null;
let races = [];
let byId = new Map();
let summary = null;

async function main() {
  initChrome({ current: 'calls' });
  const status = document.getElementById('status');
  try {
    [races, summary, calls] = await Promise.all([loadJSON('races.json'), loadJSON('summary.json').catch(() => null), fetchCalls()]);
  } catch (err) {
    console.error(err);
    showError(status, err, 'Race calls are written by `uv run electionpredictions results` (data/calls.json).');
    return;
  }
  if (!calls) { showError(status, new Error('data/calls.json not found'), 'Run `uv run electionpredictions results` to collect calls.'); return; }
  for (const r of races) byId.set(r.race_id, r);
  if (summary) { renderUpdated(summary); renderFooterMeta(summary); }
  status.hidden = true;
  document.getElementById('calls').hidden = false;
  renderControls();
  renderAll();
  setInterval(refresh, REFRESH_MS);
  setInterval(() => document.querySelectorAll('[data-ago]').forEach((el) => { el.textContent = relativeTime(el.dataset.ago); }), 15e3);
}

async function fetchCalls() {
  try {
    const r = await fetch(`${DATA_BASE}/calls.json?t=${Date.now()}`, { cache: 'no-store' });
    return r.ok ? await r.json() : null;
  } catch (e) { return null; }
}

async function refresh() {
  if (document.hidden) return;
  const fresh = await fetchCalls();
  if (fresh && fresh.updated_at !== calls.updated_at) { calls = fresh; renderAll(); }
}

function renderAll() {
  renderLiveBar();
  renderSources();
  renderTally();
  renderTable();
}

const sourceList = () => calls.sources || [];
const callsFor = (id) => (calls.races && calls.races[id]) || {};

/** Party letter of whoever won a side in this race (I for Osborn on Nebraska's D side). */
function sideParty(race, side) {
  if (side === 'other') return 'O';
  return (race && race[side] && race[side].party) || (side === 'dem' ? 'D' : 'R');
}
function sideName(race, side) {
  if (side === 'other') return 'Other';
  return (race && race[side] && lastName(race[side].name)) || (side === 'dem' ? 'Dem.' : 'Rep.');
}

// ---------------------------------------------------------------------------
function renderLiveBar() {
  const el = document.getElementById('livebar');
  const ok = sourceList().filter((s) => s.ok).length;
  const total = Object.values(calls.races || {}).length;
  const confirmed = Object.keys(calls.races || {}).filter((rid) => agreement(rid).confirmed).length;
  el.className = `card live-bar${ok === sourceList().length ? ' ok' : ' warn'}`;
  el.replaceChildren(
    h('span', { class: 'live-dot', 'aria-hidden': 'true' }),
    h('span', { class: 'live-text' }, h('b', {}, `${confirmed} race${confirmed === 1 ? '' : 's'} confirmed`), ` (${CONFIRM_AT}+ of ${sourceList().length} outlets agree) · ${total} called by at least one outlet`,
      ` · calls collected `, h('span', { 'data-ago': calls.updated_at }, relativeTime(calls.updated_at)),
      ok < sourceList().length ? ` · ${sourceList().length - ok} feed${sourceList().length - ok === 1 ? '' : 's'} not responding (showing their last calls)` : ''),
    h('span', { class: 'live-next muted' }, 'this page checks for new calls every minute'),
  );
}

function leanBadge(s) {
  return h('a', { class: `lean ${LEAN_CLASS[s.lean] || 'center'}`, href: s.rating_url || calls.ratings_source, target: '_blank', rel: 'noopener', title: 'AllSides Media Bias Rating' }, s.lean);
}

/** Races this outlet called before (or at the same moment as) every other outlet that has called them. */
function firstCount(sid) {
  let n = 0;
  for (const [rid, byOutlet] of Object.entries(calls.races || {})) {
    const mine = byOutlet[sid];
    if (!mine || mine.status === 'runoff' || !mine.at || Object.keys(byOutlet).length < 2) continue;
    if (mine.at === firstCallAt(rid)) n += 1;
  }
  return n;
}

function renderSources() {
  const el = document.getElementById('sources');
  el.replaceChildren(...sourceList().map((s) => {
    const mine = Object.values(calls.races || {}).map((c) => c[s.id]).filter(Boolean);
    const d = mine.filter((c) => c.winner === 'dem' && c.status !== 'runoff').length;
    const r = mine.filter((c) => c.winner === 'rep' && c.status !== 'runoff').length;
    return h('article', { class: `card source-card${s.ok ? '' : ' down'}` },
      h('div', { class: 'source-head' }, h('a', { class: 'source-name', href: s.url, target: '_blank', rel: 'noopener' }, s.name), leanBadge(s)),
      h('div', { class: 'source-desk' }, s.wire ? `Wire service · ${s.desk}` : s.desk),
      h('div', { class: 'source-count' }, h('b', {}, String(s.calls ?? mine.length)), ' calls',
        mine.length ? [' · ', h('span', { class: 'dem-text' }, `${d} D`), ' / ', h('span', { class: 'rep-text' }, `${r} R`)] : null),
      firstCount(s.id) ? h('div', { class: 'source-first small' }, `First to call ${firstCount(s.id)} race${firstCount(s.id) === 1 ? '' : 's'}`) : null,
      h('div', { class: 'source-status muted small' }, s.ok ? `Covers ${s.races_seen} races` : `Feed not responding${s.checked_at ? `; last read ${relativeTime(s.checked_at)}` : ''}`),
    );
  }));
}

// ---------------------------------------------------------------------------
// Seat tally per outlet: seats called for each party, including seats not up this year
// ---------------------------------------------------------------------------
function renderTally() {
  const el = document.getElementById('tally');
  const chambers = ['senate', 'house', 'governor'];
  const head = h('tr', {}, h('th', {}, 'Outlet'), ...chambers.map((ch) => h('th', { class: 'num' },
    `${CHAMBER_LABEL[ch]}${summary && summary.chambers[ch] ? ` (${summary.chambers[ch].needed} to win)` : ''}`)));
  const confirmedRow = h('tr', { class: 'confirmed-row' },
    h('td', {}, h('b', {}, 'Confirmed'), h('span', { class: 'muted small' }, ` (${CONFIRM_AT}+ of ${sourceList().length} agree)`)),
    ...chambers.map((ch) => {
      const info = summary && summary.chambers[ch];
      let d = info ? info.not_up.D : 0, r = info ? info.not_up.R : 0;
      for (const rid of Object.keys(calls.races || {})) {
        const race = byId.get(rid);
        if (!race || race.chamber !== ch) continue;
        const w = agreement(rid).confirmed;
        if (w === 'dem') d += 1; else if (w === 'rep') r += 1;
      }
      const need = info ? info.needed : Infinity;
      return h('td', { class: 'num' },
        h('span', { class: `dem-text${d >= need ? ' won' : ''}` }, `D ${d}`), ' – ', h('span', { class: `rep-text${r >= need ? ' won' : ''}` }, `R ${r}`));
    }));
  const rows = sourceList().map((s) => h('tr', {},
    h('td', {}, s.name, ' ', leanBadge(s)),
    ...chambers.map((ch) => {
      const info = summary && summary.chambers[ch];
      let d = info ? info.not_up.D : 0, r = info ? info.not_up.R : 0;
      for (const [rid, c] of Object.entries(calls.races || {})) {
        const race = byId.get(rid);
        const call = c[s.id];
        if (!race || race.chamber !== ch || !call || call.status === 'runoff') continue;
        if (call.winner === 'dem') d += 1; else if (call.winner === 'rep') r += 1;
      }
      const need = info ? info.needed : Infinity;
      return h('td', { class: 'num' },
        h('span', { class: `dem-text${d >= need ? ' won' : ''}` }, `D ${d}`), ' – ', h('span', { class: `rep-text${r >= need ? ' won' : ''}` }, `R ${r}`));
    })));
  el.replaceChildren(
    h('h2', { id: 'h-tally', style: { margin: '0 0 4px', fontSize: '17px' } }, 'Seats called, by outlet'),
    h('p', { class: 'card-sub muted small', style: { margin: '0 0 10px' } }, `Senate and governor totals include the seats not up this year. A race is confirmed once ${CONFIRM_AT} of the ${sourceList().length} outlets have called it for the same candidate. Bold means a majority.`),
    h('div', { class: 'table-wrap' }, h('table', { class: 'data' }, h('thead', {}, head), h('tbody', {}, confirmedRow, ...rows))),
  );
}

// ---------------------------------------------------------------------------
// Race table
// ---------------------------------------------------------------------------
function renderControls() {
  const c = document.getElementById('controls');
  const chamber = h('select', { 'aria-label': 'Chamber' }, h('option', { value: 'all' }, 'All races'),
    ...['senate', 'governor', 'house'].map((k) => h('option', { value: k }, CHAMBER_LABEL[k])));
  chamber.addEventListener('change', () => { state.chamber = chamber.value; renderTable(); });
  const show = h('select', { 'aria-label': 'Show' },
    h('option', { value: 'default' }, 'Called races + key races'),
    h('option', { value: 'confirmed' }, `Confirmed (${CONFIRM_AT}+ outlets agree)`),
    h('option', { value: 'called' }, 'Called by any outlet'),
    h('option', { value: 'split' }, 'Outlets disagree or are waiting'),
    h('option', { value: 'all' }, 'Every race'));
  show.addEventListener('change', () => { state.show = show.value; renderTable(); });
  const search = h('input', { type: 'search', placeholder: 'Find a state, race or candidate…', 'aria-label': 'Find a race' });
  search.addEventListener('input', () => { state.search = search.value.trim().toLowerCase(); renderTable(); });
  c.replaceChildren(chamber, show, search);
}

/** How the outlets stand on one race: called count, distinct winners, and whether any is still out. */
/** A race is confirmed once this many outlets have called it for the same candidate. */
const CONFIRM_AT = 3;

function agreement(rid) {
  const c = callsFor(rid);
  const made = Object.values(c).filter((x) => x.status !== 'runoff');
  const winners = new Set(made.map((x) => x.winner));
  const votes = {};
  for (const x of made) votes[x.winner] = (votes[x.winner] || 0) + 1;
  const [top, topN] = Object.entries(votes).sort((a, b) => b[1] - a[1])[0] || [null, 0];
  const n = Object.keys(c).length;
  const live = sourceList().filter((s) => s.ok || c[s.id]).length;
  const runoff = n > 0 && Object.values(c).every((x) => x.status === 'runoff');
  return { n, live, conflict: winners.size > 1, partial: n > 0 && n < live, runoff, winners,
    confirmed: topN >= CONFIRM_AT ? top : null, agreeing: topN };
}

const KEY = new Set(['Lean D', 'Tossup', 'Lean R']);
function visibleRaces() {
  const q = state.search;
  return races.filter((r) => {
    if (state.chamber !== 'all' && r.chamber !== state.chamber) return false;
    const a = agreement(r.race_id);
    if (state.show === 'default' && !(a.n > 0 || KEY.has(r.label) || (r.chamber !== 'house' && r.label && r.label.startsWith('Likely')))) return false;
    if (state.show === 'called' && a.n === 0) return false;
    if (state.show === 'confirmed' && !a.confirmed) return false;
    // Called by at least one outlet but not yet confirmed (fewer than 3 agree, or they disagree).
    if (state.show === 'split' && (a.confirmed || a.n === 0)) return false;
    if (q) {
      const hay = `${r.short} ${r.name} ${r.state_name} ${r.dem ? r.dem.name : ''} ${r.rep ? r.rep.name : ''}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  }).sort((a, b) => {
    // Most recent call first (any outlet's latest call on the race); races nobody has called go last.
    const A = lastCallAt(a.race_id), B = lastCallAt(b.race_id);
    if (A !== B) return !A ? 1 : !B ? -1 : B.localeCompare(A);
    return CH_ORDER[a.chamber] - CH_ORDER[b.chamber] || a.race_id.localeCompare(b.race_id);
  });
}

/** Latest time any outlet called (or sent to a runoff) this race, or null. */
function lastCallAt(rid) {
  const ats = Object.values(callsFor(rid)).map((c) => c.at).filter(Boolean).sort();
  return ats.length ? ats[ats.length - 1] : null;
}

const clock = (iso) => new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });

/** Earliest time any outlet called this race (runoff projections aside), or null. */
function firstCallAt(rid) {
  const ats = Object.values(callsFor(rid)).filter((c) => c.status !== 'runoff' && c.at).map((c) => c.at).sort();
  return ats[0] || null;
}

function callCell(race, call, first) {
  if (!call) return h('td', { class: 'call-cell muted' }, DASH);
  if (call.status === 'runoff') return h('td', { class: 'call-cell' }, h('span', { class: 'call-chip runoff' }, 'Runoff'));
  const party = sideParty(race, call.winner);
  const isFirst = first && call.at === first && Object.keys(callsFor(race.race_id)).length > 1;
  return h('td', { class: 'call-cell', title: call.at ? `Called ${new Date(call.at).toLocaleString()}` : '' },
    h('span', { class: `call-chip ${partyClass(party)}` }, `✓ ${sideName(race, call.winner)} (${party})`),
    call.at ? h('div', { class: 'call-time' }, clock(call.at), isFirst ? h('b', { class: 'first-mark' }, ' · first') : null) : null);
}

function renderTable() {
  const el = document.getElementById('table');
  const list = visibleRaces();
  const srcs = sourceList();
  const head = h('tr', {}, h('th', {}, 'Race'), h('th', {}, 'Rating'),
    ...srcs.map((s) => h('th', { class: 'src-th' }, s.name, h('div', { class: `lean-mini ${LEAN_CLASS[s.lean] || 'center'}` }, s.wire ? `${s.lean} · wire` : s.lean))),
    h('th', {}, 'Status'));
  const rows = list.map((r) => {
    const c = callsFor(r.race_id);
    const a = agreement(r.race_id);
    let status;
    if (a.confirmed) {
      const party = sideParty(r, a.confirmed);
      status = h('span', { class: `agree confirmed ${partyClass(party)}` }, `✓ Confirmed · ${a.agreeing} of ${a.live}`,
        a.conflict ? h('span', { class: 'agree-note' }, ` · ${a.n - a.agreeing} outlet${a.n - a.agreeing === 1 ? '' : 's'} differ${a.n - a.agreeing === 1 ? 's' : ''}`) : null);
    } else if (a.conflict) status = h('span', { class: 'agree conflict' }, 'Disagree');
    else if (a.n === 0) status = h('span', { class: 'agree muted' }, 'Not called');
    else if (a.runoff) status = h('span', { class: 'agree partial' }, 'Runoff');
    else if (a.partial) status = h('span', { class: 'agree partial' }, `${a.n} of ${a.live} · not yet confirmed`);
    else status = h('span', { class: 'agree all' }, 'All agree');
    return h('tr', { class: a.confirmed ? `confirmed ${a.conflict ? 'conflict' : ''}` : a.conflict ? 'conflict' : '' },
      h('td', {}, h('a', { href: raceHref(r.race_id) }, r.short), h('div', { class: 'muted small' }, [r.dem && r.dem.name, r.rep && r.rep.name].filter(Boolean).join(' vs '))),
      h('td', {}, ratingPill(r.label)),
      ...srcs.map((s) => callCell(r, c[s.id], firstCallAt(r.race_id))),
      h('td', {}, status));
  });
  const anyCalls = Object.keys(calls.races || {}).length > 0;
  el.replaceChildren(
    h('div', { class: 'table-wrap' }, h('table', { class: 'data calls-table' }, h('thead', {}, head),
      h('tbody', {}, ...(rows.length ? rows : [h('tr', {}, h('td', { class: 'empty', colspan: String(srcs.length + 3) },
        anyCalls ? 'No races match these filters.' : 'No outlet has called a race yet. The first polls close at 6 pm ET; calls usually start right after.'))])))),
    h('p', { class: 'muted small' }, `${list.length} race${list.length === 1 ? '' : 's'} shown.${!anyCalls ? ' Key races are listed until calls start coming in.' : ''}`),
  );
}

main();
