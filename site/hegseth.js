import { loadJSON, h, fmt, initChrome, renderFooterMeta, relativeTime, showError, watchForUpdates } from './common.js';
import { trendChart } from './charts.js';

const COLORS = { forced_exit: '#92712b', fired: '#95692e', impeached: '#6b64b0', removed: '#37857e' };
const METRICS = [
  ['forced_exit', 'Fired or removed', 'Presidential dismissal or Senate conviction and removal. Resignation is counted separately.'],
  ['fired', 'Fired by the president', 'Dismissed from this tenure by the president, whether before or after a House impeachment.'],
  ['impeached', 'Impeached by the House', 'At least one article adopted before departure. Introducing articles or opening an inquiry does not count.'],
  ['removed', 'Convicted & removed', 'Impeached, then convicted by the Senate while still in office.'],
];
let data;
let horizon = '90d';

function link(url, title) {
  try {
    if (new URL(url).protocol !== 'https:') return h('span', {}, title);
  } catch { return h('span', {}, title); }
  return h('a', { href: url, target: '_blank', rel: 'noopener noreferrer' }, title);
}

async function main() {
  initChrome({ current: 'hegseth' });
  const status = document.getElementById('status');
  try {
    data = await loadJSON('hegseth.json');
    if (!data.available) {
      status.textContent = data.message || 'Tracking has not begun.';
      return;
    }
    status.hidden = true;
    document.getElementById('app').hidden = false;
    document.querySelector('[data-updated]').textContent = `Tracker updated ${relativeTime(data.generated_at)}`;
    renderFooterMeta(data);
    watchForUpdates(data.generated_at, { file: 'hegseth.json', message: 'The Hegseth tracker has been updated.' });
    document.getElementById('assessment').textContent = data.summary;
    const states = { serving: 'Serving in office', impeached: 'Impeached; still serving', fired: 'Fired', resigned: 'Resigned', removed: 'Convicted and removed' };
    document.getElementById('office-status').replaceChildren(
      h('strong', {}, `Last verified status: ${states[data.status.state] || 'unverified'}`),
      ` · status last verified ${fmt.date(data.status.verified_on)} · `, link(data.status.url, 'Source'));
    const reviewLine = document.getElementById('review-status');
    reviewLine.textContent = `${data.initial_assumptions ? 'Initial assumptions dated ' + fmt.date(data.reviewed_at.slice(0, 10)) : 'Assumptions reviewed ' + fmt.dateTime(data.reviewed_at)}. ` +
      (data.review_stale ? 'Review is more than two days old; interpret the estimates with caution.' : 'Headlines and review times are shown separately below.');
    reviewLine.classList.toggle('tracker-stale', data.review_stale);
    if (data.as_of >= data.term_end) {
      document.getElementById('horizon-controls').hidden = true;
      document.getElementById('forecast-content').hidden = true;
      reviewLine.textContent = 'The forecast window has ended. The evidence and review history remain available below.';
    } else {
      document.querySelectorAll('[data-horizon]').forEach((btn) => {
        btn.addEventListener('click', () => { horizon = btn.dataset.horizon; renderHorizon(); });
      });
      renderHorizon();
    }
    renderSources(); renderNews(); renderAssumptions(); renderReviews();
  } catch (err) {
    document.getElementById('app').hidden = true;
    showError(status, err, 'The tracker is exported by the regular pipeline, or with electionpredictions hegseth.');
  }
}

function renderHorizon() {
  const selected = data.horizons.find((x) => x.id === horizon);
  document.querySelectorAll('[data-horizon]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.horizon === horizon)));
  document.getElementById('horizon-description').textContent = `${selected.label} · from ${fmt.date(data.as_of)} to before ${fmt.date(selected.deadline)} (${selected.days} days)`;
  document.getElementById('odds').replaceChildren(...METRICS.map(([key, label, description]) => {
    const p = selected.probabilities[key];
    const range = selected.sensitivity[key];
    return h('article', { class: `card tracker-odds${key === 'forced_exit' ? ' tracker-primary' : ''}`, style: { '--tracker-color': COLORS[key] } },
      h('h2', {}, label), h('div', { class: 'tracker-number num' }, fmt.pct(p)),
      h('div', { class: 'tracker-meter', 'aria-hidden': 'true' }, h('span', { style: { width: `${p * 100}%` } })),
      h('p', { class: 'small muted' }, `Sensitivity: ${fmt.pct(range[0])}–${fmt.pct(range[1])}`),
      h('p', { class: 'small' }, description));
  }));
  document.getElementById('departure-context').replaceChildren(
    h('span', {}, 'Resignation: ', h('strong', {}, fmt.pct(selected.probabilities.resigned))),
    h('span', {}, 'Any modeled departure: ', h('strong', {}, fmt.pct(selected.probabilities.any_exit))),
    h('span', {}, 'Still serving: ', h('strong', {}, fmt.pct(selected.probabilities.still_serving))));
  document.getElementById('overlap-note').textContent = 'Firing and Senate removal are distinct ways to leave office; their probabilities add to “Fired or removed.” House impeachment can precede either departure and must not be added to those odds. Requested resignations count as resignation.';
  const history = (data.history || []).map((point) => {
    const entry = point.horizons.find((x) => x.id === horizon);
    return { date: point.date, ...(entry?.probabilities || {}) };
  });
  const chart = document.getElementById('trend');
  // Keep one chart per horizon: shared charts retain resize/theme listeners, so
  // repeatedly mounting on the same container would leave competing callbacks.
  chart.querySelectorAll('[data-trend-horizon]').forEach((el) => { el.hidden = el.dataset.trendHorizon !== horizon; });
  if (!chart.querySelector(`[data-trend-horizon="${horizon}"]`)) {
    const panel = h('div', { dataset: { trendHorizon: horizon } });
    chart.append(panel);
    if (history.length < 2) {
      panel.append(h('p', { class: 'muted tracker-empty' }, 'Tracking starts with the first saved observation. A trend will appear after the next day’s update; no history has been backfilled.'));
    } else {
      trendChart(panel, history, { ref: null, height: 250,
        series: METRICS.filter(([key]) => key !== 'fired').map(([key, label]) => ({ label, color: COLORS[key], value: (d) => d[key] })),
        label: `Hegseth ${selected.label.toLowerCase()} forecast history` });
    }
  }
  document.getElementById('trend-note').textContent = horizon === 'term'
    ? 'Daily estimates for the fixed deadline of January 20, 2029.'
    : `Daily estimates for a rolling ${horizon === '30d' ? '30' : '90'}-day window. Each observation has its own deadline.`;
}

function renderSources() {
  document.getElementById('evidence').replaceChildren(...data.sources.map((s) => h('li', {},
    h('div', { class: 'news-meta' }, s.source, s.date ? ` · ${fmt.date(s.date)}` : ' · Process reference'),
    h('h3', {}, link(s.url, s.title)), h('p', { class: 'small' }, s.detail))));
}

function renderNews() {
  const latest = data.last_update;
  document.getElementById('news-status').textContent = data.news_fetched_at
    ? `Last successful collection: ${fmt.dateTime(data.news_fetched_at)}. Headlines are coverage, not confirmed outcomes.`
    : 'No live headlines collected yet. The initial assessment uses the dated sources shown alongside.';
  const warning = document.getElementById('collection-warning');
  if (latest && !latest.ok) {
    warning.hidden = false;
    warning.textContent = 'The latest collection or review had a problem. The tracker retains the last available evidence and assumptions.';
  }
  document.getElementById('coverage').replaceChildren(...data.news.map((s) => h('li', {},
    link(s.url, s.title), h('div', { class: 'news-meta' }, `${s.source || 'News'} · ${fmt.date(s.published)}`))));
}

function renderAssumptions() {
  const names = { firing: 'Firing, conditional on serving', resignation: 'Resignation, conditional on serving',
    impeachment: 'House impeachment, conditional on serving without prior impeachment', conviction: 'Senate conviction, conditional on serving after impeachment' };
  const body = h('tbody', {}, ...Object.entries(names).map(([key, name]) => h('tr', {},
    h('th', { scope: 'row' }, name), h('td', { class: 'num' }, fmt.dec(data.rates[key] * 100, 3)),
    h('td', { class: 'num' }, fmt.dec(data.background[key] * 100, 3)))));
  document.getElementById('rate-table').replaceChildren(h('table', { class: 'data' },
    h('caption', {}, 'Daily transition rates (% per day; these are hazards, not horizon probabilities)'),
    h('thead', {}, h('tr', {}, h('th', {}, 'Transition'), h('th', { class: 'num' }, 'Reviewed rate'), h('th', { class: 'num' }, 'Background rate'))), body));
  document.getElementById('rate-window').textContent = `Reviewed rates apply until ${fmt.date(data.elevated_until)}; published background rates apply afterward. A stale review does not restart its 90-day window.`;
}

function renderReviews() {
  const root = document.getElementById('reviews');
  const reviews = data.reviews || [];
  if (!reviews.length) {
    root.append(h('p', { class: 'muted' }, 'Showing the initial assumptions. The first evidence review has not been saved yet.'));
    return;
  }
  root.replaceChildren(...reviews.map((r) => h('article', { class: 'tracker-review' },
    h('h3', {}, r.initial ? `Initial assumptions · ${fmt.date(r.date.slice(0, 10))}` : `Review ${r.id} · ${fmt.dateTime(r.date)}`), h('p', {}, r.summary),
    ...Object.entries(r.reasons || {}).map(([key, reason]) => h('p', { class: 'small muted' },
      `${key}: ${fmt.dec(reason.before * 100, 3)} → ${fmt.dec(reason.after * 100, 3)}% per day. ${reason.reason} `,
      ...reason.urls.map((url, i) => link(url, `Source ${i + 1} `)))))));
}

main();
