/**
 * model.js — the model log (model.html): the current specification (nominee odds and strengths, state
 * adjustments, every setting with its bounds) and every revision with its changes and reasons.
 */
import { DASH, loadJSON, fmt, isNum, h, contestName, initChrome, renderUpdated, renderFooterMeta, showError, relativeTime, partyClass } from './common.js';

const ORIGIN = { seed: 'Initial', calibration: 'Polling update', revision: 'Revision' };

async function main() {
  initChrome({ current: 'model' });
  const status = document.getElementById('status');
  try {
    const [summary, M] = await Promise.all([loadJSON('summary.json'), loadJSON('model.json')]);
    status.hidden = true;
    document.getElementById('app').hidden = false;
    renderUpdated(summary); renderFooterMeta(summary);
    current(M, summary); stories(M.storylines || []); nominees(M.current.spec); adjustments(M.current.spec); params(M.current.parameters); log(M.versions, M.total_versions);
  } catch (err) {
    console.error(err);
    showError(status, err);
  }
}

function current(M, S) {
  const v = M.versions[0] || {};
  const e = M.current.effective;
  document.getElementById('current').append(...[
    h('div', { class: 'card-head' }, h('h2', {}, `Current model: v${M.current.version}`), h('span', { class: 'chip' }, ORIGIN[M.current.origin] || M.current.origin)),
    h('p', {}, h('strong', {}, v.title || ''), v.created_at ? h('span', { class: 'muted' }, ` · ${fmt.dateTime(v.created_at)} (${relativeTime(v.created_at)})`) : null),
    v.summary ? h('p', { class: 'prose' }, v.summary) : null,
    h('dl', { class: 'stats' },
      h('div', {}, h('dt', {}, 'National error (s.d.)'), h('dd', {}, `±${fmt.dec(e.national_sd, 1)} pts`)),
      h('div', {}, h('dt', {}, 'State error (s.d.)'), h('dd', {}, `±${fmt.dec(e.state_sd, 1)} pts`)),
      h('div', {}, h('dt', {}, 'Weight on national polls'), h('dd', {}, fmt.pct(e.poll_weight), h('span', { class: 'range' }, ` default ${fmt.pct(e.default_poll_weight)}`))),
      h('div', {}, h('dt', {}, 'Revisions so far'), h('dd', {}, fmt.num(M.versions.length))),
      h('div', {}, h('dt', {}, 'Democrat wins under this model'), h('dd', {}, fmt.pct(S.ec.p_dem)))),
  ].filter(Boolean));
}

function nominees(spec) {
  const root = document.getElementById('nominees');
  root.append(h('h2', {}, 'Candidate field'), h('p', { class: 'card-sub' }, 'Nomination odds, strength (points of November margin versus an average nominee) and home state, as the simulation uses them.'));
  for (const p of ['D', 'R']) {
    root.append(h('h3', {}, p === 'D' ? 'Democrats' : 'Republicans'));
    const body = h('tbody', {}, ...spec.nominees[p].map((c) => h('tr', {},
      h('td', {}, h('span', { class: `party-dot ${partyClass(p)}`, 'aria-hidden': 'true' }), c.name === 'Other' ? 'Someone else' : c.name),
      h('td', { class: 'num' }, fmt.pct(c.p, c.p < 0.01 ? 1 : 0)), h('td', { class: 'num' }, c.name === 'Other' ? DASH : fmt.signed(c.effect)), h('td', {}, c.home_state || DASH))));
    root.append(h('table', { class: 'races-table compact' }, h('thead', {}, h('tr', {}, h('th', {}, 'Candidate'), h('th', { class: 'num' }, 'Odds'), h('th', { class: 'num' }, 'Strength'), h('th', {}, 'Home'))), body));
  }
}

function adjustments(spec) {
  const root = document.getElementById('adjustments');
  const list = Object.entries(spec.state_adjustments || {});
  root.append(h('h2', {}, 'State adjustments'), h('p', { class: 'card-sub' }, 'Contest-specific shifts for evidence the rest of the model does not capture; at most ±4 points, and at most 12 at a time.'));
  if (!list.length) { root.append(h('p', { class: 'muted' }, 'None in the current model.')); return; }
  root.append(h('ul', { class: 'md-list' }, ...list.map(([id, a]) => h('li', {}, h('strong', {}, contestName(id)), ` ${fmt.signed(a.shift)} `, h('span', { class: 'muted' }, a.reason || '')))));
}

function fmtVal(v) {
  if (isNum(v)) return Number.isInteger(v) ? String(v) : String(Math.round(v * 1000) / 1000);
  return v == null ? DASH : String(v);
}

function params(list) {
  const body = h('tbody', {}, ...list.map((p) => h('tr', {},
    h('td', {}, p.description || p.path, h('div', { class: 'muted small mono' }, p.path)),
    h('td', { class: 'num' }, h('strong', {}, fmtVal(p.value))), h('td', { class: 'num' }, `${fmtVal(p.low)} – ${fmtVal(p.high)}`), h('td', { class: 'num' }, `±${fmtVal(p.max_step)}`))));
  document.getElementById('params').replaceChildren(h('table', { class: 'races-table' },
    h('thead', {}, h('tr', {}, h('th', {}, 'Setting'), h('th', { class: 'num' }, 'Value'), h('th', { class: 'num' }, 'Allowed range'), h('th', { class: 'num' }, 'Max change per revision'))), body));
}

function stories(list) {
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

function log(versions, total) {
  const root = document.getElementById('log');
  if (total && total > versions.length) root.append(h('p', { class: 'muted small' }, `Showing the latest ${versions.length} of ${fmt.num(total)} versions.`));
  for (const v of versions) {
    const changes = v.changes || [];
    const card = h('article', { class: 'card log-entry', id: `v${v.version}` },
      h('div', { class: 'card-head' }, h('h3', {}, `v${v.version} · ${v.title || ORIGIN[v.origin] || ''}`), h('span', { class: 'muted small' }, `${ORIGIN[v.origin] || v.origin} · ${fmt.dateTime(v.created_at)}`)),
      v.summary ? h('p', { class: 'prose' }, v.summary) : null);
    if (changes.length) {
      const shown = changes.slice(0, 40);
      const body = h('tbody', {}, ...shown.map((c) => h('tr', {}, h('td', {}, c.label || c.path), h('td', { class: 'num' }, fmtChange(c.path, c.from)), h('td', { class: 'num' }, '→'),
        h('td', { class: 'num' }, h('strong', {}, fmtChange(c.path, c.to))), h('td', { class: 'muted small' }, c.reason || ''))));
      const det = h('details', {}, h('summary', {}, `${changes.length} change${changes.length === 1 ? '' : 's'}`),
        h('div', { class: 'table-wrap' }, h('table', { class: 'races-table compact' }, body)),
        changes.length > shown.length ? h('p', { class: 'muted small' }, `…and ${changes.length - shown.length} smaller changes.`) : null);
      if (v === versions[0]) det.open = true;
      card.append(det);
    }
    root.append(card);
  }
}

function fmtChange(path, v) {
  if (v == null) return DASH;
  if (path.endsWith('.p')) return fmt.pct(v, v < 0.01 ? 1 : 0);
  if (path.endsWith('.effect') || path.startsWith('state_adjustments')) return fmt.signed(v);
  return fmtVal(v);
}

main();
