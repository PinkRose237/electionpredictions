/**
 * charts.js — reusable visuals for the 2028 site: win-probability split bar, electoral-vote histogram,
 * trend lines, the "road to 270" bar, a geographic Electoral College map, and a small margin-range bar.
 * Everything is SVG built with common.js helpers (no innerHTML) and redraws on resize / theme change.
 */
import {
  DASH, TOTAL_EV, NEEDED_EV, isNum, fmt, parseDate, isDark, probColor, textOn, h, svgEl, scaleLinear, niceTicks, dateTicks,
  responsiveChart, tooltip, tipContent, attachTooltip, contestName,
} from './common.js';

// ---------------------------------------------------------------------------
// Split bar
// ---------------------------------------------------------------------------
export function splitBar(pD, pR, pN, ariaLabel) {
  const bar = h('div', { class: 'split-bar', role: 'img', 'aria-label': ariaLabel || `Democrats ${fmt.pct(pD)}, Republicans ${fmt.pct(pR)}` });
  const d = isNum(pD) ? pD : 0, r = isNum(pR) ? pR : 0, n = isNum(pN) ? pN : Math.max(0, 1 - d - r);
  if (d > 0) bar.append(h('span', { class: 'd', style: { width: `${d * 100}%` } }));
  if (n > 0.005) bar.append(h('span', { class: 'n', style: { width: `${n * 100}%` } }));
  if (r > 0) bar.append(h('span', { class: 'r', style: { width: `${r * 100}%` } }));
  return bar;
}

// ---------------------------------------------------------------------------
// Electoral-vote histogram
// ---------------------------------------------------------------------------
export function evHistogram(container, histogram, { height = 150 } = {}) {
  const bins = (histogram || []).filter((b) => isNum(b.ev) && isNum(b.p) && b.p > 0);
  if (!bins.length) { container.replaceChildren(h('p', { class: 'muted small' }, 'No simulation output.')); return; }
  // group into 5-EV buckets when the spread is wide, so bars stay legible
  responsiveChart(container, (w) => {
    const H = height, m = { t: 22, r: 6, b: 20, l: 6 };
    const s0 = Math.min(...bins.map((b) => b.ev), NEEDED_EV - 20), s1 = Math.max(...bins.map((b) => b.ev), NEEDED_EV + 20);
    const width = s1 - s0 + 1;
    const step = width / (w - m.l - m.r) > 0.5 ? 5 : width / (w - m.l - m.r) > 0.25 ? 2 : 1;
    const agg = new Map();
    for (const b of bins) {
      const k = Math.floor(b.ev / step) * step;
      agg.set(k, (agg.get(k) || 0) + b.p);
    }
    const buckets = [...agg.entries()].sort((a, b) => a[0] - b[0]);
    const x = scaleLinear([s0 - 0.5, s1 + 0.5], [m.l, w - m.r]);
    const pmax = Math.max(...buckets.map((b) => b[1]));
    const y = scaleLinear([0, pmax], [H - m.b, m.t]);
    const svg = svgEl('svg', { class: 'chart hist', viewBox: `0 0 ${w} ${H}`, width: w, height: H, role: 'img',
      'aria-label': 'Distribution of Democratic electoral votes across simulations; 270 to win' });
    svg.append(svgEl('line', { class: 'axis', x1: m.l, x2: w - m.r, y1: H - m.b + 0.5, y2: H - m.b + 0.5 }));
    const bw = Math.max(1, x(step) - x(0) - (step === 1 ? 1 : 1.5));
    for (const [k, p] of buckets) {
      const mid = k + (step - 1) / 2;
      const fill = mid >= NEEDED_EV ? 'var(--dem)' : TOTAL_EV - mid >= NEEDED_EV ? 'var(--rep)' : 'var(--tossup)';
      const top = y(p);
      const r = svgEl('rect', { x: x(k - 0.5) + 0.5, y: top, width: bw, height: Math.max(0.5, H - m.b - top), fill, rx: bw > 3 ? 1.5 : 0 });
      svg.append(r);
      const hit = svgEl('rect', { class: 'hit', x: x(k - 0.5), y: m.t - 8, width: x(step) - x(0), height: H - m.t - m.b + 8 });
      attachTooltip(hit, () => tipContent(step === 1 ? `${k} Democratic electoral votes` : `${k}–${k + step - 1} Democratic electoral votes`, [
        ['Share of simulations', fmt.pct(p, p < 0.01 ? 1 : 0)],
        ['Republican electoral votes', step === 1 ? String(TOTAL_EV - k) : `${TOTAL_EV - k - step + 1}–${TOTAL_EV - k}`],
      ]));
      svg.append(hit);
    }
    const nx = x(NEEDED_EV - 0.5);
    svg.append(svgEl('line', { class: 'ref', x1: nx, x2: nx, y1: m.t - 8, y2: H - m.b }));
    svg.append(svgEl('text', { class: 'ref-label', x: nx, y: m.t - 11, 'text-anchor': 'middle' }, '270 to win'));
    for (const t of niceTicks(s0, s1, Math.max(2, Math.floor((w - m.l - m.r) / 70)))) {
      if (t < s0 || t > s1 || Math.abs(x(t) - nx) < 22) continue;
      svg.append(svgEl('text', { class: 'tick', x: x(t), y: H - 5, 'text-anchor': 'middle' }, fmt.num(t)));
    }
    return svg;
  });
}

// ---------------------------------------------------------------------------
// Trend
// ---------------------------------------------------------------------------
/**
 * Time ticks fitted to the span: hours (with the date at midnight) for spans up to ~2.5 days, otherwise days.
 * Returns [{ t, label }].
 */
export function timeTicks(t0, t1, count = 5, { daily = false } = {}) {
  const H = 36e5, span = Math.max(1, t1 - t0);
  if (!daily && span <= 2.5 * 864e5) {
    const stepH = [1, 2, 3, 6, 12, 24].find((hrs) => span / (hrs * H) <= count) || 24;
    const d = new Date(t0);
    d.setMinutes(0, 0, 0);
    if (d.getTime() < t0) d.setHours(d.getHours() + 1);
    const out = [];
    for (let t = d.getTime(); t <= t1; t += H) {
      const dt = new Date(t);
      if (dt.getHours() % stepH) continue;
      out.push({ t, label: dt.getHours() === 0 ? dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
        : dt.toLocaleTimeString('en-US', { hour: 'numeric' }) });
    }
    return out;
  }
  return dateTicks(t0, t1, count).map((t) => ({ t, label: new Date(t).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) }));
}

/**
 * series: [{ label, value: (d) => number, color, format }] on a shared y domain.
 * band: optional { lo: (d)=>n, hi: (d)=>n, color } shaded range.
 * Each datum has `date` (YYYY-MM-DD or a full ISO time) and optionally `when` (tooltip label) and `version`.
 * The time axis spans exactly the data (at least 6 hours, ending at the latest point); dots are drawn only where
 * points are spread out, plus the latest, so frequent updates read as one continuous line.
 */
export function trendChart(container, history, { series, domain = [0, 1], tickFmt = (v) => `${Math.round(v * 100)}%`, ref = 0.5, band, height = 230, label } = {}) {
  const hist = (history || []).filter((d) => d && parseDate(d.date)).sort((a, b) => parseDate(a.date) - parseDate(b.date));
  if (!hist.length) { container.replaceChildren(h('p', { class: 'muted' }, 'No history yet.')); return; }
  responsiveChart(container, (w) => {
    const H = height, m = { t: 14, r: 64, b: 28, l: 42 };
    const times = hist.map((d) => parseDate(d.date).getTime());
    let t0 = Math.min(...times);
    const t1 = Math.max(...times);
    const minSpan = hist.every((d) => !String(d.date).includes('T')) ? 864e5 : 6 * 36e5;
    if (t1 - t0 < minSpan) t0 = t1 - minSpan;              // a short history still gets a readable window, never a future one
    else t0 -= (t1 - t0) * 0.02;
    const x = scaleLinear([t0, t1], [m.l, w - m.r]);
    const y = scaleLinear(domain, [H - m.b, m.t]);
    const svg = svgEl('svg', { class: 'chart trend', viewBox: `0 0 ${w} ${H}`, width: w, height: H, role: 'img', 'aria-label': label || 'Trend over time' });
    for (const v of niceTicks(domain[0], domain[1], 4)) {
      if (v < domain[0] || v > domain[1]) continue;
      svg.append(svgEl('line', { class: v === ref ? 'axis' : 'grid', x1: m.l, x2: w - m.r, y1: y(v), y2: y(v) }));
      svg.append(svgEl('text', { class: 'tick', x: m.l - 6, y: y(v) + 4, 'text-anchor': 'end' }, tickFmt(v)));
    }
    const daily = hist.every((d) => !String(d.date).includes('T'));   // once-a-day points get date labels
    for (const tk of timeTicks(t0, t1, Math.max(2, Math.floor((w - m.l - m.r) / 80)), { daily })) {
      const xx = x(tk.t);
      if (xx < m.l - 1 || xx > w - m.r + 1) continue;
      const anchor = xx < m.l + 20 ? 'start' : 'middle';     // keep a label at the left edge inside the plot
      svg.append(svgEl('text', { class: 'tick', x: xx, y: H - m.b + 18, 'text-anchor': anchor }, tk.label));
    }
    if (band) {
      const pts = hist.map((d, i) => [times[i], band.lo(d), band.hi(d)]).filter((p) => isNum(p[1]) && isNum(p[2]));
      if (pts.length > 1) {
        const top = pts.map((p, i) => `${i ? 'L' : 'M'}${x(p[0]).toFixed(1)} ${y(p[2]).toFixed(1)}`).join(' ');
        const bot = pts.slice().reverse().map((p) => `L${x(p[0]).toFixed(1)} ${y(p[1]).toFixed(1)}`).join(' ');
        svg.append(svgEl('path', { d: `${top} ${bot} Z`, fill: band.color, opacity: 0.16 }));
      }
    }
    for (const s of series) {
      const pts = hist.map((d, i) => ({ t: times[i], v: s.value(d) })).filter((p) => isNum(p.v));
      if (!pts.length) continue;
      const px = pts.map((p) => x(p.t));
      if (pts.length > 1) svg.append(svgEl('path', { class: 'series', d: pts.map((p, i) => `${i ? 'L' : 'M'}${px[i].toFixed(1)} ${y(p.v).toFixed(1)}`).join(' '), stroke: s.color }));
      const last = pts.length - 1;
      const apart = (i) => (i === 0 || px[i] - px[i - 1] >= 10) && (i === last || px[i + 1] - px[i] >= 10);
      pts.forEach((p, i) => {
        if (i === last || apart(i)) svg.append(svgEl('circle', { class: 'marker', cx: px[i], cy: y(p.v), r: 3.5, fill: s.color }));
      });
      svg.append(svgEl('text', { class: 'label', x: px[last] + 8, y: y(pts[last].v) + 4, fill: s.color }, (s.format || tickFmt)(pts[last].v)));
    }
    const cross = svgEl('line', { class: 'crosshair', y1: m.t, y2: H - m.b, x1: 0, x2: 0, visibility: 'hidden' });
    const overlay = svgEl('rect', { class: 'hit', x: m.l, y: m.t, width: Math.max(1, w - m.l - m.r), height: H - m.t - m.b });
    overlay.addEventListener('pointermove', (e) => {
      const rect = svg.getBoundingClientRect();
      const t = x.invert((e.clientX - rect.left) * (w / rect.width));
      let best = 0;
      for (let i = 1; i < times.length; i++) if (Math.abs(times[i] - t) < Math.abs(times[best] - t)) best = i;
      cross.setAttribute('x1', x(times[best])); cross.setAttribute('x2', x(times[best])); cross.setAttribute('visibility', 'visible');
      const d = hist[best];
      const when = d.when || (String(d.date).includes('T') ? fmt.dateTime(d.date) : fmt.date(d.date));
      tooltip.show(tipContent(when + (d.version ? ` · model v${d.version}` : ''),
        series.map((s) => [s.label, (s.format || tickFmt)(s.value(d)), s.color])), e.clientX, e.clientY);
    });
    overlay.addEventListener('pointerleave', () => { cross.setAttribute('visibility', 'hidden'); tooltip.hide(); });
    svg.append(cross, overlay);
    return svg;
  });
}

// ---------------------------------------------------------------------------
// Road to 270: every contest as a segment, ordered from most Democratic to most Republican
// ---------------------------------------------------------------------------
export function roadTo270(container, contests, { onSelect, highlight } = {}) {
  const list = (contests || []).filter((c) => isNum(c.p_dem)).slice().sort((a, b) => b.p_dem - a.p_dem || b.margin - a.margin);
  responsiveChart(container, (w) => {
    const H = 64, m = { l: 2, r: 2, t: 18, b: 14 };
    const x = scaleLinear([0, TOTAL_EV], [m.l, w - m.r]);
    const svg = svgEl('svg', { class: 'chart road', viewBox: `0 0 ${w} ${H}`, width: w, height: H, role: 'img',
      'aria-label': 'Contests ordered from most to least likely to vote Democratic, sized by electoral votes' });
    let acc = 0, tipIdx = -1;
    list.forEach((c, i) => {
      const x0 = x(acc), x1 = x(acc + c.evs);
      if (tipIdx < 0 && acc + c.evs >= NEEDED_EV) tipIdx = i;
      const fill = probColor(c.p_dem);
      const r = svgEl('rect', { x: x0, y: m.t, width: Math.max(0.5, x1 - x0 - 0.6), height: H - m.t - m.b, fill, class: 'seg' + (highlight === c.id ? ' active' : ''), tabindex: 0,
        'aria-label': `${contestName(c.id)}, ${c.evs} electoral votes, ${fmt.pct(c.p_dem)} Democratic` });
      attachTooltip(r, () => tipContent(`${contestName(c.id)} · ${c.evs} EV`, [
        ['Chance D wins', fmt.pct(c.p_dem)], ['Expected margin', fmt.margin(c.margin)],
        ['Running total (D side)', `${acc + c.evs} EV`],
      ]));
      if (onSelect) { r.addEventListener('click', () => onSelect(c.id)); r.addEventListener('keydown', (e) => { if (e.key === 'Enter') onSelect(c.id); }); }
      svg.append(r);
      if (x1 - x0 > 22) svg.append(svgEl('text', { class: 'seg-label', x: (x0 + x1) / 2, y: m.t + (H - m.t - m.b) / 2 + 4, 'text-anchor': 'middle', fill: textOn(fill) }, c.id));
      acc += c.evs;
    });
    const nx = x(NEEDED_EV);
    svg.append(svgEl('line', { class: 'ref', x1: nx, x2: nx, y1: 4, y2: H - 4 }));
    svg.append(svgEl('text', { class: 'ref-label', x: nx, y: 12, 'text-anchor': 'middle' }, '270'));
    svg.append(svgEl('text', { class: 'tick', x: m.l, y: H - 2 }, '← Most Democratic'));
    svg.append(svgEl('text', { class: 'tick', x: w - m.r, y: H - 2, 'text-anchor': 'end' }, 'Most Republican →'));
    return svg;
  });
}

// ---------------------------------------------------------------------------
// Electoral College map
// ---------------------------------------------------------------------------
const CALLOUTS = ['VT', 'NH', 'MA', 'RI', 'CT', 'NJ', 'DE', 'MD', 'DC'];
const DISTRICTS = ['ME-1', 'ME-2', 'NE-1', 'NE-2', 'NE-3'];

function ringsPath(rings) {
  return rings.map((r) => {
    let d = `M${r[0]} ${r[1]}`;
    for (let i = 2; i < r.length; i += 2) d += `L${r[i]} ${r[i + 1]}`;
    return `${d}Z`;
  }).join('');
}

/**
 * Draw the map into `container`. `valueOf(id)` → probability (0–1) used for colour; `tipFor(id)` → tooltip rows;
 * `onSelect(id)` on click/Enter. Returns { redraw } so callers can repaint after changing what valueOf returns.
 */
export function ecMap(container, geo, { valueOf, tipFor, onSelect, selected } = {}) {
  const draw = () => {
    const W = geo.width, H = geo.height, extra = 74, bottom = 50;
    const svg = svgEl('svg', { viewBox: `0 0 ${W + extra} ${H + bottom}`, class: 'map-svg states ec-map', role: 'img',
      'aria-label': 'Electoral College map coloured by the chance a Democrat wins each contest' });
    const paint = (el, id) => {
      const p = valueOf(id);
      el.style.fill = isNum(p) ? probColor(p) : 'var(--map-none)';
      el.classList.add('shape', 'race');
      if (selected && selected() === id) el.classList.add('selected');
      el.setAttribute('tabindex', '0');
      el.setAttribute('aria-label', `${contestName(id)}: ${isNum(p) ? fmt.pct(p) : DASH} chance of a Democratic win`);
      if (tipFor) attachTooltip(el, () => tipContent(contestName(id), tipFor(id)));
      if (onSelect) {
        el.addEventListener('click', () => onSelect(id));
        el.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(id); } });
      }
      return el;
    };
    const g = svgEl('g', { class: 'shapes' });
    for (const [st, rings] of Object.entries(geo.states)) {
      if (st === 'DC') continue;
      g.append(paint(svgEl('path', { d: ringsPath(rings) }), st));
    }
    const lines = svgEl('g', { class: 'callout-lines' }), boxes = svgEl('g', { class: 'shapes callouts' }), labels = svgEl('g', { class: 'labels' });
    let y = (geo.centers.VT ? geo.centers.VT[1] : 120) - 50;
    const s = 28;
    for (const st of CALLOUTS) {
      const x = W + 16, c = geo.centers[st];
      if (c) lines.append(svgEl('line', { x1: c[0], y1: c[1], x2: x, y2: y + s / 2, class: 'callout-line' }));
      boxes.append(paint(svgEl('rect', { x, y, width: s, height: s, rx: 4 }), st));
      const p = valueOf(st);
      labels.append(svgEl('text', { x: x + s / 2, y: y + s / 2 + 4, class: 'map-label', 'text-anchor': 'middle', fill: isNum(p) ? textOn(probColor(p)) : null }, st));
      y += s + 6;
    }
    // split-elector districts along the bottom
    let dx = 40;
    const dy = H + 12;
    labels.append(svgEl('text', { x: 4, y: dy + s / 2 + 4, class: 'map-note-label' }, 'Districts'));
    for (const id of DISTRICTS) {
      boxes.append(paint(svgEl('rect', { x: dx + 26, y: dy, width: s + 14, height: s, rx: 4 }), id));
      const p = valueOf(id);
      labels.append(svgEl('text', { x: dx + 26 + (s + 14) / 2, y: dy + s / 2 + 4, class: 'map-label', 'text-anchor': 'middle', fill: isNum(p) ? textOn(probColor(p)) : null }, id));
      dx += s + 22;
    }
    for (const [st, c] of Object.entries(geo.centers)) {
      if (CALLOUTS.includes(st) || !geo.states[st]) continue;
      const p = valueOf(st);
      labels.append(svgEl('text', { x: c[0], y: c[1] + 4, class: 'map-label', 'text-anchor': 'middle', fill: isNum(p) ? textOn(probColor(p)) : null }, st));
    }
    svg.append(g, lines, boxes, labels);
    return svg;
  };
  return { redraw: responsiveChart(container, () => draw()) };
}

/** Probability legend ramp: R ← → D. */
export function probLegend() {
  const stops = [0, 0.03, 0.15, 0.35, 0.5, 0.65, 0.85, 0.97, 1];
  const ramp = h('div', { class: 'prob-legend', role: 'img', 'aria-label': 'Colour scale from safe Republican to safe Democratic' });
  for (let i = 0; i < stops.length - 1; i++) {
    const mid = (stops[i] + stops[i + 1]) / 2;
    ramp.append(h('span', { style: { background: probColor(mid), flex: String(stops[i + 1] - stops[i]) } }));
  }
  return h('div', { class: 'prob-legend-wrap' }, h('span', { class: 'small muted' }, 'Safe R'), ramp, h('span', { class: 'small muted' }, 'Safe D'));
}

// ---------------------------------------------------------------------------
// Margin range bar (80% interval on a fixed scale)
// ---------------------------------------------------------------------------
export function marginRange(p10, mean, p90, { domain = [-30, 30], width = 160 } = {}) {
  const H = 18;
  const x = scaleLinear(domain, [2, width - 2]);
  const c = (v) => Math.max(domain[0], Math.min(domain[1], v));
  const svg = svgEl('svg', { class: 'mrange', viewBox: `0 0 ${width} ${H}`, width, height: H, role: 'img',
    'aria-label': `Expected margin ${fmt.margin(mean)}, 80% range ${fmt.margin(p10)} to ${fmt.margin(p90)}` });
  svg.append(svgEl('line', { x1: x(0), x2: x(0), y1: 1, y2: H - 1, class: 'axis' }));
  if (isNum(p10) && isNum(p90)) {
    svg.append(svgEl('rect', { x: x(c(p10)), y: 6, width: Math.max(1, x(c(p90)) - x(c(p10))), height: 6, rx: 3, fill: 'var(--surface-3)' }));
  }
  if (isNum(mean)) svg.append(svgEl('circle', { cx: x(c(mean)), cy: 9, r: 4, fill: mean >= 0 ? 'var(--dem)' : 'var(--rep)' }));
  return svg;
}

export function themeColor(party) {
  if (party === 'D') return isDark() ? '#4a90d9' : '#2166ac';
  if (party === 'R') return isDark() ? '#d8504a' : '#b2182b';
  return isDark() ? '#9a9a96' : '#78786f';
}
