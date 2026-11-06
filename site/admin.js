/**
 * admin.js — the admin hub (admin.html).
 *
 * Gate: PBKDF2-SHA256 of the password (Web Crypto) compared with the hash in admin-config.json; signing in sets
 * the same 'admin-ok' flag the archived 2026 pages check (archive/2026/archive-gate.js). It is a UI gate, as on
 * any static site. After sign-in: the retired 2026 midterm site (admin-only archive), the 2028 pipeline log and
 * the raw model specification.
 */
import { loadJSON, fmt, h, initChrome, renderUpdated, renderFooterMeta, showError, relativeTime } from './common.js';

const OK_KEY = 'admin-ok';
let cfg = null;

async function main() {
  initChrome({ current: 'admin' });
  const status = document.getElementById('status');
  try {
    cfg = await fetch('./admin-config.json', { cache: 'no-store' }).then((r) => { if (!r.ok) throw new Error('admin-config.json missing'); return r.json(); });
  } catch (err) {
    showError(status, err, 'Run `uv run electionpredictions set-admin-password` first.');
    return;
  }
  loadJSON('summary.json').then((s) => { renderUpdated(s); renderFooterMeta(s); }).catch(() => {});
  if (signedIn()) proceed(); else login();
}

function signedIn() {
  try { return sessionStorage.getItem(OK_KEY) === '1' || localStorage.getItem(OK_KEY) === '1'; } catch (e) { return false; }
}

/** Only same-site archive pages are valid return targets. */
function nextTarget() {
  const n = new URLSearchParams(location.search).get('next') || '';
  return /^archive\/2026\/[a-z0-9-]+\.html(\?[A-Za-z0-9=&%._\-]*)?$/.test(n) ? n : null;
}

function proceed() {
  const n = nextTarget();
  if (n) { location.replace(n); return; }
  hub();
}

function login() {
  const box = document.getElementById('login');
  box.hidden = false;
  if (nextTarget()) box.prepend(h('p', { class: 'muted' }, 'The 2026 midterm archive is admin-only. Sign in to continue.'));
  const form = document.getElementById('login-form');
  const err = document.getElementById('login-error');
  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    err.textContent = '';
    const btn = form.querySelector('button');
    btn.disabled = true; btn.textContent = 'Checking…';
    try {
      if (!(await verify(document.getElementById('pw').value))) { err.textContent = 'Wrong password.'; return; }
      try {
        sessionStorage.setItem(OK_KEY, '1');
        if (document.getElementById('remember').checked) localStorage.setItem(OK_KEY, '1');
      } catch (e) { /* storage unavailable */ }
      box.hidden = true;
      proceed();
    } catch (e) {
      console.error(e);
      err.textContent = 'This browser cannot verify the password (needs HTTPS or localhost).';
    } finally { btn.disabled = false; btn.textContent = 'Sign in'; }
  });
  document.getElementById('pw').focus();
}

async function verify(pw) {
  const enc = new TextEncoder();
  const salt = new Uint8Array(cfg.salt.match(/.{2}/g).map((b) => parseInt(b, 16)));
  const key = await crypto.subtle.importKey('raw', enc.encode(pw), 'PBKDF2', false, ['deriveBits']);
  const bits = await crypto.subtle.deriveBits({ name: 'PBKDF2', salt, iterations: cfg.iterations || 200000, hash: 'SHA-256' }, key, 256);
  return [...new Uint8Array(bits)].map((b) => b.toString(16).padStart(2, '0')).join('') === cfg.hash;
}

function signOut() {
  try { sessionStorage.removeItem(OK_KEY); localStorage.removeItem(OK_KEY); } catch (e) { /* ignore */ }
  location.href = 'admin.html';
}

const ARCHIVE = [
  ['index.html', 'Results', 'Control of each chamber, flips, latest calls'],
  ['map.html', 'Results map', 'Senate, governor and House maps'],
  ['results.html', 'All races', 'Every 2026 race with its result'],
  ['calls.html', 'Race calls', 'Calls by CNN, NBC, Bloomberg and the AP'],
  ['scorecard.html', 'Scorecard', 'How the final forecast did'],
  ['forecast.html', 'Final forecast', 'The dashboard as frozen on Nov 3, 2026'],
  ['methodology.html', 'Midterm methodology', 'How the 2026 model worked'],
  ['admin.html', 'Corrections desk', 'Manual result overrides (publishes results.json)'],
];

async function hub() {
  const app = document.getElementById('app');
  app.hidden = false;
  const head = h('div', { class: 'page-head admin-head' }, h('h1', {}, 'Admin'),
    h('p', {}, 'Retired 2026 midterm site, the 2028 pipeline log and the raw model data. ', h('button', { type: 'button', class: 'linklike' }, 'Sign out')));
  head.querySelector('button').addEventListener('click', signOut);
  const archive = h('section', { class: 'section' }, h('div', { class: 'section-head' }, h('h2', {}, '2026 midterms (archive)'),
    h('p', {}, 'The midterm model is retired. Its pages and data are kept here, visible only after sign-in; the final forecast is frozen as of November 3, 2026.')),
    h('div', { class: 'explore-list admin-links' }, ...ARCHIVE.map(([href, title, sub]) => h('a', { class: 'card link-card', href: `archive/2026/${href}` }, h('strong', {}, title), h('span', { class: 'muted small' }, sub)))));
  const pipe = h('section', { class: 'section card' }, h('h2', {}, '2028 pipeline'));
  app.replaceChildren(head, archive, pipe);
  try {
    const [meta, model] = await Promise.all([loadJSON('meta.json'), loadJSON('model.json')]);
    const v = model.versions[0] || {};
    pipe.append(
      h('p', {}, `Model v${model.current.version} (${model.current.origin}) · ${v.title || ''} · ${relativeTime(v.created_at)}. `,
        h('a', { href: 'data/model.json' }, 'model.json'), ' · ', h('a', { href: 'data/summary.json' }, 'summary.json'), ' · ', h('a', { href: 'data/meta.json' }, 'meta.json')),
      h('div', { class: 'table-wrap' }, h('table', { class: 'races-table compact' },
        h('thead', {}, h('tr', {}, h('th', {}, 'Stage'), h('th', {}, 'Finished'), h('th', {}, 'OK'), h('th', {}, 'Note'))),
        h('tbody', {}, ...meta.runs.map((r) => h('tr', {}, h('td', {}, r.stage), h('td', {}, fmt.dateTime(r.finished_at)), h('td', {}, r.ok ? '✓' : '✗'),
          h('td', { class: 'small mono' }, String(r.note || '').slice(0, 220))))))));
    if (meta.research && meta.research.length) {
      pipe.append(h('h3', {}, 'Latest research searches'),
        h('div', { class: 'table-wrap' }, h('table', { class: 'races-table compact' },
          h('thead', {}, h('tr', {}, h('th', {}, 'When'), h('th', {}, 'Search'), h('th', {}, 'Why'), h('th', {}, 'Top result'))),
          h('tbody', {}, ...meta.research.map((r) => h('tr', {}, h('td', {}, fmt.dateTime(r.created_at)), h('td', {}, r.query), h('td', { class: 'small' }, r.why || ''),
            h('td', { class: 'small' }, (r.results[0] || {}).t || '—')))))));
    }
  } catch (err) {
    pipe.append(h('p', { class: 'error-text' }, String(err.message || err)));
  }
}

main();
