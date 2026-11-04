/**
 * scorecard.js — how the final forecast did: headline numbers, calibration, record by rating, forecast vs
 * actual margins, seat totals against the forecast's range, and every upset. Data: results-data.js.
 */
import { CHAMBER_LABEL, fmt, isNum, h, svgEl, raceHref, ratingPill, partyClass, initChrome, renderUpdated, renderFooterMeta, showError, responsiveChart } from './common.js';
import { loadResults, keepFresh, scorecard, tally, displayName, LABEL_ORDER } from './results-data.js';

async function main() {
  initChrome({ current: 'scorecard' });
  const status = document.getElementById('status');
  let S;
  try {
    S = await loadResults();
  } catch (err) {
    console.error(err);
    showError(status, err, 'This page needs data/races.json.');
    return;
  }
  if (S.summary) { renderUpdated(S.summary); renderFooterMeta(S.summary); }
  status.hidden = true;
  document.getElementById('scorecard').hidden = false;
  render(S);
  keepFresh(S, render);
}

function render(S) {
  const sc = scorecard(S);
  renderTiles(sc);
  renderCalibration(sc);
  renderByRating(sc);
  renderMargins(sc);
  renderSeats(S);
  renderUpsets(sc);
}

function renderTiles(sc) {
  const tile = (big, text, cls = '') => h('div', { class: 'tile' }, h('b', { class: cls }, big), h('span', {}, text));
  document.getElementById('tiles').replaceChildren(
    tile(`${sc.hits} / ${sc.n}`, `called races won by the forecast’s favorite (${sc.n ? Math.round((100 * sc.hits) / sc.n) : 0}%)`),
    tile(sc.brier !== null ? sc.brier.toFixed(3) : '—', 'Brier score: 0 is perfect, 0.25 is a coin flip on every race'),
    tile(sc.median !== null ? fmt.margin(sc.median) : '—', 'typical result relative to the forecast margin', sc.median > 0 ? 'dem-text' : sc.median < 0 ? 'rep-text' : ''),
    tile(sc.mae !== null ? `${sc.mae.toFixed(1)} pts` : '—', `average miss on the margin, either way (${sc.margins.length} races 95%+ counted)`),
  );
}

function renderCalibration(sc) {
  const el = document.getElementById('calibration');
  const bins = sc.bins.filter((b) => b.n > 0);
  const box = h('div', { class: 'chart-box' });
  el.replaceChildren(
    h('h2', { id: 'h-cal' }, 'Calibration'),
    h('p', { class: 'muted small' }, 'Called races grouped by the forecast’s chance the Democrat would win. If the forecast is well calibrated, Democrats win about as often as it said: the dots sit on the diagonal. Bigger dots are bigger groups.'),
    box);
  responsiveChart(box, (width) => {
    const W = Math.max(280, Math.min(width, 520)), H = W * 0.8, m = { l: 40, r: 12, t: 10, b: 36 };
    const x = (p) => m.l + p * (W - m.l - m.r), y = (p) => H - m.b - p * (H - m.t - m.b);
    const svg = svgEl('svg', { viewBox: `0 0 ${W} ${H}`, class: 'sc-chart', role: 'img', 'aria-label': 'Calibration chart' });
    for (const t of [0, 0.25, 0.5, 0.75, 1]) {
      svg.append(svgEl('line', { x1: x(0), x2: x(1), y1: y(t), y2: y(t), class: 'grid' }));
      svg.append(svgEl('text', { x: m.l - 6, y: y(t) + 4, 'text-anchor': 'end', class: 'tick' }, `${Math.round(t * 100)}%`));
      svg.append(svgEl('text', { x: x(t), y: H - m.b + 16, 'text-anchor': 'middle', class: 'tick' }, `${Math.round(t * 100)}%`));
    }
    svg.append(svgEl('line', { x1: x(0), y1: y(0), x2: x(1), y2: y(1), class: 'diag' }));
    svg.append(svgEl('text', { x: (m.l + W - m.r) / 2, y: H - 4, 'text-anchor': 'middle', class: 'axis-label' }, 'Forecast chance of a Democratic win'));
    const maxN = Math.max(...bins.map((b) => b.n), 1);
    for (const b of bins) {
      const px = b.pSum / b.n, py = b.dem / b.n;
      const c = svgEl('circle', { cx: x(px), cy: y(py), r: 4 + 10 * Math.sqrt(b.n / maxN), class: 'cal-dot' });
      c.append(svgEl('title', {}, `Forecast ${Math.round(b.lo * 100)}–${Math.round(b.hi * 100)}% D: ${b.dem} of ${b.n} won by Democrats (${Math.round((100 * b.dem) / b.n)}%)`));
      svg.append(c);
    }
    return svg;
  });
}

function renderByRating(sc) {
  const el = document.getElementById('by-rating');
  const rows = LABEL_ORDER.filter((l) => sc.byLabel[l]).map((l) => {
    const r = sc.byLabel[l];
    return h('tr', {}, h('td', {}, ratingPill(l)), h('td', { class: 'num' }, String(r.n)), h('td', { class: 'num' }, String(r.hits)),
      h('td', { class: 'num' }, `${Math.round((100 * r.hits) / r.n)}%`));
  });
  el.replaceChildren(
    h('h2', { id: 'h-rating' }, 'Record by rating'),
    h('p', { class: 'muted small' }, 'Safe and Likely races should go to the favorite almost every time; Lean races most of the time; Tossups about half.'),
    h('div', { class: 'table-wrap' }, h('table', { class: 'data' },
      h('thead', {}, h('tr', {}, h('th', {}, 'Rating'), h('th', { class: 'num' }, 'Called'), h('th', { class: 'num' }, 'Favorite won'), h('th', { class: 'num' }, 'Share'))),
      h('tbody', {}, ...rows))));
}

function renderMargins(sc) {
  const el = document.getElementById('margins');
  const box = h('div', { class: 'chart-box' });
  el.replaceChildren(
    h('h2', { id: 'h-margins' }, 'Forecast margin vs. result'),
    h('p', { class: 'muted small' }, `Each dot is a race with at least 95% of the expected vote counted (${sc.margins.length} so far). Dots above the diagonal went more Democratic than forecast; below it, more Republican.`),
    box);
  responsiveChart(box, (width) => {
    const W = Math.max(300, width), H = Math.min(460, W * 0.62), m = { l: 46, r: 14, t: 10, b: 38 }, lim = 50;
    const clamp = (v) => Math.max(-lim, Math.min(lim, v));
    const x = (v) => m.l + ((clamp(v) + lim) / (2 * lim)) * (W - m.l - m.r);
    const y = (v) => H - m.b - ((clamp(v) + lim) / (2 * lim)) * (H - m.t - m.b);
    const svg = svgEl('svg', { viewBox: `0 0 ${W} ${H}`, class: 'sc-chart', role: 'img', 'aria-label': 'Forecast margin against actual margin' });
    for (const t of [-40, -20, 0, 20, 40]) {
      svg.append(svgEl('line', { x1: x(-lim), x2: x(lim), y1: y(t), y2: y(t), class: t === 0 ? 'grid zero' : 'grid' }));
      svg.append(svgEl('line', { y1: y(-lim), y2: y(lim), x1: x(t), x2: x(t), class: t === 0 ? 'grid zero' : 'grid' }));
      svg.append(svgEl('text', { x: m.l - 6, y: y(t) + 4, 'text-anchor': 'end', class: 'tick' }, fmt.margin(t, 0)));
      svg.append(svgEl('text', { x: x(t), y: H - m.b + 16, 'text-anchor': 'middle', class: 'tick' }, fmt.margin(t, 0)));
    }
    svg.append(svgEl('line', { x1: x(-lim), y1: y(-lim), x2: x(lim), y2: y(lim), class: 'diag' }));
    svg.append(svgEl('text', { x: (m.l + W - m.r) / 2, y: H - 4, 'text-anchor': 'middle', class: 'axis-label' }, 'Forecast margin'));
    svg.append(svgEl('text', { x: 12, y: (m.t + H - m.b) / 2, 'text-anchor': 'middle', class: 'axis-label', transform: `rotate(-90 12 ${(m.t + H - m.b) / 2})` }, 'Actual margin'));
    for (const d of sc.margins) {
      const a = svgEl('a', { href: raceHref(d.race.race_id) });
      const c = svgEl('circle', { cx: x(d.model), cy: y(d.actual), r: d.race.chamber === 'house' ? 3.2 : 5, class: `m-dot ${d.actual > 0 ? 'dem' : 'rep'}` });
      c.append(svgEl('title', {}, `${displayName(d.race)}: forecast ${fmt.margin(d.model)}, result ${fmt.margin(d.actual)}`));
      a.append(c);
      svg.append(a);
    }
    return svg;
  });
}

function renderSeats(S) {
  const el = document.getElementById('seats');
  const rows = ['senate', 'house', 'governor'].map((ch) => {
    const t = tally(S, ch);
    const f = t.forecast;
    if (!f) return null;
    const range = `${Math.round(f.dem_seats.p10)}–${Math.round(f.dem_seats.p90)}`;
    const proj = t.projected.d;
    const inRange = proj >= f.dem_seats.p10 && proj <= f.dem_seats.p90;
    return h('tr', {},
      h('td', {}, CHAMBER_LABEL[ch]),
      h('td', { class: 'num' }, `D ${Math.round(f.dem_seats.mean)}`, h('div', { class: 'muted small' }, `80% range ${range}`)),
      h('td', { class: 'num' }, `${fmt.pct(f.p_dem)}`),
      h('td', { class: 'num' }, `D ${t.dWon}`, h('div', { class: 'muted small' }, `${t.uncalled.length} uncalled`)),
      h('td', { class: 'num' }, `D ${proj}`, h('div', { class: `small ${inRange ? 'muted' : 'rep-text'}` }, inRange ? 'inside the 80% range' : 'outside the 80% range')),
      h('td', {}, t.control ? h('b', { class: t.control === 'dem' ? 'dem-text' : 'rep-text' }, t.control === 'dem' ? 'Democrats' : 'Republicans') : h('span', { class: 'muted' }, 'Not yet decided')));
  }).filter(Boolean);
  el.replaceChildren(
    h('h2', { id: 'h-seats' }, 'Seats against the forecast'),
    h('p', { class: 'muted small' }, 'Democratic seats including those not up this year. "If leads hold" adds every uncalled race to whoever is ahead now.'),
    h('div', { class: 'table-wrap' }, h('table', { class: 'data' },
      h('thead', {}, h('tr', {}, h('th', {}, 'Chamber'), h('th', { class: 'num' }, 'Forecast seats'), h('th', { class: 'num' }, 'Chance of control'),
        h('th', { class: 'num' }, 'Won so far'), h('th', { class: 'num' }, 'If leads hold'), h('th', {}, 'Control'))),
      h('tbody', {}, ...rows))));
}

function renderUpsets(sc) {
  const el = document.getElementById('upsets');
  el.replaceChildren(
    h('h2', { id: 'h-upsets' }, `Upsets (${sc.upsets.length})`),
    h('p', { class: 'muted small' }, 'Called races the forecast’s underdog won, most surprising first.'),
    sc.upsets.length ? h('div', { class: 'table-wrap' }, h('table', { class: 'data' },
      h('thead', {}, h('tr', {}, h('th', {}, 'Race'), h('th', {}, 'Rating'), h('th', {}, 'Winner'), h('th', { class: 'num' }, 'Forecast chance for winner'), h('th', { class: 'num' }, 'Forecast margin'))),
      h('tbody', {}, ...sc.upsets.map((u) => {
        const side = u.demWon ? 'dem' : 'rep';
        const cand = u.race[side];
        const party = cand ? cand.party : side === 'dem' ? 'D' : 'R';
        return h('tr', {},
          h('td', {}, h('a', { href: raceHref(u.race.race_id) }, u.race.short), h('div', { class: 'muted small' }, displayName(u.race))),
          h('td', {}, ratingPill(u.race.label)),
          h('td', {}, h('span', { class: `call-chip ${partyClass(party)}` }, `${cand ? cand.name : side} (${party})`)),
          h('td', { class: 'num' }, `${Math.round((1 - u.conf) * 100)}%`),
          h('td', { class: 'num' }, isNum(u.race.margin) ? fmt.margin(u.race.margin) : '—'));
      }))))
      : h('p', { class: 'muted' }, 'None yet: every called race went to the favorite.'),
  );
}

main();
