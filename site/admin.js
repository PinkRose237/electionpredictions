/**
 * admin.js — password-gated results entry for every race.
 *
 * Gate: PBKDF2-SHA256 of the password (Web Crypto) compared with the hash in admin-config.json.
 * Data: a draft in localStorage; Publish commits data/results.json to GitHub with the admin's own
 * token (Contents API), which triggers the deploy-site workflow. Nothing secret lives in the repo.
 */
import {
  STATE_NAMES, CHAMBER_LABEL, DASH, loadJSON, raceHref, withData, fmt, isNum, h, ratingPill,
  initChrome, renderUpdated, renderFooterMeta, showError, DATA_BASE,
} from './common.js';

const ET = 'America/New_York';
const DRAFT_KEY = 'results-draft';
const TOKEN_KEY = 'gh-token';
const OK_KEY = 'admin-ok';
const STATUSES = [['pending', 'Not started'], ['counting', 'Counting'], ['called', 'Called'], ['runoff', 'Runoff'], ['recount', 'Recount'], ['final', 'Final']];

let cfg = null, schedule = null, races = [], byId = new Map(), closeOf = new Map(), groupOf = new Map();
let draft = { updated_at: null, published_at: null, races: {} };
const ui = { search: '', chamber: 'all', onlyMissing: false, onlyCompetitive: false, sort: 'time' };
let saveTimer = null;

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
function isEntered(e) {
  return !!e && (e.status !== 'pending' || isNum(e.reporting) || isNum(e.votes.dem) || isNum(e.votes.rep) || isNum(e.votes.other) || !!e.note);
}
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
  tick();
  setInterval(tick, 1000);
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
  const clearBtn = h('button', { type: 'button', class: 'btn danger' }, 'Clear draft');
  clearBtn.addEventListener('click', () => {
    if (!confirm('Delete every entered result from this browser? (Published results on the site are untouched.)')) return;
    draft = { updated_at: null, published_at: draft.published_at, races: {} };
    saveDraft(true); renderSections();
  });
  bar.replaceChildren(
    h('div', { class: 'toolbar-row' }, publish, loadBtn, exportBtn, importBtn, importInput, tokenBtn, clearBtn),
    h('div', { class: 'toolbar-stats', id: 'toolbar-stats' }),
    msg,
  );
  renderToolbarStats();
}
function renderToolbarStats() {
  const el = document.getElementById('toolbar-stats');
  if (!el) return;
  const entries = Object.entries(draft.races);
  const entered = entries.filter(([, e]) => isEntered(e)).length;
  const called = entries.filter(([, e]) => e.status === 'called' || e.status === 'final').length;
  el.replaceChildren(
    h('span', {}, h('b', {}, `${entered} / ${races.length}`), ' races entered'),
    h('span', {}, h('b', {}, String(called)), ' called'),
    h('span', {}, draft.updated_at ? `Saved locally ${fmt.time ? fmt.time(draft.updated_at) : new Date(draft.updated_at).toLocaleTimeString()}` : 'Nothing entered yet'),
    h('span', {}, draft.published_at ? `Last published ${new Date(draft.published_at).toLocaleString()}` : 'Not published yet'),
  );
}

function renderFilters() {
  const c = document.getElementById('filters');
  const search = h('input', { type: 'search', placeholder: 'Find a state, race or candidate…', 'aria-label': 'Search' });
  search.addEventListener('input', () => { ui.search = search.value.trim().toLowerCase(); renderSections(); });
  const chamber = h('select', { 'aria-label': 'Chamber' }, h('option', { value: 'all' }, 'All races'),
    ...['senate', 'governor', 'house'].map((k) => h('option', { value: k }, CHAMBER_LABEL[k])));
  chamber.addEventListener('change', () => { ui.chamber = chamber.value; renderSections(); });
  const sort = h('select', { 'aria-label': 'Order' }, h('option', { value: 'time' }, 'Order by closing time'), h('option', { value: 'state' }, 'Order by state'));
  sort.addEventListener('change', () => { ui.sort = sort.value; renderSections(); });
  const missing = h('input', { type: 'checkbox' });
  missing.addEventListener('change', () => { ui.onlyMissing = missing.checked; renderSections(); });
  const comp = h('input', { type: 'checkbox' });
  comp.addEventListener('change', () => { ui.onlyCompetitive = comp.checked; renderSections(); });
  const expand = h('button', { type: 'button', class: 'btn small' }, 'Expand all');
  expand.addEventListener('click', () => document.querySelectorAll('details.admin-state').forEach((d) => { d.open = true; }));
  const collapse = h('button', { type: 'button', class: 'btn small' }, 'Collapse all');
  collapse.addEventListener('click', () => document.querySelectorAll('details.admin-state').forEach((d) => { d.open = false; }));
  c.replaceChildren(search, chamber, sort, h('label', { class: 'check' }, missing, 'Not entered only'), h('label', { class: 'check' }, comp, 'Lean & Tossup only'), expand, collapse);
}

function visibleRaces(list) {
  return list.filter((r) => {
    const race = byId.get(r.race_id);
    if (!race) return false;
    if (ui.chamber !== 'all' && race.chamber !== ui.chamber) return false;
    if (ui.onlyMissing && isEntered(entry(r.race_id))) return false;
    if (ui.onlyCompetitive && !(r.call.tier === 2 || r.call.tier === 3)) return false;
    return true;
  });
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
  const entered = g.races.filter((r) => isEntered(entry(r.race_id))).length;
  const called = g.races.filter((r) => ['called', 'final'].includes((entry(r.race_id) || {}).status)).length;
  const links = (g.sources || []).map((s) => h('a', { class: 'src-link', href: s.url, target: '_blank', rel: 'noopener', title: s.kind || '' }, `${s.label} ↗`));
  const det = h('details', { class: 'admin-state', 'data-key': key, open: openStates.has(key) || !!ui.search ? '' : null },
    h('summary', {},
      h('span', { class: 'st-name' }, g.state_name),
      h('span', { class: 'st-close' }, `${g.close_et}`, h('span', { class: 'countdown-inline', 'data-close': g.close_utc, 'data-closed-text': 'polls closed' }, '')),
      h('span', { class: 'st-count' }, `${entered}/${g.races.length} entered · ${called} called`),
      h('span', { class: 'st-links' }, ...links),
    ),
    h('div', { class: 'table-wrap' }, raceTable(g.races)),
  );
  return det;
}

function raceTable(list) {
  const table = h('table', { class: 'admin-table' },
    h('thead', {}, h('tr', {}, h('th', {}, 'Race'), h('th', {}, 'Polls close in'), h('th', {}, 'Democratic side'), h('th', {}, 'Republican side'),
      h('th', {}, 'Other'), h('th', {}, '% in'), h('th', {}, 'Status'), h('th', {}, 'Call'), h('th', {}, 'Note'))));
  const tb = h('tbody');
  for (const r of list) tb.append(raceRow(r));
  table.append(tb);
  return table;
}

function numInput(id, field, side, placeholder) {
  const e = entry(id);
  const v = e ? (side ? e.votes[side] : e[field]) : null;
  const inp = h('input', { type: 'text', inputmode: 'numeric', class: 'vote-input', placeholder, value: isNum(v) ? String(v) : '' });
  inp.addEventListener('input', () => {
    const n = parseNum(inp.value);
    const en = touch(id);
    if (side) en.votes[side] = n; else en[field] = n;
    if (!side && field === 'reporting' && isNum(n) && n > 0 && en.status === 'pending') en.status = 'counting';
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
    const b = h('button', { type: 'button', class: `btn small call ${side}` }, label);
    b.addEventListener('click', () => { const en = touch(r.race_id); en.status = 'called'; en.winner = side; if (!isNum(en.reporting)) en.reporting = 100; refreshRow(r.race_id); refreshComputed(r.race_id); });
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
  );
  tr.append(h('td', { class: 'computed-cell', colspan: '9' }));
  refreshComputed(r.race_id, tr);
  return tr;
}
function refreshRow(id) {
  const tr = document.querySelector(`tr[data-race="${id}"]`);
  if (!tr) return;
  const e = entry(id);
  tr.classList.toggle('entered', isEntered(e));
  const sel = tr.querySelector('.status-select');
  if (sel && e) sel.value = e.status;
  tr.querySelectorAll('.call').forEach((b) => b.classList.toggle('active', !!e && (e.status === 'called' || e.status === 'final') && e.winner === b.classList[3]));
  refreshComputed(id, tr);
  refreshSectionCount(tr);
  renderToolbarStats();
}
/** Keep the state header's "n/m entered · k called" in step with the rows beneath it. */
function refreshSectionCount(tr) {
  const det = tr.closest('details.admin-state');
  if (!det) return;
  const rows = [...det.querySelectorAll('tbody tr[data-race]')];
  const entered = rows.filter((row) => isEntered(entry(row.dataset.race))).length;
  const called = rows.filter((row) => ['called', 'final'].includes((entry(row.dataset.race) || {}).status)).length;
  const el = det.querySelector('.st-count');
  if (el) el.textContent = `${entered}/${rows.length} entered · ${called} called`;
}
function refreshComputed(id, tr = document.querySelector(`tr[data-race="${id}"]`)) {
  if (!tr) return;
  const cell = tr.querySelector('.computed-cell');
  const e = entry(id);
  if (!e || !isEntered(e)) { cell.textContent = ''; cell.hidden = true; return; }
  cell.hidden = false;
  const d = e.votes.dem || 0, r = e.votes.rep || 0, o = e.votes.other || 0, tot = d + r + o;
  const parts = [];
  if (tot > 0) parts.push(`D ${(100 * d / tot).toFixed(1)}% · R ${(100 * r / tot).toFixed(1)}%${o ? ` · other ${(100 * o / tot).toFixed(1)}%` : ''} · margin ${fmt.margin(100 * (d - r) / tot)} · ${tot.toLocaleString()} votes`);
  if (isNum(e.reporting)) parts.push(`${e.reporting}% reporting`);
  if ((e.status === 'called' || e.status === 'final') && e.winner) parts.push(`Called for ${{ dem: 'the Democratic side', rep: 'the Republican side', other: 'another candidate' }[e.winner]}`);
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
  document.querySelectorAll('[data-close]').forEach((el) => {
    const ms = new Date(el.dataset.close).getTime() - now;
    if (ms <= 0) { el.textContent = el.dataset.closedText || 'closed'; el.classList.add('closed'); return; }
    const s = Math.floor(ms / 1000), d = Math.floor(s / 86400), hh = Math.floor((s % 86400) / 3600), mm = Math.floor((s % 3600) / 60), ss = s % 60;
    el.textContent = d > 0 ? `${d}d ${pad(hh)}:${pad(mm)}:${pad(ss)}` : `${pad(hh)}:${pad(mm)}:${pad(ss)}`;
    el.classList.remove('closed');
  });
}

main();
