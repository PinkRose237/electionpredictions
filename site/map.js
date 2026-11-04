/**
 * map.js — "Map" page: Senate and governor races on a state map, House races on a district cartogram.
 *
 * Geometry: geo/us-maps.json (built by tvos/tools/make_maps.py, shared with the Apple TV app).
 * Colour by live results (feeds pulled in the browser via live.js, the editor's overrides from
 * results.json on top, the saved snapshot as a fallback) or by the forecast. Outlets' calls come from
 * calls.json. Hover, focus or tap a shape for the detail panel; it refreshes every minute.
 */
import {
  CHAMBER_LABEL, DASH, loadJSON, raceHref, fmt, isNum, h, svgEl, ratingPill, probChip, probColor, probGradient,
  partyClass, initChrome, renderUpdated, renderFooterMeta, showError, relativeTime, onThemeChange, DATA_BASE, withData,
} from './common.js';
import { fetchLive, mergeResults, applyConsensus, shares, isCalled } from './live.js';

const REFRESH_MS = 60e3;
const CHAMBERS = ['senate', 'house', 'governor'];
const CALLOUTS = ['VT', 'NH', 'MA', 'RI', 'CT', 'NJ', 'DE', 'MD'];
const TILE = 24;

const state = { chamber: 'senate', mode: 'live', selected: null, hover: null };
let geo = null, races = [], byId = new Map(), summary = null, closeAt = new Map(), firstClose = null;
let manual = null, snapshot = null, feed = null, calls = null, results = {};
let shapes = new Map(); // race_id -> SVG elements drawn for it (a state, a callout box, a tile)
let svg = null, overlay = null;
let lastPull = null;

async function main() {
  initChrome({ current: 'map' });
  const status = document.getElementById('status');
  let schedule;
  try {
    [geo, races, summary, schedule, manual, snapshot, calls] = await Promise.all([
      fetch('./geo/us-maps.json').then((r) => { if (!r.ok) throw new Error('geo/us-maps.json missing'); return r.json(); }),
      loadJSON('races.json'), loadJSON('summary.json').catch(() => null), loadJSON('schedule.json').catch(() => null),
      fetchFresh('results.json'), fetchFresh('results-auto.json'), fetchFresh('calls.json')]);
  } catch (err) {
    console.error(err);
    showError(status, err, 'The map needs geo/us-maps.json and data/races.json.');
    return;
  }
  for (const r of races) byId.set(r.race_id, r);
  if (schedule) {
    for (const g of schedule.groups) for (const r of g.races) closeAt.set(r.race_id, Date.parse(g.close_utc));
    firstClose = Date.parse(schedule.first_close_utc);
  }
  if (summary) { renderUpdated(summary); renderFooterMeta(summary); }
  const hash = location.hash.replace('#', '');
  if (CHAMBERS.includes(hash)) state.chamber = hash;
  state.mode = liveWindow() ? 'live' : 'forecast';
  remerge();
  status.hidden = true;
  document.getElementById('mapview').hidden = false;
  renderControls();
  drawMap();
  wireSearch();
  onThemeChange(() => paint());
  window.addEventListener('hashchange', () => {
    const ch = location.hash.replace('#', '');
    if (CHAMBERS.includes(ch) && ch !== state.chamber) { state.chamber = ch; state.selected = null; state.hover = null; renderControls(); drawMap(); }
  });
  if (liveWindow()) { pull(); setInterval(() => { if (!document.hidden) pull(); }, REFRESH_MS); }
  setInterval(renderLiveStatus, 15e3);
}

const liveWindow = () => firstClose !== null && Date.now() >= firstClose - 3600e3;

async function fetchFresh(name) {
  try {
    const r = await fetch(`${DATA_BASE}/${name}?t=${Date.now()}`, { cache: 'no-store' });
    return r.ok ? await r.json() : null;
  } catch (e) { return null; }
}

async function pull() {
  const [live, man, cl] = await Promise.all([
    fetchLive(races).catch(() => ({ races: {} })), fetchFresh('results.json'), fetchFresh('calls.json')]);
  if (Object.keys(live.races || {}).length) feed = live;
  if (man) manual = man;
  if (cl) calls = cl;
  lastPull = new Date().toISOString();
  remerge();
  paint();
  renderSummary();
  renderDetail();
  renderLiveStatus();
}

function remerge() {
  const base = feed || (snapshot ? { races: snapshot.races || {}, by: snapshot.by || {} } : { races: {}, by: {} });
  results = mergeResults(applyConsensus(base.races, calls), base.by, manual && manual.races);
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
const chamberRaces = () => races.filter((r) => r.chamber === state.chamber);
const pollsClosed = (id) => !closeAt.has(id) || Date.now() >= closeAt.get(id);
const sideParty = (race, side) => (side === 'other' ? 'O' : (race[side] && race[side].party) || (side === 'dem' ? 'D' : 'R'));
const held = (race) => race.holder_party || race.incumbent_party;

function isFlip(race) {
  const e = results[race.race_id];
  if (!isCalled(e) || !held(race)) return false;
  return sideParty(race, e.winner) !== held(race);
}

function ordinal(n) {
  const v = n % 100;
  return n + (v >= 11 && v <= 13 ? 'th' : ['th', 'st', 'nd', 'rd'][n % 10] || 'th');
}
function displayName(race) {
  if (race.chamber === 'house' && race.state_name && race.district != null) {
    return race.district === 0 ? `${race.state_name} at-large` : `${race.state_name} ${ordinal(race.district)} District`;
  }
  return race.name || race.race_id;
}

/** CSS class for a race's live state. */
function liveClass(race) {
  const e = results[race.race_id];
  if (isCalled(e)) return `won-${partyClass(sideParty(race, e.winner))}`;
  const sh = shares(e);
  if (sh && sh.margin !== 0) {
    const party = sideParty(race, sh.margin > 0 ? 'dem' : 'rep');
    return `lead-${partyClass(party)}${Math.abs(sh.margin) >= 10 ? ' strong' : ''}`;
  }
  return pollsClosed(race.race_id) ? 'closed' : 'open';
}

// ---------------------------------------------------------------------------
// Controls
// ---------------------------------------------------------------------------
function segButton(label, active, onClick, attrs = {}) {
  const b = h('button', { type: 'button', class: active ? 'on' : '', 'aria-pressed': active ? 'true' : 'false', ...attrs }, label);
  b.addEventListener('click', onClick);
  return b;
}

function renderControls() {
  document.getElementById('chamber-tabs').replaceChildren(...CHAMBERS.map((ch) => segButton(CHAMBER_LABEL[ch], state.chamber === ch, () => {
    if (state.chamber === ch) return;
    state.chamber = ch;
    state.selected = null; state.hover = null;
    history.replaceState(null, '', `#${ch}`);
    renderControls();
    drawMap();
  }, { role: 'tab', 'aria-selected': state.chamber === ch ? 'true' : 'false' })));
  document.getElementById('mode-tabs').replaceChildren(
    segButton('Live results', state.mode === 'live', () => { state.mode = 'live'; renderControls(); paint(); renderSummary(); renderLegend(); renderDetail(); }),
    segButton('Forecast', state.mode === 'forecast', () => { state.mode = 'forecast'; renderControls(); paint(); renderSummary(); renderLegend(); renderDetail(); }));
  document.getElementById('map-races').replaceChildren(...chamberRaces().map((r) => h('option', { value: `${r.short} · ${displayName(r)}` })));
  renderLiveStatus();
}

function renderLiveStatus() {
  const el = document.getElementById('map-live');
  if (!el) return;
  if (state.mode !== 'live') { el.textContent = 'Model forecast from the final pre-election run'; return; }
  const at = lastPull || (snapshot && snapshot.updated_at);
  el.textContent = at ? `Results · updated ${relativeTime(at)} · refreshes every minute` : 'Results appear after polls close';
}

function wireSearch() {
  const form = document.getElementById('map-search');
  const input = document.getElementById('map-q');
  const go = () => {
    const q = input.value.trim().toLowerCase();
    if (!q) return;
    const key = q.split(' · ')[0];
    const list = chamberRaces();
    const hit = list.find((r) => r.short.toLowerCase() === key || r.race_id.toLowerCase() === key)
      || list.find((r) => `${r.short} ${displayName(r)} ${r.state_name} ${r.dem ? r.dem.name : ''} ${r.rep ? r.rep.name : ''}`.toLowerCase().includes(q));
    if (hit) { state.selected = hit.race_id; highlight(); renderDetail(); }
  };
  form.addEventListener('submit', (ev) => { ev.preventDefault(); go(); });
  input.addEventListener('change', go);
}

// ---------------------------------------------------------------------------
// Drawing
// ---------------------------------------------------------------------------
function ringsPath(rings) {
  return rings.map((r) => {
    let d = `M${r[0]} ${r[1]}`;
    for (let i = 2; i < r.length; i += 2) d += `L${r[i]} ${r[i + 1]}`;
    return `${d}Z`;
  }).join('');
}

function register(id, el) {
  el.dataset.id = id;
  el.setAttribute('tabindex', '0');
  el.setAttribute('role', 'button');
  const race = byId.get(id);
  el.setAttribute('aria-label', race ? displayName(race) : id);
  shapes.set(id, [...(shapes.get(id) || []), el]);
}

function drawMap() {
  shapes = new Map();
  const wrap = document.getElementById('map-wrap');
  if (state.chamber === 'house') drawHouse(); else drawStates();
  wrap.replaceChildren(svg);
  wireMap();
  paint();
  renderSummary();
  renderLegend();
  renderDetail();
}

function drawStates() {
  const W = geo.width, H = geo.height, extra = 70;
  svg = svgEl('svg', { viewBox: `0 0 ${W + extra} ${H}`, class: 'map-svg states', role: 'img', 'aria-label': `${CHAMBER_LABEL[state.chamber]} map` });
  const byState = new Map(chamberRaces().map((r) => [r.state, r]));
  const g = svgEl('g', { class: 'shapes' });
  for (const [st, rings] of Object.entries(geo.states)) {
    const p = svgEl('path', { d: ringsPath(rings), class: 'shape none' });
    const race = byState.get(st);
    if (race) register(race.race_id, p);
    g.append(p);
  }
  const lines = svgEl('g', { class: 'callout-lines' });
  const boxes = svgEl('g', { class: 'shapes callouts' });
  const labels = svgEl('g', { class: 'labels' });
  let y = (geo.centers.VT ? geo.centers.VT[1] : 120) - 40;
  for (const st of CALLOUTS) {
    const race = byState.get(st);
    if (!race) continue;
    const x = W + 14, s = 30;
    const c = geo.centers[st];
    if (c) lines.append(svgEl('line', { x1: c[0], y1: c[1], x2: x, y2: y + s / 2, class: 'callout-line' }));
    const box = svgEl('rect', { x, y, width: s, height: s, rx: 4, class: 'shape none' });
    register(race.race_id, box);
    boxes.append(box);
    labels.append(svgEl('text', { x: x + s / 2, y: y + s / 2 + 4, class: 'map-label', 'text-anchor': 'middle' }, st));
    y += s + 8;
  }
  for (const [st, c] of Object.entries(geo.centers)) {
    if (!byState.has(st) || CALLOUTS.includes(st)) continue;
    labels.append(svgEl('text', { x: c[0], y: c[1] + 5, class: 'map-label', 'text-anchor': 'middle' }, st));
  }
  overlay = svgEl('g', { class: 'overlay' });
  svg.append(g, lines, boxes, overlay, labels);
}

function drawHouse() {
  const hs = geo.house, W = hs.cols * TILE, H = hs.rows * TILE;
  svg = svgEl('svg', { viewBox: `-4 -4 ${W + 8} ${H + 8}`, class: 'map-svg house', role: 'img', 'aria-label': 'House map, one square per district' });
  const g = svgEl('g', { class: 'shapes' });
  let border = '';
  for (const t of hs.tiles) {
    const x = t.x * TILE, y = t.y * TILE;
    const r = svgEl('rect', { x: x + 1.2, y: y + 1.2, width: TILE - 2.4, height: TILE - 2.4, rx: 3, class: 'shape none' });
    if (byId.has(t.id)) register(t.id, r);
    g.append(r);
    if (t.edges.includes('t')) border += `M${x} ${y}h${TILE}`;
    if (t.edges.includes('r')) border += `M${x + TILE} ${y}v${TILE}`;
    if (t.edges.includes('b')) border += `M${x} ${y + TILE}h${TILE}`;
    if (t.edges.includes('l')) border += `M${x} ${y}v${TILE}`;
  }
  const labels = svgEl('g', { class: 'labels' });
  const sizes = {};
  for (const t of hs.tiles) sizes[t.st] = (sizes[t.st] || 0) + 1;
  for (const [st, c] of Object.entries(hs.labels)) {
    labels.append(svgEl('text', { x: c[0] * TILE, y: c[1] * TILE + 4, class: `map-label${sizes[st] < 3 ? ' tiny' : ''}`, 'text-anchor': 'middle' }, st));
  }
  overlay = svgEl('g', { class: 'overlay' });
  svg.append(g, svgEl('path', { d: border, class: 'state-border' }), overlay, labels);
}

function paint() {
  for (const [id, els] of shapes) {
    const race = byId.get(id);
    const fill = state.mode === 'forecast' ? probColor(race.p_dem) : '';
    const cls = state.mode === 'forecast' ? 'fc' : liveClass(race);
    for (const el of els) {
      el.setAttribute('class', `shape race ${cls}`);
      el.style.fill = fill;
    }
  }
  highlight();
}

/** Redraw the overlay: gold outlines on flips (live mode), and the hovered / selected race. */
function highlight() {
  if (!overlay) return;
  overlay.replaceChildren();
  const add = (id, cls) => {
    for (const el of shapes.get(id) || []) {
      const c = el.cloneNode(false);
      c.removeAttribute('tabindex'); c.removeAttribute('role'); c.removeAttribute('aria-label'); delete c.dataset.id;
      c.setAttribute('class', cls);
      c.style.fill = '';
      overlay.append(c);
    }
  };
  if (state.mode === 'live') for (const id of shapes.keys()) if (isFlip(byId.get(id))) add(id, 'flip-outline');
  if (state.selected) add(state.selected, 'active-outline selected');
  if (state.hover && state.hover !== state.selected) add(state.hover, 'active-outline');
}

function wireMap() {
  const idOf = (ev) => { const t = ev.target.closest && ev.target.closest('[data-id]'); return t ? t.dataset.id : null; };
  svg.addEventListener('pointerover', (ev) => {
    const id = idOf(ev);
    if (id && id !== state.hover && ev.pointerType !== 'touch') { state.hover = id; highlight(); renderDetail(); }
  });
  svg.addEventListener('pointerleave', () => { if (state.hover) { state.hover = null; highlight(); renderDetail(); } });
  svg.addEventListener('click', (ev) => {
    const id = idOf(ev);
    state.selected = id && id !== state.selected ? id : null;
    highlight(); renderDetail();
    // On narrow screens the panel sits under the map: bring it into view after a tap.
    if (state.selected && window.matchMedia('(max-width: 900px)').matches) {
      document.getElementById('map-detail').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  });
  svg.addEventListener('focusin', (ev) => { const id = idOf(ev); if (id) { state.hover = id; highlight(); renderDetail(); } });
  svg.addEventListener('keydown', (ev) => {
    const id = idOf(ev);
    if (id && (ev.key === 'Enter' || ev.key === ' ')) { ev.preventDefault(); state.selected = id; highlight(); renderDetail(); }
    if (ev.key === 'Escape') { state.selected = null; highlight(); renderDetail(); }
  });
}

// ---------------------------------------------------------------------------
// Seat summary
// ---------------------------------------------------------------------------
function tally() {
  const c = summary && summary.chambers && summary.chambers[state.chamber];
  const t = { dWon: c ? c.not_up.D : 0, rWon: c ? c.not_up.R : 0, oWon: 0, dLead: 0, rLead: 0, open: 0, called: 0, up: 0,
    total: c ? c.total : 0, needed: c ? c.needed : 0, flips: [] };
  for (const race of chamberRaces()) {
    t.up += 1;
    const e = results[race.race_id];
    const sh = shares(e);
    if (isCalled(e)) {
      t.called += 1;
      if (e.winner === 'dem') t.dWon += 1; else if (e.winner === 'rep') t.rWon += 1; else t.oWon += 1;
      if (isFlip(race)) t.flips.push(race);
    } else if (sh && sh.margin > 0) t.dLead += 1;
    else if (sh && sh.margin < 0) t.rLead += 1;
    else t.open += 1;
  }
  return t;
}

function renderSummary() {
  const el = document.getElementById('map-summary');
  const c = summary && summary.chambers && summary.chambers[state.chamber];
  if (!c) { el.hidden = true; return; }
  el.hidden = false;
  if (state.mode === 'forecast') {
    const pct = (n) => `${(100 * n) / c.total}%`;
    el.replaceChildren(
      h('div', { class: 'ms-row' },
        h('div', { class: 'ms-side dem' }, h('span', { class: 'ms-big' }, fmt.pct(c.p_dem)), h('span', { class: 'ms-lbl' }, 'chance Democrats control')),
        h('div', { class: 'ms-mid muted small' }, `Model's expected seats: D ${Math.round(c.dem_seats.mean)} · R ${Math.round(c.rep_seats.mean)} · ${c.needed} for control`),
        h('div', { class: 'ms-side rep' }, h('span', { class: 'ms-big' }, fmt.pct(c.p_rep)), h('span', { class: 'ms-lbl' }, 'chance Republicans control'))),
      h('div', { class: 'sb-bar' },
        h('span', { class: 'sb-seg dem', style: { width: pct(c.dem_seats.mean) } }),
        h('span', { class: 'sb-seg open', style: { width: pct(Math.max(0, c.total - c.dem_seats.mean - c.rep_seats.mean)) } }),
        h('span', { class: 'sb-seg rep', style: { width: pct(c.rep_seats.mean) } }),
        h('span', { class: 'sb-mark', style: { left: pct(c.needed) } })));
    return;
  }
  const t = tally();
  const pct = (n) => `${(100 * n) / t.total}%`;
  const seg = (n, cls) => (n ? h('span', { class: `sb-seg ${cls}`, style: { width: pct(n) } }) : null);
  const control = t.dWon >= t.needed ? 'Democrats win control' : t.rWon >= t.needed ? 'Republicans win control' : null;
  el.replaceChildren(
    h('div', { class: 'ms-row' },
      h('div', { class: 'ms-side dem' }, h('span', { class: 'ms-big' }, String(t.dWon)), h('span', { class: 'ms-lbl' }, 'Democrats', t.dLead ? ` +${t.dLead} leading` : '')),
      h('div', { class: 'ms-mid muted small' }, control ? h('b', {}, control) : `${t.needed} for control`, ` · ${t.called} of ${t.up} called`,
        t.total !== t.up ? ` · ${t.total - t.up} not up` : '',
        t.flips.length ? [' · ', h('span', { class: 'ms-flips' }, `${t.flips.length} flip${t.flips.length === 1 ? '' : 's'}`)] : ''),
      h('div', { class: 'ms-side rep' }, h('span', { class: 'ms-big' }, String(t.rWon)), h('span', { class: 'ms-lbl' }, 'Republicans', t.rLead ? ` +${t.rLead} leading` : ''))),
    h('div', { class: 'sb-bar' }, seg(t.dWon, 'dem'), seg(t.dLead, 'dem lead'), seg(t.open + t.oWon, 'open'), seg(t.rLead, 'rep lead'), seg(t.rWon, 'rep'),
      h('span', { class: 'sb-mark', style: { left: pct(t.needed) } })));
}

function renderLegend() {
  const el = document.getElementById('map-legend');
  const sw = (cls, label, style) => h('span', { class: 'lg-item' }, h('span', { class: `lg-sw shape ${cls}`, style }), label);
  if (state.mode === 'forecast') {
    el.replaceChildren(...[h('span', { class: 'lg-item' }, 'Safe R'), h('span', { class: 'lg-ramp', style: { background: probGradient(15) } }),
      h('span', { class: 'lg-item' }, 'Safe D'), h('span', { class: 'lg-item muted' }, '· colour = model’s chance the Democrat wins'),
      state.chamber !== 'house' ? sw('none', 'No race this year') : null].filter(Boolean));
    return;
  }
  el.replaceChildren(...[sw('won-dem', 'Won D'), sw('lead-dem strong', 'Leading D'), sw('lead-rep strong', 'Leading R'), sw('won-rep', 'Won R'),
    sw('closed', 'Polls closed, no votes yet'), sw('open', 'Polls open'),
    h('span', { class: 'lg-item' }, h('span', { class: 'lg-sw flip' }), 'Flip'),
    state.chamber !== 'house' ? sw('none', 'No race this year') : null].filter(Boolean));
}

// ---------------------------------------------------------------------------
// Detail panel
// ---------------------------------------------------------------------------
const clock = (ms) => new Date(ms).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });

function renderDetail() {
  const el = document.getElementById('map-detail');
  const id = state.hover || state.selected;
  const race = id && byId.get(id);
  if (!race) { el.replaceChildren(...overviewPanel()); return; }
  const e = results[id];
  const sh = shares(e);
  const parts = [];
  let statusLine;
  if (isCalled(e)) {
    const party = sideParty(race, e.winner);
    const cand = race[e.winner];
    statusLine = h('div', { class: `md-status won ${partyClass(party)}` }, `✓ ${cand ? cand.name : 'Another candidate'} wins`,
      isFlip(race) ? h('span', { class: 'md-flip' }, `Flip ${held(race)}→${party}`) : null);
  } else if (e && e.status === 'runoff') statusLine = h('div', { class: 'md-status' }, 'Headed to a runoff');
  else if (!pollsClosed(id)) statusLine = h('div', { class: 'md-status muted' }, `Polls close at ${clock(closeAt.get(id))}`);
  else if (e && e.awaiting) statusLine = h('div', { class: 'md-status muted' }, `Called by ${e.awaiting} of ${e.awaitingOf} outlets · awaiting confirmation (2 needed)`);
  else statusLine = h('div', { class: 'md-status muted' }, sh ? 'Counting' : 'Polls closed · awaiting votes');
  parts.push(h('div', { class: 'md-head' }, h('h2', {}, displayName(race)), ratingPill(race.label)), statusLine);

  for (const side of ['dem', 'rep']) {
    const c = race[side];
    if (!c) continue;
    const won = isCalled(e) && e.winner === side;
    parts.push(h('div', { class: `rc-cand${won ? ' won' : ''}` },
      h('span', { class: 'rc-name' }, h('span', { class: `party-dot ${partyClass(c.party)}`, 'aria-hidden': 'true' }), c.name, ` (${c.party})`, c.incumbent ? ' †' : '', won ? ' ✓' : ''),
      h('span', { class: 'rc-pct num' }, sh ? `${sh[side].toFixed(1)}%` : DASH),
      h('span', { class: 'rc-votes num muted' }, sh ? (e.votes[side] || 0).toLocaleString() : ''),
      h('span', { class: 'rc-bar' }, h('span', { class: `rc-fill ${partyClass(c.party)}`, style: { width: `${sh ? sh[side] : 0}%` } }))));
  }
  if (race.uncontested) parts.push(h('p', { class: 'muted small' }, 'Uncontested.'));
  const facts = [];
  if (e && isNum(e.reporting) && (sh || e.reporting > 0)) facts.push(`${Math.round(e.reporting)}% of expected vote in`);
  if (sh && sh.other >= 0.5) facts.push(`others ${sh.other.toFixed(1)}%`);
  if (isNum(race.margin)) facts.push(`model ${fmt.margin(race.margin)}`);
  if (sh) facts.push(`now ${fmt.margin(sh.margin)}`);
  if (facts.length) parts.push(h('p', { class: 'md-facts muted small' }, facts.join(' · ')));
  parts.push(h('div', { class: 'md-model' }, 'Forecast: ', probChip(race.p_dem), ' chance the Democratic side wins',
    held(race) ? h('span', { class: 'muted' }, ` · seat held by ${held(race)}`) : null));

  const oc = calls && calls.races && calls.races[id];
  if (calls && calls.sources) {
    parts.push(h('div', { class: 'outlet-calls' }, ...calls.sources.map((s) => {
      const c = oc && oc[s.id];
      if (!c) return h('span', { class: 'outlet-call muted' }, h('b', {}, s.name), ' —');
      if (c.status === 'runoff') return h('span', { class: 'outlet-call' }, h('b', {}, s.name), ' runoff');
      const cand = race[c.winner];
      return h('span', { class: `outlet-call ${partyClass(cand ? cand.party : 'O')}` }, h('b', {}, s.name), ` ✓ ${cand ? cand.name.split(' ').slice(-1)[0] : 'other'}`);
    })));
  }
  parts.push(h('a', { class: 'md-link', href: raceHref(id) }, 'Full race page →'));
  if (state.selected === id) parts.push(h('button', { type: 'button', class: 'btn small md-clear' }, 'Clear selection'));
  el.replaceChildren(...parts);
  const clear = el.querySelector('.md-clear');
  if (clear) clear.addEventListener('click', () => { state.selected = null; highlight(); renderDetail(); });
}

function overviewPanel() {
  const list = chamberRaces();
  const out = [h('h2', {}, `${CHAMBER_LABEL[state.chamber]} · ${list.length} races`),
    h('p', { class: 'muted small' }, 'Hover over a state or district (tap on a phone) to see the race here. Click to keep it pinned; Esc clears.')];
  if (state.mode === 'live') {
    const t = tally();
    if (t.flips.length) {
      out.push(h('h3', { class: 'sub-h' }, 'Flips'), h('ul', { class: 'md-list' }, ...t.flips.map((r) => {
        const e = results[r.race_id];
        const party = sideParty(r, e.winner);
        return h('li', {}, h('a', { href: raceHref(r.race_id) }, r.short), ` ${held(r)}→`, h('b', { class: `${partyClass(party)}-text` }, party));
      })));
    }
    const close = list.filter((r) => { const e = results[r.race_id]; const sh = shares(e); return !isCalled(e) && sh && isNum(e.reporting) && e.reporting >= 50 && Math.abs(sh.margin) < 3; })
      .sort((a, b) => Math.abs(shares(results[a.race_id]).margin) - Math.abs(shares(results[b.race_id]).margin)).slice(0, 8);
    if (close.length) {
      out.push(h('h3', { class: 'sub-h' }, 'Closest uncalled (half the vote in)'), h('ul', { class: 'md-list' }, ...close.map((r) => {
        const e = results[r.race_id];
        return h('li', {}, h('button', { type: 'button', class: 'linklike', 'data-pick': r.race_id }, r.short), ` ${fmt.margin(shares(e).margin)} · ${Math.round(e.reporting)}% in`);
      })));
    }
  } else {
    const toss = list.filter((r) => r.label === 'Tossup').map((r) => r.short);
    if (toss.length) out.push(h('h3', { class: 'sub-h' }, 'Tossups'), h('p', { class: 'small' }, toss.join(', ')));
  }
  setTimeout(() => document.querySelectorAll('[data-pick]').forEach((b) => b.addEventListener('click', () => {
    state.selected = b.dataset.pick; highlight(); renderDetail();
  })), 0);
  return out;
}

main();
