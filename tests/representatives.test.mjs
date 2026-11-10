import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { active, buildResults, layerLevel, lookup, looksLikeStreetAddress, matchContact, safeEmail, safeURL } from '../site/representatives-data.js';

const state = { id: 1, level: 'state', name: 'Example', state_abbr: 'CA', ocd_id: 'ocd-division/country:us/state:ca', seats: [] };
const city = { id: 2, level: 'place', name: 'Example City', state_abbr: 'CA', ocd_id: state.ocd_id + '/place:example', seats: [] };
const makeRecord = (overrides = {}) => ({ id: 'person-1', name: 'Jane Example', aliases: [], office: 'Mayor', division: city.ocd_id, jurisdiction: city.ocd_id, level: 'local', kind: 'local', emails: ['jane@example.gov'], phones: ['555-123-4567'], urls: ['https://example.gov'], ...overrides });
const makeSeat = (overrides = {}) => ({ id: 12, label: 'Mayor', body: { name: 'City Council' }, holder: { id: 19, full_name: 'Jane Example' }, ...overrides });
const today = '2026-11-10';

test('city and ZIP entries receive approximate-search messaging even in address mode', () => {
  assert.equal(looksLikeStreetAddress('300 Hemlock St, Vacaville, CA'), true);
  assert.equal(looksLikeStreetAddress('Vacaville, CA'), false);
  assert.equal(looksLikeStreetAddress('95688'), false);
  assert.equal(looksLikeStreetAddress('95688, CA'), false);
});

test('contact links reject executable URLs and email header injection', () => {
  for (const url of ['javascript:alert(1)', 'data:text/html,hello', 'https://user:pass@example.gov', '/relative']) assert.equal(safeURL(url), null);
  assert.equal(safeURL('https://example.gov/contact'), 'https://example.gov/contact');
  assert.equal(safeEmail('mailto:jane@example.gov'), 'jane@example.gov');
  for (const email of ['jane@example.gov?bcc=other@example.gov', 'jane@example.gov\r\nBcc: other@example.gov', '<jane@example.gov>', 'jane%0a@example.gov']) assert.equal(safeEmail(email), null);
});

test('name matching stays inside the represented jurisdiction and supports aliases', () => {
  const otherCity = makeRecord({ jurisdiction: state.ocd_id + '/place:elsewhere', division: state.ocd_id + '/place:elsewhere' });
  assert.equal(matchContact(city, makeSeat(), [otherCity]), null);
  const alias = makeRecord({ name: 'Janet Example', aliases: ['Jane Example'] });
  assert.equal(matchContact(city, makeSeat(), [alias]), alias);
});

test('federal stable IDs win over ambiguous names', () => {
  const record = makeRecord({ id: 'E000001', name: 'Jane E. Example', level: 'federal' });
  const seat = makeSeat({ holder: { id: 19, full_name: 'Jane Example', identifiers: [{ scheme: 'bioguide', identifier: 'E000001' }] } });
  assert.equal(matchContact(state, seat, [record]), record);
  assert.equal(layerLevel(state, { label: 'U.S. Senator', body: { name: 'United States Senate' } }), 'federal');
});

test('lists matched contacts once, preserves unknown officeholders, and excludes adjacent districts', () => {
  const layers = [{ ...city, seats: [makeSeat(), makeSeat({ id: 13, label: 'Clerk', holder: null })] }];
  const records = [makeRecord(), makeRecord({ id: 'other-district', name: 'Other Person', division: city.ocd_id + '/council_district:9' })];
  const results = buildResults(layers, records, today);
  assert.equal(results.length, 2);
  assert.equal(results.find(r => r.name === 'Jane Example').emails[0], 'jane@example.gov');
  assert.equal(results.find(r => r.office === 'Clerk').holder, false);
  assert.ok(!results.some(r => r.name === 'Other Person'));
});

test('adds matching statewide and national officers absent from the district API', () => {
  const federal = { id: 3, level: 'federal', name: 'United States', ocd_id: 'ocd-division/country:us', seats: [] };
  const governor = makeRecord({ id: 'governor', name: 'Governor Example', office: 'Governor', kind: 'governor', division: state.ocd_id, jurisdiction: state.ocd_id, level: 'state' });
  const president = makeRecord({ id: 'president', name: 'President Example', office: 'President', kind: 'prez', division: federal.ocd_id, jurisdiction: federal.ocd_id, level: 'federal' });
  const results = buildResults([state, federal], [governor, president], today);
  assert.deepEqual(results.map(r => r.name), ['Governor Example', 'President Example']);
});

test('does not add a second mayor when the live seat and directory disagree', () => {
  const layers = [{ ...city, seats: [makeSeat({ holder: { id: 20, full_name: 'New Mayor' } })] }];
  const results = buildResults(layers, [makeRecord()], today);
  assert.equal(results.length, 1);
  assert.equal(results[0].name, 'New Mayor');
  assert.deepEqual(results[0].emails, []);
});

test('excludes departed and future officeholders, accepts uncertain month/year dates', () => {
  assert.equal(active({ end: '2026-11-09' }, today), false);
  assert.equal(active({ start: '2027-01-03' }, today), false);
  assert.equal(active({ end: '2026' }, today), true);
  assert.equal(active({ end: '2026-11' }, today), true);
  const results = buildResults([city], [makeRecord({ end: '2026-10-01' })], today);
  assert.equal(results.length, 0);
});

test('lookup sends the address only to the resolver and loads only relevant state files', async () => {
  const calls = [];
  const fetcher = async (url, options) => {
    calls.push([url, options]);
    if (url.startsWith('https://jurisdictional.org/')) return Response.json({ data: { address: 'Example City, CA', latitude: 38, longitude: -121, jurisdictions: [state, city] } });
    return Response.json(url.endsWith('ca.json') ? [makeRecord()] : []);
  };
  const result = await lookup('Example City, CA', { fetcher });
  assert.equal(result.results.length, 1);
  assert.equal(result.latitude, 38);
  assert.deepEqual(calls.slice(1).map(c => c[0]), ['./representatives-data/us.json', './representatives-data/ca.json']);
  assert.ok(calls.every(([, options]) => options.credentials === 'omit' && options.referrerPolicy === 'no-referrer'));
});

test('partial contact download failures preserve district records with a warning', async () => {
  const result = await lookup('Example City, CA', { fetcher: async url => url.startsWith('https:') ? Response.json({ data: { jurisdictions: [state, { ...city, seats: [makeSeat()] }] } }) : new Response('unavailable', { status: 503 }) });
  assert.equal(result.contactWarning, true);
  assert.equal(result.results.length, 1);
  assert.deepEqual(result.results[0].emails, []);
});

test('rate limits and invalid locations return useful errors', async () => {
  await assert.rejects(lookup('Example', { fetcher: async () => new Response('', { status: 429 }) }), /daily request limit/);
  await assert.rejects(lookup('Example', { fetcher: async () => Response.json({ data: { jurisdictions: [] } }) }), /No supported U.S. location/);
  await assert.rejects(lookup('Example', { fetcher: async () => Response.json({ data: {} }) }), /no district information/);
});

test('shipped directory is coherent and has public email coverage', async () => {
  const manifest = JSON.parse(await readFile(new URL('../site/representatives-data/manifest.json', import.meta.url)));
  assert.ok(Object.keys(manifest.states).length >= 50);
  let emails = 0;
  for (const [state, count] of Object.entries(manifest.states)) {
    const records = JSON.parse(await readFile(new URL(`../site/representatives-data/${state}.json`, import.meta.url)));
    assert.equal(records.length, count);
    for (const record of records) {
      assert.ok(record.name && record.office && record.division.startsWith('ocd-division/country:us'));
      assert.ok(safeURL(record.source));
      emails += record.emails.filter(safeEmail).length;
    }
  }
  assert.ok(emails > 10000);
});
