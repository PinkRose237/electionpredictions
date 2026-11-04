/**
 * results.js — "All races": every race with its result next to the final forecast. Filter by chamber
 * and status (called, still counting, flips, upsets, runoffs), search, sort. Data: results-data.js.
 */
import { CHAMBER_LABEL, DASH, fmt, isNum, h, raceHref, ratingPill, partyClass, lastName, initChrome, renderUpdated, renderFooterMeta, showError } from './common.js';
import { loadResults, keepFresh, standing, displayName, sideParty } from './results-data.js';

const STATUS = [['all', 'Every race'], ['called', 'Called'], ['counting', 'Still counting'], ['flips', 'Flipped seats'],
  ['upsets', 'Upsets (forecast underdog won)'], ['runoff', 'Runoffs']];
const SORTS = [['state', 'By state'], ['close', 'Closest margin first'], ['counted', 'Least counted first'], ['forecast', 'Most competitive forecast first']];
const CH_ORDER = { senate: 0, governor: 1, house: 2 };
const ui = { chamber: 'all', status: 'all', sort: 'state', q: '' };
let S = null;

async function main() {
  initChrome({ current: 'races' });
  const status = document.getElementById('status');
  try {
    S = await loadResults();
  } catch (err) {
    console.error(err);
    showError(status, err, 'This page needs data/races.json.');
    return;
  }
  if (S.summary) { renderUpdated(S.summary); renderFooterMeta(S.summary); }
  const hash = location.hash.replace('#', '');
  if (STATUS.some(([k]) => k === hash)) { ui.status = hash; if (hash === 'counting') ui.sort = 'close'; }
  status.hidden = true;
  document.getElementById('races').hidden = false;
  renderControls();
  renderTable();
  keepFresh(S, renderTable);
}

function select(label, options, value, onChange) {
  const el = h('select', { 'aria-label': label }, ...options.map(([v, l]) => h('option', { value: v, selected: v === value ? '' : null }, l)));
  el.addEventListener('change', () => onChange(el.value));
  return el;
}

function renderControls() {
  const search = h('input', { type: 'search', placeholder: 'Find a state, district or candidate…', 'aria-label': 'Find a race', value: ui.q });
  search.addEventListener('input', () => { ui.q = search.value.trim().toLowerCase(); renderTable(); });
  document.getElementById('controls').replaceChildren(
    select('Chamber', [['all', 'All chambers'], ...['senate', 'governor', 'house'].map((k) => [k, CHAMBER_LABEL[k]])], ui.chamber, (v) => { ui.chamber = v; renderTable(); }),
    select('Show', STATUS, ui.status, (v) => { ui.status = v; history.replaceState(null, '', v === 'all' ? location.pathname : `#${v}`); renderTable(); }),
    select('Sort', SORTS, ui.sort, (v) => { ui.sort = v; renderTable(); }),
    search);
}

function rows() {
  const list = [];
  for (const race of S.races) {
    if (ui.chamber !== 'all' && race.chamber !== ui.chamber) continue;
    const st = standing(S, race);
    const upset = st.kind === 'called' && isNum(race.p_dem) && (st.winner === 'dem') !== (race.p_dem >= 0.5) && st.winner !== 'other';
    if (ui.status === 'called' && st.kind !== 'called') continue;
    if (ui.status === 'counting' && (st.kind === 'called' || st.kind === 'runoff')) continue;
    if (ui.status === 'flips' && !st.flip) continue;
    if (ui.status === 'upsets' && !upset) continue;
    if (ui.status === 'runoff' && st.kind !== 'runoff') continue;
    if (ui.q) {
      const hay = `${race.short} ${displayName(race)} ${race.state_name} ${race.dem ? race.dem.name : ''} ${race.rep ? race.rep.name : ''}`.toLowerCase();
      if (!hay.includes(ui.q)) continue;
    }
    list.push({ race, st, upset });
  }
  const margin = (x) => (x.st.sh ? Math.abs(x.st.sh.margin) : 999);
  const counted = (x) => (x.st.e && isNum(x.st.e.reporting) ? x.st.e.reporting : -1);
  const byState = (a, b) => a.race.state_name.localeCompare(b.race.state_name) || CH_ORDER[a.race.chamber] - CH_ORDER[b.race.chamber] || (a.race.district || 0) - (b.race.district || 0);
  const cmp = {
    state: byState,
    close: (a, b) => margin(a) - margin(b) || byState(a, b),
    counted: (a, b) => counted(a) - counted(b) || byState(a, b),
    forecast: (a, b) => Math.abs((a.race.p_dem ?? 0.5) - 0.5) - Math.abs((b.race.p_dem ?? 0.5) - 0.5) || byState(a, b),
  }[ui.sort];
  return list.sort(cmp);
}

function resultCell(race, st) {
  if (st.kind === 'called') {
    const cand = race[st.winner];
    return h('td', {}, h('span', { class: `call-chip ${partyClass(st.party)}` }, `✓ ${cand ? cand.name : 'Other'}`),
      st.flip ? h('span', { class: `lc-flip ${partyClass(st.party)}`, style: { marginLeft: '6px' } }, `Flip ${race.holder_party || race.incumbent_party}→${st.party}`) : null);
  }
  if (st.kind === 'runoff') return h('td', {}, h('span', { class: 'call-chip runoff' }, 'Runoff'));
  if (st.kind === 'counting' && st.leader) {
    const cand = race[st.leader];
    return h('td', {}, h('span', { class: `lead-chip ${partyClass(sideParty(race, st.leader))}` }, `${cand ? cand.name : 'Leader'} leads`),
      st.e.awaiting ? h('div', { class: 'muted small' }, `${st.e.awaiting} of ${st.e.awaitingOf} outlets have called it`) : null);
  }
  return h('td', { class: 'muted' }, race.uncontested ? 'Uncontested' : 'No votes counted yet');
}

function renderTable() {
  const list = rows();
  document.getElementById('count').textContent = `${list.length} race${list.length === 1 ? '' : 's'}`;
  const head = h('tr', {}, h('th', {}, 'Race'), h('th', {}, 'Result'), h('th', { class: 'num' }, 'Dem.'), h('th', { class: 'num' }, 'Rep.'),
    h('th', { class: 'num' }, 'Margin'), h('th', { class: 'num' }, 'Counted'), h('th', {}, 'Forecast'));
  const body = list.slice(0, 600).map(({ race, st, upset }) => {
    const sh = st.sh;
    return h('tr', { class: upset ? 'upset' : '' },
      h('td', {}, h('a', { href: raceHref(race.race_id) }, race.short), h('div', { class: 'muted small' }, displayName(race))),
      resultCell(race, st),
      h('td', { class: 'num' }, sh ? `${sh.dem.toFixed(1)}%` : DASH, race.dem ? h('div', { class: 'muted small' }, lastName(race.dem.name)) : null),
      h('td', { class: 'num' }, sh ? `${sh.rep.toFixed(1)}%` : DASH, race.rep ? h('div', { class: 'muted small' }, lastName(race.rep.name)) : null),
      h('td', { class: `num ${sh ? (sh.margin > 0 ? 'dem-text' : sh.margin < 0 ? 'rep-text' : '') : ''}` }, sh ? fmt.margin(sh.margin) : DASH),
      h('td', { class: 'num' }, st.e && isNum(st.e.reporting) && (sh || st.e.reporting > 0) ? `${Math.round(st.e.reporting)}%` : DASH),
      h('td', {}, ratingPill(race.label), h('div', { class: 'muted small' }, isNum(race.margin) ? `${fmt.margin(race.margin)} · ${fmt.pct(race.p_dem)} D` : '')));
  });
  document.getElementById('table').replaceChildren(h('div', { class: 'table-wrap' },
    h('table', { class: 'data races-table' }, h('thead', {}, head),
      h('tbody', {}, ...(body.length ? body : [h('tr', {}, h('td', { class: 'empty', colspan: '7' }, 'No races match these filters.'))])))));
}

main();
