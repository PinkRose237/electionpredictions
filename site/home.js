/**
 * home.js — the forecast home page (index.html): headline odds, electoral-vote distribution, trend, road to
 * 270, map, overview, nominee odds, likeliest matchups, national environment, tipping points, closest contests,
 * the latest model revision and the markets comparison.
 */
import {
  DASH, TOTAL_EV, NEEDED_EV, loadJSON, fmt, isNum, h, probChip, partyClass, stateHref, contestName,
  initChrome, renderUpdated, renderFooterMeta, showError, paintProb, relativeTime,
} from './common.js';
import { splitBar, evHistogram, trendChart, roadTo270, ecMap, probLegend, themeColor } from './charts.js';

async function main() {
  initChrome({ current: 'home' });
  const status = document.getElementById('status');
  try {
    const [S, states, geo] = await Promise.all([loadJSON('summary.json'), loadJSON('states.json'),
      fetch('./geo/us-maps.json').then((r) => { if (!r.ok) throw new Error('geo/us-maps.json missing'); return r.json(); })]);
    status.hidden = true;
    document.getElementById('app').hidden = false;
    renderUpdated(S); renderFooterMeta(S);
    const byId = new Map(states.map((s) => [s.id, s]));
    lede(S); hero(S); evBlock(S); trend(S); road(states); map(geo, byId); overview(S);
    stories(S); nominees(S, 'D'); nominees(S, 'R'); matchups(S); environment(S); tipping(S, byId); closest(S, byId); revision(S); markets(S);
  } catch (err) {
    console.error(err);
    showError(status, err, 'Run `uv run electionpredictions run` to generate site/data.');
  }
}

function leader(S) {
  const { p_dem: d, p_rep: r } = S.ec;
  if (Math.abs(d - r) < 0.04) return 'The race is a toss-up';
  return d > r ? `Democrats are favoured to win the White House` : `Republicans are favoured to win the White House`;
}

function lede(S) {
  const p = Math.max(S.ec.p_dem, S.ec.p_rep);
  const move = movement(S);
  document.getElementById('lede').textContent =
    `${leader(S)}, winning ${fmt.pct(p)} of ${fmt.num(S.model.n_sims || 50000)} simulations${move ? ` (${move})` : ''}. `
    + `${fmt.num(S.days_to_election)} days out, with neither nominee chosen, the range of outcomes is still wide.`;
}

/** "up 1.2 points in the last 24 hours" from the per-update log. */
function movement(S) {
  const pts = (S.recent || []).filter((r) => isNum(r.p_dem));
  if (pts.length < 2) return '';
  const last = pts[pts.length - 1];
  const cutoff = Date.parse(last.ts) - 24 * 36e5;
  const prior = pts.filter((r) => Date.parse(r.ts) <= cutoff).pop() || pts[0];
  const d = (last.p_dem - prior.p_dem) * 100;
  const hours = Math.round((Date.parse(last.ts) - Date.parse(prior.ts)) / 36e5);
  if (hours < 3) return '';
  if (Math.abs(d) < 0.5) return `the Democratic chance is steady over the last ${hours >= 23 ? 'day' : `${hours} hours`}`;
  return `the Democratic chance is ${d > 0 ? 'up' : 'down'} ${Math.abs(d).toFixed(1)} points over the last ${hours >= 23 ? 'day' : `${hours} hours`}`;
}

function hero(S) {
  const ec = S.ec;
  const card = h('article', { class: 'card hero-card pres-card', 'aria-label': 'Chance of winning the presidency' });
  card.append(
    h('div', { class: 'control-probs' },
      h('div', { class: 'side dem' },
        h('div', { class: 'big', style: { color: 'var(--dem)' } }, fmt.pct(ec.p_dem)),
        h('div', { class: 'lbl' }, h('span', { class: 'party-dot dem', 'aria-hidden': 'true' }), 'Democrat wins')),
      h('div', { class: 'side rep' },
        h('div', { class: 'big', style: { color: 'var(--rep)' } }, fmt.pct(ec.p_rep)),
        h('div', { class: 'lbl' }, h('span', { class: 'party-dot rep', 'aria-hidden': 'true' }), 'Republican wins'))),
    splitBar(ec.p_dem, ec.p_rep, ec.p_tie),
    h('p', { class: 'note' }, isNum(ec.p_tie) && ec.p_tie >= 0.005
      ? `A 269–269 tie, which the House would decide, happens in ${fmt.pct(ec.p_tie, 1)} of simulations.`
      : '270 electoral votes wins.'),
    h('dl', { class: 'stats' },
      stat('Expected Democratic EVs', `${fmt.num(ec.dem_ev.mean)}`, `80% range ${fmt.num(ec.dem_ev.p10)}–${fmt.num(ec.dem_ev.p90)}`),
      stat('Expected Republican EVs', `${fmt.num(ec.rep_ev.mean)}`, `80% range ${fmt.num(ec.rep_ev.p10)}–${fmt.num(ec.rep_ev.p90)}`),
      stat('National popular vote', fmt.margin(S.popular.margin), `80% range ${fmt.margin(S.popular.p10)} to ${fmt.margin(S.popular.p90)}`),
      stat('Popular vote / Electoral College split', fmt.pct((S.splits.dem_ec_rep_pv || 0) + (S.splits.rep_ec_dem_pv || 0)),
        `R wins EC while losing vote: ${fmt.pct(S.splits.rep_ec_dem_pv)}`)),
  );
  if (S.model && S.model.version) {
    card.append(h('p', { class: 'model-chip small' },
      h('a', { href: 'model.html' }, `Model v${S.model.version}`), ' · last revised ', h('span', { 'data-rel': S.model.updated || '' }, relativeTime(S.model.updated)),
      S.model.title ? ` · ${S.model.title}` : ''));
  }
  document.getElementById('hero').replaceChildren(card);
}

function stat(label, value, sub) {
  return h('div', {}, h('dt', {}, label), h('dd', {}, value, sub ? h('span', { class: 'range' }, ` ${sub}`) : null));
}

function evBlock(S) {
  evHistogram(document.getElementById('hist'), S.ec.histogram);
  const ev = S.ec.dem_ev;
  document.getElementById('ev-stats').replaceChildren(
    stat('Median Democratic EVs', fmt.num(ev.median)),
    stat('Middle half of outcomes', `${fmt.num(ev.p25)}–${fmt.num(ev.p75)}`),
    stat('Simulations', fmt.num(S.model.n_sims || 20000)),
  );
}

function trend(S) {
  // daily history, with every update of the last week in finer detail
  const recent = (S.recent || []).map((r) => ({ date: r.ts, p_dem: r.p_dem, p_rep: r.p_rep, version: r.v }));
  const cutoff = recent.length ? Date.parse(recent[0].date) : Infinity;
  // a daily point is that day's last update, so it sits at the end of its (UTC) day
  const daily = (S.history || []).map((d) => ({ ...d, date: `${d.date}T23:59:00Z`, when: `${fmt.date(d.date)} (end of day)` }))
    .filter((d) => Date.parse(d.date) < cutoff);
  const series = [...daily, ...recent];
  trendChart(document.getElementById('trend'), series.length ? series : S.history, {
    label: 'Chance of winning over time',
    series: [
      { label: 'Democrat', value: (d) => d.p_dem, color: themeColor('D') },
      { label: 'Republican', value: (d) => d.p_rep, color: themeColor('R') },
    ],
  });
  if (series.length < 3) {
    document.getElementById('trend').after(h('p', { class: 'chart-note' }, 'The trend builds up with each update of the forecast (every 15 minutes).'));
  }
}

function road(states) {
  roadTo270(document.getElementById('road'), states, { onSelect: (id) => { location.href = stateHref(id); } });
}

function map(geo, byId) {
  ecMap(document.getElementById('map'), geo, {
    valueOf: (id) => (byId.get(id) || {}).p_dem,
    tipFor: (id) => {
      const s = byId.get(id);
      if (!s) return [];
      return [['Electoral votes', String(s.evs)], ['Chance D wins', fmt.pct(s.p_dem)], ['Expected margin', fmt.margin(s.margin)], ['2024 result', fmt.margin(s.margin24)]];
    },
    onSelect: (id) => { location.href = stateHref(id); },
  });
  document.getElementById('legend').replaceChildren(probLegend());
}

function overview(S) {
  const o = S.overview;
  if (!o || !o.summary) return;
  document.getElementById('overview-block').hidden = false;
  const root = document.getElementById('overview');
  root.append(...String(o.summary).split(/\n\s*\n/).map((p) => h('p', { class: 'prose' }, p)));
  if (o.key_factors && o.key_factors.length) {
    root.append(h('h3', {}, 'Key factors'), h('ul', { class: 'check-list' }, ...o.key_factors.map((k) => h('li', {}, k))));
  }
  if (o.watch) root.append(h('p', { class: 'muted' }, h('strong', {}, 'What to watch: '), o.watch));
}

function nominees(S, party) {
  const root = document.getElementById(`nom-${party}`);
  const list = (S.nominees[party] || []).slice(0, 7);
  const word = party === 'D' ? 'Democratic' : 'Republican';
  root.append(h('div', { class: 'card-head' }, h('h2', {}, `${word} nomination`), h('a', { href: 'field.html' + (party === 'R' ? '#R' : '') }, 'The field →')),
    h('p', { class: 'card-sub' }, 'Chance of being the nominee, and the party\'s chance of winning the presidency with them.'));
  const tbl = h('table', { class: 'races-table compact' },
    h('thead', {}, h('tr', {}, h('th', {}, 'Candidate'), h('th', { class: 'num' }, 'Nominee'), h('th', {}, ''), h('th', { class: 'num' }, 'Wins if nominee'))));
  const body = h('tbody');
  const max = Math.max(...list.map((c) => c.p || 0), 0.01);
  for (const c of list) {
    body.append(h('tr', {},
      h('td', {}, h('span', { class: `party-dot ${partyClass(party)}`, 'aria-hidden': 'true' }), c.name === 'Other' ? 'Someone else' : c.name,
        c.home_state ? h('span', { class: 'muted small' }, ` ${c.home_state}`) : null),
      h('td', { class: 'num' }, fmt.pct(c.p)),
      h('td', { class: 'bar-cell' }, h('span', { class: `mini-bar ${partyClass(party)}`, style: { width: `${(c.p / max) * 100}%` } })),
      h('td', { class: 'num' }, fmt.pct(c.p_win_if_nominee))));
  }
  tbl.append(body);
  root.append(tbl);
}

function matchups(S) {
  const rows = (S.scenarios || []).slice(0, 8);
  const tbl = h('table', { class: 'races-table' },
    h('thead', {}, h('tr', {}, h('th', {}, 'Matchup'), h('th', { class: 'num' }, 'Chance of this matchup'), h('th', { class: 'num' }, 'Democrat wins'),
      h('th', { class: 'num' }, 'Republican wins'), h('th', { class: 'num' }, 'Expected EVs (D–R)'), h('th', { class: 'num' }, 'Popular vote'))));
  const body = h('tbody');
  for (const s of rows) {
    body.append(h('tr', {},
      h('td', {}, h('span', { class: 'party-dot dem', 'aria-hidden': 'true' }), s.dem, h('span', { class: 'vs' }, ' vs '), h('span', { class: 'party-dot rep', 'aria-hidden': 'true' }), s.rep),
      h('td', { class: 'num' }, fmt.pct(s.p, 1)),
      h('td', { class: 'num' }, probChip(s.p_dem)),
      h('td', { class: 'num' }, fmt.pct(s.p_rep)),
      h('td', { class: 'num' }, `${fmt.num(s.dem_ev)}–${fmt.num(TOTAL_EV - s.dem_ev)}`),
      h('td', { class: 'num' }, fmt.margin(s.pv_margin))));
  }
  tbl.append(body);
  document.getElementById('matchups').replaceChildren(tbl,
    h('p', { class: 'table-note' }, h('a', { href: 'map.html' }, 'See the map for any matchup →')));
}

function environment(S) {
  const E = S.environment;
  const root = document.getElementById('env');
  const np = E.national_polls || {};
  root.append(
    h('h2', {}, 'The national environment'),
    h('p', { class: 'card-sub' }, 'The expected national margin before candidate effects: national polls blended with presidential approval and the economy. The blend shifts toward polls as the election nears.'),
    h('div', { class: 'generic-big', style: { color: E.environment >= 0 ? 'var(--dem)' : 'var(--rep)' } }, fmt.margin(E.environment)),
    h('dl', { class: 'kv' },
      kv('National polls (average-strength matchup)', isNum(E.polls) ? fmt.margin(E.polls) : 'No polls yet', np.n ? `${np.n} polls, latest ${fmt.dateShort(np.last)}` : ''),
      kv('Approval & economy imply', fmt.margin(E.fundamentals), E.approval ? `net approval ${fmt.signed(E.approval.net)}; economy index ${fmt.signed(E.econ_index)}` : ''),
      kv('Weight on polls', fmt.pct(E.poll_weight), 'rises toward Election Day'),
      E.adjustment ? kv('Judgment adjustment', fmt.signed(E.adjustment), 'from the latest model revision') : null,
      S.midterm_2026 ? kv('2026 midterm House vote', fmt.margin(S.midterm_2026.house_vote.margin),
        `raw national count; seats D ${S.midterm_2026.seats.house.D} · R ${S.midterm_2026.seats.house.R}`) : null),
    h('p', { class: 'small' }, h('a', { href: 'polls.html' }, 'Polls and fundamentals →')),
  );
}

function kv(k, v, sub) {
  return h('div', {}, h('dt', {}, k), h('dd', {}, v, sub ? h('span', { class: 'muted small' }, ` · ${sub}`) : null));
}

function tipping(S, byId) {
  const root = document.getElementById('tipping');
  root.append(h('h2', {}, 'Tipping-point states'), h('p', { class: 'card-sub' }, 'Chance each contest casts the decisive 270th electoral vote.'));
  const list = h('ol', { class: 'count-list tip-list' });
  const max = Math.max(...S.tipping.map((t) => t.p), 0.01);
  for (const t of S.tipping.slice(0, 8)) {
    const s = byId.get(t.id) || {};
    list.append(h('li', {},
      h('a', { href: stateHref(t.id) }, contestName(t.id)), h('span', { class: 'muted small' }, ` ${t.evs} EV`),
      h('span', { class: 'tip-bar' }, h('span', { style: { width: `${(t.p / max) * 100}%` } })),
      h('span', { class: 'num' }, fmt.pct(t.p, 1)), ' ', probChip(s.p_dem)));
  }
  root.append(list);
}

function closest(S, byId) {
  const root = document.getElementById('closest');
  for (const id of S.closest) {
    const s = byId.get(id);
    if (!s) continue;
    const card = h('a', { class: 'race-card', href: stateHref(id) },
      h('div', { class: 'rc-head' }, h('span', { class: 'rc-title' }, contestName(id)), h('span', { class: 'muted small' }, `${s.evs} EV`)),
      h('div', { class: 'rc-pct big-num' }, fmt.pct(Math.max(s.p_dem, 1 - s.p_dem)), h('span', { class: 'small' }, s.p_dem >= 0.5 ? ' D' : ' R')),
      h('div', { class: 'muted small' }, `Expected ${fmt.margin(s.margin)} · 2024 ${fmt.margin(s.margin24)}`));
    paintProb(card.querySelector('.rc-pct'), s.p_dem);
    root.append(card);
  }
}

const ORIGIN = { seed: 'Initial', calibration: 'Polling update', revision: 'Revision' };

function revision(S) {
  const root = document.getElementById('revision');
  const list = S.revisions && S.revisions.length ? S.revisions : [{ version: S.model.version, created_at: S.model.updated, title: S.model.title, summary: S.model.summary }];
  root.append(
    h('div', { class: 'card-head' }, h('h2', { id: 'h-rev' }, 'How the model is changing'), h('a', { href: 'model.html' }, 'Full model log →')),
    h('p', { class: 'card-sub' }, 'The model re-specifies itself as evidence arrives: nomination odds, candidate strength, poll weighting, uncertainty and state adjustments are rebuilt and logged.'),
    h('ol', { class: 'rev-feed' }, ...list.slice(0, 5).map((v) => h('li', {},
      h('div', { class: 'rev-head' }, h('a', { href: `model.html#v${v.version}` }, `v${v.version}`), h('strong', {}, v.title || ORIGIN[v.origin] || 'Update'),
        h('span', { class: 'muted small', 'data-rel': v.created_at || '' }, relativeTime(v.created_at))),
      v.summary ? h('p', { class: 'small' }, v.summary) : null))),
  );
}

function stories(S) {
  const list = S.storylines || [];
  if (!list.length) return;
  document.getElementById('stories-block').hidden = false;
  const LEAN = { D: ['dem', 'Helps Democrats'], R: ['rep', 'Helps Republicans'], neutral: ['neutral', 'Uncertain impact'] };
  document.getElementById('stories').replaceChildren(...list.map((st) => {
    const [cls, label] = LEAN[st.leans] || LEAN.neutral;
    return h('article', { class: `card story ${cls}` },
      h('div', { class: 'story-meta' }, h('span', { class: `story-lean ${cls}` }, label), h('span', { class: 'muted small' }, `since ${fmt.dateShort(st.since)}`)),
      h('h3', {}, st.title), st.detail ? h('p', { class: 'small' }, st.detail) : null);
  }));
}

function markets(S) {
  const mk = S.markets || {};
  const el = document.getElementById('markets');
  const party = (mk.party || []).filter((m) => m.outcome === 'D');
  if (!party.length) { el.hidden = true; return; }
  el.append('Prediction markets, for comparison (not used by the forecast): Democrat wins ');
  party.forEach((m, i) => {
    if (i) el.append(' · ');
    el.append(h('a', { href: m.url, target: '_blank', rel: 'noopener' }, `${fmt.platform(m.platform)} ${fmt.pct(m.p)}`));
  });
  el.append(`. Forecast: ${fmt.pct(S.ec.p_dem)}.`);
}

main();
