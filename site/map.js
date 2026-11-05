/**
 * map.js — the Electoral College map (map.html). Colours every contest by the chance a Democrat wins it,
 * either over all simulations or under one specific matchup (scenarios.json), with a detail panel for the
 * selected contest and electoral votes by category.
 */
import {
  LABELS, TOTAL_EV, NEEDED_EV, loadJSON, fmt, isNum, h, probChip, stateHref, contestName, query,
  initChrome, renderUpdated, renderFooterMeta, showError, probColor, textOn,
} from './common.js';
import { ecMap, probLegend, marginRange } from './charts.js';

const S = { summary: null, states: [], byId: new Map(), scenarios: [], scenario: -1, selected: null, map: null };

async function main() {
  initChrome({ current: 'map' });
  const status = document.getElementById('status');
  try {
    const [summary, states, scenarios, geo] = await Promise.all([loadJSON('summary.json'), loadJSON('states.json'), loadJSON('scenarios.json'),
      fetch('./geo/us-maps.json').then((r) => { if (!r.ok) throw new Error('geo/us-maps.json missing'); return r.json(); })]);
    Object.assign(S, { summary, states, scenarios, byId: new Map(states.map((s) => [s.id, s])) });
    S.selected = query.get('id') && S.byId.has(query.get('id')) ? query.get('id') : (summary.tipping[0] || {}).id;
    status.hidden = true;
    document.getElementById('app').hidden = false;
    renderUpdated(summary); renderFooterMeta(summary);
    picker();
    S.map = ecMap(document.getElementById('map'), geo, {
      valueOf: pOf,
      tipFor: (id) => [['Electoral votes', String((S.byId.get(id) || {}).evs)], ['Chance D wins', fmt.pct(pOf(id))],
        S.scenario < 0 ? ['Expected margin', fmt.margin((S.byId.get(id) || {}).margin)] : ['Overall chance D wins', fmt.pct((S.byId.get(id) || {}).p_dem)]],
      onSelect: (id) => { S.selected = id; S.map.redraw(); detail(); },
      selected: () => S.selected,
    });
    document.getElementById('legend').replaceChildren(probLegend());
    refresh();
  } catch (err) {
    console.error(err);
    showError(status, err, 'Run `uv run electionpredictions run` to generate site/data.');
  }
}

function pOf(id) {
  if (S.scenario >= 0) return (S.scenarios[S.scenario].states || {})[id];
  return (S.byId.get(id) || {}).p_dem;
}

function picker() {
  const sel = document.getElementById('scenario');
  sel.append(h('option', { value: '-1' }, 'All possible matchups (the forecast)'));
  S.scenarios.forEach((s, i) => sel.append(h('option', { value: String(i) }, `${s.dem} vs ${s.rep} (${fmt.pct(s.p, 1)} likely)`)));
  sel.addEventListener('change', () => { S.scenario = Number(sel.value); refresh(); });
}

function refresh() {
  const note = document.getElementById('scenario-note');
  if (S.scenario >= 0) {
    const s = S.scenarios[S.scenario];
    note.textContent = `If ${s.dem} faces ${s.rep}: Democrat wins ${fmt.pct(s.p_dem)}, expected ${fmt.num(s.dem_ev)}–${fmt.num(TOTAL_EV - s.dem_ev)} electoral votes.`;
  } else {
    note.textContent = `Democrat wins ${fmt.pct(S.summary.ec.p_dem)} · Republican wins ${fmt.pct(S.summary.ec.p_rep)}.`;
  }
  S.map.redraw();
  summary();
  buckets();
  detail();
}

function category(p) {
  if (p >= 0.97) return 'Safe D'; if (p >= 0.85) return 'Likely D'; if (p >= 0.65) return 'Lean D';
  if (p > 0.35) return 'Tossup'; if (p > 0.15) return 'Lean R'; if (p > 0.03) return 'Likely R'; return 'Safe R';
}

function summary() {
  let d = 0, r = 0, t = 0;
  for (const s of S.states) {
    const p = pOf(s.id);
    if (!isNum(p)) continue;
    if (p >= 0.65) d += s.evs; else if (p <= 0.35) r += s.evs; else t += s.evs;
  }
  document.getElementById('map-summary').replaceChildren(
    h('span', { class: 'dem-text' }, `${d} EV at least lean D`), ' · ', h('span', {}, `${t} EV toss-up`), ' · ', h('span', { class: 'rep-text' }, `${r} EV at least lean R`));
}

function buckets() {
  const by = Object.fromEntries(LABELS.map((l) => [l, []]));
  for (const s of S.states) {
    const p = pOf(s.id);
    if (isNum(p)) by[category(p)].push(s);
  }
  const bar = h('div', { class: 'ev-stack', role: 'img', 'aria-label': 'Electoral votes by category' });
  const rows = h('div', { class: 'bucket-rows' });
  const mid = { 'Safe D': 0.99, 'Likely D': 0.9, 'Lean D': 0.75, Tossup: 0.5, 'Lean R': 0.25, 'Likely R': 0.1, 'Safe R': 0.01 };
  for (const l of LABELS) {
    const ev = by[l].reduce((a, s) => a + s.evs, 0);
    if (!ev) continue;
    const bg = probColor(mid[l]);
    bar.append(h('span', { style: { width: `${(ev / TOTAL_EV) * 100}%`, background: bg, color: textOn(bg) }, title: `${l}: ${ev} EV` }, ev >= 20 ? String(ev) : ''));
    rows.append(h('div', { class: 'bucket-row' },
      h('span', { class: 'pill', style: { background: bg, color: textOn(bg) } }, l), h('span', { class: 'num' }, ` ${ev} EV `),
      h('span', { class: 'muted small' }, by[l].sort((a, b) => b.evs - a.evs).map((s) => s.id).join(', '))));
  }
  const marker = h('div', { class: 'ev-270', style: { left: `${(NEEDED_EV / TOTAL_EV) * 100}%` } }, '270');
  document.getElementById('buckets').replaceChildren(h('div', { class: 'ev-stack-wrap' }, bar, marker), rows);
}

function detail() {
  const root = document.getElementById('detail');
  const s = S.byId.get(S.selected);
  if (!s) { root.replaceChildren(h('p', { class: 'muted' }, 'Select a state or district on the map.')); return; }
  const p = pOf(s.id);
  root.replaceChildren(...[
    h('h2', {}, contestName(s.id)), h('p', { class: 'muted' }, `${s.evs} electoral vote${s.evs === 1 ? '' : 's'} · lean ${s.lean_label || 'EVEN'}`),
    h('div', { class: 'md-big' }, probChip(p), h('span', {}, ' chance of a Democratic win', S.scenario >= 0 ? ' in this matchup' : '')),
    S.scenario >= 0 ? h('p', { class: 'small' }, `Over all matchups: ${fmt.pct(s.p_dem)}`) : null,
    h('dl', { class: 'kv' },
      h('div', {}, h('dt', {}, 'Expected margin (all matchups)'), h('dd', {}, fmt.margin(s.margin), h('span', { class: 'muted small' }, ` 80%: ${fmt.margin(s.p10)} to ${fmt.margin(s.p90)}`))),
      h('div', {}, h('dt', {}, ''), h('dd', {}, marginRange(s.p10, s.margin, s.p90, { width: 220 }))),
      h('div', {}, h('dt', {}, 'Tipping-point chance'), h('dd', {}, fmt.pct(s.tip, 1))),
      h('div', {}, h('dt', {}, '2024 / 2020'), h('dd', {}, `${fmt.margin(s.margin24)} / ${fmt.margin(s.margin20)}`)),
      h('div', {}, h('dt', {}, 'State polls'), h('dd', {}, s.n_polls ? String(s.n_polls) : 'none yet'))),
    h('a', { class: 'btn', href: stateHref(s.id) }, `${contestName(s.id)} forecast →`),
  ].filter(Boolean));
}

main();
