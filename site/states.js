/**
 * states.js — the table of all 56 contests (states.html): search, category filter, sortable columns.
 */
import { loadJSON, fmt, h, probChip, stateHref, contestName, initChrome, renderUpdated, renderFooterMeta, showError, ratingPill, query } from './common.js';
import { marginRange } from './charts.js';

const COLS = [
  ['name', 'Contest', (s) => contestName(s.id)],
  ['evs', 'EV', (s) => s.evs],
  ['margin24', '2024', (s) => s.margin24],
  ['lean', 'Lean', (s) => s.lean],
  ['margin', 'Forecast margin', (s) => s.margin],
  ['p_dem', 'Democrat wins', (s) => s.p_dem],
  ['p_rep', 'Republican wins', (s) => 1 - s.p_dem],
  ['tip', 'Tipping point', (s) => s.tip],
  ['label', 'Category', (s) => s.p_dem],
];
const V = { sort: 'p_dem', dir: -1, q: '', cat: '' };

async function main() {
  initChrome({ current: 'states' });
  const status = document.getElementById('status');
  try {
    const [summary, states] = await Promise.all([loadJSON('summary.json'), loadJSON('states.json')]);
    status.hidden = true;
    document.getElementById('app').hidden = false;
    renderUpdated(summary); renderFooterMeta(summary);
    const q = document.getElementById('q'), cat = document.getElementById('cat');
    if (query.get('cat')) { V.cat = query.get('cat'); cat.value = V.cat; }
    q.addEventListener('input', () => { V.q = q.value.trim().toLowerCase(); draw(states); });
    cat.addEventListener('change', () => { V.cat = cat.value; draw(states); });
    draw(states);
  } catch (err) {
    console.error(err);
    showError(status, err);
  }
}

function draw(states) {
  const key = COLS.find((c) => c[0] === V.sort)[2];
  const list = states.filter((s) => (!V.q || contestName(s.id).toLowerCase().includes(V.q) || s.id.toLowerCase() === V.q)
    && (!V.cat || s.label === V.cat));
  list.sort((a, b) => {
    const x = key(a), y = key(b);
    return (typeof x === 'string' ? x.localeCompare(y) : (x ?? -1e9) - (y ?? -1e9)) * V.dir;
  });
  const head = h('tr', {}, ...COLS.map(([k, label]) => {
    const th = h('th', { scope: 'col', class: k === 'name' ? '' : 'num', 'aria-sort': V.sort === k ? (V.dir > 0 ? 'ascending' : 'descending') : 'none' },
      h('button', { type: 'button', class: 'linklike' }, label, V.sort === k ? (V.dir > 0 ? ' ▲' : ' ▼') : ''));
    th.querySelector('button').addEventListener('click', () => { V.dir = V.sort === k ? -V.dir : (k === 'name' ? 1 : -1); V.sort = k; draw(states); });
    return th;
  }));
  const body = h('tbody');
  for (const s of list) {
    body.append(h('tr', {},
      h('td', {}, h('a', { href: stateHref(s.id) }, contestName(s.id)), s.adjustment ? h('span', { class: 'muted small', title: 'State-specific adjustment in the current model' }, ' ◆') : null),
      h('td', { class: 'num' }, String(s.evs)),
      h('td', { class: 'num' }, fmt.margin(s.margin24)),
      h('td', { class: 'num' }, s.lean_label),
      h('td', { class: 'num' }, h('span', { class: 'mr-cell' }, marginRange(s.p10, s.margin, s.p90, { width: 120 }), ' ', fmt.margin(s.margin))),
      h('td', { class: 'num' }, probChip(s.p_dem)),
      h('td', { class: 'num' }, fmt.pct(1 - s.p_dem)),
      h('td', { class: 'num' }, fmt.pct(s.tip, 1)),
      h('td', { class: 'num' }, ratingPill(s.label))));
  }
  document.getElementById('table').replaceChildren(h('table', { class: 'races-table' }, h('thead', {}, head), body));
  document.getElementById('count').textContent = `${list.length} of ${states.length} contests · ${list.reduce((a, s) => a + s.evs, 0)} electoral votes`;
}

main();
