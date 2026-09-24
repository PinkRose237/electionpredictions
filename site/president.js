/**
 * president.js — the 2028 presidential forecast page (president.html).
 *
 * Loads data2028/summary.json + races.json (PBASE, overridable with ?data_pres=)
 * and renders: hero card (win odds / expected EVs + histogram), trend chart,
 * electoral-vote buckets with tipping point, EC tile map, state table, closest
 * states, and a methodology note. Reuses shared helpers from common.js.
 */
import {
  LABELS, STATE_GRID, DASH,
  query, resolveDataBase, loadJSON, fmt, isNum, clamp, parseDate,
  isDark, onThemeChange, probColor, probGradient, textOn,
  h, svgEl, scaleLinear, niceTicks, dateTicks, responsiveChart,
  tooltip, tipContent, attachTooltip,
  ratingP, ratingPill, probChip, matchupNode, partyClass,
  initChrome, renderUpdated, renderFooterMeta, showError,
} from './common.js';

/** Data directory for the 2028 model (separate from the 2026 dashboard's ./data). */
const PBASE = (() => {
  const raw = query.get('data_pres');
  if (!raw) return './data2028';
  const b = resolveDataBase(raw);
  return b === './data' ? './data2028' : b;
})();
const PDATA = PBASE === './data' ? null : PBASE.slice(2);
const loadPres = (rel) => loadJSON(rel, PBASE);
/** Link to a race page reading from the 2028 data dir. */
function presRaceHref(id) {
  const base = `race.html?id=${encodeURIComponent(id)}`;
  return PDATA ? `${base}&data=${encodeURIComponent(PDATA)}` : base;
}

/** Extra tile row carrying DC (STATE_GRID covers the 50 states only). */
const PRES_GRID = [...STATE_GRID.map((r) => [...r]), ['', '', '', '', '', '', '', '', 'DC', '', '']];
const TOTAL_EV = 538, NEEDED_EV = 270;

const S = { summary: null, races: [], byId: new Map(), view: 'control' };
try {
  const saved = localStorage.getItem('pres-view');
  if (saved === 'evs' || saved === 'control') S.view = saved;
} catch (e) { /* storage unavailable */ }

async function main() {
  initChrome({ current: 'president' });
  const status = document.getElementById('status');
  try {
    const [summary, races] = await Promise.all([loadPres('summary.json'), loadPres('races.json')]);
    S.summary = summary || {};
    S.races = Array.isArray(races) ? races : [];
    for (const r of S.races) S.byId.set(r.race_id, r);
    status.hidden = true;
    document.getElementById('pres').hidden = false;
    renderUpdated(S.summary);
    renderFooterMeta(S.summary);
    initPresView();
    renderHero();
    renderTrend();
    renderBuckets();
    renderMap();
    renderTable();
    renderClosest();
  } catch (err) {
    console.error(err);
    showError(status, err, 'Run the 2028 pipeline (EP_CYCLE=2028) to generate site/data2028.');
  }
}

// ---------------------------------------------------------------------------
// View toggle + hero card
// ---------------------------------------------------------------------------

function pres() {
  return (S.summary.chambers || {}).president || null;
}

function initPresView() {
  const root = document.getElementById('pres-view');
  if (!root) return;
  const btns = [...root.querySelectorAll('button[data-view]')];
  const paint = () => {
    for (const b of btns) b.setAttribute('aria-pressed', b.dataset.view === S.view ? 'true' : 'false');
  };
  for (const b of btns) {
    b.addEventListener('click', () => {
      if (S.view === b.dataset.view) return;
      S.view = b.dataset.view;
      try { localStorage.setItem('pres-view', S.view); } catch (e) { /* storage unavailable */ }
      paint();
      renderHero();
      renderTrend();
    });
  }
  paint();
}

function splitBar(pD, pR, pN, ariaLabel) {
  const bar = h('div', { class: 'split-bar', role: 'img', 'aria-label': ariaLabel || `Democrats ${fmt.pct(pD)}, Republicans ${fmt.pct(pR)}` });
  const d = isNum(pD) ? pD : 0, r = isNum(pR) ? pR : 0, n = isNum(pN) ? pN : Math.max(0, 1 - d - r);
  if (d > 0) bar.append(h('span', { class: 'd', style: { width: `${d * 100}%` } }));
  if (n > 0.005) bar.append(h('span', { class: 'n', style: { width: `${n * 100}%` } }));
  if (r > 0) bar.append(h('span', { class: 'r', style: { width: `${r * 100}%` } }));
  return bar;
}

function renderHero() {
  const root = document.getElementById('pres-card');
  const ch = pres();
  root.replaceChildren(heroCard(ch));
}

function heroCard(ch) {
  const card = h('article', { class: 'card chamber-card pres-card', 'aria-label': 'Presidential forecast' });
  if (!ch) {
    card.append(h('h2', {}, 'President'), h('p', { class: 'muted' }, 'No forecast data.'));
    return card;
  }
  card.append(
    h('header', {},
      h('h2', {}, 'President'),
      h('span', { class: 'sub' }, `51 contests · ${fmt.num(TOTAL_EV)} electoral votes`, h('br'), `${fmt.num(NEEDED_EV)} to win`)),
  );
  if (S.view === 'evs') {
    const dMean = ch.dem_seats && ch.dem_seats.mean, rMean = ch.rep_seats && ch.rep_seats.mean;
    const dShare = isNum(dMean) ? dMean / TOTAL_EV : null, rShare = isNum(rMean) ? rMean / TOTAL_EV : null;
    const probs = h('div', { class: 'control-probs' },
      h('div', { class: 'side dem' },
        h('div', { class: 'big', style: { color: 'var(--dem)' } }, fmt.num(dMean)),
        h('div', { class: 'lbl' }, h('span', { class: 'party-dot dem', 'aria-hidden': 'true' }), `Dem EVs · ${fmt.pct(dShare)}`)),
      h('div', { class: 'side rep' },
        h('div', { class: 'big', style: { color: 'var(--rep)' } }, fmt.num(rMean)),
        h('div', { class: 'lbl' }, h('span', { class: 'party-dot rep', 'aria-hidden': 'true' }), `Rep EVs · ${fmt.pct(rShare)}`)),
    );
    card.append(probs, splitBar(dShare, rShare, null,
      `Democrats ${fmt.num(dMean)} electoral votes, Republicans ${fmt.num(rMean)} electoral votes`));
  } else {
    const probs = h('div', { class: 'control-probs' },
      h('div', { class: 'side dem' },
        h('div', { class: 'big', style: { color: 'var(--dem)' } }, fmt.pct(ch.p_dem)),
        h('div', { class: 'lbl' }, h('span', { class: 'party-dot dem', 'aria-hidden': 'true' }), 'Democrat wins')),
      h('div', { class: 'side rep' },
        h('div', { class: 'big', style: { color: 'var(--rep)' } }, fmt.pct(ch.p_rep)),
        h('div', { class: 'lbl' }, h('span', { class: 'party-dot rep', 'aria-hidden': 'true' }), 'Republican wins')),
    );
    if (isNum(ch.p_neither) && ch.p_neither > 0.005) {
      probs.append(h('div', { class: 'neither' }, `Electoral College tie (269–269), decided by the House: ${fmt.pct(ch.p_neither)}`));
    }
    card.append(probs, splitBar(ch.p_dem, ch.p_rep, ch.p_neither));
  }
  card.append(h('p', { class: 'note' }, '270 electoral votes wins. A 269–269 tie goes to a House contingent election and counts for neither party.'));

  const cur = ch.current || {};
  const flips = ch.expected_flips || {};
  const evRange = (s) => (s ? h('span', {}, fmt.num(s.mean), ' ', h('span', { class: 'range' }, `(${fmt.num(s.p10)}–${fmt.num(s.p90)})`)) : DASH);
  card.append(
    h('dl', { class: 'stats' },
      h('div', {}, h('dt', {}, 'Expected D EVs', h('span', { class: 'muted' }, ' · 80% range')), h('dd', {}, evRange(ch.dem_seats))),
      h('div', {}, h('dt', {}, 'Expected R EVs', h('span', { class: 'muted' }, ' · 80% range')), h('dd', {}, evRange(ch.rep_seats))),
      h('div', {}, h('dt', {}, '2024 result'), h('dd', {}, `D ${fmt.num(cur.D)} · R ${fmt.num(cur.R)}`)),
      h('div', {}, h('dt', {}, 'Expected flips vs 2024'), h('dd', {}, `D ${fmt.dec(flips.D, 1)} · R ${fmt.dec(flips.R, 1)}`)),
    ),
  );

  const box = h('div', { class: 'chart-box' });
  card.append(
    h('div', { class: 'hist-caption' }, h('span', {}, 'Democratic electoral votes across simulations'), h('span', {}, `To win: ${fmt.num(NEEDED_EV)}`)),
    box,
  );
  responsiveChart(box, (w) => drawHistogram(w, ch));

  if (Array.isArray(ch.markets) && ch.markets.length) {
    const line = h('p', { class: 'markets-line' }, 'Markets (D wins presidency): ');
    ch.markets.forEach((mk, i) => {
      if (i) line.append(' · ');
      const text = `${fmt.platform(mk.platform)} ${fmt.pct(mk.p_dem)}`;
      line.append(mk.url ? h('a', { href: mk.url, target: '_blank', rel: 'noopener' }, text) : text);
    });
    card.append(line);
  }
  return card;
}

/** Histogram of Democratic electoral votes with the 270 line. */
function drawHistogram(w, ch) {
  const bins = (ch.histogram || []).filter((b) => isNum(b.seats) && isNum(b.p) && b.p > 0);
  if (!bins.length) return h('p', { class: 'muted small' }, 'No simulation output.');
  const H = 120, m = { t: 20, r: 6, b: 18, l: 6 };
  const needed = NEEDED_EV, total = TOTAL_EV;
  let s0 = Math.min(...bins.map((b) => b.seats)), s1 = Math.max(...bins.map((b) => b.seats));
  s0 = Math.min(s0, needed - 1); s1 = Math.max(s1, needed + 1);
  const x = scaleLinear([s0 - 0.5, s1 + 0.5], [m.l, w - m.r]);
  const pmax = Math.max(...bins.map((b) => b.p));
  const y = scaleLinear([0, pmax], [H - m.b, m.t]);
  const band = x(1) - x(0);
  const gap = band >= 6 ? 2 : band >= 3 ? 1 : 0;
  const bw = Math.max(1, band - gap);
  const colorFor = (seats) => {
    if (seats >= needed) return 'var(--dem)';
    if (total - seats >= needed) return 'var(--rep)';
    return 'var(--tossup)';
  };
  const svg = svgEl('svg', {
    class: 'chart hist', viewBox: `0 0 ${w} ${H}`, width: w, height: H, role: 'img',
    'aria-label': `Distribution of Democratic electoral votes across simulations; 270 to win`,
  });
  svg.append(svgEl('line', { class: 'axis', x1: m.l, x2: w - m.r, y1: H - m.b + 0.5, y2: H - m.b + 0.5 }));
  for (const b of bins) {
    const top = y(b.p);
    svg.append(svgEl('rect', {
      x: x(b.seats - 0.5) + gap / 2, y: top, width: bw, height: Math.max(0.5, H - m.b - top),
      fill: colorFor(b.seats), rx: bw > 3 ? 1.5 : 0,
    }));
  }
  const nx = x(needed - 0.5);
  svg.append(svgEl('line', { class: 'ref', x1: nx, x2: nx, y1: m.t - 8, y2: H - m.b }));
  svg.append(svgEl('text', { class: 'ref-label', x: nx, y: m.t - 10, 'text-anchor': 'middle' }, `${needed}`));
  const tickVals = niceTicks(s0, s1, Math.max(2, Math.floor((w - m.l - m.r) / 70)));
  for (const t of tickVals) {
    if (t < s0 || t > s1) continue;
    if (Math.abs(x(t) - x(needed - 0.5)) < 18) continue;
    svg.append(svgEl('text', { class: 'tick', x: x(t), y: H - 4, 'text-anchor': 'middle' }, fmt.num(t)));
  }
  svg.append(svgEl('text', { class: 'tick', x: x(needed - 0.5), y: H - 4, 'text-anchor': 'middle' }, fmt.num(needed)));
  for (const b of bins) {
    const hit = svgEl('rect', { class: 'hit', x: x(b.seats - 0.5), y: m.t - 8, width: band, height: H - m.t - m.b + 8 });
    attachTooltip(hit, () => tipContent(`${fmt.num(b.seats)} Democratic electoral votes`, [
      ['Share of simulations', fmt.pct(b.p, b.p < 0.01 ? 1 : 0)],
      ['Outcome', b.seats >= needed ? 'Democratic win' : total - b.seats >= needed ? 'Republican win' : '269–269 tie (House decides)'],
    ]));
    svg.append(hit);
  }
  return svg;
}

// ---------------------------------------------------------------------------
// Trend + electoral-vote buckets
// ---------------------------------------------------------------------------

function renderTrend() {
  const root = document.getElementById('pres-trend');
  const mode = S.view === 'evs' ? 'evs' : 'control';
  const history = (Array.isArray(S.summary.history) ? S.summary.history : []).filter((d) => d && parseDate(d.date));
  history.sort((a, b) => parseDate(a.date) - parseDate(b.date));
  root.replaceChildren();
  root.append(
    h('h2', {}, mode === 'evs' ? 'Democratic electoral votes over time' : 'Chance of a Democratic win over time'),
    h('p', { class: 'card-sub' }, mode === 'evs'
      ? 'Expected Democratic electoral votes after the election, per model run'
      : 'One point per model run'),
  );
  if (!history.length) {
    root.append(h('p', { class: 'muted' }, 'No model history yet.'));
    return;
  }
  const box = h('div', { class: 'chart-box' });
  root.append(box);
  responsiveChart(box, (w) => drawTrend(w, history, mode));
  if (history.length < 3) {
    root.append(h('p', { class: 'chart-note' }, `${history.length} model run${history.length === 1 ? '' : 's'} so far — the trend accumulates as the model runs.`));
  }
}

function drawTrend(w, history, mode) {
  const H = 232, m = { t: 14, r: 96, b: 30, l: 40 };
  const val = (d) => {
    if (!d.president) return null;
    return mode === 'evs' ? d.president.dem_seats / TOTAL_EV : d.president.p_dem;
  };
  const raw = (d) => (d.president ? d.president.dem_seats : null);
  const times = history.map((d) => parseDate(d.date).getTime());
  let t0 = Math.min(...times), t1 = Math.max(...times);
  if (t1 - t0 < 6 * 864e5) {
    const mid = (t0 + t1) / 2;
    t0 = mid - 3 * 864e5;
    t1 = mid + 3 * 864e5;
  }
  const x = scaleLinear([t0, t1], [m.l, w - m.r]);
  const y = scaleLinear([0, 1], [H - m.b, m.t]);
  const color = isDark() ? '#3987e5' : '#2a78d6';
  const svg = svgEl('svg', {
    class: 'chart trend', viewBox: `0 0 ${w} ${H}`, width: w, height: H, role: 'img',
    'aria-label': mode === 'evs' ? 'Expected Democratic electoral votes over time' : 'Chance of a Democratic presidential win over time',
  });
  for (const v of [0, 0.25, 0.5, 0.75, 1]) {
    svg.append(svgEl('line', { class: v === 0.5 ? 'axis' : 'grid', x1: m.l, x2: w - m.r, y1: y(v), y2: y(v) }));
    svg.append(svgEl('text', { class: 'tick', x: m.l - 6, y: y(v) + 4, 'text-anchor': 'end' },
      mode === 'evs' ? fmt.num(Math.round(v * TOTAL_EV)) : `${Math.round(v * 100)}%`));
  }
  const xt = dateTicks(t0, t1, Math.max(2, Math.floor((w - m.l - m.r) / 90)));
  for (const t of xt) {
    svg.append(svgEl('text', { class: 'tick', x: x(t), y: H - m.b + 18, 'text-anchor': 'middle' },
      new Date(t).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })));
  }
  const pts = history.map((d, i) => ({ t: times[i], v: val(d), ev: raw(d) })).filter((p) => isNum(p.v));
  if (pts.length > 1) {
    const d = pts.map((p, i) => `${i ? 'L' : 'M'}${x(p.t).toFixed(1)} ${y(p.v).toFixed(1)}`).join(' ');
    svg.append(svgEl('path', { class: 'series', d, stroke: color }));
  }
  const markers = pts.length <= 40 ? pts : [pts[pts.length - 1]];
  for (const p of markers) svg.append(svgEl('circle', { class: 'marker', cx: x(p.t), cy: y(p.v), r: 4, fill: color }));
  if (pts.length) {
    const last = pts[pts.length - 1];
    const label = mode === 'evs' ? `${fmt.num(Math.round(last.ev))} EVs` : fmt.pct(last.v);
    svg.append(svgEl('text', { class: 'label', x: x(last.t) + 14, y: y(last.v) + 4 }, label));
  }
  const cross = svgEl('line', { class: 'crosshair', y1: m.t, y2: H - m.b, x1: 0, x2: 0, visibility: 'hidden' });
  const overlay = svgEl('rect', { class: 'hit', x: m.l, y: m.t, width: Math.max(1, w - m.l - m.r), height: H - m.t - m.b });
  overlay.addEventListener('pointermove', (e) => {
    const rect = svg.getBoundingClientRect();
    const px = (e.clientX - rect.left) * (w / rect.width);
    const t = x.invert(px);
    let best = 0;
    for (let i = 1; i < times.length; i++) if (Math.abs(times[i] - t) < Math.abs(times[best] - t)) best = i;
    const xx = x(times[best]);
    cross.setAttribute('x1', xx);
    cross.setAttribute('x2', xx);
    cross.setAttribute('visibility', 'visible');
    const d = history[best];
    const rows = [];
    if (d.president) {
      rows.push(['D win', `${fmt.pct(d.president.p_dem)} · ${fmt.num(Math.round(d.president.dem_seats))} EVs`, color]);
    }
    tooltip.show(tipContent(fmt.date(d.date), rows), e.clientX, e.clientY);
  });
  overlay.addEventListener('pointerleave', () => { cross.setAttribute('visibility', 'hidden'); tooltip.hide(); });
  svg.append(cross, overlay);
  return svg;
}

/** Electoral votes by rating bucket plus the tipping-point state. */
function renderBuckets() {
  const root = document.getElementById('pres-path');
  root.replaceChildren();
  root.append(h('h2', {}, 'Path to 270'), h('p', { class: 'card-sub' }, 'Electoral votes by rating, and the state that tips the College'));
  const evs = {};
  for (const r of S.races) {
    if (!isNum(r.evs)) continue;
    evs[r.label] = (evs[r.label] || 0) + r.evs;
  }
  const order = [...LABELS];
  const bar = h('div', { class: 'ev-stack', role: 'img', 'aria-label': 'Electoral votes by rating' });
  for (const lab of order) {
    const n = evs[lab] || 0;
    if (!n) continue;
    const seg = h('span', { class: 'seg', style: { width: `${(n / TOTAL_EV) * 100}%`, background: probColor(ratingP(lab)) }, title: `${lab}: ${n} EVs` });
    attachTooltip(seg, () => tipContent(lab, [['Electoral votes', fmt.num(n)]]));
    bar.append(seg);
  }
  const marker = h('span', { class: 'win-line', style: { left: `${(NEEDED_EV / TOTAL_EV) * 100}%` }, title: '270 to win' });
  const wrap = h('div', { class: 'ev-stack-wrap' }, bar, marker);
  root.append(wrap);
  const legend = h('div', { class: 'legend' }, order.filter((l) => evs[l]).map((l) =>
    h('span', { class: 'legend-item' }, h('span', { class: 'legend-swatch', style: { background: probColor(ratingP(l)) } }), `${l} ${fmt.num(evs[l])}`)));
  root.append(legend);
  // Tipping point: order states D→R by margin, find where cumulative D EVs cross 270.
  const ranked = S.races.filter((r) => isNum(r.margin) && isNum(r.evs)).sort((a, b) => b.margin - a.margin);
  let cum = 0, tip = null;
  for (const r of ranked) {
    cum += r.evs;
    if (cum >= NEEDED_EV) { tip = r; break; }
  }
  if (tip) {
    root.append(h('p', { class: 'chart-note' },
      `Tipping point: ${tip.state_name || tip.state} (${fmt.margin(tip.margin)}, ${fmt.num(tip.evs)} EVs) — the state that puts the Democrat over 270 when states are ordered by margin.`));
  }
}

// ---------------------------------------------------------------------------
// Map, table, closest
// ---------------------------------------------------------------------------

function stateTip(r) {
  if (!r) return null;
  const rows = [
    ['Electoral votes', fmt.num(r.evs)],
    ['D win', fmt.pct(r.p_dem)],
    ['Model margin', fmt.margin(r.margin)],
    ['2024 winner', r.prev === 'D' ? 'Democrat' : r.prev === 'R' ? 'Republican' : DASH],
  ];
  if (r.rating && r.rating.label) rows.push(['Experts', r.rating.label]);
  if (r.polls && isNum(r.polls.margin)) rows.push(['Polls', `${fmt.margin(r.polls.margin)} (n=${fmt.num(r.polls.n)})`]);
  return tipContent(r.state_name || r.state, rows);
}

function renderMap() {
  const box = document.getElementById('pres-map');
  box.replaceChildren();
  responsiveChart(box, (w) => drawTileMap(w));
  const ramp = h('span', { class: 'ramp', 'aria-hidden': 'true' });
  ramp.style.background = probGradient();
  onThemeChange(() => { ramp.style.background = probGradient(); });
  document.getElementById('pres-map-legend').replaceChildren(
    h('div', { class: 'legend' },
      h('span', { class: 'legend-ramp' }, 'Safe R', ramp, 'Safe D'),
      h('span', { class: 'legend-item' }, 'Gray = toss-up'),
      h('span', { class: 'legend-item' }, 'Number = electoral votes')));
}

function drawTileMap(w) {
  const cols = PRES_GRID[0].length, rowsN = PRES_GRID.length, gap = 3;
  const tile = clamp(Math.floor((w - gap * (cols - 1)) / cols), 22, 56);
  const W = cols * tile + (cols - 1) * gap, H = rowsN * tile + (rowsN - 1) * gap;
  const byState = new Map(S.races.map((r) => [r.state, r]));
  const svg = svgEl('svg', {
    class: 'chart tile-map', viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: 'group',
    'aria-label': 'Map of 2028 presidential races by state, coloured by the chance of a Democratic win',
  });
  const fs = Math.max(9, Math.round(tile * 0.3));
  PRES_GRID.forEach((row, ri) => row.forEach((st, ci) => {
    if (!st) return;
    const r = byState.get(st);
    const x0 = ci * (tile + gap), y0 = ri * (tile + gap);
    const g = svgEl('g', { role: 'img', 'aria-label': r ? `${r.state_name || st}: ${fmt.pct(r.p_dem)} chance of a Democratic win, ${fmt.num(r.evs)} electoral votes` : `${st}: no data` });
    const link = r ? svgEl('a', { href: presRaceHref(r.race_id) }) : null;
    const target = link || g;
    target.append(svgEl('rect', { class: 'tile', x: x0, y: y0, width: tile, height: tile, rx: 3, fill: probColor(r ? r.p_dem : null) }));
    const ink = textOn(probColor(r ? r.p_dem : null));
    target.append(svgEl('text', {
      x: x0 + tile / 2, y: y0 + tile / 2 - 2, 'text-anchor': 'middle', 'dominant-baseline': 'central',
      'font-size': fs, fill: ink,
    }, st));
    if (r && isNum(r.evs)) {
      target.append(svgEl('text', {
        x: x0 + tile / 2, y: y0 + tile / 2 + fs * 0.75, 'text-anchor': 'middle', 'dominant-baseline': 'central',
        'font-size': Math.max(8, fs - 3), fill: ink,
      }, fmt.num(r.evs)));
    }
    if (link) {
      attachTooltip(link, () => stateTip(r));
      g.append(link);
    } else {
      attachTooltip(g, () => tipContent(st, [['2028', 'No forecast']]));
    }
    svg.append(g);
  }));
  return svg;
}

function flipVs2024(r) {
  if (!isNum(r.p_dem) || (r.prev !== 'D' && r.prev !== 'R')) return null;
  return r.prev === 'R' ? r.p_dem : 1 - r.p_dem;
}

function renderTable() {
  const root = document.getElementById('pres-table-block');
  const rows = S.races.slice().sort((a, b) =>
    Math.abs((isNum(a.p_dem) ? a.p_dem : 1) - 0.5) - Math.abs((isNum(b.p_dem) ? b.p_dem : 1) - 0.5));
  const tbody = h('tbody');
  for (const r of rows) {
    const flip = flipVs2024(r);
    tbody.append(h('tr', {},
      h('td', {}, h('a', { href: presRaceHref(r.race_id) }, h('b', {}, r.state_name || r.state))),
      h('td', { class: 'num' }, fmt.num(r.evs)),
      h('td', {}, h('span', { class: `party-dot ${partyClass(r.prev)}`, 'aria-hidden': 'true' }), r.prev || DASH),
      h('td', { class: 'num' }, r.pvi_label || (isNum(r.pvi) ? fmt.margin(r.pvi, 0) : DASH)),
      h('td', {}, r.rating && r.rating.label ? ratingPill(r.rating.label) : DASH),
      h('td', { class: 'num' }, r.polls && isNum(r.polls.margin) ? `${fmt.margin(r.polls.margin)} ` : DASH,
        r.polls && isNum(r.polls.margin) ? h('span', { class: 'muted' }, `(n=${fmt.num(r.polls.n)})`) : null),
      h('td', { class: 'num' }, fmt.margin(r.margin)),
      h('td', { class: 'num' }, probChip(r.p_dem)),
      h('td', { class: 'num' }, fmt.pct(flip)),
    ));
  }
  root.replaceChildren(
    h('div', { class: 'card' },
      h('h3', {}, 'All 51 contests'),
      h('p', { class: 'card-sub' }, 'Ordered by closeness. Flip: chance the jurisdiction votes differently than in 2024.'),
      h('div', { class: 'table-wrap' },
        h('table', { class: 'data' },
          h('thead', {}, h('tr', {},
            h('th', { scope: 'col' }, 'State'), h('th', { scope: 'col', class: 'num' }, 'EVs'),
            h('th', { scope: 'col' }, '2024'), h('th', { scope: 'col', class: 'num' }, 'PVI'),
            h('th', { scope: 'col' }, 'Rating'), h('th', { scope: 'col', class: 'num' }, 'Polls'),
            h('th', { scope: 'col', class: 'num' }, 'Model'), h('th', { scope: 'col', class: 'num' }, 'D win'),
            h('th', { scope: 'col', class: 'num' }, 'Flip'))),
          tbody))));
}

function renderClosest() {
  const root = document.getElementById('pres-closest');
  const list = S.races.filter((r) => isNum(r.p_dem)).sort((a, b) => Math.abs(a.p_dem - 0.5) - Math.abs(b.p_dem - 0.5)).slice(0, 8);
  if (!list.length) {
    root.append(h('p', { class: 'muted' }, 'No races found.'));
    return;
  }
  root.replaceChildren(...list.map((r) => {
    const pR = 1 - r.p_dem;
    return h('a', { class: 'race-card', href: presRaceHref(r.race_id), 'aria-label': `${r.state_name || r.state}: ${fmt.pct(r.p_dem)} chance of a Democratic win` },
      h('div', { class: 'title' }, h('span', {}, `${r.state_name || r.state} · ${fmt.num(r.evs)} EVs`), ratingPill(r.label)),
      h('div', { class: 'cands' }, matchupNode(r, { short: true })),
      splitBar(r.p_dem, pR, 0),
      h('div', { class: 'pct' }, h('span', {}, h('b', {}, fmt.pct(r.p_dem)), ' D'), h('span', {}, h('b', {}, fmt.pct(pR)), ' R')));
  }));
}

main();
