/**
 * admin.js — password-gated results corrections for every race.
 *
 * The public page pulls vote counts and calls from the live feed by itself (live.js); this page shows
 * the same feed values for every race and lets the admin override any field, call a race, or paste
 * numbers copied from an official results site. Only the overrides are saved and published.
 *
 * Gate: PBKDF2-SHA256 of the password (Web Crypto) compared with the hash in admin-config.json.
 * Data: a draft in localStorage; Publish commits data/results.json to GitHub with the admin's own
 * token (Contents API), which triggers the deploy-site workflow. Nothing secret lives in the repo.
 */
import {
  STATE_NAMES, CHAMBER_LABEL, DASH, loadJSON, raceHref, withData, fmt, isNum, h, ratingPill,
  initChrome, renderUpdated, renderFooterMeta, showError, DATA_BASE, relativeTime,
} from './common.js';
import { fetchLive, mergeResults, hasOverride, shares, isCalled, parsePasted, FEED_SHORT } from './live.js';

const ET = 'America/New_York';
const DRAFT_KEY = 'results-draft';
const TOKEN_KEY = 'gh-token';
const OK_KEY = 'admin-ok';
const STATUSES = [['pending', 'Auto (feed)'], ['counting', 'Counting'], ['called', 'Called'], ['runoff', 'Runoff'], ['recount', 'Recount'], ['final', 'Final']];
const FEED_MS = 60e3;

let cfg = null, schedule = null, races = [], byId = new Map(), closeOf = new Map(), groupOf = new Map();
let draft = { updated_at: null, published_at: null, races: {} };
const ui = { search: '', chamber: 'all', show: 'all', onlyCompetitive: false, sort: 'time' };
let saveTimer = null;
let feed = { races: {}, by: {}, sources: [], errors: [], fetched_at: null };
let feedAuto = true, feedBusy = false, nextFeed = 0;

// ---------------------------------------------------------------------------
// Boot + gate
// ---------------------------------------------------------------------------
async function main() {
  initChrome({ current: 'admin' });
  const status = document.getElementById('status');
  try {
    [cfg, schedule, races] = await Promise.all([fetch('./admin-config.json', { cache: 'no-store' }).then((r) => { if (!r.ok) throw new Error('admin-config.json missing'); return r.json(); }),
      loadJSON('schedule.json'), loadJSON('races.json')]);
  } catch (err) {
    console.error(err);
    showError(status, err, 'Run `uv run electionpredictions set-admin-password` and `export` first.');
    return;
  }
  loadJSON('summary.json').then((s) => { renderUpdated(s); renderFooterMeta(s); }).catch(() => {});
  for (const r of races) byId.set(r.race_id, r);
  for (const g of schedule.groups) for (const r of g.races) { closeOf.set(r.race_id, g.close_utc); groupOf.set(r.race_id, g); }
  status.hidden = true;
  if (isSignedIn()) start(); else showLogin();
}

function isSignedIn() {
  try { return sessionStorage.getItem(OK_KEY) === '1' || localStorage.getItem(OK_KEY) === '1'; } catch (e) { return false; }
}
function showLogin() {
  const box = document.getElementById('login');
  box.hidden = false;
  const form = document.getElementById('login-form');
  const err = document.getElementById('login-error');
  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    err.textContent = '';
    const btn = form.querySelector('button');
    btn.disabled = true; btn.textContent = 'Checking…';
    try {
      const ok = await verifyPassword(document.getElementById('pw').value);
      if (!ok) { err.textContent = 'Wrong password.'; return; }
      try {
        sessionStorage.setItem(OK_KEY, '1');
        if (document.getElementById('remember').checked) localStorage.setItem(OK_KEY, '1');
      } catch (e) { /* ignore */ }
      box.hidden = true;
      start();
    } catch (e) {
      console.error(e);
      err.textContent = 'This browser cannot verify the password (needs HTTPS or localhost).';
    } finally { btn.disabled = false; btn.textContent = 'Sign in'; }
  });
  document.getElementById('pw').focus();
}
async function verifyPassword(pw) {
  const enc = new TextEncoder();
  const salt = new Uint8Array(cfg.salt.match(/.{2}/g).map((b) => parseInt(b, 16)));
  const key = await crypto.subtle.importKey('raw', enc.encode(pw), 'PBKDF2', false, ['deriveBits']);
  const bits = await crypto.subtle.deriveBits({ name: 'PBKDF2', salt, iterations: cfg.iterations || 200000, hash: 'SHA-256' }, key, 256);
  const hex = [...new Uint8Array(bits)].map((b) => b.toString(16).padStart(2, '0')).join('');
  return hex === cfg.hash;
}
function signOut() {
  try { sessionStorage.removeItem(OK_KEY); localStorage.removeItem(OK_KEY); } catch (e) { /* ignore */ }
  location.reload();
}

// ---------------------------------------------------------------------------
// Draft storage
// ---------------------------------------------------------------------------
function loadDraft() {
  try {
    const raw = localStorage.getItem(DRAFT_KEY);
    if (raw) { const d = JSON.parse(raw); if (d && d.races) draft = d; }
  } catch (e) { /* ignore */ }
}
function saveDraft(immediate = false) {
  clearTimeout(saveTimer);
  const doSave = () => {
    draft.updated_at = new Date().toISOString();
    try { localStorage.setItem(DRAFT_KEY, JSON.stringify(draft)); } catch (e) { /* ignore */ }
    renderToolbarStats();
  };
  if (immediate) doSave(); else saveTimer = setTimeout(doSave, 300);
}
function entry(id, create = false) {
  let e = draft.races[id];
  if (!e && create) {
    e = draft.races[id] = { status: 'pending', reporting: null, votes: { dem: null, rep: null, other: null }, winner: null, note: '', updated_at: null };
  }
  return e;
}
const isEntered = hasOverride;
/** Feed value with the admin's overrides on top, for one race. */
function merged(id) {
  const m = draft.races[id];
  return mergeResults(feed.races[id] ? { [id]: feed.races[id] } : {}, feed.by, m ? { [id]: m } : {})[id] || null;
}
function pollsClosed(id) { const c = closeOf.get(id); return !!c && Date.now() >= new Date(c).getTime(); }
function touch(id) { const e = entry(id, true); e.updated_at = new Date().toISOString(); saveDraft(); return e; }

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------
function start() {
  loadDraft();
  document.getElementById('admin').hidden = false;
  document.getElementById('signout').addEventListener('click', signOut);
  renderToolbar();
  renderFilters();
  renderSections();
  pullFeed();
  tick();
  setInterval(tick, 1000);
}

async function pullFeed() {
  if (feedBusy) return;
  feedBusy = true; nextFeed = Infinity;
  renderFeedStatus();
  try {
    const res = await fetchLive(races);
    if (Object.keys(res.races).length) feed = res;
    else feed = { ...feed, errors: res.errors.length ? res.errors : ['no data'] };
  } catch (e) { feed = { ...feed, errors: [e.message] }; }
  feedBusy = false; nextFeed = Date.now() + FEED_MS;
  renderFeedStatus();
  // Refresh rows in place so nothing the admin is typing gets rebuilt under them.
  if (ui.show !== 'all') { renderSections(); renderToolbarStats(); return; }
  document.querySelectorAll('tr[data-race]').forEach((tr) => paintRow(tr.dataset.race, tr));
  document.querySelectorAll('details.admin-state').forEach((det) => { const tr = det.querySelector('tr[data-race]'); if (tr) refreshSectionCount(tr); });
  renderToolbarStats();
}
function renderFeedStatus() {
  const el = document.getElementById('feed-status');
  if (!el) return;
  const n = Object.keys(feed.races).length;
  const reporting = Object.values(feed.races).filter((e) => shares(e)).length;
  const called = Object.values(feed.races).filter(isCalled).length;
  const btn = h('button', { type: 'button', class: 'btn small', disabled: feedBusy ? '' : null }, feedBusy ? 'Pulling…' : 'Pull now');
  btn.addEventListener('click', pullFeed);
  const auto = h('input', { type: 'checkbox', checked: feedAuto ? '' : null });
  auto.addEventListener('change', () => { feedAuto = auto.checked; if (feedAuto) nextFeed = Date.now() + FEED_MS; });
  el.replaceChildren(...[
    h('span', { class: `live-dot${n && !feed.errors.length ? ' ok' : feed.errors.length ? ' warn' : ''}`, 'aria-hidden': 'true' }),
    n ? h('span', {}, h('b', {}, 'Live feed'), ` ${feed.sources.map((k) => FEED_SHORT[k]).join(' + ')} · ${n} races · ${reporting} reporting · ${called} called · pulled `, h('span', { 'data-ago': feed.fetched_at }, relativeTime(feed.fetched_at)))
      : h('span', {}, feedBusy ? 'Pulling the live feed…' : 'Live feed not loaded'),
    feed.errors.length ? h('span', { class: 'error-text' }, ` (${feed.errors.join('; ')})`) : null,
    btn,
    h('label', { class: 'check' }, auto, 'every minute'),
  ].filter(Boolean));
}

function getToken() { try { return sessionStorage.getItem(TOKEN_KEY) || localStorage.getItem(TOKEN_KEY) || ''; } catch (e) { return ''; } }
function setToken(t, remember) {
  try {
    sessionStorage.setItem(TOKEN_KEY, t);
    if (remember) localStorage.setItem(TOKEN_KEY, t); else localStorage.removeItem(TOKEN_KEY);
  } catch (e) { /* ignore */ }
}

function renderToolbar() {
  const bar = document.getElementById('toolbar');
  const msg = h('div', { class: 'pub-msg', id: 'pub-msg', role: 'status' });
  const publish = h('button', { type: 'button', class: 'btn primary' }, 'Publish to site');
  publish.addEventListener('click', () => publishResults(publish, msg));
  const exportBtn = h('button', { type: 'button', class: 'btn' }, 'Export JSON');
  exportBtn.addEventListener('click', exportJSON);
  const importInput = h('input', { type: 'file', accept: 'application/json', style: { display: 'none' } });
  importInput.addEventListener('change', () => importJSON(importInput.files[0], msg));
  const importBtn = h('button', { type: 'button', class: 'btn' }, 'Import JSON');
  importBtn.addEventListener('click', () => importInput.click());
  const loadBtn = h('button', { type: 'button', class: 'btn' }, 'Load published');
  loadBtn.addEventListener('click', () => loadPublished(msg));
  const tokenBtn = h('button', { type: 'button', class: 'btn' }, getToken() ? 'GitHub token ✓' : 'GitHub token…');
  tokenBtn.addEventListener('click', () => tokenDialog(tokenBtn, msg));
  const clearBtn = h('button', { type: 'button', class: 'btn danger' }, 'Clear all overrides');
  clearBtn.addEventListener('click', () => {
    if (!confirm('Delete every override from this browser? (Published results on the site are untouched until you publish again.)')) return;
    draft = { updated_at: null, published_at: draft.published_at, races: {} };
    saveDraft(true); renderSections();
  });
  bar.replaceChildren(
    h('div', { class: 'feed-status', id: 'feed-status' }),
    h('div', { class: 'toolbar-row' }, publish, loadBtn, exportBtn, importBtn, importInput, tokenBtn, clearBtn),
    h('div', { class: 'toolbar-stats', id: 'toolbar-stats' }),
    msg,
  );
  renderFeedStatus();
  renderToolbarStats();
}
function renderToolbarStats() {
  const el = document.getElementById('toolbar-stats');
  if (!el) return;
  const entries = Object.entries(draft.races);
  const entered = entries.filter(([, e]) => isEntered(e)).length;
  const called = entries.filter(([, e]) => e.status === 'called' || e.status === 'final').length;
  const attention = races.filter((r) => needsAttention(r.race_id)).length;
  el.replaceChildren(
    h('span', {}, h('b', {}, String(entered)), ` manual override${entered === 1 ? '' : 's'}`),
    h('span', {}, h('b', {}, String(called)), ' called by hand'),
    h('span', {}, h('b', {}, String(attention)), ' closed and uncalled'),
    h('span', {}, draft.updated_at ? `Saved locally ${fmt.time ? fmt.time(draft.updated_at) : new Date(draft.updated_at).toLocaleTimeString()}` : 'Nothing entered yet'),
    h('span', {}, draft.published_at ? `Last published ${new Date(draft.published_at).toLocaleString()}` : 'Not published yet'),
  );
}

function renderFilters() {
  const c = document.getElementById('filters');
  const search = h('input', { type: 'search', placeholder: 'Find a state, race or candidate…', 'aria-label': 'Search' });
  search.addEventListener('input', () => { ui.search = search.value.trim().toLowerCase(); renderSections(); });
  const chamber = h('select', { 'aria-label': 'Chamber' }, h('option', { value: 'all' }, 'All chambers'),
    ...['senate', 'governor', 'house'].map((k) => h('option', { value: k }, CHAMBER_LABEL[k])));
  chamber.addEventListener('change', () => { ui.chamber = chamber.value; renderSections(); });
  const sort = h('select', { 'aria-label': 'Order' }, h('option', { value: 'time' }, 'Order by closing time'), h('option', { value: 'state' }, 'Order by state'));
  sort.addEventListener('change', () => { ui.sort = sort.value; renderSections(); });
  const show = h('select', { 'aria-label': 'Show' },
    h('option', { value: 'all' }, 'Every race'),
    h('option', { value: 'attention' }, 'Polls closed, not called'),
    h('option', { value: 'override' }, 'Has a manual override'),
    h('option', { value: 'nofeed' }, 'Missing from the feed'));
  show.addEventListener('change', () => { ui.show = show.value; renderSections(); });
  const comp = h('input', { type: 'checkbox' });
  comp.addEventListener('change', () => { ui.onlyCompetitive = comp.checked; renderSections(); });
  const expand = h('button', { type: 'button', class: 'btn small' }, 'Expand all');
  expand.addEventListener('click', () => document.querySelectorAll('details.admin-state').forEach((d) => { d.open = true; }));
  const collapse = h('button', { type: 'button', class: 'btn small' }, 'Collapse all');
  collapse.addEventListener('click', () => document.querySelectorAll('details.admin-state').forEach((d) => { d.open = false; }));
  c.replaceChildren(search, show, chamber, sort, h('label', { class: 'check' }, comp, 'Lean & Tossup only'), expand, collapse);
}

function visibleRaces(list) {
  return list.filter((r) => {
    const race = byId.get(r.race_id);
    if (!race) return false;
    if (ui.chamber !== 'all' && race.chamber !== ui.chamber) return false;
    if (ui.show === 'attention' && !needsAttention(r.race_id)) return false;
    if (ui.show === 'override' && !isEntered(entry(r.race_id))) return false;
    if (ui.show === 'nofeed' && feed.races[r.race_id]) return false;
    if (ui.onlyCompetitive && !(r.call.tier === 2 || r.call.tier === 3)) return false;
    return true;
  });
}

function needsAttention(id) {
  const m = merged(id);
  return pollsClosed(id) && !isCalled(m) && !(m && ['runoff', 'recount'].includes(m.status));
}

function renderSections() {
  const root = document.getElementById('sections');
  const openStates = new Set([...root.querySelectorAll('details.admin-state[open]')].map((d) => d.dataset.key));
  const sections = [];
  const q = ui.search;
  const matchesSearch = (g, r) => !q || g.state_name.toLowerCase().includes(q) || g.state.toLowerCase() === q ||
    `${r.short} ${r.name} ${r.dem || ''} ${r.rep || ''}`.toLowerCase().includes(q);
  if (ui.sort === 'state') {
    const byState = new Map();
    for (const g of schedule.groups) {
      const rs = visibleRaces(g.races).filter((r) => matchesSearch(g, r)).map((r) => ({ ...r, close_utc: g.close_utc, close_et: g.close_et }));
      if (rs.length) byState.set(g.state, [...(byState.get(g.state) || []), ...rs]);
    }
    for (const [st, rs] of [...byState.entries()].sort((a, b) => STATE_NAMES[a[0]].localeCompare(STATE_NAMES[b[0]]))) {
      const g0 = schedule.groups.find((g) => g.state === st);
      sections.push(stateSection({ ...g0, races: rs, close_utc: rs.reduce((m, r) => (r.close_utc > m ? r.close_utc : m), rs[0].close_utc) }, `state:${st}`, openStates));
    }
  } else {
    for (const g of schedule.groups) {
      const rs = visibleRaces(g.races).filter((r) => matchesSearch(g, r));
      if (rs.length) sections.push(stateSection({ ...g, races: rs }, `${g.close_utc}:${g.state}`, openStates));
    }
  }
  root.replaceChildren(...(sections.length ? sections : [h('div', { class: 'results-empty' }, 'No races match these filters.')]));
  tick();
}

function stateSection(g, key, openStates) {
  const links = (g.sources || []).map((s) => h('a', { class: 'src-link', href: s.url, target: '_blank', rel: 'noopener', title: s.kind || '' }, `${s.label} ↗`));
  const det = h('details', { class: 'admin-state', 'data-key': key, open: openStates.has(key) || !!ui.search || ui.show !== 'all' ? '' : null },
    h('summary', {},
      h('span', { class: 'st-name' }, g.state_name),
      h('span', { class: 'st-close' }, `${g.close_et}`, h('span', { class: 'countdown-inline', 'data-close': g.close_utc, 'data-closed-text': 'polls closed' }, '')),
      h('span', { class: 'st-count' }, sectionCount(g.races.map((r) => r.race_id))),
      h('span', { class: 'st-links' }, ...links),
    ),
    h('div', { class: 'table-wrap' }, raceTable(g.races)),
  );
  return det;
}

function raceTable(list) {
  const table = h('table', { class: 'admin-table' },
    h('thead', {}, h('tr', {}, h('th', {}, 'Race'), h('th', {}, 'Polls close in'), h('th', {}, 'Democratic side'), h('th', {}, 'Republican side'),
      h('th', {}, 'Other'), h('th', {}, '% in'), h('th', {}, 'Status'), h('th', {}, 'Call'), h('th', {}, 'Note'), h('th', {}, ''))));
  const tb = h('tbody');
  for (const r of list) tb.append(...raceRow(r));
  table.append(tb);
  return table;
}

function numInput(id, field, side, placeholder) {
  const e = entry(id);
  const v = e ? (side ? e.votes[side] : e[field]) : null;
  const inp = h('input', { type: 'text', inputmode: 'numeric', class: 'vote-input', placeholder, value: isNum(v) ? String(v) : '', 'data-field': side || field });
  inp.addEventListener('input', () => {
    const n = parseNum(inp.value);
    const en = touch(id);
    if (side) en.votes[side] = n; else en[field] = n;
    refreshRow(id);
  });
  return inp;
}
function parseNum(s) {
  const t = String(s).replace(/[,\s%]/g, '');
  if (t === '') return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

function raceRow(r) {
  const race = byId.get(r.race_id);
  const e = entry(r.race_id);
  const dem = race.dem, rep = race.rep;
  const tr = h('tr', { 'data-race': r.race_id, class: isEntered(e) ? 'entered' : '' });
  const status = h('select', { class: 'status-select' }, ...STATUSES.map(([v, l]) => h('option', { value: v, selected: (e ? e.status : 'pending') === v ? '' : null }, l)));
  status.addEventListener('change', () => { const en = touch(r.race_id); en.status = status.value; if (!['called', 'final'].includes(en.status)) en.winner = null; refreshRow(r.race_id); });
  const note = h('input', { type: 'text', class: 'note-input', placeholder: 'note', value: e ? e.note || '' : '' });
  note.addEventListener('input', () => { touch(r.race_id).note = note.value; });
  const callBtn = (side, label) => {
    const b = h('button', { type: 'button', class: `btn small call ${side}`, 'data-side': side, title: `Call for ${label === 'Oth' ? 'another candidate' : `the ${label} side`} (click again to undo)` }, label);
    b.addEventListener('click', () => {
      const en = touch(r.race_id);
      if ((en.status === 'called' || en.status === 'final') && en.winner === side) { en.status = 'pending'; en.winner = null; } else { en.status = 'called'; en.winner = side; }
      refreshRow(r.race_id);
    });
    return b;
  };
  const sources = (groupOf.get(r.race_id) || {}).sources || [];
  tr.append(
    h('td', { class: 'race-cell' },
      h('a', { class: 'rname', href: raceHref(r.race_id), target: '_blank', rel: 'noopener', title: 'Open the public race page' }, r.short),
      ' ', ratingPill(race.label),
      h('div', { class: 'muted small' }, `${race.name} · model ${fmt.pct(race.p_dem)} D`,
        sources[0] ? [' · ', h('a', { href: sources[0].url, target: '_blank', rel: 'noopener' }, 'official ↗')] : null)),
    h('td', { class: 'cd-cell' }, h('span', { class: 'countdown-inline', 'data-close': r.close_utc || closeOf.get(r.race_id), 'data-closed-text': 'closed' }, '')),
    h('td', {}, dem ? [h('div', { class: 'cand-name' }, h('span', { class: `party-dot ${dem.party === 'D' ? 'dem' : 'ind'}` }), dem.name), numInput(r.race_id, null, 'dem', 'votes')] : h('span', { class: 'muted' }, DASH)),
    h('td', {}, rep ? [h('div', { class: 'cand-name' }, h('span', { class: `party-dot ${rep.party === 'R' ? 'rep' : 'ind'}` }), rep.name), numInput(r.race_id, null, 'rep', 'votes')] : h('span', { class: 'muted' }, DASH)),
    h('td', {}, numInput(r.race_id, null, 'other', 'votes')),
    h('td', {}, numInput(r.race_id, 'reporting', null, '%')),
    h('td', {}, status),
    h('td', { class: 'call-cell' }, dem ? callBtn('dem', 'D') : null, rep ? callBtn('rep', 'R') : null, callBtn('other', 'Oth')),
    h('td', {}, note),
    h('td', { class: 'row-tools' }, pasteBtn(r.race_id, race), clearBtn(r.race_id)),
  );
  // What the public page will show for this race, on its own row underneath.
  const cell = h('td', { class: 'computed-cell', colspan: '10' });
  const info = h('tr', { class: 'computed-row' }, cell);
  tr.computedCell = cell;
  paintRow(r.race_id, tr);
  return [tr, info];
}

function clearBtn(id) {
  const b = h('button', { type: 'button', class: 'btn small', title: 'Drop the manual override and go back to the feed' }, 'Use feed');
  b.addEventListener('click', () => {
    delete draft.races[id];
    saveDraft();
    const tr = document.querySelector(`tr[data-race="${id}"]`);
    if (tr) {
      tr.querySelectorAll('input.vote-input, input.note-input').forEach((i) => { i.value = ''; });
      const sel = tr.querySelector('.status-select'); if (sel) sel.value = 'pending';
    }
    refreshRow(id);
  });
  return b;
}

/** "Paste" opens a box under the row: paste a race's table from any results site and apply the numbers it finds. */
function pasteBtn(id, race) {
  const b = h('button', { type: 'button', class: 'btn small', title: 'Paste results copied from an official site' }, 'Paste');
  b.addEventListener('click', () => {
    const tr = document.querySelector(`tr[data-race="${id}"]`);
    const below = tr.computedCell.parentElement;
    const open = below.nextElementSibling && below.nextElementSibling.classList.contains('paste-row') ? below.nextElementSibling : null;
    if (open) { open.remove(); return; }
    const ta = h('textarea', { class: 'paste-input', rows: '5', placeholder: `Select the ${race.short} table on the results site (candidate names, votes, % reporting), copy it, and paste it here.` });
    const preview = h('div', { class: 'paste-preview muted small' });
    const apply = h('button', { type: 'button', class: 'btn small primary', disabled: '' }, 'Apply');
    let parsed = null;
    ta.addEventListener('input', () => {
      parsed = parsePasted(ta.value, race);
      const bits = [];
      if (isNum(parsed.dem)) bits.push(`${race.dem ? race.dem.name : 'Dem side'}: ${parsed.dem.toLocaleString()}`);
      if (isNum(parsed.rep)) bits.push(`${race.rep ? race.rep.name : 'Rep side'}: ${parsed.rep.toLocaleString()}`);
      if (isNum(parsed.other)) bits.push(`others: ${parsed.other.toLocaleString()}`);
      if (isNum(parsed.reporting)) bits.push(`${parsed.reporting}% reporting`);
      preview.textContent = bits.length ? `Found ${bits.join(' · ')}` : 'No candidate names found yet; include the rows with the candidates’ names.';
      apply.disabled = !(isNum(parsed.dem) || isNum(parsed.rep));
    });
    apply.addEventListener('click', () => {
      if (!parsed) return;
      const en = touch(id);
      for (const side of ['dem', 'rep', 'other']) en.votes[side] = isNum(parsed[side]) ? parsed[side] : (side === 'other' ? 0 : en.votes[side]);
      if (isNum(parsed.reporting)) en.reporting = parsed.reporting;
      const row = document.querySelector(`tr[data-race="${id}"]`);
      row.querySelectorAll('input.vote-input').forEach((i) => {
        const f = i.dataset.field;
        const v = f === 'reporting' ? en.reporting : en.votes[f];
        i.value = isNum(v) ? String(v) : '';
      });
      refreshRow(id);
      pr.remove();
    });
    const cancel = h('button', { type: 'button', class: 'btn small' }, 'Cancel');
    const pr = h('tr', { class: 'paste-row' }, h('td', { colspan: '10' }, ta, h('div', { class: 'paste-actions' }, apply, cancel, preview)));
    cancel.addEventListener('click', () => pr.remove());
    below.after(pr);
    ta.focus();
  });
  return b;
}
function refreshRow(id, tr = document.querySelector(`tr[data-race="${id}"]`)) {
  if (!tr) return;
  paintRow(id, tr);
  refreshSectionCount(tr);
  renderToolbarStats();
}
/** Row classes, call buttons, feed placeholders and the "site shows" line. */
function paintRow(id, tr) {
  const e = entry(id);
  const f = feed.races[id];
  tr.classList.toggle('entered', isEntered(e));
  const sel = tr.querySelector('.status-select');
  if (sel && e) sel.value = e.status;
  const manualCall = !!e && (e.status === 'called' || e.status === 'final');
  tr.querySelectorAll('.call').forEach((b) => {
    const side = b.dataset.side;
    b.classList.toggle('active', manualCall && e.winner === side);
    b.classList.toggle('feed', !manualCall && isCalled(f) && f.winner === side);
  });
  // Feed numbers sit in the placeholders, so an empty box means "use the feed".
  tr.querySelectorAll('input.vote-input').forEach((i) => {
    const k = i.dataset.field;
    const v = !f ? null : k === 'reporting' ? f.reporting : f.votes[k];
    i.placeholder = isNum(v) ? (k === 'reporting' ? `${v}%` : v.toLocaleString()) : (k === 'reporting' ? '%' : 'votes');
  });
  refreshComputed(id, tr);
}
/** Keep the state header's "n/m entered · k called" in step with the rows beneath it. */
function refreshSectionCount(tr) {
  const det = tr.closest('details.admin-state');
  if (!det) return;
  const rows = [...det.querySelectorAll('tbody tr[data-race]')];
  const el = det.querySelector('.st-count');
  if (el) el.textContent = sectionCount(rows.map((row) => row.dataset.race));
}
function sectionCount(ids) {
  const called = ids.filter((id) => isCalled(merged(id))).length;
  const over = ids.filter((id) => isEntered(entry(id))).length;
  return `${called}/${ids.length} called${over ? ` · ${over} overridden` : ''}`;
}
function refreshComputed(id, tr = document.querySelector(`tr[data-race="${id}"]`)) {
  if (!tr) return;
  const cell = tr.computedCell;
  const e = merged(id);
  const sh = shares(e);
  if (!e || (!sh && !isCalled(e) && e.status === 'pending' && !e.note)) { cell.textContent = ''; cell.hidden = true; return; }
  cell.hidden = false;
  const parts = [];
  parts.push(e.src === 'feed' ? `Site shows (feed ${FEED_SHORT[e.feed] || ''})` : e.src === 'mixed' ? 'Site shows (feed + your overrides)' : 'Site shows (your entry)');
  if (sh) parts.push(`D ${sh.dem.toFixed(1)}% · R ${sh.rep.toFixed(1)}%${sh.other >= 0.05 ? ` · other ${sh.other.toFixed(1)}%` : ''} · margin ${fmt.margin(sh.margin)} · ${sh.total.toLocaleString()} votes`);
  if (isNum(e.reporting) && (sh || e.reporting > 0)) parts.push(`${e.reporting}% in`);
  if (isCalled(e)) parts.push(`Called for ${{ dem: 'the Democratic side', rep: 'the Republican side', other: 'another candidate' }[e.winner]}`);
  else if (e.status !== 'pending' && e.status !== 'counting') parts.push(e.status);
  if (e.updated_at) parts.push(`updated ${new Date(e.updated_at).toLocaleTimeString()}`);
  cell.textContent = parts.join(' · ');
}

// ---------------------------------------------------------------------------
// Import / export / publish
// ---------------------------------------------------------------------------
function exportJSON() {
  const blob = new Blob([JSON.stringify({ updated_at: new Date().toISOString(), races: draft.races }, null, 2)], { type: 'application/json' });
  const a = h('a', { href: URL.createObjectURL(blob), download: 'results.json' });
  document.body.append(a); a.click(); a.remove();
}
async function importJSON(file, msg) {
  if (!file) return;
  try {
    const d = JSON.parse(await file.text());
    if (!d || typeof d.races !== 'object') throw new Error('not a results file');
    draft.races = { ...draft.races, ...d.races };
    saveDraft(true); renderSections();
    msg.textContent = `Imported ${Object.keys(d.races).length} races from ${file.name}.`;
  } catch (e) { msg.textContent = `Import failed: ${e.message}`; }
}
async function loadPublished(msg) {
  try {
    const r = await fetch(`${DATA_BASE}/results.json?t=${Date.now()}`, { cache: 'no-store' });
    if (r.status === 404) { msg.textContent = 'Nothing has been published yet.'; return; }
    const d = await r.json();
    if (!confirm(`Replace this browser's draft with the published results (${Object.keys(d.races || {}).length} races)?`)) return;
    draft.races = d.races || {}; draft.published_at = d.updated_at || null;
    saveDraft(true); renderSections();
    msg.textContent = `Loaded published results from ${d.updated_at ? new Date(d.updated_at).toLocaleString() : 'the site'}.`;
  } catch (e) { msg.textContent = `Could not load published results: ${e.message}`; }
}
function tokenDialog(btn, msg) {
  const cur = getToken();
  const t = prompt('GitHub fine-grained personal access token with "Contents: read and write" on ' + (cfg.repo || 'the site repo') + '.\nIt is stored only in this browser.', cur ? '(keep current)' : '');
  if (t === null) return;
  if (t && t !== '(keep current)') {
    const remember = confirm('Remember this token on this device? (Cancel = this tab only)');
    setToken(t.trim(), remember);
    btn.textContent = 'GitHub token ✓';
    msg.textContent = 'Token saved.';
  } else if (t === '') { setToken('', false); btn.textContent = 'GitHub token…'; msg.textContent = 'Token removed.'; }
}
function b64(str) {
  const bytes = new TextEncoder().encode(str);
  let bin = '';
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}
async function publishResults(btn, msg) {
  const token = getToken();
  if (!token) { msg.textContent = 'Add your GitHub token first (button on the right).'; return; }
  if (!cfg.repo) { msg.textContent = 'admin-config.json has no repo; run set-admin-password --repo owner/name.'; return; }
  btn.disabled = true; btn.textContent = 'Publishing…';
  const api = `https://api.github.com/repos/${cfg.repo}/contents/${cfg.path}`;
  const headers = { Authorization: `Bearer ${token}`, Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28' };
  try {
    let sha = null;
    const cur = await fetch(`${api}?ref=${encodeURIComponent(cfg.branch)}&t=${Date.now()}`, { headers, cache: 'no-store' });
    if (cur.status === 200) sha = (await cur.json()).sha;
    else if (cur.status !== 404) throw new Error(`GitHub returned ${cur.status} reading the current file (token scope?)`);
    const payload = { updated_at: new Date().toISOString(), races: draft.races };
    const body = { message: `Results update ${payload.updated_at}`, content: b64(JSON.stringify(payload, null, 1)), branch: cfg.branch };
    if (sha) body.sha = sha;
    const res = await fetch(api, { method: 'PUT', headers, body: JSON.stringify(body) });
    const out = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(out.message || `GitHub returned ${res.status}`);
    draft.published_at = payload.updated_at;
    saveDraft(true);
    msg.replaceChildren('Published. ', h('a', { href: out.commit && out.commit.html_url ? out.commit.html_url : `https://github.com/${cfg.repo}`, target: '_blank', rel: 'noopener' }, 'View commit ↗'),
      ' The site redeploys in about a minute.');
  } catch (e) {
    console.error(e);
    msg.textContent = `Publish failed: ${e.message}`;
  } finally { btn.disabled = false; btn.textContent = 'Publish to site'; }
}

// ---------------------------------------------------------------------------
// Countdowns
// ---------------------------------------------------------------------------
const pad = (n) => String(n).padStart(2, '0');
function tick() {
  const now = Date.now();
  if (feedAuto && !feedBusy && now >= nextFeed && !document.hidden) pullFeed();
  document.querySelectorAll('[data-ago]').forEach((el) => { el.textContent = relativeTime(el.dataset.ago); });
  document.querySelectorAll('[data-close]').forEach((el) => {
    const ms = new Date(el.dataset.close).getTime() - now;
    if (ms <= 0) { el.textContent = el.dataset.closedText || 'closed'; el.classList.add('closed'); return; }
    const s = Math.floor(ms / 1000), d = Math.floor(s / 86400), hh = Math.floor((s % 86400) / 3600), mm = Math.floor((s % 3600) / 60), ss = s % 60;
    el.textContent = d > 0 ? `${d}d ${pad(hh)}:${pad(mm)}:${pad(ss)}` : `${pad(hh)}:${pad(mm)}:${pad(ss)}`;
    el.classList.remove('closed');
  });
}

main();
