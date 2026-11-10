/** Address lookup and contact matching. No address is saved to storage or URLs. */
export const API = 'https://jurisdictional.org/api/v1';
export const LEVELS = ['local', 'county', 'school', 'state', 'federal', 'other'];
export const LEVEL_NAMES = { local: 'City, town & township', county: 'County', school: 'School boards', state: 'State', federal: 'Federal', other: 'Other districts & boards' };

export function safeURL(value) {
  try {
    const url = new URL(value);
    return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? url.href : null;
  } catch { return null; }
}
export function safeEmail(value) {
  const email = String(value || '').replace(/^mailto:/i, '').trim();
  return /^[^\s@<>?&#%:,;"()]+@[^\s@<>?&#%:,;"()]+\.[^\s@<>?&#%:,;"()]+$/.test(email) ? email : null;
}
export function normalizeName(name) {
  return String(name || '').normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]/g, '');
}
export function active(record, today = new Date().toISOString().slice(0, 10)) {
  return (!record.start || record.start <= today) && (!record.end || record.end >= today.slice(0, record.end.length));
}
export function looksLikeStreetAddress(value) {
  return /^\d+[a-z]?(?:[-/]\d+)?\s+\S+/i.test(String(value).trim()) && !/^\d{5}(?:-\d{4})?(?:\s*,|\s*$)/.test(String(value).trim());
}
export function layerLevel(layer, seat = {}) {
  if (/United States (Senate|House)|U\.S\. (Senator|Representative)/i.test(`${seat.body?.name} ${seat.label}`)) return 'federal';
  const level = layer.level || '';
  if (level === 'federal' || level === 'congressional_district') return 'federal';
  if (level === 'state' || level.startsWith('state_legislative') || level === 'board_of_equalization_district') return 'state';
  if (level.includes('school')) return 'school';
  if (level.startsWith('county') && level !== 'county_subdivision') return 'county';
  if (['place', 'municipal', 'city_council_district', 'county_subdivision'].includes(level)) return 'local';
  return 'other';
}

export async function getJSON(url, { signal, fetcher = fetch } = {}) {
  let response;
  try {
    response = await fetcher(url, { signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(30000)]) : AbortSignal.timeout(30000), credentials: 'omit', referrerPolicy: 'no-referrer' });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new Error('The lookup service could not be reached. Please try again shortly.');
  }
  if (response.status === 429) throw new Error('The lookup service’s daily request limit has been reached for your connection. Try again tomorrow or use the official directories below.');
  if (!response.ok) throw new Error(response.status === 404 || response.status === 422 ? 'No U.S. location matched. Add a city and state, ZIP code, or full street address.' : `The lookup service returned an error (${response.status}). Please try again.`);
  try { return await response.json(); }
  catch { throw new Error('The lookup service returned an unreadable response. Please try again.'); }
}

function unique(values) { return [...new Set(values.filter(Boolean))]; }
function cleanContact(record) {
  return {
    emails: unique((record.emails || []).map(safeEmail)),
    phones: unique((record.phones || []).map(p => String(p).trim()).filter(p => /\d{3}/.test(p))),
    urls: unique((record.urls || []).map(safeURL)),
    contact_form: safeURL(record.contact_form),
  };
}
function names(record) { return [record.name, ...(record.aliases || [])].map(normalizeName).filter(Boolean); }
function officePriority(rep) {
  if (/^(president|governor|mayor)$/i.test(rep.office)) return 0;
  if (/vice president|lieutenant governor/i.test(rep.office)) return 1;
  if (/U\.S\.|state senator|state representative|assembly member|council member|supervisor/i.test(rep.office)) return 2;
  if (/commission|justice|judge/i.test(rep.office)) return 4;
  return 3;
}
function sameOffice(record, layer, seat) {
  if (record.division !== layer.ocd_id) return false;
  const label = String(seat.label || '').toLowerCase();
  if (record.kind === 'rep') return /u\.s\. representative|delegate|resident commissioner/.test(label);
  if (record.kind === 'upper') return /state senator|senate/.test(label);
  if (record.kind === 'lower') return /state representative|assembly|house/.test(label);
  if (record.kind === 'governor') return label === 'governor';
  return normalizeName(record.office) === normalizeName(seat.label);
}

/** Match a seat by stable federal id first, then by name inside its jurisdiction.
 * Never match people just because they share a name in different places.
 */
export function matchContact(layer, seat, directory) {
  const holder = seat.holder;
  if (!holder) return null;
  const bioguide = holder.identifiers?.find(i => i.scheme === 'bioguide')?.identifier;
  if (bioguide) {
    const match = directory.find(r => r.id === bioguide && r.level === 'federal');
    if (match) return match;
  }
  const name = normalizeName(holder.full_name);
  const division = layer.ocd_id;
  const candidates = directory.filter(r => names(r).includes(name) &&
    (r.division === division || r.jurisdiction === division || division?.startsWith(`${r.jurisdiction}/`)));
  return candidates.find(r => r.division === division) || candidates[0] || null;
}

export function buildResults(layers, records, today) {
  const directory = records.filter(r => active(r, today));
  const divisions = new Set(layers.map(l => l.ocd_id).filter(Boolean));
  const results = [];
  const matched = new Set();
  const seenSeats = new Set();
  for (const layer of layers) {
    for (const seat of layer.seats || []) {
      if (seenSeats.has(seat.id)) continue;
      seenSeats.add(seat.id);
      const record = matchContact(layer, seat, directory);
      // A dated departure is stronger evidence than an undated API seat holder.
      if (seat.holder?.term_end && seat.holder.term_end < (today || new Date().toISOString().slice(0, 10))) continue;
      if (record) matched.add(record);
      const contact = cleanContact(record || {});
      if (!contact.urls.length && safeURL(seat.holder?.source_url)) contact.urls.push(safeURL(seat.holder.source_url));
      results.push({
        id: `seat-${seat.id}`, personId: seat.holder?.id,
        name: seat.holder?.full_name || 'Officeholder not recorded',
        office: seat.label, body: seat.body?.name || '',
        area: layer.display_name || layer.name, layerId: layer.id,
        level: layerLevel(layer, seat), holder: !!seat.holder,
        ...contact,
        sources: unique([safeURL(seat.holder?.source_url), safeURL(record?.source)]),
        recordURL: seat.holder?.id ? `https://jurisdictional.org/people/${seat.holder.id}` : `https://jurisdictional.org/jurisdictions/${layer.id}`,
        checked: record?.checked || seat.holder?.verified_on || '',
      });
    }
  }
  for (const record of directory) {
    if (matched.has(record) || !divisions.has(record.division)) continue;
    // Name + jurisdiction also suppresses alternate spellings/role duplicates
    // already seated by the live provider, without merging unrelated offices.
    const existing = results.find(r => r.holder && names(record).includes(normalizeName(r.name)) && layers.find(l => l.id === r.layerId)?.ocd_id === record.jurisdiction);
    if (existing) {
      const contact = cleanContact(record);
      for (const field of ['emails', 'phones', 'urls']) existing[field] = unique([...existing[field], ...contact[field]]);
      existing.sources = unique([...existing.sources, safeURL(record.source)]);
      continue;
    }
    // Do not display a second incumbent when the live seat and downloaded
    // directory disagree on the person occupying a specific office.
    const conflictingSeat = layers.some(l => (l.seats || []).some(s => s.holder && sameOffice(record, l, s)));
    if (conflictingSeat) continue;
    const layer = layers.find(l => l.ocd_id === record.division);
    results.push({ ...cleanContact(record), id: `directory-${record.id}-${record.office}`, name: record.name, office: record.office,
      body: '', area: layer?.display_name || layer?.name || '', layerId: layer?.id,
      level: record.level, holder: true, sources: [safeURL(record.source)].filter(Boolean),
      checked: record.checked || '', recordURL: safeURL(record.source),
    });
  }
  return results.sort((a, b) => LEVELS.indexOf(a.level) - LEVELS.indexOf(b.level) || officePriority(a) - officePriority(b) || a.body.localeCompare(b.body) || a.office.localeCompare(b.office) || a.name.localeCompare(b.name));
}

export async function lookup(address, { signal, fetcher = fetch } = {}) {
  const options = { signal, fetcher };
  const json = await getJSON(`${API}/juricode?${new URLSearchParams({ address, include: 'seats' })}`, options);
  const data = json.data;
  if (!data || !Array.isArray(data.jurisdictions)) throw new Error('The lookup service returned no district information. Please try a fuller U.S. address.');
  const layers = data.jurisdictions;
  if (!layers.length || !layers.some(l => ['state', 'territory'].includes(l.level))) throw new Error('No supported U.S. location matched. Please include a state or U.S. territory.');
  const states = unique(layers.map(l => l.state_abbr?.toLowerCase()).filter(s => /^[a-z]{2}$/.test(s || '')));
  const files = ['us', ...states];
  const contacts = await Promise.allSettled(files.map(s => getJSON(`./representatives-data/${s}.json`, options)));
  if (signal?.aborted) throw signal.reason;
  const records = contacts.flatMap(r => r.status === 'fulfilled' && Array.isArray(r.value) ? r.value : []);
  return { address: data.address || address, latitude: data.latitude, longitude: data.longitude, layers, results: buildResults(layers, records), contactWarning: contacts.some(r => r.status === 'rejected') };
}
