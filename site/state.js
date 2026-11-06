/**
 * state.js — one contest's forecast page (state.html?id=PA): headline odds, what drives the margin, matchups,
 * trend, polls, past results, expert ratings and coverage.
 */
import {
  DASH, loadJSON, fmt, isNum, h, probChip, ratingPill, contestName, query, initChrome, renderUpdated, renderFooterMeta, showError,
  scaleLinear, svgEl, responsiveChart, relativeTime,
} from './common.js';
import { splitBar, trendChart, marginRange, themeColor } from './charts.js';

async function main() {
  initChrome({ current: 'states' });
  const status = document.getElementById('status');
  const id = (query.get('id') || '').toUpperCase();
  if (!/^[A-Z]{2}(-\d)?$/.test(id)) { showError(status, new Error('No contest selected.'), 'Open a state from the map or the states table.'); return; }
  try {
    const [summary, s] = await Promise.all([loadJSON('summary.json'), loadJSON(`states/${id}.json`)]);
    status.hidden = true;
    const app = document.getElementById('app');
    app.hidden = false;
    renderUpdated(summary); renderFooterMeta(summary);
    document.title = `${contestName(id)} — Presidential Model 2028`;
    app.append(header(s), headline(s), overview(s), breakdown(s), matchups(s), trend(s), polls(s), results(s), ratings(s), news(s));
  } catch (err) {
    console.error(err);
    showError(status, err);
  }
}

function header(s) {
  const r24 = s.winner24 === 'D' ? 'Harris' : 'Trump', r20 = s.winner20 === 'D' ? 'Biden' : 'Trump';
  return h('div', { class: 'page-head race-header' },
    h('a', { class: 'back-link', href: 'states.html' }, '← All states'),
    h('h1', {}, contestName(s.id)),
    h('p', {}, `${s.evs} electoral vote${s.evs === 1 ? '' : 's'} · lean ${s.lean_label || 'EVEN'} relative to the nation · `
      + `${r24} won it by ${Math.abs(s.margin24).toFixed(1)} in 2024, ${r20} by ${Math.abs(s.margin20).toFixed(1)} in 2020`));
}

function headline(s) {
  return h('section', { class: 'section card headline' },
    h('div', { class: 'control-probs' },
      h('div', { class: 'side dem' }, h('div', { class: 'big', style: { color: 'var(--dem)' } }, fmt.pct(s.p_dem)), h('div', { class: 'lbl' }, 'Democrat wins')),
      h('div', { class: 'side rep' }, h('div', { class: 'big', style: { color: 'var(--rep)' } }, fmt.pct(1 - s.p_dem)), h('div', { class: 'lbl' }, 'Republican wins'))),
    splitBar(s.p_dem, 1 - s.p_dem, 0),
    h('dl', { class: 'stats' },
      h('div', {}, h('dt', {}, 'Expected margin'), h('dd', {}, fmt.margin(s.margin), h('span', { class: 'range' }, ` 80% range ${fmt.margin(s.p10)} to ${fmt.margin(s.p90)}`))),
      h('div', {}, h('dt', {}, 'Range'), h('dd', {}, marginRange(s.p10, s.margin, s.p90, { width: 240, domain: [Math.min(-30, s.p10 - 2), Math.max(30, s.p90 + 2)] }))),
      h('div', {}, h('dt', {}, 'Category'), h('dd', {}, ratingPill(s.label))),
      h('div', {}, h('dt', {}, 'Tipping-point chance'), h('dd', {}, fmt.pct(s.tip, 1))),
      h('div', {}, h('dt', {}, 'Chance it flips from 2024'), h('dd', {}, fmt.pct(s.flip)))));
}

function overview(s) {
  const o = s.overview;
  if (!o || !o.overview) return h('span');
  const card = h('section', { class: 'section card overview-card' }, h('h2', {}, 'Outlook'),
    ...String(o.overview).split(/\n\s*\n/).map((p) => h('p', { class: 'prose' }, p)));
  if (o.key_factors && o.key_factors.length) card.append(h('h3', {}, 'Key factors'), h('ul', { class: 'check-list' }, ...o.key_factors.map((k) => h('li', {}, k))));
  if (o.watch) card.append(h('p', { class: 'muted' }, h('strong', {}, 'What to watch: '), o.watch));
  return card;
}

function breakdown(s) {
  const b = s.breakdown;
  const steps = [
    ['Partisan lean (2020 & 2024)', b.historical_lean, `${fmt.margin(b.rel24)} vs nation in 2024, ${fmt.margin(b.rel20)} in 2020`],
    ['State polls', b.poll_shift, s.poll_update ? `${s.poll_update.n_polls} poll${s.poll_update.n_polls === 1 ? '' : 's'}, ${fmt.pct(s.poll_update.poll_weight)} weight` : 'no state polls yet'],
    ['National environment', b.environment, 'polls blended with approval and the economy'],
    ['Nominee strength', b.nominee_effects, 'averaged over possible nominees'],
    ['Home state', b.home_effect, 'possible nominees from here'],
    ['State adjustment', b.adjustment, b.adjustment_reason || 'none in the current model'],
    ['Expert ratings', b.rating_pull, 'pull toward published ratings'],
  ].filter(([, v], i) => i < 3 || Math.abs(v || 0) >= 0.05);
  const total = s.margin;
  const card = h('section', { class: 'section card' }, h('h2', {}, 'What drives the forecast'),
    h('p', { class: 'card-sub' }, 'How the expected margin is built, in points (Democratic-positive).'));
  const box = h('div', { class: 'chart-box' });
  card.append(box);
  responsiveChart(box, (w) => waterfall(w, steps, total));
  return card;
}

function waterfall(w, steps, total) {
  const rowH = 30, m = { l: Math.min(230, w * 0.42), r: 64, t: 6, b: 6 };
  const rows = [...steps, ['Expected margin', total, '']];
  const H = rows.length * rowH + m.t + m.b;
  let acc = 0;
  const spans = rows.map(([label, v], i) => {
    if (i === rows.length - 1) return [0, v];
    const a = acc; acc += v || 0; return [a, acc];
  });
  const lo = Math.min(0, ...spans.flat()) - 2, hi = Math.max(0, ...spans.flat()) + 2;
  const x = scaleLinear([lo, hi], [m.l, w - m.r]);
  const svg = svgEl('svg', { class: 'chart waterfall-svg', viewBox: `0 0 ${w} ${H}`, width: w, height: H, role: 'img', 'aria-label': 'Breakdown of the expected margin' });
  svg.append(svgEl('line', { class: 'axis', x1: x(0), x2: x(0), y1: 0, y2: H }));
  rows.forEach(([label, v, note], i) => {
    const [a, b] = spans[i];
    const y = m.t + i * rowH;
    const last = i === rows.length - 1;
    svg.append(svgEl('text', { class: last ? 'label strong' : 'label', x: 4, y: y + 15 }, label));
    if (note) svg.append(svgEl('text', { class: 'tick', x: 4, y: y + 27 }, note.length > 46 ? `${note.slice(0, 44)}…` : note));
    const x0 = x(Math.min(a, b)), x1 = x(Math.max(a, b));
    svg.append(svgEl('rect', { x: x0, y: y + 6, width: Math.max(1.5, x1 - x0), height: rowH - 12, rx: 3,
      fill: last ? ((v || 0) >= 0 ? 'var(--dem)' : 'var(--rep)') : ((v || 0) >= 0 ? 'color-mix(in srgb, var(--dem) 55%, var(--surface))' : 'color-mix(in srgb, var(--rep) 55%, var(--surface))') }));
    svg.append(svgEl('text', { class: 'tick', x: Math.max(x0, x1) + 6, y: y + 19 }, last ? fmt.margin(v) : fmt.signed(v)));
  });
  return svg;
}

function matchups(s) {
  const list = (s.matchups || []).filter((m) => isNum(m.p_dem));
  if (!list.length) return h('span');
  const body = h('tbody');
  for (const m of list.slice(0, 10)) {
    body.append(h('tr', {}, h('td', {}, `${m.dem} vs ${m.rep}`), h('td', { class: 'num' }, fmt.pct(m.p, 1)), h('td', { class: 'num' }, probChip(m.p_dem))));
  }
  return h('section', { class: 'section card' }, h('h2', {}, 'By matchup'),
    h('p', { class: 'card-sub' }, `Chance a Democrat carries ${contestName(s.id)} under each likely pairing of nominees.`),
    h('div', { class: 'table-wrap' }, h('table', { class: 'races-table' },
      h('thead', {}, h('tr', {}, h('th', {}, 'Matchup'), h('th', { class: 'num' }, 'Chance of matchup'), h('th', { class: 'num' }, 'Democrat wins here'))), body)));
}

function trend(s) {
  const card = h('section', { class: 'section card' }, h('h2', {}, 'Over time'));
  const box = h('div', { class: 'chart-box' });
  card.append(box);
  trendChart(box, s.history, { label: 'Chance of a Democratic win over time', series: [{ label: 'Democrat wins', value: (d) => d.p_dem, color: themeColor('D') }] });
  return card;
}

function polls(s) {
  const card = h('section', { class: 'section card' }, h('h2', {}, 'Polls'));
  if (!s.polls.length) {
    card.append(h('p', { class: 'muted' }, `No general-election polls of ${contestName(s.id)} yet. Its outlook rests on its voting history and the national picture.`));
    return card;
  }
  if (s.poll_update) {
    card.append(h('p', { class: 'card-sub' }, `Polls here run ${fmt.margin(s.poll_update.poll_relative)} relative to national polls of the same matchups; `
      + `they move the state's lean by ${fmt.signed(s.poll_update.shift)} points.`));
  }
  const body = h('tbody');
  for (const p of s.polls) {
    body.append(h('tr', {}, h('td', {}, p.pollster, p.sponsor ? h('span', { class: 'muted small' }, ` (${p.sponsor})`) : null), h('td', {}, fmt.dateRange(p.start, p.end)),
      h('td', { class: 'num' }, p.n ? `${fmt.num(p.n)} ${p.pop || ''}` : DASH), h('td', {}, `${p.dem} ${fmt.pts(p.dem_pct, 0)} – ${p.rep} ${fmt.pts(p.rep_pct, 0)}`),
      h('td', { class: 'num' }, fmt.margin(p.margin)), h('td', { class: 'num' }, isNum(p.weight) ? fmt.dec(p.weight, 2) : DASH)));
  }
  card.append(h('div', { class: 'table-wrap' }, h('table', { class: 'races-table' },
    h('thead', {}, h('tr', {}, h('th', {}, 'Pollster'), h('th', {}, 'Dates'), h('th', { class: 'num' }, 'Sample'), h('th', {}, 'Result'), h('th', { class: 'num' }, 'Margin'), h('th', { class: 'num' }, 'Weight'))), body)));
  return card;
}

const MID_LABEL = { senate: '2026 Senate', senate_special: '2026 Senate (special)', governor: '2026 Governor' };

function results(s) {
  const mid = Object.entries(s.midterm_2026 || {}).map(([k, x]) => h('tr', {}, h('td', {}, MID_LABEL[k] || `2026 ${k}`),
    h('td', {}, x.margin >= 0 ? 'Democrat' : 'Republican', x.status !== 'called' ? h('span', { class: 'muted small' }, ` (${x.reporting ?? '—'}% counted)`) : null),
    h('td', { class: 'num' }, fmt.margin(x.margin)), h('td', { class: 'num' }, `${fmt.margin(x.vs_national_house)} vs House vote`)));
  return h('section', { class: 'section card' }, h('h2', {}, 'Past results'),
    h('table', { class: 'races-table compact' }, h('thead', {}, h('tr', {}, h('th', {}, 'Year'), h('th', {}, 'Winner'), h('th', { class: 'num' }, 'Margin'), h('th', { class: 'num' }, 'vs nation'))),
      h('tbody', {},
        h('tr', {}, h('td', {}, '2024'), h('td', {}, s.winner24 === 'D' ? 'Harris (D)' : 'Trump (R)'), h('td', { class: 'num' }, fmt.margin(s.margin24)), h('td', { class: 'num' }, fmt.margin(s.breakdown.rel24))),
        h('tr', {}, h('td', {}, '2020'), h('td', {}, s.winner20 === 'D' ? 'Biden (D)' : 'Trump (R)'), h('td', { class: 'num' }, fmt.margin(s.margin20)), h('td', { class: 'num' }, fmt.margin(s.breakdown.rel20))),
        ...mid)),
    mid.length ? h('p', { class: 'table-note' }, '2026 rows are midterm statewide races (different candidates and electorate); they inform the forecast\'s judgment rather than the lean directly.') : null);
}

function ratings(s) {
  if (!s.ratings || !s.ratings.length) return h('span');
  return h('section', { class: 'section card' }, h('h2', {}, 'Expert ratings'),
    h('ul', { class: 'rating-list' }, ...s.ratings.map((r) => h('li', {}, h('span', {}, r.rater), ' ', ratingPill(r.rating), r.as_of ? h('span', { class: 'muted small' }, ` ${fmt.dateShort(r.as_of)}`) : null))));
}

function news(s) {
  if (!s.news || !s.news.length) return h('span');
  return h('section', { class: 'section card' }, h('h2', {}, 'Recent coverage'),
    h('ul', { class: 'news-list' }, ...s.news.map((n) => h('li', {}, h('a', { href: n.url, target: '_blank', rel: 'noopener' }, n.title),
      h('span', { class: 'news-meta' }, ` ${n.source || ''} · ${relativeTime(n.published)}`)))));
}

main();
