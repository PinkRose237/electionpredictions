/**
 * app.js — the dashboard (index.html).
 *
 * Loads summary.json + races.json, then renders:
 *   chamber cards (control odds, seat ranges, histograms, market lines)
 *   generic-ballot panel, control-probability trend chart
 *   chamber tabs: tile map / seat grid + sortable, filterable race table
 *   closest-races strip, model-vs-markets scatter, footer metadata
 */
import {
  CHAMBERS, CHAMBER_LABEL, CHAMBER_SINGULAR, LABELS, COMPETITIVE, STATE_NAMES, STATE_GRID, DASH,
  loadJSON, raceHref, fmt, isNum, clamp, parseDate,
  isDark, onThemeChange, probColor, probGradient, textOn, paintProb,
  h, svgEl, scaleLinear, niceTicks, dateTicks, responsiveChart,
  tooltip, tipContent, attachTooltip, delegateTooltip,
  ratingPill, probChip, matchupNode, holderNode,
  initChrome, renderUpdated, renderFooterMeta, showError,
} from './common.js';

/** Categorical hues for the three chambers (validated for CVD separation in each mode). */
const SERIES_LIGHT = { house: '#2a78d6', senate: '#1baf7a', governor: '#eb6834' };
const SERIES_DARK = { house: '#3987e5', senate: '#199e70', governor: '#d95926' };
const seriesColor = (ch) => (isDark() ? SERIES_DARK : SERIES_LIGHT)[ch];

/** Page state. */
const S = {
  summary: null,
  races: [],
  byChamber: { house: [], senate: [], governor: [] },
  byId: new Map(),
  built: new Set(),
  view: 'control',
};

try {
  const saved = localStorage.getItem('chamber-view');
  if (saved === 'seats' || saved === 'control') S.view = saved;
} catch (e) { /* storage unavailable */ }

/** Expected seat share (0–1) for a chamber forecast, or nulls when missing. */
function seatShare(ch) {
  const dMean = ch && ch.dem_seats && ch.dem_seats.mean;
  const rMean = ch && ch.rep_seats && ch.rep_seats.mean;
  const total = ch && ch.total;
  if (!isNum(dMean) || !isNum(rMean) || !isNum(total) || total <= 0) {
    return { dMean: null, rMean: null, total: isNum(total) ? total : null, dShare: null, rShare: null, nShare: null };
  }
  const dShare = dMean / total;
  const rShare = rMean / total;
  return { dMean, rMean, total, dShare, rShare, nShare: Math.max(0, 1 - dShare - rShare) };
}

async function main() {
  initChrome({ current: 'dashboard' });
  const status = document.getElementById('status');
  try {
    const [summary, races] = await Promise.all([loadJSON('summary.json'), loadJSON('races.json')]);
    S.summary = summary || {};
    S.races = Array.isArray(races) ? races : [];
    for (const r of S.races) {
      if (S.byChamber[r.chamber]) S.byChamber[r.chamber].push(r);
      S.byId.set(r.race_id, r);
    }
    status.hidden = true;
    document.getElementById('dashboard').hidden = false;
    renderUpdated(S.summary);
    renderFooterMeta(S.summary);
    initChamberView();
    renderChambers(S.summary);
    renderOverview(S.summary);
    renderGeneric(S.summary);
    renderTrend(S.summary);
    initTabs();
    renderClosest();
    renderScatter();
  } catch (err) {
    console.error(err);
    showError(status, err, 'Run the pipeline to generate site/data, or open ?data=_fixture to use the development fixture.');
  }
}

// ---------------------------------------------------------------------------
// Chamber cards
// ---------------------------------------------------------------------------

/** Two paragraphs on where things stand plus key factors, when the pipeline produced them. */
function renderOverview(summary) {
  const root = document.getElementById('overview');
  const o = summary && summary.overview;
  if (!root || !o || !o.summary) return;
  root.hidden = false;
  root.replaceChildren(h('h2', {}, 'Where things stand'));
  for (const para of String(o.summary).split(/\n\s*\n/).map((t) => t.trim()).filter(Boolean)) root.append(h('p', {}, para));
  const chambers = o.chambers || {};
  const lines = ['house', 'senate', 'governor'].filter((k) => chambers[k]);
  if (lines.length) root.append(h('dl', { class: 'overview-chambers' }, ...lines.flatMap((k) => [h('dt', {}, CHAMBER_LABEL[k]), h('dd', {}, chambers[k])])));
  if (Array.isArray(o.key_factors) && o.key_factors.length) {
    root.append(h('h3', { class: 'sub-h' }, 'Key factors'), h('ul', { class: 'model-notes factors' }, ...o.key_factors.map((f) => h('li', {}, String(f)))));
  }
}

function renderChambers(summary) {
  const root = document.getElementById('chambers');
  const chambers = summary.chambers || {};
  root.replaceChildren(...CHAMBERS.map((key) => chamberCard(key, chambers[key], S.view)));
}

/** Segmented control switching the chamber cards + trend between control odds and seat share. */
function initChamberView() {
  const root = document.getElementById('chamber-view');
  if (!root) return;
  const btns = [...root.querySelectorAll('button[data-view]')];
  const paint = () => {
    for (const b of btns) b.setAttribute('aria-pressed', b.dataset.view === S.view ? 'true' : 'false');
  };
  for (const b of btns) {
    b.addEventListener('click', () => {
      if (S.view === b.dataset.view) return;
      S.view = b.dataset.view;
      try { localStorage.setItem('chamber-view', S.view); } catch (e) { /* storage unavailable */ }
      paint();
      renderChambers(S.summary);
      renderTrend(S.summary);
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

function chamberCard(key, ch, view) {
  const card = h('article', { class: 'card chamber-card', 'aria-label': `${CHAMBER_LABEL[key]} forecast` });
  if (!ch) {
    card.append(h('h2', {}, CHAMBER_LABEL[key]), h('p', { class: 'muted' }, 'No forecast data.'));
    return card;
  }
  card.append(
    h('header', {},
      h('h2', {}, ch.label || CHAMBER_LABEL[key]),
      h('span', { class: 'sub' }, `${fmt.num(ch.seats_up)} of ${fmt.num(ch.total)} seats up`, h('br'), `${fmt.num(ch.needed)} for control`)),
  );
  if (view === 'seats') {
    const { dMean, rMean, total, dShare, rShare, nShare } = seatShare(ch);
    const otherMean = isNum(total) && isNum(dMean) && isNum(rMean) ? Math.max(0, total - dMean - rMean) : null;
    const probs = h('div', { class: 'control-probs' },
      h('div', { class: 'side dem' },
        h('div', { class: 'big', style: { color: 'var(--dem)' } }, fmt.dec(dMean, 1)),
        h('div', { class: 'lbl' }, h('span', { class: 'party-dot dem', 'aria-hidden': 'true' }), `Dem seats · ${fmt.pct(dShare)}`)),
      h('div', { class: 'side rep' },
        h('div', { class: 'big', style: { color: 'var(--rep)' } }, fmt.dec(rMean, 1)),
        h('div', { class: 'lbl' }, h('span', { class: 'party-dot rep', 'aria-hidden': 'true' }), `Rep seats · ${fmt.pct(rShare)}`)),
    );
    if (isNum(otherMean) && otherMean > 0.05) probs.append(h('div', { class: 'neither' }, `Other / no-party majority: ${fmt.dec(otherMean, 1)} seats`));
    card.append(probs, splitBar(dShare, rShare, nShare,
      `Democrats ${fmt.dec(dMean, 1)} seats (${fmt.pct(dShare)}), Republicans ${fmt.dec(rMean, 1)} seats (${fmt.pct(rShare)})`));
  } else {
    const pD = ch.p_dem, pR = ch.p_rep, pN = ch.p_neither;
    const probs = h('div', { class: 'control-probs' },
      h('div', { class: 'side dem' },
        h('div', { class: 'big', style: { color: 'var(--dem)' } }, fmt.pct(pD)),
        h('div', { class: 'lbl' }, h('span', { class: 'party-dot dem', 'aria-hidden': 'true' }), 'Democratic control')),
      h('div', { class: 'side rep' },
        h('div', { class: 'big', style: { color: 'var(--rep)' } }, fmt.pct(pR)),
        h('div', { class: 'lbl' }, h('span', { class: 'party-dot rep', 'aria-hidden': 'true' }), 'Republican control')),
    );
    if (isNum(pN) && pN > 0.005) probs.append(h('div', { class: 'neither' }, `Neither party outright (independents decide): ${fmt.pct(pN)}`));
    card.append(probs, splitBar(pD, pR, pN));
  }
  if (key === 'senate') card.append(h('p', { class: 'note' }, '51 needed; the Vice President breaks ties for Republicans.'));

  const cur = ch.current || {};
  const flips = ch.expected_flips || {};
  const seatRange = (s) => (s ? h('span', {}, fmt.dec(s.mean, 1), ' ', h('span', { class: 'range' }, `(${fmt.num(s.p10)}–${fmt.num(s.p90)})`)) : DASH);
  card.append(
    h('dl', { class: 'stats' },
      h('div', {}, h('dt', {}, 'Expected D seats', h('span', { class: 'muted' }, ' · 80% range')), h('dd', {}, seatRange(ch.dem_seats))),
      h('div', {}, h('dt', {}, 'Expected R seats', h('span', { class: 'muted' }, ' · 80% range')), h('dd', {}, seatRange(ch.rep_seats))),
      h('div', {}, h('dt', {}, 'Current'), h('dd', {}, `D ${fmt.num(cur.D)} · R ${fmt.num(cur.R)}`, isNum(cur.other) && cur.other > 0 ? ` · ${fmt.num(cur.other)} other` : '')),
      h('div', {}, h('dt', {}, 'Expected pickups'), h('dd', {}, `D ${fmt.dec(flips.D, 1)} · R ${fmt.dec(flips.R, 1)}`)),
    ),
  );

  const box = h('div', { class: 'chart-box' });
  card.append(
    h('div', { class: 'hist-caption' }, h('span', {}, 'Democratic seats across simulations'), h('span', {}, `Majority line: ${fmt.num(ch.needed)}`)),
    box,
  );
  responsiveChart(box, (w) => drawHistogram(w, key, ch));

  if (Array.isArray(ch.markets) && ch.markets.length) {
    const line = h('p', { class: 'markets-line' }, 'Markets (D control): ');
    ch.markets.forEach((mk, i) => {
      if (i) line.append(' · ');
      const text = `${fmt.platform(mk.platform)} ${fmt.pct(mk.p_dem)}`;
      line.append(mk.url ? h('a', { href: mk.url, target: '_blank', rel: 'noopener' }, text) : text);
    });
    card.append(line);
  }
  return card;
}

/** Compact histogram of Democratic seat totals with the majority line. */
function drawHistogram(w, key, ch) {
  const bins = (ch.histogram || []).filter((b) => isNum(b.seats) && isNum(b.p) && b.p > 0);
  if (!bins.length) return h('p', { class: 'muted small' }, 'No simulation output.');
  const H = 104, m = { t: 20, r: 6, b: 18, l: 6 };
  const needed = isNum(ch.needed) ? ch.needed : null;
  const total = isNum(ch.total) ? ch.total : null;
  let s0 = Math.min(...bins.map((b) => b.seats)), s1 = Math.max(...bins.map((b) => b.seats));
  if (needed != null) { s0 = Math.min(s0, needed - 1); s1 = Math.max(s1, needed + 1); }
  const x = scaleLinear([s0 - 0.5, s1 + 0.5], [m.l, w - m.r]);
  const pmax = Math.max(...bins.map((b) => b.p));
  const y = scaleLinear([0, pmax], [H - m.b, m.t]);
  const band = x(1) - x(0);
  const gap = band >= 6 ? 2 : band >= 3 ? 1 : 0;
  const bw = Math.max(1, band - gap);
  const rNeeded = key === 'senate' ? 50 : needed;
  const colorFor = (seats) => {
    if (needed != null && seats >= needed) return 'var(--dem)';
    if (rNeeded != null && total != null && total - seats >= rNeeded) return 'var(--rep)';
    return 'var(--tossup)';
  };
  const svg = svgEl('svg', {
    class: 'chart hist', viewBox: `0 0 ${w} ${H}`, width: w, height: H, role: 'img',
    'aria-label': `Distribution of Democratic ${key === 'governor' ? 'governorships' : 'seats'} across simulations; majority at ${needed}`,
  });
  svg.append(svgEl('line', { class: 'axis', x1: m.l, x2: w - m.r, y1: H - m.b + 0.5, y2: H - m.b + 0.5 }));
  for (const b of bins) {
    const top = y(b.p);
    svg.append(svgEl('rect', {
      x: x(b.seats - 0.5) + gap / 2, y: top, width: bw, height: Math.max(0.5, H - m.b - top),
      fill: colorFor(b.seats), rx: bw > 3 ? 1.5 : 0,
    }));
  }
  if (needed != null) {
    const nx = x(needed - 0.5);
    svg.append(svgEl('line', { class: 'ref', x1: nx, x2: nx, y1: m.t - 8, y2: H - m.b }));
    svg.append(svgEl('text', { class: 'ref-label', x: nx, y: m.t - 10, 'text-anchor': 'middle' }, `${needed}`));
  }
  const tickVals = niceTicks(s0, s1, Math.max(2, Math.floor((w - m.l - m.r) / 70)));
  for (const t of tickVals) {
    if (t < s0 || t > s1) continue;
    if (needed != null && Math.abs(x(t) - x(needed - 0.5)) < 18) continue;
    svg.append(svgEl('text', { class: 'tick', x: x(t), y: H - 4, 'text-anchor': 'middle' }, fmt.num(t)));
  }
  if (needed != null) svg.append(svgEl('text', { class: 'tick', x: x(needed - 0.5), y: H - 4, 'text-anchor': 'middle' }, fmt.num(needed)));
  // hover targets: one per bin, full height
  const binByLeft = new Map();
  for (const b of bins) {
    const hit = svgEl('rect', { class: 'hit', x: x(b.seats - 0.5), y: m.t - 8, width: band, height: H - m.t - m.b + 8 });
    attachTooltip(hit, () => tipContent(`${fmt.num(b.seats)} Democratic ${key === 'governor' ? 'governors' : 'seats'}`, [
      ['Share of simulations', fmt.pct(b.p, b.p < 0.01 ? 1 : 0)],
      ['Outcome', needed != null && b.seats >= needed ? 'Democratic control' : rNeeded != null && total != null && total - b.seats >= rNeeded ? 'Republican control' : 'Neither party outright'],
    ]));
    svg.append(hit);
    binByLeft.set(b.seats, hit);
  }
  return svg;
}

// ---------------------------------------------------------------------------
// Generic ballot + trend
// ---------------------------------------------------------------------------

function marginColor(m) {
  if (!isNum(m) || Math.abs(m) < 0.05) return 'var(--ink)';
  return m > 0 ? 'var(--dem)' : 'var(--rep)';
}

function renderGeneric(summary) {
  const root = document.getElementById('generic');
  const gb = summary.generic_ballot || {};
  root.append(
    h('h2', {}, 'Generic ballot'),
    h('p', { class: 'card-sub' }, 'National House vote preference, averaged across published averages'),
    h('div', { class: 'generic-big', style: { color: marginColor(gb.margin) } }, fmt.margin(gb.margin)),
    h('div', { class: 'generic-sub' }, `Democrats ${fmt.pts(gb.dem)} · Republicans ${fmt.pts(gb.rep)}`),
  );
  const sources = Array.isArray(gb.sources) ? gb.sources : [];
  if (!sources.length) {
    root.append(h('p', { class: 'muted small' }, 'No source averages available.'));
    return;
  }
  root.append(
    h('div', { class: 'table-wrap' },
      h('table', { class: 'data' },
        h('thead', {}, h('tr', {},
          h('th', { scope: 'col' }, 'Source'), h('th', { scope: 'col' }, 'As of'),
          h('th', { scope: 'col', class: 'num' }, 'D'), h('th', { scope: 'col', class: 'num' }, 'R'), h('th', { scope: 'col', class: 'num' }, 'Margin'))),
        h('tbody', {}, sources.map((s) => h('tr', {},
          h('td', {}, s.source || DASH), h('td', {}, s.as_of ? fmt.dateShort(s.as_of) : DASH),
          h('td', { class: 'num' }, fmt.dec(s.dem, 1)), h('td', { class: 'num' }, fmt.dec(s.rep, 1)),
          h('td', { class: 'num' }, h('b', {}, fmt.margin(s.margin)))))))),
  );
}

function renderTrend(summary) {
  const root = document.getElementById('trend');
  const mode = S.view === 'seats' ? 'seats' : 'control';
  const totals = {};
  for (const ch of CHAMBERS) totals[ch] = summary.chambers && summary.chambers[ch] ? summary.chambers[ch].total : null;
  const history = (Array.isArray(summary.history) ? summary.history : []).filter((d) => d && parseDate(d.date));
  history.sort((a, b) => parseDate(a.date) - parseDate(b.date));
  root.replaceChildren();
  root.append(
    h('h2', {}, mode === 'seats' ? 'Democratic seat share over time' : 'Chance of Democratic control over time'),
    h('p', { class: 'card-sub' }, mode === 'seats'
      ? 'Expected share of seats for Democrats after the election, per daily model run'
      : 'One point per daily model run'),
  );
  if (!history.length) {
    root.append(h('p', { class: 'muted' }, 'No model history yet.'));
    return;
  }
  const box = h('div', { class: 'chart-box' });
  root.append(box);
  responsiveChart(box, (w) => drawTrend(w, history, mode, totals));
  const legend = h('div', { class: 'legend' }, CHAMBERS.map((ch) => {
    const key = h('span', { class: 'legend-line' });
    key.style.background = seriesColor(ch);
    onThemeChange(() => { key.style.background = seriesColor(ch); });
    return h('span', { class: 'legend-item' }, key, CHAMBER_LABEL[ch]);
  }));
  root.append(legend);
  if (history.length < 3) {
    root.append(h('p', { class: 'chart-note' }, `${history.length} model run${history.length === 1 ? '' : 's'} so far — the trend accumulates as the model runs daily.`));
  }
}

function drawTrend(w, history, mode = 'control', totals = {}) {
  const H = 232, m = { t: 14, r: 104, b: 30, l: 40 };
  const valueOf = (d, ch) => {
    if (!d[ch]) return null;
    if (mode === 'seats') {
      const seats = d[ch].dem_seats, total = totals[ch];
      return isNum(seats) && isNum(total) && total > 0 ? seats / total : null;
    }
    return d[ch].p_dem;
  };
  const seatsOf = (d, ch) => (d[ch] ? d[ch].dem_seats : null);
  const times = history.map((d) => parseDate(d.date).getTime());
  let t0 = Math.min(...times), t1 = Math.max(...times);
  if (t1 - t0 < 6 * 864e5) {
    const mid = (t0 + t1) / 2;
    t0 = mid - 3 * 864e5;
    t1 = mid + 3 * 864e5;
  }
  const x = scaleLinear([t0, t1], [m.l, w - m.r]);
  const y = scaleLinear([0, 1], [H - m.b, m.t]);
  const svg = svgEl('svg', {
    class: 'chart trend', viewBox: `0 0 ${w} ${H}`, width: w, height: H, role: 'img',
    'aria-label': mode === 'seats'
      ? 'Expected Democratic share of House, Senate and governorship seats over time'
      : 'Probability of Democratic control of the House, Senate and governorships over time',
  });
  for (const v of [0, 0.25, 0.5, 0.75, 1]) {
    svg.append(svgEl('line', { class: v === 0.5 ? 'axis' : 'grid', x1: m.l, x2: w - m.r, y1: y(v), y2: y(v) }));
    svg.append(svgEl('text', { class: 'tick', x: m.l - 6, y: y(v) + 4, 'text-anchor': 'end' }, `${Math.round(v * 100)}%`));
  }
  const xt = dateTicks(t0, t1, Math.max(2, Math.floor((w - m.l - m.r) / 90)));
  for (const t of xt) {
    svg.append(svgEl('text', { class: 'tick', x: x(t), y: H - m.b + 18, 'text-anchor': 'middle' },
      new Date(t).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })));
  }
  const ends = [];
  for (const ch of CHAMBERS) {
    const pts = history.map((d, i) => ({ t: times[i], v: valueOf(d, ch) })).filter((p) => isNum(p.v));
    if (!pts.length) continue;
    const color = seriesColor(ch);
    if (pts.length > 1) {
      const d = pts.map((p, i) => `${i ? 'L' : 'M'}${x(p.t).toFixed(1)} ${y(p.v).toFixed(1)}`).join(' ');
      svg.append(svgEl('path', { class: 'series', d, stroke: color }));
    }
    const markers = pts.length <= 40 ? pts : [pts[pts.length - 1]];
    for (const p of markers) svg.append(svgEl('circle', { class: 'marker', cx: x(p.t), cy: y(p.v), r: 4, fill: color }));
    const last = pts[pts.length - 1];
    ends.push({ ch, color, x: x(last.t), y: y(last.v), ly: y(last.v), text: `${CHAMBER_LABEL[ch]} ${fmt.pct(last.v)}` });
  }
  // End labels: keep at least 15px apart, add a leader line where a label had to move.
  ends.sort((a, b) => a.y - b.y);
  for (let i = 1; i < ends.length; i++) if (ends[i].ly - ends[i - 1].ly < 15) ends[i].ly = ends[i - 1].ly + 15;
  for (let i = ends.length - 2; i >= 0; i--) if (ends[i + 1].ly - ends[i].ly < 15) ends[i].ly = ends[i + 1].ly - 15;
  for (const e of ends) {
    if (Math.abs(e.ly - e.y) > 1) svg.append(svgEl('line', { class: 'grid', x1: e.x + 5, y1: e.y, x2: e.x + 11, y2: e.ly, style: 'stroke: var(--border-strong)' }));
    svg.append(svgEl('text', { class: 'label', x: e.x + 14, y: e.ly + 4 }, e.text));
  }
  // Crosshair + tooltip listing every chamber at the nearest run.
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
    const rows = CHAMBERS.filter((ch) => isNum(valueOf(d, ch)))
      .map((ch) => {
        const v = valueOf(d, ch), seats = seatsOf(d, ch);
        const detail = mode === 'seats'
          ? `${fmt.pct(v)} of seats · ${fmt.dec(seats, 1)} seats`
          : `${fmt.pct(v)} · ${fmt.dec(seats, 1)} seats`;
        return [CHAMBER_LABEL[ch], detail, seriesColor(ch)];
      });
    if (isNum(d.generic)) rows.push(['Generic ballot', fmt.margin(d.generic)]);
    tooltip.show(tipContent(fmt.date(d.date), rows), e.clientX, e.clientY);
  });
  overlay.addEventListener('pointerleave', () => { cross.setAttribute('visibility', 'hidden'); tooltip.hide(); });
  svg.append(cross, overlay);
  return svg;
}

// ---------------------------------------------------------------------------
// Chamber tabs: map + table
// ---------------------------------------------------------------------------

function initTabs() {
  const tablist = document.getElementById('tablist');
  const panels = document.getElementById('panels');
  const tabs = {};
  for (const ch of CHAMBERS) {
    const n = S.byChamber[ch].length;
    const tab = h('button', {
      class: 'tab', role: 'tab', type: 'button', id: `tab-${ch}`, 'aria-selected': 'false', 'aria-controls': `panel-${ch}`, tabindex: '-1',
      onClick: () => selectTab(ch, true),
    }, CHAMBER_LABEL[ch], h('span', { class: 'count' }, fmt.num(n)));
    tabs[ch] = tab;
    tablist.append(tab);
    panels.append(h('div', { id: `panel-${ch}`, role: 'tabpanel', 'aria-labelledby': `tab-${ch}`, hidden: true }));
  }
  tablist.addEventListener('keydown', (e) => {
    const i = CHAMBERS.indexOf(document.activeElement && document.activeElement.id.replace('tab-', ''));
    if (i < 0) return;
    let j = null;
    if (e.key === 'ArrowRight') j = (i + 1) % CHAMBERS.length;
    if (e.key === 'ArrowLeft') j = (i - 1 + CHAMBERS.length) % CHAMBERS.length;
    if (e.key === 'Home') j = 0;
    if (e.key === 'End') j = CHAMBERS.length - 1;
    if (j == null) return;
    e.preventDefault();
    selectTab(CHAMBERS[j], true);
    tabs[CHAMBERS[j]].focus();
  });
  function selectTab(ch, updateHash) {
    for (const c of CHAMBERS) {
      const on = c === ch;
      tabs[c].setAttribute('aria-selected', on ? 'true' : 'false');
      tabs[c].tabIndex = on ? 0 : -1;
      document.getElementById(`panel-${c}`).hidden = !on;
    }
    if (!S.built.has(ch)) {
      S.built.add(ch);
      buildPanel(ch);
    }
    if (updateHash && window.history.replaceState) window.history.replaceState(null, '', `#${ch}`);
  }
  const fromHash = () => {
    const ch = window.location.hash.replace('#', '');
    return CHAMBERS.includes(ch) ? ch : null;
  };
  selectTab(fromHash() || 'house', false);
  window.addEventListener('hashchange', () => { const ch = fromHash(); if (ch) selectTab(ch, false); });
}

function buildPanel(ch) {
  const panel = document.getElementById(`panel-${ch}`);
  const races = S.byChamber[ch];
  const mapCard = h('div', { class: 'card map-card' });
  if (ch === 'house') {
    mapCard.append(
      h('h3', {}, 'All 435 districts'),
      h('p', { class: 'card-sub' }, 'Grouped by state and coloured by the chance a Democrat wins. Hover or focus a seat for details; click to open the race.'),
      seatGrid(races),
    );
  } else {
    const box = h('div', { class: 'chart-box map-wrap' });
    mapCard.append(
      h('h3', {}, `${CHAMBER_LABEL[ch]} races by state`),
      h('p', { class: 'card-sub' }, 'Tiles are coloured by the chance a Democrat wins. Hatched states have no race this year.'),
      box,
    );
    responsiveChart(box, (w) => drawTileMap(w, ch, races));
  }
  mapCard.append(mapLegend(ch !== 'house'));
  panel.append(mapCard, raceTable(ch, races));
}

/** Tooltip body shared by tiles, seats and cards. */
function raceTip(r) {
  if (!r) return null;
  const rows = [
    ['Candidates', r.dem || r.rep ? [r.dem ? `${r.dem.name} (${r.dem.party})` : 'no D', ' vs ', r.rep ? `${r.rep.name} (${r.rep.party})` : 'no R'].join('') : DASH],
    ['D win', fmt.pct(r.p_dem)],
    ['Model margin', fmt.margin(r.margin)],
  ];
  if (r.polls && isNum(r.polls.margin)) rows.push(['Polls', `${fmt.margin(r.polls.margin)} (n=${fmt.num(r.polls.n)})`]);
  if (r.rating && r.rating.label) rows.push(['Experts', r.rating.label]);
  if (r.markets && isNum(r.markets.p_dem)) rows.push(['Markets', fmt.pct(r.markets.p_dem)]);
  const out = tipContent(`${r.name}${r.label ? ` · ${r.label}` : ''}`, rows);
  if (r.uncontested) out.push(h('div', { class: 'tip-note' }, 'Uncontested / same-party general'));
  return out;
}

function mapLegend(showNoRace) {
  const ramp = h('span', { class: 'ramp', 'aria-hidden': 'true' });
  ramp.style.background = probGradient();
  onThemeChange(() => { ramp.style.background = probGradient(); });
  return h('div', { class: 'legend' },
    h('span', { class: 'legend-ramp' }, 'Safe R', ramp, 'Safe D'),
    h('span', { class: 'legend-item' }, 'Gray = toss-up'),
    showNoRace ? h('span', { class: 'legend-item' }, h('span', { class: 'legend-swatch hatch', 'aria-hidden': 'true' }), 'No race in 2026') : null,
  );
}

/** Tile-grid map of the 50 states (Senate / Governors). */
function drawTileMap(w, ch, races) {
  const cols = STATE_GRID[0].length, rows = STATE_GRID.length, gap = 3;
  const tile = clamp(Math.floor((w - gap * (cols - 1)) / cols), 22, 56);
  const W = cols * tile + (cols - 1) * gap, H = rows * tile + (rows - 1) * gap;
  const byState = new Map();
  for (const r of races) {
    if (!byState.has(r.state)) byState.set(r.state, []);
    byState.get(r.state).push(r);
  }
  const svg = svgEl('svg', {
    class: 'chart tile-map', viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: 'group',
    'aria-label': `${CHAMBER_LABEL[ch]} map: one tile per state, coloured by the chance of a Democratic win`,
  });
  const pid = `hatch-${ch}`;
  svg.append(svgEl('defs', {},
    svgEl('pattern', { id: pid, patternUnits: 'userSpaceOnUse', width: 6, height: 6, patternTransform: 'rotate(45)' },
      svgEl('rect', { width: 6, height: 6, style: 'fill: var(--surface-2)' }),
      svgEl('line', { x1: 0, y1: 0, x2: 0, y2: 6, style: 'stroke: var(--border-strong); stroke-width: 1.5' }))));
  const fs = Math.max(9, Math.round(tile * 0.34));
  STATE_GRID.forEach((row, ri) => row.forEach((st, ci) => {
    if (!st) return;
    const x0 = ci * (tile + gap), y0 = ri * (tile + gap);
    const list = (byState.get(st) || []).slice().sort((a, b) => (a.special ? 1 : 0) - (b.special ? 1 : 0));
    if (!list.length) {
      const g = svgEl('g', { role: 'img', 'aria-label': `${STATE_NAMES[st] || st}: no ${CHAMBER_SINGULAR[ch].toLowerCase()} race in 2026` });
      g.append(
        svgEl('rect', { class: 'tile tile-none', x: x0, y: y0, width: tile, height: tile, rx: 3, fill: `url(#${pid})` }),
        svgEl('text', { x: x0 + tile / 2, y: y0 + tile / 2, 'text-anchor': 'middle', 'dominant-baseline': 'central', 'font-size': fs, style: 'fill: var(--ink-3); font-weight: 500' }, st),
      );
      attachTooltip(g, () => tipContent(STATE_NAMES[st] || st, [['2026', `No ${CHAMBER_SINGULAR[ch].toLowerCase()} race`]]));
      svg.append(g);
      return;
    }
    const n = list.length;
    const hgt = (tile - gap * (n - 1)) / n;
    list.forEach((r, k) => {
      const a = svgEl('a', { href: raceHref(r.race_id), 'aria-label': `${r.name}: ${fmt.pct(r.p_dem)} chance of a Democratic win` });
      a.append(svgEl('rect', { class: 'tile', x: x0, y: y0 + k * (hgt + gap), width: tile, height: hgt, rx: 3, fill: probColor(r.p_dem) }));
      attachTooltip(a, () => raceTip(r));
      svg.append(a);
    });
    const ink = textOn(probColor(list[0].p_dem));
    svg.append(svgEl('text', {
      x: x0 + tile / 2, y: y0 + (n > 1 ? hgt / 2 : tile / 2), 'text-anchor': 'middle', 'dominant-baseline': 'central', 'font-size': fs, fill: ink,
    }, st));
    if (n > 1) {
      list.slice(1).forEach((r, k) => {
        svg.append(svgEl('text', {
          x: x0 + tile / 2, y: y0 + (k + 1) * (hgt + gap) + hgt / 2, 'text-anchor': 'middle', 'dominant-baseline': 'central',
          'font-size': Math.max(8, fs - 3), fill: textOn(probColor(r.p_dem)),
        }, r.special ? 'SP' : st));
      });
    }
  }));
  return svg;
}

/** Seat grid of all House districts grouped by state. */
function seatGrid(races) {
  const byState = new Map();
  for (const r of races) {
    if (!byState.has(r.state)) byState.set(r.state, []);
    byState.get(r.state).push(r);
  }
  const states = [...byState.keys()].sort((a, b) => (STATE_NAMES[a] || a).localeCompare(STATE_NAMES[b] || b));
  const root = h('div', { class: 'seat-grid', role: 'list' });
  for (const st of states) {
    const list = byState.get(st).slice().sort((a, b) => (a.district ?? 0) - (b.district ?? 0));
    root.append(h('div', { class: 'seat-state', role: 'listitem' },
      h('span', { class: 'seat-state-label', title: STATE_NAMES[st] || st }, st),
      h('div', { class: 'seats' }, list.map((r) => {
        const a = h('a', {
          class: 'seat', href: raceHref(r.race_id), dataset: { id: r.race_id },
          'aria-label': `${r.short || r.race_id}: ${fmt.pct(r.p_dem)} chance of a Democratic win`,
        });
        return paintProb(a, r.p_dem);
      }))));
  }
  delegateTooltip(root, '.seat', (el) => raceTip(S.byId.get(el.dataset.id)));
  return root;
}

// ---------------------------------------------------------------------------
// Race table
// ---------------------------------------------------------------------------

const COLUMNS = [
  { key: 'race', label: 'Race', type: 'text', sortKey: (r) => r.short || r.race_id, cell: (r) => h('a', { href: raceHref(r.race_id) }, h('b', {}, r.short || r.race_id)) },
  { key: 'holder', label: 'Incumbent / holder', type: 'text', cls: 'wrap-sm', sortKey: (r) => r.incumbent || '', cell: holderNode },
  { key: 'cands', label: 'Candidates', type: 'text', cls: 'wrap', sortKey: (r) => (r.dem && r.dem.name) || (r.rep && r.rep.name) || '', cell: (r) => matchupNode(r) },
  { key: 'pvi', label: 'PVI', type: 'num', cls: 'num', sortKey: (r) => r.pvi, cell: (r) => r.pvi_label || (isNum(r.pvi) ? fmt.margin(r.pvi, 0) : DASH) },
  { key: 'rating', label: 'Rating', type: 'num', sortKey: (r) => (r.rating ? r.rating.score : null), cell: (r) => (r.rating && r.rating.label ? ratingPill(r.rating.label, { title: r.rating.n ? `${r.rating.n} rater${r.rating.n === 1 ? '' : 's'}` : 'Not listed by any rater; treated as safe for the holder' }) : DASH) },
  { key: 'polls', label: 'Polls', type: 'num', cls: 'num', sortKey: (r) => (r.polls ? r.polls.margin : null), cell: (r) => (r.polls && isNum(r.polls.margin) ? h('span', {}, fmt.margin(r.polls.margin), h('span', { class: 'muted' }, ` (n=${fmt.num(r.polls.n)})`)) : DASH) },
  { key: 'margin', label: 'Model', type: 'num', cls: 'num', sortKey: (r) => r.margin, cell: (r) => fmt.margin(r.margin) },
  { key: 'p_dem', label: 'D win', type: 'num', cls: 'num', sortKey: (r) => r.p_dem, cell: (r) => probChip(r.p_dem) },
  { key: 'market', label: 'Market', type: 'num', cls: 'num', sortKey: (r) => (r.markets ? r.markets.p_dem : null), cell: (r) => (r.markets ? fmt.pct(r.markets.p_dem) : DASH) },
  { key: 'flip', label: 'Flip', type: 'num', cls: 'num', sortKey: (r) => r.flip_prob, cell: (r) => fmt.pct(r.flip_prob) },
];

function isMissing(v) {
  return v == null || v === '' || (typeof v === 'number' && !Number.isFinite(v));
}

function raceTable(ch, races) {
  const st = { q: '', label: '', competitive: false, sort: null, dir: 'asc' };
  const rowFor = new Map();
  const rowOf = (r) => {
    let tr = rowFor.get(r.race_id);
    if (!tr) {
      tr = h('tr', {}, COLUMNS.map((c) => h('td', { class: c.cls }, c.cell(r))));
      rowFor.set(r.race_id, tr);
    }
    return tr;
  };
  const search = h('input', { type: 'search', placeholder: 'Search race, state or candidate', 'aria-label': `Search ${CHAMBER_LABEL[ch]} races` });
  const select = h('select', { 'aria-label': 'Filter by rating' },
    h('option', { value: '' }, 'All ratings'),
    LABELS.map((l) => h('option', { value: l }, l)));
  const check = h('input', { type: 'checkbox' });
  const count = h('span', { class: 'count', 'aria-live': 'polite' });
  const controls = h('div', { class: 'controls' },
    search, select,
    h('label', { class: 'check' }, check, 'Competitive only'),
    count);

  const thead = h('thead', {}, h('tr', {}, COLUMNS.map((c) => {
    const btn = h('button', { class: 'sort', type: 'button', onClick: () => setSort(c.key) }, c.label);
    return h('th', { scope: 'col', class: c.cls, dataset: { key: c.key } }, btn);
  })));
  const tbody = h('tbody');
  const table = h('table', { class: 'data race-table' }, thead, tbody);
  const wrap = h('div', { class: 'table-wrap' }, table);
  const note = h('p', { class: 'table-note' },
    ch === 'house'
      ? 'Default order: closest races first. Click a column heading to sort; † marks an incumbent. Polls: the model’s weighted polling average (number of polls). Model: projected margin. D win: chance the Democratic-side candidate wins. Market: prediction-market chance of a Democratic win. Flip: chance the seat changes party.'
      : 'Default order: alphabetical by state. Click a column heading to sort; † marks an incumbent. Polls: the model’s weighted polling average (number of polls). Model: projected margin. D win: chance the Democratic-side candidate wins. Market: prediction-market chance of a Democratic win. Flip: chance the seat changes party.');

  const defaultCompare = ch === 'house'
    ? (a, b) => (Math.abs((isNum(a.p_dem) ? a.p_dem : 1) - 0.5) - Math.abs((isNum(b.p_dem) ? b.p_dem : 1) - 0.5)) || String(a.race_id).localeCompare(String(b.race_id))
    : (a, b) => String(a.state_name || a.state).localeCompare(String(b.state_name || b.state)) || ((a.special ? 1 : 0) - (b.special ? 1 : 0)) || String(a.race_id).localeCompare(String(b.race_id));

  function matches(r) {
    if (st.competitive && !COMPETITIVE.has(r.label)) return false;
    if (st.label && r.label !== st.label) return false;
    if (st.q) {
      if (!r._hay) r._hay = [r.short, r.race_id, r.name, r.state_name, r.state, r.incumbent, r.dem && r.dem.name, r.rep && r.rep.name, r.label].filter(Boolean).join(' ').toLowerCase();
      if (!r._hay.includes(st.q)) return false;
    }
    return true;
  }
  function apply() {
    const col = st.sort ? COLUMNS.find((c) => c.key === st.sort) : null;
    const list = races.filter(matches);
    if (col) {
      list.sort((a, b) => {
        const va = col.sortKey(a), vb = col.sortKey(b);
        const ma = isMissing(va), mb = isMissing(vb);
        if (ma && mb) return defaultCompare(a, b);
        if (ma) return 1;
        if (mb) return -1;
        const c = typeof va === 'number' && typeof vb === 'number' ? va - vb : String(va).localeCompare(String(vb));
        return (st.dir === 'asc' ? c : -c) || defaultCompare(a, b);
      });
    } else {
      list.sort(defaultCompare);
    }
    for (const th of thead.querySelectorAll('th')) {
      if (col && th.dataset.key === col.key) th.setAttribute('aria-sort', st.dir === 'asc' ? 'ascending' : 'descending');
      else th.removeAttribute('aria-sort');
    }
    if (!list.length) {
      tbody.replaceChildren(h('tr', {}, h('td', { class: 'empty', colspan: String(COLUMNS.length) }, 'No races match these filters.')));
    } else {
      const frag = document.createDocumentFragment();
      for (const r of list) frag.append(rowOf(r));
      tbody.replaceChildren(frag);
    }
    count.textContent = `Showing ${fmt.num(list.length)} of ${fmt.num(races.length)} races`;
  }
  function setSort(key) {
    const col = COLUMNS.find((c) => c.key === key);
    if (st.sort === key) {
      st.dir = st.dir === 'asc' ? 'desc' : 'asc';
    } else {
      st.sort = key;
      st.dir = col.type === 'num' ? 'desc' : 'asc';
    }
    apply();
  }
  let timer = null;
  search.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(() => { st.q = search.value.trim().toLowerCase(); apply(); }, 120);
  });
  select.addEventListener('change', () => { st.label = select.value; apply(); });
  check.addEventListener('change', () => { st.competitive = check.checked; apply(); });
  apply();
  return h('div', { class: 'race-table-block' }, controls, wrap, note);
}

// ---------------------------------------------------------------------------
// Closest races + scatter
// ---------------------------------------------------------------------------

function renderClosest() {
  const root = document.getElementById('closest');
  const list = S.races
    .filter((r) => isNum(r.p_dem) && !r.uncontested)
    .sort((a, b) => Math.abs(a.p_dem - 0.5) - Math.abs(b.p_dem - 0.5) || String(a.race_id).localeCompare(String(b.race_id)))
    .slice(0, 12);
  if (!list.length) {
    root.append(h('p', { class: 'muted' }, 'No contested races found.'));
    return;
  }
  root.replaceChildren(...list.map(raceCard));
}

function raceCard(r) {
  const dSide = (r.dem && r.dem.party) || 'D';
  const pR = isNum(r.p_dem) ? 1 - r.p_dem : null;
  const card = h('a', { class: 'race-card', href: raceHref(r.race_id), 'aria-label': `${r.name}: ${fmt.pct(r.p_dem)} chance of a Democratic win` },
    h('div', { class: 'title' }, h('span', {}, r.short || r.race_id), ratingPill(r.label)),
    h('div', { class: 'cands' }, matchupNode(r, { short: true })),
    splitBar(r.p_dem, pR, 0),
    h('div', { class: 'pct' }, h('span', {}, h('b', {}, fmt.pct(r.p_dem)), ` ${dSide}`), h('span', {}, h('b', {}, fmt.pct(pR)), ` ${(r.rep && r.rep.party) || 'R'}`)),
  );
  return card;
}

function renderScatter() {
  const root = document.getElementById('scatter');
  const pts = S.races.filter((r) => r.markets && isNum(r.markets.p_dem) && isNum(r.p_dem));
  if (!pts.length) {
    root.append(h('p', { class: 'muted' }, 'No races have prediction-market prices yet.'));
    return;
  }
  const box = h('div', { class: 'chart-box' });
  root.append(box);
  responsiveChart(box, (w) => drawScatter(w, pts));
  const legend = h('div', { class: 'legend' }, CHAMBERS.map((ch) => {
    const dot = h('span', { class: 'legend-dot' });
    dot.style.background = seriesColor(ch);
    onThemeChange(() => { dot.style.background = seriesColor(ch); });
    return h('span', { class: 'legend-item' }, dot, CHAMBER_LABEL[ch]);
  }), h('span', { class: 'legend-item' }, `${fmt.num(pts.length)} races with markets`));
  root.append(legend);
}

function drawScatter(w, pts) {
  const H = clamp(Math.round(w * 0.78), 260, 440), m = { t: 12, r: 16, b: 44, l: 48 };
  const x = scaleLinear([0, 1], [m.l, w - m.r]);
  const y = scaleLinear([0, 1], [H - m.b, m.t]);
  const svg = svgEl('svg', {
    class: 'chart scatter', viewBox: `0 0 ${w} ${H}`, width: w, height: H, role: 'img',
    'aria-label': 'Scatter plot of model probability against market probability for each race with a market',
  });
  for (const v of [0, 0.25, 0.5, 0.75, 1]) {
    svg.append(svgEl('line', { class: 'grid', x1: m.l, x2: w - m.r, y1: y(v), y2: y(v) }));
    svg.append(svgEl('line', { class: 'grid', y1: m.t, y2: H - m.b, x1: x(v), x2: x(v) }));
    svg.append(svgEl('text', { class: 'tick', x: m.l - 6, y: y(v) + 4, 'text-anchor': 'end' }, `${Math.round(v * 100)}%`));
    svg.append(svgEl('text', { class: 'tick', x: x(v), y: H - m.b + 16, 'text-anchor': 'middle' }, `${Math.round(v * 100)}%`));
  }
  svg.append(svgEl('line', { class: 'ref', x1: x(0), y1: y(0), x2: x(1), y2: y(1), style: 'stroke: var(--border-strong)' }));
  svg.append(svgEl('text', { class: 'axis-title', x: (m.l + w - m.r) / 2, y: H - 6, 'text-anchor': 'middle' }, 'Market: chance of a Democratic win'));
  svg.append(svgEl('text', { class: 'axis-title', x: 12, y: (m.t + H - m.b) / 2, 'text-anchor': 'middle', transform: `rotate(-90 12 ${(m.t + H - m.b) / 2})` }, 'Model: chance of a Democratic win'));
  for (const r of pts) {
    const cx = x(r.markets.p_dem), cy = y(r.p_dem);
    const a = svgEl('a', { href: raceHref(r.race_id), 'aria-label': `${r.name}: model ${fmt.pct(r.p_dem)}, markets ${fmt.pct(r.markets.p_dem)}` });
    a.append(
      svgEl('circle', { class: 'hit', cx, cy, r: 12 }),
      svgEl('circle', { class: 'marker mark', cx, cy, r: 4.5, fill: seriesColor(r.chamber) }),
    );
    attachTooltip(a, () => tipContent(r.name, [
      ['Model', fmt.pct(r.p_dem)],
      ['Markets', `${fmt.pct(r.markets.p_dem)}${isNum(r.markets.n) ? ` (${r.markets.n} market${r.markets.n === 1 ? '' : 's'})` : ''}`],
      ['Model − market', `${fmt.signed((r.p_dem - r.markets.p_dem) * 100, 0)} pts`],
    ]));
    svg.append(a);
  }
  return svg;
}

main();
