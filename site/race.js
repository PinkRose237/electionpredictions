/**
 * race.js — race detail page (race.html?id=GA-SEN).
 *
 * Loads data/races/{id}.json (plus races.json for prev/next navigation) and renders:
 *   header, headline probability bar, candidates, polls (chart + table + other averages),
 *   expert ratings, markets, model breakdown, history sparkline, news, prev/next.
 */
import {
  SITE_NAME, CHAMBER_SINGULAR, STATE_NAMES, DASH,
  query, loadJSON, raceHref, withData, fmt, isNum, clamp, parseDate, relativeTime,
  probColor, paintProb, h, svgEl, scaleLinear, niceTicks, dateTicks, responsiveChart,
  tipContent, attachTooltip, partyVar, partyClass, partyName, ratingPill,
  initChrome, renderUpdated, renderFooterMeta, showError,
} from './common.js';

const id = (query.get('id') || '').trim();

/** Election-day label, replaced from summary.json once it loads (president data is 2028). */
let electionLabel = 'November 3, 2026';

/** "Arizona 1st District" for House races whose data name is just the id; otherwise the data name. */
function ordinal(n) {
  const v = n % 100;
  return n + (v >= 11 && v <= 13 ? 'th' : ['th', 'st', 'nd', 'rd'][n % 10] || 'th');
}
function displayName(race) {
  if (race && race.chamber === 'house' && race.state_name && race.district != null
      && (!race.name || race.name === race.short || race.name === race.race_id || /^[A-Z]{2}[- ]/.test(race.name))) {
    return race.district === 0 ? `${race.state_name} at-large District` : `${race.state_name} ${ordinal(race.district)} District`;
  }
  return (race && (race.name || race.race_id)) || id;
}

async function main() {
  initChrome({ current: 'dashboard' });
  const status = document.getElementById('status');
  const root = document.getElementById('race');
  if (!/^[A-Za-z0-9][A-Za-z0-9\-]{2,24}$/.test(id)) {
    showError(status, new Error('No race selected.'), 'Choose a race from the dashboard.');
    return;
  }
  let race, all, published;
  try {
    [race, all, published] = await Promise.all([
      loadJSON(`races/${encodeURIComponent(id)}.json`),
      loadJSON('races.json').catch(() => null),
      loadJSON('results.json').catch(() => null),
    ]);
  } catch (err) {
    console.error(err);
    showError(status, err, `There is no race with the id “${id}”.`);
    return;
  }
  loadJSON('summary.json').then((s) => {
    renderUpdated(s); renderFooterMeta(s);
    if (s && s.election_date) electionLabel = fmt.date(s.election_date);
    const eb = document.querySelector('[data-election-day]');
    if (eb) eb.textContent = electionLabel;
  }).catch(() => {});
  document.title = `${displayName(race)} — ${SITE_NAME}`;
  status.hidden = true;
  root.hidden = false;
  const back = race.chamber === 'president' ? 'president.html' : `index.html#${race.chamber || 'house'}`;
  root.append(
    h('a', { class: 'back-link', href: withData(back) }, race.chamber === 'president' ? '← Back to 2028 forecast' : '← Back to dashboard'),
    header(race),
    headline(race),
    h('div', { class: 'race-grid' },
      h('div', { class: 'col' }, resultsSection(race, published), overviewSection(race), candidatesSection(race), pollsSection(race), modelSection(race), newsSection(race)),
      h('div', { class: 'col' }, ratingsSection(race), marketsSection(race), historySection(race))),
    pager(race, all),
  );
}

// ---------------------------------------------------------------------------
// Header + headline
// ---------------------------------------------------------------------------

function header(race) {
  const chamber = CHAMBER_SINGULAR[race.chamber] || race.chamber || DASH;
  const chips = [];
  chips.push(race.state_name || STATE_NAMES[race.state] || race.state || DASH);
  chips.push(race.district == null ? chamber : `${chamber} · ${race.district === 0 ? 'At-large' : `District ${race.district}`}`);
  if (race.special) chips.push('Special election');
  if (race.chamber === 'president') {
    chips.push('Open seat · incumbent term-limited');
    if (isNum(race.evs)) chips.push(`${fmt.num(race.evs)} electoral votes`);
  } else if (race.incumbent) {
    const status = race.open_seat || race.incumbent_running === false ? 'Open seat' : race.incumbent_running ? 'Incumbent running' : 'Incumbent';
    chips.push(`${status}: ${race.incumbent}${race.incumbent_party ? ` (${race.incumbent_party})` : ''}`);
  } else {
    chips.push(race.holder_party ? `Vacant (last held by ${partyName(race.holder_party)})` : 'Vacant seat');
  }
  chips.push(`PVI ${race.pvi_label || (isNum(race.pvi) ? fmt.margin(race.pvi, 0) : DASH)}`);
  return h('header', { class: 'race-header' },
    h('div', { class: 'eyebrow' }, `${chamber}${race.short && race.chamber === 'house' ? ` · ${race.short}` : ''} · `, h('span', { 'data-election-day': '' }, electionLabel)),
    h('h1', {}, displayName(race)),
    h('div', { class: 'chips' }, chips.map((c) => h('span', { class: 'chip' }, c))),
  );
}

function candTitle(c, fallback) {
  return c && c.name ? `${c.name} (${c.party || '?'})` : fallback;
}

function headline(race) {
  const pD = race.p_dem;
  const pR = isNum(pD) ? 1 - pD : null;
  const dParty = (race.dem && race.dem.party) || 'D';
  const rParty = (race.rep && race.rep.party) || 'R';
  const sec = h('section', { class: 'card headline', 'aria-label': 'Forecast' });
  sec.append(
    h('div', { class: 'headline-probs' },
      h('div', { class: 'side' },
        h('div', { class: 'who' }, candTitle(race.dem, 'No Democratic candidate')),
        h('div', { class: 'big', style: { color: partyVar(dParty) } }, fmt.pct(pD)),
        h('div', { class: 'muted small' }, 'chance to win')),
      h('div', { class: 'side right' },
        h('div', { class: 'who' }, candTitle(race.rep, 'No Republican candidate')),
        h('div', { class: 'big', style: { color: partyVar(rParty) } }, fmt.pct(pR)),
        h('div', { class: 'muted small' }, 'chance to win'))),
  );
  const bar = h('div', { class: 'prob-bar', role: 'img', 'aria-label': `${fmt.pct(pD)} Democratic side, ${fmt.pct(pR)} Republican side` });
  if (isNum(pD)) {
    if (pD > 0) bar.append(h('span', { class: `seg ${partyClass(dParty)}`, style: { width: `${pD * 100}%` } }));
    if (pR > 0) bar.append(h('span', { class: `seg ${partyClass(rParty)}`, style: { width: `${pR * 100}%` } }));
  }
  sec.append(bar);
  const meta = h('div', { class: 'headline-meta' });
  meta.append(ratingPill(race.label));
  meta.append(h('span', {}, 'Model margin ', h('b', {}, fmt.margin(race.margin)), isNum(race.sd) ? h('span', { class: 'muted' }, ` ± ${fmt.dec(race.sd, 1)}`) : null));
  if (race.rating && race.rating.label) {
    meta.append(h('span', {}, 'Expert consensus ', h('b', {}, race.rating.label), h('span', { class: 'muted' }, race.rating.n ? ` (${race.rating.n} rater${race.rating.n === 1 ? '' : 's'})` : ' (unrated; safe for holder)')));
  } else {
    meta.append(h('span', {}, 'Expert consensus ', h('b', {}, DASH)));
  }
  if (race.polls && isNum(race.polls.margin)) meta.append(h('span', {}, 'Polls ', h('b', {}, fmt.margin(race.polls.margin)), h('span', { class: 'muted' }, ` (${fmt.num(race.polls.n)})`)));
  if (race.markets && isNum(race.markets.p_dem)) meta.append(h('span', {}, 'Markets ', h('b', {}, fmt.pct(race.markets.p_dem))));
  sec.append(meta);
  if (race.uncontested) sec.append(h('div', { class: 'uncontested-note' }, 'Uncontested / same-party general election — the model does not treat this seat as a contest.'));
  return sec;
}

// ---------------------------------------------------------------------------
// Candidates
// ---------------------------------------------------------------------------

function kv(label, value) {
  return [h('dt', {}, label), h('dd', {}, value)];
}

function candidatesSection(race) {
  const sec = h('section', { class: 'card', 'aria-labelledby': 'h-cands' }, h('h2', { id: 'h-cands' }, 'Candidates'));
  const full = Array.isArray(race.candidates) ? race.candidates : [];
  const detail = (c) => (c ? full.find((x) => x.name === c.name && x.party === c.party) || {} : {});
  const card = (c, side) => {
    const cls = c ? partyClass(c.party) : partyClass(side);
    const el = h('div', { class: `cand-card ${cls}` });
    if (!c || !c.name) {
      el.append(h('div', { class: 'name none' }, side === 'D' ? 'No Democratic-side candidate' : 'No Republican-side candidate'));
      return el;
    }
    const d = detail(c);
    el.append(
      h('div', { class: 'name' }, c.name, h('span', { class: `badge ${cls}` }, partyName(c.party)), c.incumbent ? h('span', { class: 'badge' }, 'Incumbent') : null),
      h('dl', { class: 'kv' },
        kv('Receipts', fmt.money(c.receipts)),
        kv('Cash on hand', fmt.money(c.cash)),
        kv('FEC data through', d.coverage_end ? fmt.date(d.coverage_end) : DASH)),
    );
    return el;
  };
  sec.append(h('div', { class: 'cand-cards' }, card(race.dem, 'D'), card(race.rep, 'R')));
  if (full.length) {
    sec.append(h('div', { class: 'table-wrap' },
      h('table', { class: 'data' },
        h('thead', {}, h('tr', {},
          h('th', { scope: 'col' }, 'Candidate'), h('th', { scope: 'col' }, 'Party'), h('th', { scope: 'col' }, 'Status'),
          h('th', { scope: 'col', class: 'num' }, 'Receipts'), h('th', { scope: 'col', class: 'num' }, 'Spent'),
          h('th', { scope: 'col', class: 'num' }, 'Cash on hand'), h('th', { scope: 'col' }, 'Through'))),
        h('tbody', {}, full.map((c) => h('tr', {},
          h('td', {}, h('span', { class: `party-dot ${partyClass(c.party)}`, 'aria-hidden': 'true' }), c.name || DASH),
          h('td', {}, partyName(c.party)),
          h('td', {}, [c.incumbent ? 'Incumbent' : null, c.major === false ? 'Minor' : null].filter(Boolean).join(' · ') || DASH),
          h('td', { class: 'num' }, fmt.money(c.receipts)), h('td', { class: 'num' }, fmt.money(c.disbursements)),
          h('td', { class: 'num' }, fmt.money(c.cash)), h('td', {}, c.coverage_end ? fmt.dateShort(c.coverage_end) : DASH)))))));
  } else {
    sec.append(h('p', { class: 'muted small' }, 'No candidate list available.'));
  }
  return sec;
}

// ---------------------------------------------------------------------------
// Polls
// ---------------------------------------------------------------------------

function sponsorColor(lean) {
  return lean === 'D' ? 'var(--dem)' : lean === 'R' ? 'var(--rep)' : 'var(--ink-3)';
}

function pollsSection(race) {
  const sec = h('section', { class: 'card', 'aria-labelledby': 'h-polls' }, h('h2', { id: 'h-polls' }, 'Polls'));
  const polls = Array.isArray(race.poll_list) ? race.poll_list : [];
  const model = race.model || {};
  const avg = race.polls && isNum(race.polls.margin) ? race.polls.margin : isNum(model.poll_margin) ? model.poll_margin : null;
  if (!polls.length) {
    sec.append(h('p', { class: 'muted' }, 'No polls found for this race.'));
  } else {
    const used = polls.filter((p) => isNum(p.weight) && p.weight > 0).length;
    sec.append(h('p', { class: 'card-sub' },
      `${fmt.num(polls.length)} poll${polls.length === 1 ? '' : 's'} · ${fmt.num(used)} used by the model · model average ${fmt.margin(avg)}`,
      race.polls && isNum(race.polls.n_eff) ? ` (${fmt.dec(race.polls.n_eff, 1)} effective polls)` : ''));
    const box = h('div', { class: 'chart-box' });
    sec.append(box);
    responsiveChart(box, (w) => drawPolls(w, polls, avg));
    sec.append(h('div', { class: 'legend' },
      h('span', { class: 'legend-item' }, h('span', { class: 'legend-dot', style: { background: 'var(--ink-3)' } }), 'Nonpartisan'),
      h('span', { class: 'legend-item' }, h('span', { class: 'legend-dot', style: { background: 'var(--dem)' } }), 'D-aligned sponsor'),
      h('span', { class: 'legend-item' }, h('span', { class: 'legend-dot', style: { background: 'var(--rep)' } }), 'R-aligned sponsor'),
      h('span', { class: 'legend-item' }, h('span', { class: 'legend-dot hollow' }), 'Hypothetical matchup'),
      h('span', { class: 'legend-item' }, 'Size = model weight')));
    sec.append(pollTable(polls));
  }
  const aggs = Array.isArray(race.poll_aggregates) ? race.poll_aggregates : [];
  if (aggs.length) {
    sec.append(
      h('h3', { style: { marginTop: '20px', marginBottom: '8px' } }, 'Other averages'),
      h('div', { class: 'table-wrap' },
        h('table', { class: 'data' },
          h('thead', {}, h('tr', {}, h('th', { scope: 'col' }, 'Source'), h('th', { scope: 'col' }, 'As of'),
            h('th', { scope: 'col', class: 'num' }, 'D'), h('th', { scope: 'col', class: 'num' }, 'R'), h('th', { scope: 'col', class: 'num' }, 'Margin'))),
          h('tbody', {}, aggs.map((a) => h('tr', {},
            h('td', {}, a.source || DASH), h('td', {}, a.as_of ? fmt.dateShort(a.as_of) : DASH),
            h('td', { class: 'num' }, fmt.dec(a.dem, 1)), h('td', { class: 'num' }, fmt.dec(a.rep, 1)),
            h('td', { class: 'num' }, h('b', {}, fmt.margin(a.margin)))))))));
  }
  return sec;
}

function drawPolls(w, polls, avg) {
  const pts = polls.filter((p) => isNum(p.margin) && parseDate(p.end_date || p.start_date));
  if (!pts.length) return h('p', { class: 'muted small' }, 'Polls lack dates or margins to chart.');
  const H = 250, m = { t: 18, r: 18, b: 32, l: 44 };
  const times = pts.map((p) => parseDate(p.end_date || p.start_date).getTime());
  let t0 = Math.min(...times) - 2 * 864e5, t1 = Math.max(...times) + 2 * 864e5;
  if (t1 - t0 < 14 * 864e5) { const mid = (t0 + t1) / 2; t0 = mid - 7 * 864e5; t1 = mid + 7 * 864e5; }
  const vals = pts.map((p) => Math.abs(p.margin)).concat(isNum(avg) ? [Math.abs(avg)] : []);
  const vmax = Math.max(5, Math.ceil((Math.max(...vals) + 1) / 5) * 5);
  const x = scaleLinear([t0, t1], [m.l, w - m.r]);
  const y = scaleLinear([-vmax, vmax], [H - m.b, m.t]);
  const svg = svgEl('svg', {
    class: 'chart polls', viewBox: `0 0 ${w} ${H}`, width: w, height: H, role: 'img',
    'aria-label': 'Poll margins over time with the model polling average',
  });
  for (const v of niceTicks(-vmax, vmax, 6)) {
    svg.append(svgEl('line', { class: v === 0 ? 'axis' : 'grid', x1: m.l, x2: w - m.r, y1: y(v), y2: y(v) }));
    svg.append(svgEl('text', { class: 'tick', x: m.l - 6, y: y(v) + 4, 'text-anchor': 'end' }, v === 0 ? 'Even' : fmt.margin(v, 0)));
  }
  for (const t of dateTicks(t0, t1, Math.max(2, Math.floor((w - m.l - m.r) / 80)))) {
    svg.append(svgEl('text', { class: 'tick', x: x(t), y: H - m.b + 18, 'text-anchor': 'middle' },
      new Date(t).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })));
  }
  if (isNum(avg)) {
    svg.append(svgEl('line', { class: 'ref', x1: m.l, x2: w - m.r, y1: y(avg), y2: y(avg), style: 'stroke: var(--ink)' }));
    svg.append(svgEl('text', { class: 'ref-label', x: m.l + 4, y: y(avg) - 5, 'text-anchor': 'start' }, `Model average ${fmt.margin(avg)}`));
  }
  // Draw low-weight polls first so the ones the model uses sit on top.
  const order = pts.map((p, i) => i).sort((a, b) => (pts[a].weight || 0) - (pts[b].weight || 0));
  for (const i of order) {
    const p = pts[i];
    const cx = x(times[i]), cy = y(p.margin);
    const wgt = isNum(p.weight) ? clamp(p.weight, 0, 1) : 0;
    const r = 3.5 + 5 * wgt;
    const color = sponsorColor(p.sponsor_lean);
    const g = svgEl('g', { tabindex: '0', role: 'img', 'aria-label': `${p.pollster || 'Poll'}, ${fmt.dateRange(p.start_date, p.end_date)}: ${fmt.margin(p.margin)}` });
    g.append(svgEl('circle', { class: 'hit', cx, cy, r: Math.max(12, r + 6) }));
    g.append(p.hypothetical
      ? svgEl('circle', { class: 'mark', cx, cy, r, style: `fill: var(--surface); stroke: ${color}; stroke-width: 2` })
      : svgEl('circle', { class: 'marker mark', cx, cy, r, fill: color }));
    attachTooltip(g, () => {
      const rows = [
        ['Dates', fmt.dateRange(p.start_date, p.end_date)],
        ['Sample', `${isNum(p.sample_size) ? fmt.num(p.sample_size) : DASH}${p.population ? ` ${p.population}` : ''}`],
        ['Result', `${p.dem_pct != null ? `D ${fmt.dec(p.dem_pct, 0)}` : 'D —'} · ${p.rep_pct != null ? `R ${fmt.dec(p.rep_pct, 0)}` : 'R —'}${isNum(p.und_pct) ? ` · und. ${fmt.dec(p.und_pct, 0)}` : ''}`],
        ['Margin', fmt.margin(p.margin)],
        ['Model weight', fmt.dec(p.weight, 2)],
      ];
      const out = tipContent(p.pollster || 'Poll', rows);
      const notes = [];
      if (p.sponsor_lean) notes.push(`${p.sponsor_lean}-aligned sponsor`);
      if (p.hypothetical) notes.push('hypothetical matchup');
      if (notes.length) out.push(h('div', { class: 'tip-note' }, notes.join(' · ')));
      return out;
    });
    svg.append(g);
  }
  return svg;
}

function pollTable(polls) {
  const head = ['Pollster', 'Dates', 'Sample', 'MoE', 'D', 'R', 'Und.', 'Margin', 'Weight'];
  const numeric = new Set(['Sample', 'MoE', 'D', 'R', 'Und.', 'Margin', 'Weight']);
  return h('div', { class: 'table-wrap', style: { marginTop: '12px' } },
    h('table', { class: 'data' },
      h('caption', {}, 'Newest first. Weight is the model’s weight after recency, sample size, population and sponsor adjustments; 0 = ignored (too old, or a hypothetical matchup when real ones exist).'),
      h('thead', {}, h('tr', {}, head.map((t) => h('th', { scope: 'col', class: numeric.has(t) ? 'num' : null }, t)))),
      h('tbody', {}, polls.map((p) => h('tr', { style: isNum(p.weight) && p.weight === 0 ? { color: 'var(--ink-3)' } : null },
        h('td', {}, p.pollster || DASH,
          p.sponsor_lean ? h('span', { class: `badge ${partyClass(p.sponsor_lean)}`, style: { marginLeft: '6px' }, title: `${p.sponsor_lean}-aligned sponsor` }, `${p.sponsor_lean} spons.`) : null,
          p.hypothetical ? h('span', { class: 'badge', style: { marginLeft: '6px' }, title: 'Hypothetical matchup' }, 'Hyp.') : null),
        h('td', {}, fmt.dateRange(p.start_date, p.end_date)),
        h('td', { class: 'num' }, isNum(p.sample_size) ? fmt.num(p.sample_size) : DASH, p.population ? h('span', { class: 'muted' }, ` ${p.population}`) : null),
        h('td', { class: 'num' }, isNum(p.moe) ? `±${fmt.dec(p.moe, 1)}` : DASH),
        h('td', { class: 'num' }, fmt.dec(p.dem_pct, 1)),
        h('td', { class: 'num' }, fmt.dec(p.rep_pct, 1)),
        h('td', { class: 'num' }, fmt.dec(p.und_pct, 1)),
        h('td', { class: 'num' }, h('b', {}, fmt.margin(p.margin))),
        h('td', { class: 'num' }, fmt.dec(p.weight, 2)))))));
}

// ---------------------------------------------------------------------------
// Ratings + markets
// ---------------------------------------------------------------------------

function ratingsSection(race) {
  const sec = h('section', { class: 'card', 'aria-labelledby': 'h-ratings' }, h('h2', { id: 'h-ratings' }, 'Expert ratings'));
  const list = Array.isArray(race.ratings) ? race.ratings : [];
  if (race.rating && race.rating.label) {
    sec.append(h('p', { class: 'card-sub' }, 'Consensus ', h('b', {}, race.rating.label),
      isNum(race.rating.score) ? ` · score ${fmt.signed(race.rating.score, 1)} on a −4 to +4 scale` : ''));
  }
  if (!list.length) {
    sec.append(h('p', { class: 'muted small' }, race.rating && race.rating.n === 0
      ? 'No rater lists this race; the model treats it as safe for the seat holder.'
      : 'No expert ratings available.'));
    return sec;
  }
  sec.append(h('div', { class: 'table-wrap' },
    h('table', { class: 'data' },
      h('thead', {}, h('tr', {}, h('th', { scope: 'col' }, 'Rater'), h('th', { scope: 'col' }, 'Rating'), h('th', { scope: 'col' }, 'As of'))),
      h('tbody', {}, list.map((r) => h('tr', {},
        h('td', {}, r.rater || DASH), h('td', {}, ratingPill(r.rating)), h('td', {}, r.as_of ? fmt.dateShort(r.as_of) : DASH)))))));
  return sec;
}

function marketsSection(race) {
  const sec = h('section', { class: 'card', 'aria-labelledby': 'h-markets' }, h('h2', { id: 'h-markets' }, 'Prediction markets'));
  const list = Array.isArray(race.market_list) ? race.market_list : [];
  if (!list.length) {
    sec.append(h('p', { class: 'muted small' }, 'No prediction market found for this race.'));
    return sec;
  }
  const hasOther = list.some((mk) => isNum(mk.p_other));
  sec.append(h('p', { class: 'card-sub' }, 'For comparison only — markets are not a model input.'));
  sec.append(h('div', { class: 'table-wrap' },
    h('table', { class: 'data' },
      h('thead', {}, h('tr', {},
        h('th', { scope: 'col' }, 'Platform'), h('th', { scope: 'col', class: 'num' }, 'D'), h('th', { scope: 'col', class: 'num' }, 'R'),
        hasOther ? h('th', { scope: 'col', class: 'num' }, 'Other') : null,
        h('th', { scope: 'col', class: 'num' }, 'Volume'), h('th', { scope: 'col' }, 'Link'))),
      h('tbody', {}, list.map((mk) => h('tr', {},
        h('td', { title: mk.title || null }, fmt.platform(mk.platform)),
        h('td', { class: 'num' }, fmt.pct(mk.p_dem)), h('td', { class: 'num' }, fmt.pct(mk.p_rep)),
        hasOther ? h('td', { class: 'num' }, fmt.pct(mk.p_other)) : null,
        h('td', { class: 'num' }, fmt.money(mk.volume)),
        h('td', {}, mk.url ? h('a', { href: mk.url, target: '_blank', rel: 'noopener', 'aria-label': `Open ${fmt.platform(mk.platform)} market` }, 'Open ↗') : DASH)))))));
  const fetched = list.map((mk) => mk.fetched_at).filter(Boolean).sort().pop();
  if (fetched) sec.append(h('p', { class: 'muted small', style: { marginTop: '8px' } }, `Prices fetched ${relativeTime(fetched)}.`));
  return sec;
}

// ---------------------------------------------------------------------------
// Election results (entered on the admin page, published as data/results.json)
// ---------------------------------------------------------------------------

function resultsSection(race, published) {
  const e = published && published.races ? published.races[race.race_id] : null;
  if (!e) return null;
  const sec = h('section', { class: 'card results', 'aria-labelledby': 'h-results' }, h('h2', { id: 'h-results' }, 'Election results'));
  const d = e.votes && e.votes.dem || 0, r = e.votes && e.votes.rep || 0, o = e.votes && e.votes.other || 0, tot = d + r + o;
  const label = { pending: 'Not started', counting: 'Counting', called: 'Called', runoff: 'Headed to a runoff', recount: 'Recount', final: 'Final' }[e.status] || e.status;
  const winner = e.winner === 'dem' ? race.dem : e.winner === 'rep' ? race.rep : null;
  sec.append(h('p', { class: 'card-sub' }, h('b', {}, winner && (e.status === 'called' || e.status === 'final') ? `${label} for ${winner.name}` : label),
    isNum(e.reporting) ? ` · ${e.reporting}% reporting` : '', e.updated_at ? ` · updated ${relativeTime(e.updated_at)}` : ''));
  if (tot > 0) {
    const rows = [[race.dem, d], [race.rep, r]].filter(([c]) => c).map(([c, v]) => h('tr', {}, h('td', {}, c.name, ` (${c.party})`), h('td', { class: 'num' }, v.toLocaleString()), h('td', { class: 'num' }, `${(100 * v / tot).toFixed(1)}%`)));
    if (o) rows.push(h('tr', {}, h('td', {}, 'Other'), h('td', { class: 'num' }, o.toLocaleString()), h('td', { class: 'num' }, `${(100 * o / tot).toFixed(1)}%`)));
    sec.append(h('div', { class: 'table-wrap' }, h('table', { class: 'data' }, h('thead', {}, h('tr', {}, h('th', {}, 'Candidate'), h('th', { class: 'num' }, 'Votes'), h('th', { class: 'num' }, 'Share'))), h('tbody', {}, ...rows))));
  }
  if (e.note) sec.append(h('p', { class: 'muted small' }, e.note));
  sec.append(h('p', { class: 'muted small' }, 'Unofficial results entered by the site editor; official results come from the state.'));
  return sec;
}

// ---------------------------------------------------------------------------
// Race overview
// ---------------------------------------------------------------------------

/** Two short paragraphs on where the race stands, when the pipeline has produced them. */
function overviewSection(race) {
  const text = typeof race.overview === 'string' ? race.overview.trim() : '';
  if (!text) return null;
  const sec = h('section', { class: 'card brief', 'aria-labelledby': 'h-overview' }, h('h2', { id: 'h-overview' }, 'Race overview'));
  for (const para of text.split(/\n\s*\n/).map((t) => t.trim()).filter(Boolean)) sec.append(h('p', {}, para));
  const m = race.model || {};
  if (m.watch) sec.append(h('p', { class: 'muted small' }, 'What to watch: ', m.watch));
  return sec;
}

// ---------------------------------------------------------------------------
// Model breakdown
// ---------------------------------------------------------------------------

function modelSection(race) {
  const sec = h('section', { class: 'card', 'aria-labelledby': 'h-model' }, h('h2', { id: 'h-model' }, 'How the model gets here'));
  const m = race.model || {};
  const f = m.fundamentals || {};
  const pollW = isNum(m.poll_weight) ? m.poll_weight : null;
  const rows = [
    { label: 'Partisan lean', sub: race.pvi_label ? `Cook PVI ${race.pvi_label}` : 'Cook PVI', v: f.lean },
    { label: 'National environment', sub: 'generic ballot × chamber weight', v: f.environment },
    { label: 'Incumbency', v: f.incumbency },
    { label: 'Fundraising', sub: '1.5 × log10(D ÷ R receipts), capped ±3', v: f.money },
    { label: 'Fundamentals', v: f.margin, total: true },
    { divider: true },
    { label: 'Expert-rating margin', sub: isNum(m.rating_margin) ? 'average implied margin' : 'no rater lists this race', v: m.rating_margin },
    { label: 'Prior', sub: isNum(m.rating_margin) ? '40% fundamentals + 60% ratings' : 'fundamentals only', v: m.prior_margin, sd: m.prior_sd, total: true },
    { divider: true },
    { label: 'Polling average', sub: isNum(m.poll_margin) ? `weight ${fmt.pct(pollW)}` : 'no usable polls', v: m.poll_margin, sd: m.poll_sd },
  ];
  if (isNum(m.baseline_margin) && isNum(m.analyst_adjustment)) {
    rows.push({ label: 'Baseline margin', sub: pollW != null ? `${fmt.pct(pollW)} polls + ${fmt.pct(1 - pollW)} prior` : 'prior only', v: m.baseline_margin, total: true });
    rows.push({ divider: true });
    rows.push({ label: 'Race review', sub: m.confidence ? `${m.confidence} confidence` : 'evidence review', v: m.analyst_adjustment });
    rows.push({ label: 'Forecast margin', v: isNum(race.margin) ? race.margin : null, sd: isNum(race.sd) ? race.sd : m.sigma_total, total: true });
  } else {
    rows.push({ label: 'Model margin', sub: pollW != null ? `${fmt.pct(pollW)} polls + ${fmt.pct(1 - pollW)} prior` : 'prior only', v: isNum(race.margin) ? race.margin : null, sd: isNum(race.sd) ? race.sd : m.sigma_total, total: true });
  }
  const vals = rows.map((r) => r.v).filter(isNum).map(Math.abs);
  const scale = Math.max(5, Math.ceil((Math.max(0, ...vals) + 0.5) / 5) * 5);
  const grid = h('div', { class: 'waterfall', role: 'table', 'aria-label': 'Model margin breakdown' });
  for (const r of rows) {
    if (r.divider) { grid.append(h('div', { class: 'divider', role: 'presentation' })); continue; }
    const cls = r.total ? 'total' : '';
    const track = h('div', { class: `wf-track ${cls}` });
    if (isNum(r.v) && Math.abs(r.v) > 0.001) {
      const pct = Math.min(50, (Math.abs(r.v) / scale) * 50);
      track.append(h('span', { class: `wf-bar ${r.v > 0 ? 'dem' : 'rep'}`, style: r.v > 0 ? { left: '50%', width: `${pct}%` } : { right: '50%', width: `${pct}%` } }));
    }
    grid.append(
      h('div', { class: `wf-label ${cls}`, role: 'cell' }, r.label, r.sub ? h('small', {}, r.sub) : null),
      h('div', { class: `wf-cell ${cls}`, role: 'cell' }, track),
      h('div', { class: `wf-value ${cls}`, role: 'cell' }, fmt.margin(r.v), isNum(r.v) && isNum(r.sd) ? h('small', {}, ` ± ${fmt.dec(r.sd, 1)}`) : null),
    );
  }
  sec.append(h('p', { class: 'card-sub' }, 'Margins are Democratic minus Republican, in points. Bars extend right for D, left for R.'), grid);
  sec.append(h('div', { class: 'model-stats' },
    h('span', {}, 'Race-specific σ ', h('b', {}, fmt.dec(m.sigma_race, 1))),
    h('span', {}, 'Total σ (with national, regional and state swings) ', h('b', {}, fmt.dec(m.sigma_total, 1))),
    h('span', {}, 'Win probability ', h('b', {}, fmt.pct(race.p_dem)), ' D')));
  const factors = Array.isArray(m.key_factors) ? m.key_factors.filter(Boolean) : [];
  if (factors.length) {
    sec.append(h('h3', { class: 'sub-h' }, 'Key factors'), h('ul', { class: 'model-notes factors' }, factors.map((f) => h('li', {}, String(f)))));
    if (m.rationale) sec.append(h('p', { class: 'muted small' }, m.rationale));
  }
  const notes = Array.isArray(m.notes) ? m.notes.filter(Boolean) : [];
  if (notes.length) sec.append(h('ul', { class: 'model-notes' }, notes.map((n) => h('li', {}, String(n)))));
  return sec;
}

// ---------------------------------------------------------------------------
// History, news, navigation
// ---------------------------------------------------------------------------

function historySection(race) {
  const sec = h('section', { class: 'card', 'aria-labelledby': 'h-history' }, h('h2', { id: 'h-history' }, 'Forecast history'));
  const hist = (Array.isArray(race.history) ? race.history : []).filter((d) => d && parseDate(d.date) && isNum(d.p_dem));
  hist.sort((a, b) => parseDate(a.date) - parseDate(b.date));
  if (!hist.length) {
    sec.append(h('p', { class: 'muted small' }, 'No history yet.'));
    return sec;
  }
  const box = h('div', { class: 'chart-box' });
  sec.append(h('p', { class: 'card-sub' }, 'Chance of a Democratic win, by model run'), box);
  responsiveChart(box, (w) => drawSparkline(w, hist));
  if (hist.length < 3) sec.append(h('p', { class: 'chart-note' }, `${hist.length} model run${hist.length === 1 ? '' : 's'} so far — history accumulates daily.`));
  return sec;
}

function drawSparkline(w, hist) {
  const H = 120, m = { t: 12, r: 56, b: 24, l: 36 };
  const times = hist.map((d) => parseDate(d.date).getTime());
  let t0 = Math.min(...times), t1 = Math.max(...times);
  if (t1 - t0 < 6 * 864e5) { const mid = (t0 + t1) / 2; t0 = mid - 3 * 864e5; t1 = mid + 3 * 864e5; }
  const x = scaleLinear([t0, t1], [m.l, w - m.r]);
  const y = scaleLinear([0, 1], [H - m.b, m.t]);
  const svg = svgEl('svg', { class: 'chart spark', viewBox: `0 0 ${w} ${H}`, width: w, height: H, role: 'img', 'aria-label': 'Democratic win probability over time' });
  for (const v of [0, 0.5, 1]) {
    svg.append(svgEl('line', { class: v === 0.5 ? 'axis' : 'grid', x1: m.l, x2: w - m.r, y1: y(v), y2: y(v) }));
    svg.append(svgEl('text', { class: 'tick', x: m.l - 6, y: y(v) + 4, 'text-anchor': 'end' }, `${v * 100}%`));
  }
  for (const t of dateTicks(t0, t1, Math.max(2, Math.floor((w - m.l - m.r) / 80)))) {
    svg.append(svgEl('text', { class: 'tick', x: x(t), y: H - m.b + 16, 'text-anchor': 'middle' }, new Date(t).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })));
  }
  const last = hist[hist.length - 1];
  const color = probColor(last.p_dem);
  if (hist.length > 1) {
    svg.append(svgEl('path', { class: 'series', d: hist.map((d, i) => `${i ? 'L' : 'M'}${x(times[i]).toFixed(1)} ${y(d.p_dem).toFixed(1)}`).join(' '), stroke: color }));
  }
  hist.forEach((d, i) => {
    const g = svgEl('g', { tabindex: '0', role: 'img', 'aria-label': `${fmt.date(d.date)}: ${fmt.pct(d.p_dem)}` });
    g.append(svgEl('circle', { class: 'hit', cx: x(times[i]), cy: y(d.p_dem), r: 12 }), svgEl('circle', { class: 'marker mark', cx: x(times[i]), cy: y(d.p_dem), r: 4, fill: color }));
    attachTooltip(g, () => tipContent(fmt.date(d.date), [['D win', fmt.pct(d.p_dem)], ['Margin', fmt.margin(d.margin)]]));
    svg.append(g);
  });
  svg.append(svgEl('text', { class: 'label', x: x(times[times.length - 1]) + 10, y: y(last.p_dem) + 4 }, fmt.pct(last.p_dem)));
  return svg;
}

function newsSection(race) {
  const sec = h('section', { class: 'card', 'aria-labelledby': 'h-news' }, h('h2', { id: 'h-news' }, 'In the news'));
  const news = Array.isArray(race.news) ? race.news.filter((n) => n && n.title) : [];
  if (!news.length) {
    sec.append(h('p', { class: 'muted small' }, 'No recent headlines found.'));
    return sec;
  }
  sec.append(h('ul', { class: 'news-list' }, news.map((n) => h('li', {},
    n.url ? h('a', { href: n.url, target: '_blank', rel: 'noopener' }, n.title) : h('span', {}, n.title),
    h('div', { class: 'news-meta' }, [n.source, n.published ? relativeTime(n.published) : null].filter(Boolean).join(' · '))))));
  return sec;
}

function pager(race, all) {
  const nav = h('nav', { class: 'pager', 'aria-label': 'Previous and next race' });
  if (!Array.isArray(all)) return nav;
  const list = all.filter((r) => r.chamber === race.chamber);
  const i = list.findIndex((r) => r.race_id === race.race_id);
  const prev = i > 0 ? list[i - 1] : null;
  const next = i >= 0 && i < list.length - 1 ? list[i + 1] : null;
  nav.append(
    prev ? h('a', { href: raceHref(prev.race_id), rel: 'prev' }, h('small', {}, '← Previous'), displayName(prev)) : h('span'),
    next ? h('a', { href: raceHref(next.race_id), rel: 'next', style: { textAlign: 'right' } }, h('small', {}, 'Next →'), displayName(next)) : h('span'),
  );
  return nav;
}

main();
