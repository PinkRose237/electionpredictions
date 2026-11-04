/**
 * results.js — "Election Results" page.
 *
 * Live results pulled in the browser from public results feeds (live.js), with the admin's manual
 * entries (data/results.json) laid over them and the last saved feed snapshot (data/results-auto.json)
 * as a fallback. Above the countdown blocks: a chamber scoreboard and a board of the key races.
 */
import {
  CHAMBER_LABEL, DASH, query, loadJSON, raceHref, fmt, isNum, h, svgEl, ratingPill,
  initChrome, renderUpdated, renderFooterMeta, showError, responsiveChart, relativeTime, partyClass, DATA_BASE,
} from './common.js';
import { fetchLive, mergeResults, shares, isCalled, FEED_LABEL } from './live.js';

const ET = 'America/New_York';
const LOCAL = (Intl.DateTimeFormat().resolvedOptions().timeZone) || ET;
const ELECTION_INSTANT = new Date('2026-11-04T00:00:00Z'); // 7 pm ET on election day, used to compare zones
const SAME_ZONE = hourIn(ELECTION_INSTANT, ET) === hourIn(ELECTION_INSTANT, LOCAL) && dayIn(ELECTION_INSTANT, ET) === dayIn(ELECTION_INSTANT, LOCAL);

function hourIn(d, tz) { return new Intl.DateTimeFormat('en-US', { timeZone: tz, hour: 'numeric', hour12: false }).format(d); }
function dayIn(d, tz) { return new Intl.DateTimeFormat('en-US', { timeZone: tz, day: 'numeric' }).format(d); }
function zoneAbbr(tz, d = ELECTION_INSTANT) {
  const parts = new Intl.DateTimeFormat('en-US', { timeZone: tz, timeZoneName: 'short' }).formatToParts(d);
  return (parts.find((p) => p.type === 'timeZoneName') || {}).value || tz;
}
/** "7 pm" / "7:30 pm" in a zone. */
function timeIn(d, tz) {
  return new Intl.DateTimeFormat('en-US', { timeZone: tz, hour: 'numeric', minute: '2-digit', hour12: true }).format(d)
    .replace(':00', '').replace(' AM', ' am').replace(' PM', ' pm');
}
/** "Tue, Nov 3, 7 pm" in a zone. */
function dateTimeIn(d, tz) {
  return new Intl.DateTimeFormat('en-US', { timeZone: tz, weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', hour12: true })
    .format(d).replace(':00', '').replace(' AM', ' am').replace(' PM', ' pm');
}
/** Both zones when the viewer isn't on Eastern time: "7 pm ET (4 pm PST)". */
function bothZones(d, { date = false } = {}) {
  const f = date ? dateTimeIn : timeIn;
  const et = `${f(d, ET)} ET`;
  return SAME_ZONE ? et : `${et} (${f(d, LOCAL)} ${zoneAbbr(LOCAL, d)})`;
}
const pad = (n) => String(n).padStart(2, '0');
function countdownText(ms) {
  if (ms <= 0) return null;
  const s = Math.floor(ms / 1000);
  const d = Math.floor(s / 86400), hh = Math.floor((s % 86400) / 3600), mm = Math.floor((s % 3600) / 60), ss = s % 60;
  return d > 0 ? `${d}d ${pad(hh)}:${pad(mm)}:${pad(ss)}` : `${pad(hh)}:${pad(mm)}:${pad(ss)}`;
}

const state = { chamber: 'all', competitive: false, search: '', sort: 'time', board: 'all' };
let schedule = null;
let summary = null;
let raceInfo = new Map(); // race_id -> races.json entry (holder party, model margin, candidate parties)
let manual = null; // data/results.json (overrides entered on the admin page)
let snapshot = null; // data/results-auto.json (feed snapshot saved by the pipeline)
let calls = null; // data/calls.json (each news outlet's calls, with times)
let feed = null; // last successful in-browser pull: { races, by, sources, fetched_at }
let feedError = null;
let results = { races: {} }; // merged view used everywhere below
const REFRESH_MS = 60e3;
let nextPull = 0;
let paused = false;

async function main() {
  initChrome({ current: 'results' });
  const status = document.getElementById('status');
  const root = document.getElementById('results');
  let races;
  try {
    [schedule, races, summary, manual, snapshot] = await Promise.all([
      loadJSON('schedule.json'), loadJSON('races.json').catch(() => []), loadJSON('summary.json').catch(() => null),
      fetchFresh('results.json'), fetchFresh('results-auto.json')]);
    calls = await fetchFresh('calls.json');
  } catch (err) {
    console.error(err);
    showError(status, err, 'The schedule is written by the pipeline’s export step (data/schedule.json).');
    return;
  }
  for (const r of races) raceInfo.set(r.race_id, r);
  if (summary) { renderUpdated(summary); renderFooterMeta(summary); }
  remerge();
  status.hidden = true;
  root.hidden = false;
  renderLiveBar();
  renderScoreboard();
  renderLatest();
  renderCheck();
  renderBoard();
  renderHero();
  renderTimeline();
  renderControls();
  renderBlocks();
  renderMethod();
  pull(); // sets nextPull before the first tick, so the clock doesn't start a second pull
  tick();
  setInterval(tick, 1000);
}

/** A data file that changes during the night: bypass the HTTP cache; null when absent. */
async function fetchFresh(name) {
  try {
    const r = await fetch(`${DATA_BASE}/${name}?t=${Date.now()}`, { cache: 'no-store' });
    return r.ok ? await r.json() : null;
  } catch (e) { return null; }
}

/** Results only start flowing an hour before the first polls close; before that one pull is enough. */
const liveWindow = () => Date.now() >= new Date(schedule.first_close_utc).getTime() - 3600e3;

async function pull() {
  nextPull = Infinity;
  renderLiveBar();
  const scheduleRaces = schedule.groups.flatMap((g) => g.races);
  const [live, man, cl] = await Promise.all([
    fetchLive(scheduleRaces).catch((e) => ({ races: {}, by: {}, sources: [], errors: [e.message] })),
    fetchFresh('results.json'),
    fetchFresh('calls.json'),
  ]);
  if (man) manual = man;
  if (cl) calls = cl;
  if (Object.keys(live.races).length) { feed = live; feedError = null; } else { feedError = live.errors.join('; ') || 'no data'; }
  remerge();
  nextPull = Date.now() + REFRESH_MS;
  renderLiveBar();
  renderScoreboard();
  renderLatest();
  renderCheck();
  renderBoard();
  renderBlocks();
}

function remerge() {
  const base = feed || (snapshot ? { races: snapshot.races || {}, by: snapshot.by || {} } : { races: {}, by: {} });
  results = { races: mergeResults(base.races, base.by, manual && manual.races) };
}

// ---------------------------------------------------------------------------
// Live status bar
// ---------------------------------------------------------------------------
function renderLiveBar() {
  const el = document.getElementById('livebar');
  if (!el) return;
  const pulling = nextPull === Infinity;
  const src = feed ? feed.sources.map((k) => FEED_LABEL[k]).join(' + ') : null;
  const refresh = h('button', { type: 'button', class: 'btn small', disabled: pulling ? '' : null }, pulling ? 'Checking…' : 'Refresh now');
  refresh.addEventListener('click', () => pull());
  const pause = h('button', { type: 'button', class: 'btn small' }, paused ? 'Resume auto-refresh' : 'Pause');
  pause.addEventListener('click', () => { paused = !paused; if (!paused) nextPull = Date.now(); renderLiveBar(); });
  const ok = !!feed && !feedError;
  let text;
  if (ok) text = [h('b', {}, 'Live'), ` · votes and race calls from ${src}`, h('span', { class: 'muted' }, ` · checked `, h('span', { 'data-ago': feed.fetched_at }, relativeTime(feed.fetched_at)))];
  else if (feed) text = [h('b', {}, 'Live feed unreachable'), ' · showing the results from the last check, ', h('span', { 'data-ago': feed.fetched_at }, relativeTime(feed.fetched_at)), '; retrying'];
  else if (snapshot && snapshot.updated_at) text = [h('b', {}, 'Saved results'), ` · the live feed is unreachable right now; showing the copy saved ${relativeTime(snapshot.updated_at)}`];
  else if (feedError) text = [h('b', {}, 'Live feed unavailable'), ' · results will appear here once it responds'];
  else text = ['Connecting to the live results feed…'];
  el.className = `card live-bar${ok ? ' ok' : feedError ? ' warn' : ''}`;
  el.replaceChildren(
    h('span', { class: 'live-dot', 'aria-hidden': 'true' }),
    h('span', { class: 'live-text' }, ...text),
    h('span', { class: 'live-next muted', 'data-next': '' }, ''),
    h('span', { class: 'live-actions' }, refresh, pause),
  );
}

// ---------------------------------------------------------------------------
// Scoreboard: seats won and leading per chamber
// ---------------------------------------------------------------------------
function chamberTally(chamber) {
  const c = summary && summary.chambers && summary.chambers[chamber];
  const t = { dWon: c ? c.not_up.D : 0, rWon: c ? c.not_up.R : 0, oWon: 0, dLead: 0, rLead: 0, open: 0, flips: [], total: c ? c.total : 0, needed: c ? c.needed : 0, model: c ? c.dem_seats.mean : null, called: 0, up: 0 };
  for (const g of schedule.groups) for (const r of g.races) {
    if (r.chamber !== chamber) continue;
    t.up += 1;
    const e = results.races[r.race_id];
    const sh = shares(e);
    if (isCalled(e)) {
      t.called += 1;
      if (e.winner === 'dem') t.dWon += 1; else if (e.winner === 'rep') t.rWon += 1; else t.oWon += 1;
      const info = raceInfo.get(r.race_id);
      const winParty = info && info[e.winner] ? info[e.winner].party : e.winner === 'dem' ? 'D' : e.winner === 'rep' ? 'R' : 'O';
      const held = info && (info.holder_party || info.incumbent_party);
      if (held && winParty && held !== winParty) t.flips.push({ race: r, from: held, to: winParty });
    } else if (sh && sh.total > 0) {
      if (sh.margin > 0) t.dLead += 1; else if (sh.margin < 0) t.rLead += 1; else t.open += 1;
    } else t.open += 1;
  }
  return t;
}

function renderScoreboard() {
  const el = document.getElementById('scoreboard');
  if (!summary) { el.hidden = true; return; }
  el.replaceChildren(...['senate', 'house', 'governor'].map((ch) => {
    const t = chamberTally(ch);
    const pct = (n) => `${(100 * n) / t.total}%`;
    const seg = (n, cls, title) => (n ? h('span', { class: `sb-seg ${cls}`, style: { width: pct(n) }, title }) : null);
    const winner = t.dWon >= t.needed ? 'dem' : t.rWon >= t.needed ? 'rep' : null;
    const isGov = ch === 'governor';
    return h('article', { class: `card sb-card${winner ? ` won ${winner}` : ''}` },
      h('div', { class: 'sb-head' }, h('h2', {}, CHAMBER_LABEL[ch]),
        h('span', { class: 'sb-need' }, winner ? `${winner === 'dem' ? 'Democrats' : 'Republicans'} ${isGov ? 'hold a majority' : 'win control'}` : `${t.needed} for ${isGov ? 'a majority' : 'control'}`)),
      h('div', { class: 'sb-nums' },
        h('div', { class: 'sb-side dem' }, h('span', { class: 'sb-big' }, String(t.dWon)), h('span', { class: 'sb-lbl' }, 'Democrats', t.dLead ? h('span', { class: 'sb-lead' }, ` +${t.dLead} leading`) : null)),
        h('div', { class: 'sb-side rep' }, h('span', { class: 'sb-big' }, String(t.rWon)), h('span', { class: 'sb-lbl' }, 'Republicans', t.rLead ? h('span', { class: 'sb-lead' }, ` +${t.rLead} leading`) : null))),
      h('div', { class: 'sb-bar', role: 'img', 'aria-label': `${t.dWon} Democratic, ${t.rWon} Republican, ${t.total - t.dWon - t.rWon - t.oWon} undecided of ${t.total}` },
        seg(t.dWon, 'dem', `${t.dWon} won by Democrats${t.total !== t.up ? ' (incl. seats not up)' : ''}`),
        seg(t.dLead, 'dem lead', `${t.dLead} Democrats leading`),
        seg(t.open + t.oWon, 'open', `${t.open} no clear leader yet${t.oWon ? `, ${t.oWon} won by others` : ''}`),
        seg(t.rLead, 'rep lead', `${t.rLead} Republicans leading`),
        seg(t.rWon, 'rep', `${t.rWon} won by Republicans`),
        h('span', { class: 'sb-mark', style: { left: pct(t.needed) } })),
      h('div', { class: 'sb-foot' },
        `${t.called} of ${t.up} races called`,
        t.total !== t.up ? ` · ${t.total - t.up} seats not up` : '',
        isNum(t.model) ? ` · model expected D ${Math.round(t.model)}` : '',
        t.flips.length ? h('div', { class: 'sb-flips' }, `${t.flips.length} flip${t.flips.length === 1 ? '' : 's'}: `, ...t.flips.slice(0, 8).flatMap((f, i) => [i ? ', ' : '',
          h('a', { href: raceHref(f.race.race_id), class: `flip ${partyClass(f.to)}` }, `${f.race.short} ${f.from}→${f.to}`)]),
          t.flips.length > 8 ? ` and ${t.flips.length - 8} more` : '') : null),
    );
  }));
}

// ---------------------------------------------------------------------------
// Latest calls (from the news outlets' calls, with the time each was first made)
// ---------------------------------------------------------------------------
const clock = (iso) => new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });

function latestCalls() {
  if (!calls || !calls.races) return [];
  const names = Object.fromEntries((calls.sources || []).map((s) => [s.id, s.name]));
  const out = [];
  for (const [rid, byOutlet] of Object.entries(calls.races)) {
    const race = raceInfo.get(rid);
    if (!race) continue;
    const made = Object.entries(byOutlet).filter(([, c]) => c.status !== 'runoff' && c.at);
    if (!made.length) continue;
    made.sort((a, b) => a[1].at.localeCompare(b[1].at));
    const first = made[0][1];
    const firsts = made.filter(([, c]) => c.at === first.at).map(([sid]) => names[sid] || sid);
    out.push({ race, at: first.at, winner: first.winner, firsts, n: made.length, total: (calls.sources || []).length,
      split: new Set(made.map(([, c]) => c.winner)).size > 1 });
  }
  return out.sort((a, b) => b.at.localeCompare(a.at));
}

function renderLatest() {
  const el = document.getElementById('latest');
  if (!el) return;
  const list = latestCalls();
  if (!list.length) { el.hidden = true; return; }
  el.hidden = false;
  el.replaceChildren(
    h('div', { class: 'card-head' }, h('h2', { id: 'h-latest' }, 'Latest calls'),
      h('a', { class: 'small', href: 'calls.html' }, 'Compare outlets →')),
    h('ol', { class: 'latest-list' }, ...list.slice(0, 10).map((c) => {
      const cand = c.race[c.winner];
      const party = cand ? cand.party : 'O';
      const held = c.race.holder_party || c.race.incumbent_party;
      return h('li', {},
        h('span', { class: 'lc-time num' }, clock(c.at)),
        h('a', { class: 'lc-race', href: raceHref(c.race.race_id) }, c.race.short),
        h('span', { class: `lc-win ${partyClass(party)}` }, cand ? `${cand.name} (${party})` : 'Another candidate'),
        held && party !== held ? h('span', { class: `lc-flip ${partyClass(party)}` }, `Flip ${held}→${party}`) : null,
        h('span', { class: 'lc-who muted' }, c.split ? 'outlets disagree' : `first: ${c.firsts.join(', ')} · ${c.n} of ${c.total}`));
    })),
  );
}

// ---------------------------------------------------------------------------
// Forecast check: how the model's favorites are doing
// ---------------------------------------------------------------------------
function renderCheck() {
  const el = document.getElementById('check');
  if (!el) return;
  const called = [], against = [], swings = [];
  for (const [rid, e] of Object.entries(results.races)) {
    const race = raceInfo.get(rid);
    if (!race || !isNum(race.p_dem) || race.uncontested) continue;
    const fav = race.p_dem >= 0.5 ? 'dem' : 'rep';
    const conf = Math.max(race.p_dem, 1 - race.p_dem);
    const sh = shares(e);
    if (isCalled(e) && (e.winner === 'dem' || e.winner === 'rep')) called.push({ race, hit: e.winner === fav, conf, winner: e.winner });
    else if (sh && isNum(e.reporting) && e.reporting >= 50 && sh.margin !== 0 && (sh.margin > 0 ? 'dem' : 'rep') !== fav) against.push({ race, conf, e, sh });
    if (sh && isNum(e.reporting) && e.reporting >= 50 && isNum(race.margin)) swings.push(sh.margin - race.margin);
  }
  if (!called.length && !against.length) { el.hidden = true; return; }
  el.hidden = false;
  const hits = called.filter((c) => c.hit).length;
  const upsets = called.filter((c) => !c.hit).sort((a, b) => b.conf - a.conf);
  against.sort((a, b) => b.conf - a.conf);
  swings.sort((a, b) => a - b);
  const median = swings.length ? swings[Math.floor(swings.length / 2)] : null;
  const name = (race, side) => (race[side] ? race[side].name.split(' ').slice(-1)[0] : side === 'dem' ? 'Dem.' : 'Rep.');
  el.replaceChildren(
    h('div', { class: 'card-head' }, h('h2', { id: 'h-check' }, 'Forecast check')),
    h('div', { class: 'check-big' }, h('b', {}, `${hits} of ${called.length}`), ' called races went to the model’s favorite',
      called.length ? h('span', { class: 'muted' }, ` (${Math.round((100 * hits) / called.length)}%)`) : null),
    median !== null && swings.length >= 5 ? h('p', { class: 'check-line' },
      `In the ${swings.length} races with at least half the expected vote in, the typical result is running `,
      h('b', { class: median > 0 ? 'dem-text' : 'rep-text' }, `${Math.abs(median).toFixed(1)} points ${median > 0 ? 'more Democratic' : 'more Republican'}`),
      ' than the model’s margin.') : null,
    h('h3', { class: 'sub-h' }, 'Upsets so far'),
    upsets.length ? h('ul', { class: 'check-list' }, ...upsets.slice(0, 6).map((u) => h('li', {},
      h('a', { href: raceHref(u.race.race_id) }, u.race.short), ' ', ratingPill(u.race.label), ` won by ${name(u.race, u.winner)}; model had the other side at ${Math.round(u.conf * 100)}%`)))
      : h('p', { class: 'muted small' }, 'None: every called race has gone to the favorite.'),
    h('h3', { class: 'sub-h' }, 'Leading against the model'),
    against.length ? h('ul', { class: 'check-list' }, ...against.slice(0, 6).map((a) => h('li', {},
      h('a', { href: raceHref(a.race.race_id) }, a.race.short), ' ', ratingPill(a.race.label),
      ` ${name(a.race, a.sh.margin > 0 ? 'dem' : 'rep')} up ${Math.abs(a.sh.margin).toFixed(1)} with ${Math.round(a.e.reporting)}% in`)))
      : h('p', { class: 'muted small' }, 'No uncalled race with half the vote in has the model’s underdog ahead.'),
    h('p', { class: 'muted small' }, 'Early counts can lean one way depending on which ballots a state counts first (mail, early in-person or election-day votes), so margins move as the count goes on.'),
  );
}

// ---------------------------------------------------------------------------
// Key races board
// ---------------------------------------------------------------------------
const CH_ORDER = { senate: 0, governor: 1, house: 2 };
function boardRaces() {
  const out = [];
  for (const g of schedule.groups) for (const r of g.races) {
    if (state.board !== 'all' && r.chamber !== state.board) continue;
    const e = results.races[r.race_id];
    const competitive = r.call.tier === 2 || r.call.tier === 3 || (r.chamber !== 'house' && r.call.tier === 1);
    const info = raceInfo.get(r.race_id);
    const flipped = isCalled(e) && info && info[e.winner] && (info.holder_party || info.incumbent_party) && info[e.winner].party !== (info.holder_party || info.incumbent_party);
    if (competitive || flipped) out.push({ ...r, group: g });
  }
  return out.sort((a, b) => CH_ORDER[a.chamber] - CH_ORDER[b.chamber] || Math.abs(a.p_dem - 0.5) - Math.abs(b.p_dem - 0.5));
}

function renderBoard() {
  const el = document.getElementById('board');
  const tabs = h('div', { class: 'board-tabs', role: 'tablist' }, ...[['all', 'All'], ['senate', 'Senate'], ['governor', 'Governors'], ['house', 'House']].map(([k, l]) => {
    const b = h('button', { type: 'button', role: 'tab', class: `chip${state.board === k ? ' on' : ''}`, 'aria-selected': state.board === k ? 'true' : 'false' }, l);
    b.addEventListener('click', () => { state.board = k; renderBoard(); });
    return b;
  }));
  const list = boardRaces();
  el.replaceChildren(
    h('div', { class: 'board-head' }, h('h2', {}, 'Key races'), h('span', { class: 'muted small' }, 'Lean and Tossup races (and Likely ones for Senate and governor), plus any seat that has flipped'), tabs),
    list.length ? h('div', { class: 'board-grid' }, ...list.map(resultCard)) : h('div', { class: 'results-empty' }, 'No races here.'),
  );
  tick();
}

function statusBadge(r, e) {
  const info = raceInfo.get(r.race_id);
  if (isCalled(e)) {
    const name = e.winner === 'dem' ? r.dem : e.winner === 'rep' ? r.rep : null;
    const party = info && info[e.winner] ? info[e.winner].party : e.winner === 'dem' ? 'D' : e.winner === 'rep' ? 'R' : 'O';
    return h('span', { class: `rc-badge called ${partyClass(party)}` }, `✓ ${e.status === 'final' ? 'Final' : 'Called'}${name ? `: ${name.split(' ').slice(-1)[0]}` : ''}`);
  }
  if (e && e.status === 'runoff') return h('span', { class: 'rc-badge' }, 'Runoff');
  if (e && e.status === 'recount') return h('span', { class: 'rc-badge' }, 'Recount');
  const closed = Date.now() >= new Date(r.group.close_utc).getTime();
  if (!closed) return h('span', { class: 'rc-badge muted' }, 'Polls close in ', h('span', { 'data-close': r.group.close_utc, 'data-closed-text': 'now' }, ''));
  const sh = shares(e);
  return h('span', { class: 'rc-badge muted' }, sh ? 'Counting' : 'Awaiting results');
}

function candRow(r, e, side) {
  const info = raceInfo.get(r.race_id);
  const name = side === 'dem' ? r.dem : r.rep;
  if (!name) return null;
  const party = info && info[side] ? info[side].party : side === 'dem' ? 'D' : 'R';
  const sh = shares(e);
  const v = e && e.votes ? e.votes[side] : null;
  const pct = sh ? sh[side] : null;
  const won = isCalled(e) && e.winner === side;
  return h('div', { class: `rc-cand${won ? ' won' : ''}` },
    h('span', { class: 'rc-name' }, h('span', { class: `party-dot ${partyClass(party)}`, 'aria-hidden': 'true' }), name, ` (${party})`, won ? h('span', { class: 'rc-check', title: 'Winner' }, ' ✓') : null),
    h('span', { class: 'rc-pct num' }, isNum(pct) ? `${pct.toFixed(1)}%` : DASH),
    h('span', { class: 'rc-votes num muted' }, isNum(v) && v > 0 ? v.toLocaleString() : ''),
    h('span', { class: 'rc-bar' }, h('span', { class: `rc-fill ${partyClass(party)}`, style: { width: `${isNum(pct) ? pct : 0}%` } })),
  );
}

function resultCard(r) {
  const e = results.races[r.race_id];
  const info = raceInfo.get(r.race_id);
  const sh = shares(e);
  const foot = [];
  if (e && isNum(e.reporting) && (e.reporting > 0 || sh)) foot.push(`${Math.round(e.reporting)}% of expected vote in`);
  if (sh && sh.other >= 0.5) foot.push(`others ${sh.other.toFixed(1)}%`);
  if (info && isNum(info.margin)) foot.push(`Model ${fmt.margin(info.margin)}`);
  if (sh) foot.push(`Now ${fmt.margin(sh.margin)}`);
  return h('a', { class: `card rc${isCalled(e) ? ` called ${e.winner}` : ''}`, href: raceHref(r.race_id) },
    h('div', { class: 'rc-head' }, ratingPill(r.label), h('span', { class: 'rc-title' }, r.short), statusBadge(r, e)),
    r.uncontested ? h('div', { class: 'muted small' }, `Uncontested · ${r.dem || r.rep}`) : [candRow(r, e, 'dem'), candRow(r, e, 'rep')],
    foot.length ? h('div', { class: 'rc-foot' }, foot.join(' · ')) : null,
    e && e.note ? h('div', { class: 'rc-note' }, e.note) : null,
  );
}

// ---------------------------------------------------------------------------
// Hero countdowns
// ---------------------------------------------------------------------------
function allRaces() { return schedule.groups.flatMap((g) => g.races.map((r) => ({ ...r, group: g }))); }

function renderHero() {
  const hero = document.getElementById('hero');
  const first = new Date(schedule.first_close_utc);
  const last = new Date(schedule.last_close_utc);
  const firstStates = schedule.groups.filter((g) => g.close_utc === schedule.first_close_utc).map((g) => g.state_name);
  const lastStates = schedule.groups.filter((g) => g.close_utc === schedule.last_close_utc).map((g) => g.state_name);
  const races = allRaces();
  const competitive = races.filter((r) => r.call.tier === 2 || r.call.tier === 3);
  const lastTypical = races.reduce((m, r) => (r.call.typical > m ? r.call.typical : m), '');
  const card = (label, big, sub, attrs = {}) => h('div', { class: 'card hero-card' },
    h('div', { class: 'label' }, label), h('div', { class: 'big', ...attrs }, big), h('div', { class: 'sub' }, sub));
  hero.replaceChildren(
    card('First polls close', '', `${firstStates.join(' & ')} · ${bothZones(first, { date: true })}`, { 'data-close': first.toISOString(), 'data-closed-text': 'Polls closed' }),
    card('Last polls close', '', `${lastStates.join(' & ')} · ${bothZones(last, { date: true })}`, { 'data-close': last.toISOString(), 'data-closed-text': 'All polls closed' }),
    card('Races tracked', fmt.num(races.length), `${schedule.groups.length} state/time groups · ${competitive.length} Lean or Tossup`),
    card('Most calls in by', dateTimeIn(new Date(lastTypical), ET).replace(/,\s\d+ (am|pm)$/, ''), `Slowest counts: Alaska (ranked choice), California, Arizona and Nevada`),
  );
}

// ---------------------------------------------------------------------------
// Election-night timeline (races closing per time slot)
// ---------------------------------------------------------------------------
function renderTimeline() {
  const el = document.getElementById('timeline');
  el.replaceChildren(h('h2', { style: { margin: '0 0 4px', fontSize: '16px' } }, 'Election night at a glance'),
    h('p', { class: 'card-sub', style: { marginBottom: '8px' } }, `Number of races whose polls close at each time (${SAME_ZONE ? 'Eastern time' : 'Eastern time, your local time below'}). Bars split by which party the model favours.`));
  const slots = new Map();
  for (const g of schedule.groups) {
    const s = slots.get(g.close_utc) || { t: new Date(g.close_utc), dem: 0, rep: 0, toss: 0, states: new Set() };
    for (const r of g.races) {
      if (r.p_dem >= 0.65) s.dem += 1; else if (r.p_dem <= 0.35) s.rep += 1; else s.toss += 1;
    }
    s.states.add(g.state);
    slots.set(g.close_utc, s);
  }
  const data = [...slots.values()].sort((a, b) => a.t - b.t);
  const box = h('div', { class: 'chart-box' });
  el.append(box);
  responsiveChart(box, (width) => {
    const w = Math.max(320, width), H = 150, m = { l: 12, r: 12, t: 26, b: SAME_ZONE ? 30 : 44 };
    const t0 = new Date(schedule.first_close_utc).getTime() - 30 * 60e3, t1 = new Date(schedule.last_close_utc).getTime() + 30 * 60e3;
    const x = (t) => m.l + ((t - t0) / (t1 - t0)) * (w - m.l - m.r);
    const max = Math.max(1, ...data.map((d) => d.dem + d.rep + d.toss));
    const y = (v) => m.t + (H - m.t - m.b) * (1 - v / max);
    const svg = svgEl('svg', { viewBox: `0 0 ${w} ${H}`, role: 'img', 'aria-label': 'Races closing per time slot' });
    const bw = Math.min(26, (w - m.l - m.r) / data.length - 6);
    for (const d of data) {
      const cx = x(d.t.getTime());
      let base = y(0);
      for (const [key, cls] of [['rep', 'bar rep'], ['toss', 'bar toss'], ['dem', 'bar']]) {
        const v = d[key];
        if (!v) continue;
        const top = base - (y(0) - y(v));
        const attrs = { class: cls, x: cx - bw / 2, y: top, width: bw, height: base - top };
        if (key === 'toss') attrs.style = 'fill: var(--tossup)';
        svg.append(svgEl('rect', attrs));
        base = top;
      }
      const total = d.dem + d.rep + d.toss;
      svg.append(svgEl('text', { class: 'count', x: cx, y: base - 4, 'text-anchor': 'middle' }, String(total)));
      svg.append(svgEl('text', { class: 'tick', x: cx, y: H - m.b + 14, 'text-anchor': 'middle' }, timeIn(d.t, ET)));
      if (!SAME_ZONE) svg.append(svgEl('text', { class: 'tick', x: cx, y: H - m.b + 27, 'text-anchor': 'middle' }, timeIn(d.t, LOCAL)));
    }
    svg.append(svgEl('line', { class: 'grid', x1: m.l, x2: w - m.r, y1: y(0) + 0.5, y2: y(0) + 0.5, style: 'stroke: var(--border-strong)' }));
    const now = Date.now();
    if (now > t0 && now < t1) {
      svg.append(svgEl('line', { class: 'now', x1: x(now), x2: x(now), y1: m.t - 8, y2: y(0) }));
      svg.append(svgEl('text', { class: 'tick', x: x(now), y: m.t - 12, 'text-anchor': 'middle' }, 'now'));
    }
    return svg;
  });
}

// ---------------------------------------------------------------------------
// Controls + blocks
// ---------------------------------------------------------------------------
function renderControls() {
  const c = document.getElementById('controls');
  const chamber = h('select', { 'aria-label': 'Chamber' },
    h('option', { value: 'all' }, 'All races'),
    ...['senate', 'governor', 'house'].map((k) => h('option', { value: k }, CHAMBER_LABEL[k])));
  chamber.addEventListener('change', () => { state.chamber = chamber.value; renderBlocks(); });
  const sort = h('select', { 'aria-label': 'Order' }, h('option', { value: 'time' }, 'Order by closing time'), h('option', { value: 'state' }, 'Order by state'));
  sort.addEventListener('change', () => { state.sort = sort.value; renderBlocks(); });
  const comp = h('input', { type: 'checkbox' });
  comp.addEventListener('change', () => { state.competitive = comp.checked; renderBlocks(); });
  const search = h('input', { type: 'search', placeholder: 'Find a state or race…', 'aria-label': 'Find a state or race' });
  search.addEventListener('input', () => { state.search = search.value.trim().toLowerCase(); renderBlocks(); });
  c.replaceChildren(chamber, sort, h('label', { class: 'check' }, comp, 'Lean & Tossup only'), search,
    h('span', { class: 'tz-note' }, SAME_ZONE ? 'Times in Eastern time' : `Times in ET, with your local time (${zoneAbbr(LOCAL)}) in parentheses`));
}

function filteredGroups() {
  return schedule.groups.map((g) => {
    let races = g.races;
    if (state.chamber !== 'all') races = races.filter((r) => r.chamber === state.chamber);
    if (state.competitive) races = races.filter((r) => r.call.tier === 2 || r.call.tier === 3);
    if (state.search) {
      const q = state.search;
      const stateHit = g.state_name.toLowerCase().includes(q) || g.state.toLowerCase() === q;
      if (!stateHit) races = races.filter((r) => `${r.short} ${r.name} ${r.dem || ''} ${r.rep || ''}`.toLowerCase().includes(q));
    }
    return { ...g, races };
  }).filter((g) => g.races.length);
}

function renderBlocks() {
  const root = document.getElementById('blocks');
  const openMore = new Set([...root.querySelectorAll('details.more[open]')].map((d) => d.dataset.key));
  const groups = filteredGroups();
  if (!groups.length) {
    root.replaceChildren(h('div', { class: 'results-empty' }, 'No races match these filters.'));
    return;
  }
  const blocks = [];
  if (state.sort === 'state') {
    const byState = new Map();
    for (const g of groups) byState.set(g.state_name, [...(byState.get(g.state_name) || []), g]);
    for (const [name, gs] of [...byState.entries()].sort((a, b) => a[0].localeCompare(b[0]))) {
      blocks.push(h('section', { class: 'close-block' },
        h('h2', {}, name, h('span', { class: 'meta' }, `${gs.reduce((n, g) => n + g.races.length, 0)} race${gs.reduce((n, g) => n + g.races.length, 0) === 1 ? '' : 's'}`)),
        h('div', { class: 'state-grid' }, ...gs.map(stateCard))));
    }
  } else {
    const byTime = new Map();
    for (const g of groups) byTime.set(g.close_utc, [...(byTime.get(g.close_utc) || []), g]);
    for (const [iso, gs] of [...byTime.entries()].sort((a, b) => a[0].localeCompare(b[0]))) {
      const d = new Date(iso);
      const n = gs.reduce((s, g) => s + g.races.length, 0);
      blocks.push(h('section', { class: 'close-block' },
        h('h2', {}, bothZones(d), h('span', { class: 'meta' }, `${dateTimeIn(d, ET).split(',')[0]} · ${gs.length} state${gs.length === 1 ? '' : 's'} · ${n} race${n === 1 ? '' : 's'}`)),
        h('div', { class: 'state-grid' }, ...gs.map(stateCard))));
    }
  }
  root.replaceChildren(...blocks);
  root.querySelectorAll('details.more').forEach((d) => { if (openMore.has(d.dataset.key)) d.open = true; });
  tick();
}

function stateCard(g) {
  const close = new Date(g.close_utc);
  const competitive = g.races.filter((r) => r.call.tier === 2 || r.call.tier === 3);
  const rest = g.races.filter((r) => !(r.call.tier === 2 || r.call.tier === 3));
  const shown = competitive.length ? competitive : rest.slice(0, 3);
  const hidden = competitive.length ? rest : rest.slice(3);
  const settled = new Date(g.settled_typical);
  const called = g.races.filter((r) => isCalled(results.races[r.race_id])).length;
  const card = h('article', { class: 'card state-card' },
    h('div', { class: 'state-head' }, h('h3', {}, g.state_name), h('span', { class: 'closes' }, `${g.races.length} race${g.races.length === 1 ? '' : 's'}${called ? ` · ${called} called` : ''}`)),
    h('div', { class: 'closes' }, `Polls close ${g.local}${SAME_ZONE ? '' : ` — ${timeIn(close, LOCAL)} ${zoneAbbr(LOCAL, close)} for you`}`),
    h('div', { class: 'countdown', 'data-close': close.toISOString(), 'data-closed-text': 'Polls closed' }, ''),
    h('div', { class: 'countdown-label' }, 'until polls close'),
    g.note ? h('div', { class: 'note' }, g.note) : null,
    g.sources && g.sources.length ? h('div', { class: 'note' }, 'Official results: ', ...g.sources.flatMap((sr, i) => [i ? ' · ' : '', h('a', { href: sr.url, target: '_blank', rel: 'noopener', title: sr.kind || '' }, sr.label)])) : null,
    h('div', { class: 'race-lines' }, ...shown.map(raceLine)),
    hidden.length ? h('details', { class: 'more', 'data-key': `${g.state}:${g.close_utc}` }, h('summary', {}, `Show ${hidden.length} more race${hidden.length === 1 ? '' : 's'} (${competitive.length ? 'not competitive' : 'all'})`),
      h('div', { class: 'race-lines' }, ...hidden.map(raceLine))) : null,
    h('div', { class: 'settle' }, 'Most calls expected by ', h('b', {}, bothZones(settled, { date: true })),
      g.settled_late !== g.settled_typical ? h('span', { class: 'muted' }, `; slowest could run to ${dateTimeIn(new Date(g.settled_late), ET).split(',').slice(0, 2).join(',')}`) : null),
  );
  return card;
}

/** One line of results ("D 51.2% · R 47.1% · 62% in · Called for Ossoff") with a thin two-party bar. */
export function resultLine(r, e) {
  if (!e) return null;
  const sh = shares(e);
  const parts = [];
  if (sh) parts.push(`D ${sh.dem.toFixed(1)}% · R ${sh.rep.toFixed(1)}%${sh.other >= 0.05 ? ` · other ${sh.other.toFixed(1)}%` : ''}`);
  if (isNum(e.reporting) && (sh || e.reporting > 0)) parts.push(`${Math.round(e.reporting)}% in`);
  const label = { pending: null, counting: sh ? null : 'Counting', called: 'Called', runoff: 'Runoff', recount: 'Recount', final: 'Final' }[e.status];
  const winner = e.winner === 'dem' ? r.dem : e.winner === 'rep' ? r.rep : e.winner === 'other' ? 'another candidate' : null;
  if (!parts.length && !label) return null;
  return h('div', { class: 'result-line' },
    sh ? h('span', { class: 'mini-bar', 'aria-hidden': 'true' }, h('span', { class: 'd', style: { width: `${sh.dem}%` } }), h('span', { class: 'r', style: { width: `${sh.rep}%` } })) : null,
    parts.join(' · '), parts.length && label ? ' · ' : '', label ? h('b', {}, winner && isCalled(e) ? `${label} for ${winner}` : label) : null);
}

function raceLine(r) {
  const typical = new Date(r.call.typical);
  const who = r.uncontested ? 'Uncontested' : [r.dem, r.rep].filter(Boolean).join(' vs ') || DASH;
  const e = results.races[r.race_id];
  return h('div', { class: 'race-line' },
    ratingPill(r.label),
    h('div', {}, h('a', { class: 'rname', href: raceHref(r.race_id) }, r.short), h('span', { class: 'who' }, ` · ${who}`)),
    resultLine(r, e),
    h('div', { class: 'call', title: r.call.why || '' }, 'Expected call: ', h('b', {}, r.call.summary),
      r.call.tier === 'uncontested' || r.call.tier === 0 ? '' : ` · ~${bothZones(typical, { date: true })}`),
  );
}

function renderMethod() {
  const el = document.getElementById('method');
  el.replaceChildren(
    h('h2', { id: 'h-method', style: { marginTop: 0 } }, 'How the countdowns and call estimates work'),
    h('ul', {}, ...schedule.method.map((t) => h('li', {}, t))),
    h('p', { class: 'muted small' }, 'Sources: ', ...schedule.sources.flatMap((s, i) => [i ? ' · ' : '', h('a', { href: s.url, target: '_blank', rel: 'noopener' }, s.title)])),
  );
}

// ---------------------------------------------------------------------------
// Ticking clocks
// ---------------------------------------------------------------------------
function tick() {
  const now = Date.now();
  if (schedule && !paused && now >= nextPull && liveWindow() && !document.hidden) pull();
  document.querySelectorAll('[data-ago]').forEach((el) => { el.textContent = relativeTime(el.dataset.ago); });
  document.querySelectorAll('[data-next]').forEach((el) => {
    el.textContent = paused ? 'auto-refresh paused' : nextPull === Infinity ? '' : liveWindow() ? `next check in ${Math.max(0, Math.ceil((nextPull - now) / 1000))}s` : 'auto-refresh starts an hour before polls close';
  });
  document.querySelectorAll('[data-close]').forEach((el) => {
    const ms = new Date(el.dataset.close).getTime() - now;
    const text = countdownText(ms);
    if (text) {
      el.textContent = text;
      el.classList.remove('closed');
    } else {
      el.textContent = el.dataset.closedText || 'Closed';
      el.classList.add('closed');
    }
  });
}

main();
