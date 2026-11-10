import { initChrome, h, fmt } from './common.js';
import { lookup, getJSON, LEVELS, LEVEL_NAMES, safeURL, looksLikeStreetAddress } from './representatives-data.js';

initChrome({ current: 'representatives' });
const $ = id => document.getElementById(id);
let controller;
let current = null;
let filter = 'all';

function external(url, text) {
  return h('a', { href: url, target: '_blank', rel: 'noopener noreferrer' }, text);
}

function row(label, children, className = '') {
  return h('div', { class: className }, h('dt', {}, label), h('dd', {}, ...children));
}

function card(rep) {
  const emailContent = rep.emails.length ? rep.emails.map(email => h('a', { href: `mailto:${email}` }, email)) : [h('span', { class: 'muted' }, rep.holder ? 'Not listed in sources' : 'Officeholder not recorded')];
  if (rep.contact_form) emailContent.push(external(rep.contact_form, 'Use official contact form ↗'));
  if (rep.emails.length && navigator.clipboard?.writeText) {
    const button = h('button', { class: 'btn', type: 'button', 'aria-label': `Copy email for ${rep.name}` }, 'Copy email');
    button.addEventListener('click', async () => {
      try { await navigator.clipboard.writeText(rep.emails.join(', ')); button.textContent = 'Copied'; }
      catch { button.textContent = 'Select the email to copy it'; }
    });
    emailContent.push(button);
  }
  const sources = [...new Set([...rep.sources, rep.recordURL].filter(safeURL))];
  return h('article', { class: 'card rep-card' },
    h('p', { class: 'rep-office' }, rep.office),
    h('h4', {}, rep.name),
    h('p', { class: 'rep-area' }, [rep.body, rep.area].filter(Boolean).join(' · ')),
    h('dl', { class: 'rep-contacts' },
      row('Website', rep.urls.length ? rep.urls.map(url => external(url, new URL(url).hostname.replace(/^www\./, '') + ' ↗')) : [h('span', { class: 'muted' }, 'Not listed in sources')]),
      row('Phone', rep.phones.length ? rep.phones.map(phone => h('a', { href: `tel:${phone.replace(/[^+0-9,;]/g, '')}` }, phone)) : [h('span', { class: 'muted' }, 'Not listed in sources')]),
      row('Email', emailContent, rep.emails.length ? 'rep-email' : ''),
    ),
    h('p', { class: 'rep-source' }, ...sources.map((url, i) => external(url, i === 0 ? 'Check source ↗' : 'Officeholder record ↗')),
      rep.checked ? h('span', {}, ` · Source checked ${fmt.date(rep.checked)}`) : null),
  );
}

function renderList() {
  if (!current) return;
  const results = current.results.filter(r => (filter === 'all' || r.level === filter) && (!$('email-only').checked || r.emails.length));
  $('result-count').textContent = `Showing ${results.length} of ${current.results.length} office records. Contact details may be incomplete.`;
  const groups = LEVELS.map(level => {
    const officials = results.filter(r => r.level === level);
    if (!officials.length) return null;
    return h('section', { class: 'reps-group', 'aria-label': LEVEL_NAMES[level] },
      h('h3', {}, `${LEVEL_NAMES[level]} · ${officials.length}`), h('div', { class: 'reps-grid' }, ...officials.map(card)));
  }).filter(Boolean);
  $('representatives-list').replaceChildren(...(groups.length ? groups : [h('p', { class: 'reps-notice' }, 'No records match this filter. Try another level or uncheck “With a listed email”.')]));
}

function renderResults(data, precision) {
  current = data;
  filter = 'all';
  $('email-only').checked = false;
  $('matched-address').textContent = `Lookup for ${data.address}`;
  const { latitude, longitude } = data;
  $('matched-location').replaceChildren(...(Number.isFinite(latitude) && Number.isFinite(longitude) ? [external(`https://www.openstreetmap.org/?mlat=${latitude}&mlon=${longitude}#map=16/${latitude}/${longitude}`, 'Check the matched location on a map ↗')] : []));
  $('accuracy-note').replaceChildren(
    h('p', {}, precision === 'area' ? 'Approximate area search: district offices below are matched to a point near the center of this area. They may not represent your home. Search again with a full street address to narrow the match.' : 'Address search: check the matched location before contacting a district office. Address matching and boundary records can have errors.'),
    h('p', {}, 'These are available officeholder records, not a guarantee of a complete roster. Election winners are not necessarily the people currently in office. Check the linked sources for recent changes.'),
  );
  $('contact-warning').hidden = !data.contactWarning;
  const counts = Object.fromEntries(LEVELS.map(level => [level, data.results.filter(r => r.level === level).length]));
  $('level-filters').replaceChildren(...['all', ...LEVELS.filter(level => counts[level])].map(level => {
    const button = h('button', { type: 'button', 'aria-pressed': String(level === 'all') }, `${level === 'all' ? 'All levels' : LEVEL_NAMES[level]} (${level === 'all' ? data.results.length : counts[level]})`);
    button.addEventListener('click', () => {
      filter = level;
      $('level-filters').querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', String(b === button)));
      renderList();
    });
    return button;
  }));
  $('coverage-list').replaceChildren(...data.layers.map(layer => {
    const n = data.results.filter(r => r.layerId === layer.id).length;
    return h('li', {}, external(`https://jurisdictional.org/jurisdictions/${layer.id}`, layer.display_name || layer.name),
      ` — ${n ? `${n} office record${n === 1 ? '' : 's'} found; more may exist` : 'No office records found; check the government directory'}`);
  }));
  renderList();
  $('representatives-results').hidden = false;
  $('results-heading').focus({ preventScroll: true });
  $('results-heading').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function setBusy(busy) {
  $('find-representatives').disabled = busy;
  $('find-representatives').textContent = busy ? 'Finding your representatives…' : 'Find my representatives →';
  $('cancel-lookup').hidden = !busy;
  $('representatives-form').setAttribute('aria-busy', String(busy));
}

$('representatives-form').addEventListener('submit', async event => {
  event.preventDefault();
  const address = $('address').value.trim();
  if (address.length < 3) { $('address').setCustomValidity('Enter a U.S. address, city and state, or ZIP code.'); $('address').reportValidity(); return; }
  controller?.abort();
  const request = new AbortController();
  controller = request;
  const precision = document.querySelector('input[name="precision"]:checked').value === 'address' && looksLikeStreetAddress(address) ? 'address' : 'area';
  $('lookup-error').hidden = true;
  $('representatives-results').hidden = true;
  $('lookup-status').textContent = 'Matching your location to districts and public contact records…';
  setBusy(true);
  try {
    const data = await lookup(address, { signal: request.signal });
    if (request.signal.aborted) return;
    renderResults(data, precision);
    $('lookup-status').textContent = `${data.results.length} office records found. Review coverage below for missing offices.`;
  } catch (error) {
    if (request.signal.aborted) return;
    $('lookup-status').textContent = '';
    $('lookup-error').textContent = error.message;
    $('lookup-error').hidden = false;
  } finally {
    if (controller === request) { controller = null; setBusy(false); }
  }
});
$('address').addEventListener('input', () => $('address').setCustomValidity(''));
$('cancel-lookup').addEventListener('click', () => {
  controller?.abort(); controller = null; setBusy(false);
  $('lookup-status').textContent = 'Lookup canceled. You can edit your location and try again.';
});
$('email-only').addEventListener('change', renderList);
document.querySelectorAll('input[name="precision"]').forEach(input => input.addEventListener('change', () => {
  const area = input.value === 'area';
  $('address-label').textContent = area ? 'U.S. city and state, or ZIP code' : 'U.S. street address, city and state or ZIP code';
  $('address').placeholder = area ? 'Springfield, IL or 62701' : '123 Main Street, Springfield, IL 62701';
  $('address').autocomplete = area ? 'off' : 'street-address';
}));

getJSON('./representatives-data/manifest.json').then(manifest => {
  if (manifest.updated) $('directory-updated').textContent = `Contact directory refreshed ${fmt.date(manifest.updated)}. Source verification dates vary.`;
}).catch(() => { /* Lookup still works when only the refresh timestamp is unavailable. */ });
