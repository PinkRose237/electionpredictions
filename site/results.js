/**
 * results.js — "Election Results" page.
 *
 * For now: live countdowns to poll closing for every race (grouped by state + closing time, from
 * data/schedule.json) plus the expected time of an AP call. Results themselves will land here later.
 */
import {
  CHAMBER_LABEL, DASH, query, loadJSON, raceHref, fmt, isNum, h, svgEl, ratingPill,
  initChrome, renderUpdated, renderFooterMeta, showError, responsiveChart,
} from './common.js';

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

const state = { chamber: 'all', competitive: false, search: '', sort: 'time' };
let schedule = null;

async function main() {
  initChrome({ current: 'results' });
  const status = document.getElementById('status');
  const root = document.getElementById('results');
  try {
    schedule = await loadJSON('schedule.json');
  } catch (err) {
    console.error(err);
    showError(status, err, 'The schedule is written by the pipeline’s export step (data/schedule.json).');
    return;
  }
  loadJSON('summary.json').then((s) => { renderUpdated(s); renderFooterMeta(s); }).catch(() => {});
  status.hidden = true;
  root.hidden = false;
  renderHero();
  renderTimeline();
  renderControls();
  renderBlocks();
  renderMethod();
  tick();
  setInterval(tick, 1000);
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
  tick();
}

function stateCard(g) {
  const close = new Date(g.close_utc);
  const competitive = g.races.filter((r) => r.call.tier === 2 || r.call.tier === 3);
  const rest = g.races.filter((r) => !(r.call.tier === 2 || r.call.tier === 3));
  const shown = competitive.length ? competitive : rest.slice(0, 3);
  const hidden = competitive.length ? rest : rest.slice(3);
  const settled = new Date(g.settled_typical);
  const card = h('article', { class: 'card state-card' },
    h('div', { class: 'state-head' }, h('h3', {}, g.state_name), h('span', { class: 'closes' }, `${g.races.length} race${g.races.length === 1 ? '' : 's'}`)),
    h('div', { class: 'closes' }, `Polls close ${g.local}${SAME_ZONE ? '' : ` — ${timeIn(close, LOCAL)} ${zoneAbbr(LOCAL, close)} for you`}`),
    h('div', { class: 'countdown', 'data-close': close.toISOString(), 'data-closed-text': 'Polls closed' }, ''),
    h('div', { class: 'countdown-label' }, 'until polls close'),
    g.note ? h('div', { class: 'note' }, g.note) : null,
    h('div', { class: 'race-lines' }, ...shown.map(raceLine)),
    hidden.length ? h('details', { class: 'more' }, h('summary', {}, `Show ${hidden.length} more race${hidden.length === 1 ? '' : 's'} (${competitive.length ? 'not competitive' : 'all'})`),
      h('div', { class: 'race-lines' }, ...hidden.map(raceLine))) : null,
    h('div', { class: 'settle' }, 'Most calls expected by ', h('b', {}, bothZones(settled, { date: true })),
      g.settled_late !== g.settled_typical ? h('span', { class: 'muted' }, `; slowest could run to ${dateTimeIn(new Date(g.settled_late), ET).split(',').slice(0, 2).join(',')}`) : null),
  );
  return card;
}

function raceLine(r) {
  const typical = new Date(r.call.typical);
  const who = r.uncontested ? 'Uncontested' : [r.dem, r.rep].filter(Boolean).join(' vs ') || DASH;
  return h('div', { class: 'race-line' },
    ratingPill(r.label),
    h('div', {}, h('a', { class: 'rname', href: raceHref(r.race_id) }, r.short), h('span', { class: 'who' }, ` · ${who}`)),
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
