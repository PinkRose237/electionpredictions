/**
 * live.js — live election-night results pulled straight from public results feeds in the browser.
 *
 * Primary feed: The New York Times' results JSON (AP vote counts and AP race calls; "reporting" is
 * the AP's estimated share of the expected vote). Backup: CNN's national-races JSON, used only for
 * races the primary feed could not supply. Both send `Access-Control-Allow-Origin: *`.
 *
 * Everything is normalised to the results.json entry shape (docs/DATA_CONTRACT.md):
 *   { status, reporting, votes: { dem, rep, other }, winner, updated_at }
 * with feed candidates matched to our Democratic/Republican sides by name (so an independent standing
 * in for a party lands on that side), falling back to party.
 *
 * mergeResults() lays the admin's manual entries (results.json) over the feed: any field the admin
 * filled in wins, everything else comes from the feed.
 */
import { isNum } from './common.js';

const NYT_URL = (office) => `https://static01.nyt.com/elections-assets/pages/data/2026-11-03/results-${office}.json`;
const CNN_URL = (code) => `https://politics.api.cnn.io/results/national-races/2026-${code}.json`;

export const FEED_LABEL = { nyt: 'The Associated Press via The New York Times', cnn: 'CNN', snapshot: 'saved snapshot' };
export const FEED_SHORT = { nyt: 'AP (NYT)', cnn: 'CNN', snapshot: 'snapshot' };

// ---------------------------------------------------------------------------
// Race index: feed (state, chamber, district, special) -> our race_id
// ---------------------------------------------------------------------------
const pad2 = (n) => String(n).padStart(2, '0');

function makeResolver(ids) {
  const set = new Set(ids);
  return (st, chamber, district, special) => {
    if (chamber === 'governor') return set.has(`${st}-GOV`) ? `${st}-GOV` : null;
    if (chamber === 'senate') {
      const order = special ? [`${st}-SEN-SP`, `${st}-SEN`] : [`${st}-SEN`, `${st}-SEN-SP`];
      return order.find((id) => set.has(id)) || null;
    }
    if (chamber === 'house') {
      const d = Number(district);
      if (!Number.isFinite(d)) return null;
      if (set.has(`${st}-${pad2(d)}`)) return `${st}-${pad2(d)}`;
      if (d <= 1 && set.has(`${st}-00`)) return `${st}-00`;
    }
    return null;
  };
}

// ---------------------------------------------------------------------------
// Candidate -> side matching
// ---------------------------------------------------------------------------
const SUFFIX = /^(jr|sr|ii|iii|iv)$/;
export function nameTokens(s) {
  return String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()
    .replace(/\(.*?\)/g, ' ').replace(/[^a-z\s-]/g, ' ').split(/[\s-]+/).filter((t) => t && !SUFFIX.test(t));
}
const sideName = (c) => (c && typeof c === 'object' ? c.name : c) || '';

/** How well a feed candidate {first, last, party} fits one of our candidates (name string). */
function fit(ourName, cand, side) {
  const toks = new Set(nameTokens(ourName));
  const last = nameTokens(cand.last);
  let s = 0;
  if (toks.size && last.length && last.every((t) => toks.has(t))) {
    s += 2;
    const first = nameTokens(cand.first)[0];
    if (first && nameTokens(ourName)[0] === first) s += 1;
  }
  if ((side === 'dem' && cand.party === 'DEM') || (side === 'rep' && cand.party === 'REP')) s += 0.5;
  return s;
}

/**
 * Split feed candidates into our two sides + other. Name matches beat party matches; a side with no
 * name match takes the best same-party candidate. Returns { dem, rep, other } vote totals and the
 * index of the candidate assigned to each side.
 */
export function assignSides(race, cands) {
  const pick = { dem: -1, rep: -1 };
  const scores = cands.map((c) => ({ dem: fit(sideName(race.dem), c, 'dem'), rep: fit(sideName(race.rep), c, 'rep') }));
  const pairs = [];
  scores.forEach((s, i) => { for (const side of ['dem', 'rep']) if (s[side] >= 0.5) pairs.push([s[side], side, i]); });
  pairs.sort((a, b) => b[0] - a[0] || (cands[b[2]].votes || 0) - (cands[a[2]].votes || 0));
  const used = new Set();
  for (const [, side, i] of pairs) {
    if (pick[side] !== -1 || used.has(i)) continue;
    pick[side] = i; used.add(i);
  }
  const votes = { dem: null, rep: null, other: 0 };
  cands.forEach((c, i) => {
    const v = isNum(c.votes) ? c.votes : 0;
    if (i === pick.dem) votes.dem = v; else if (i === pick.rep) votes.rep = v; else votes.other += v;
  });
  return { votes, pick };
}

function entryFrom(race, cands, { winnerIdx = [], runoff = false, final = false, reporting = null, updated_at = null }) {
  const { votes, pick } = assignSides(race, cands);
  const total = (votes.dem || 0) + (votes.rep || 0) + (votes.other || 0);
  let winner = null;
  if (winnerIdx.length) {
    const w = winnerIdx[0];
    winner = w === pick.dem ? 'dem' : w === pick.rep ? 'rep' : 'other';
  }
  const status = final && winner ? 'final' : winner ? 'called' : runoff ? 'runoff' : total > 0 || (isNum(reporting) && reporting > 0) ? 'counting' : 'pending';
  return {
    status, winner,
    reporting: isNum(reporting) ? Math.round(reporting * 10) / 10 : null,
    votes: { dem: votes.dem, rep: votes.rep, other: votes.other || (total ? 0 : null) },
    updated_at,
    candidates: cands.map((c, i) => ({ name: c.name, party: c.party, votes: isNum(c.votes) ? c.votes : 0, side: i === pick.dem ? 'dem' : i === pick.rep ? 'rep' : 'other', winner: winnerIdx.includes(i) })),
  };
}

// ---------------------------------------------------------------------------
// Feeds
// ---------------------------------------------------------------------------
async function getJSON(url, timeoutMs = 25000) {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), timeoutMs);
  try {
    const r = await fetch(url, { cache: 'no-cache', signal: ctl.signal });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return await r.json();
  } finally { clearTimeout(t); }
}

const NYT_CHAMBER = { S: 'senate', H: 'house', G: 'governor' };
async function fetchNYT(byId, resolve) {
  const out = {}, errors = [];
  await Promise.all(['senate', 'house', 'governor'].map(async (office) => {
    let d;
    try { d = await getJSON(NYT_URL(office)); } catch (e) { errors.push(`${office}: ${e.message}`); return; }
    for (const race of d.races || []) {
      const ru = race.top_reporting_unit;
      if (!ru || ru.level !== 'state') continue;
      const chamber = NYT_CHAMBER[race.office_id];
      const special = race.race_type_id === 'W' || /special/i.test(race.type || '');
      const id = resolve(ru.state_postal, chamber, race.seat_number, special);
      if (!id || out[id]) continue;
      const meta = race.candidate_metadata || {};
      const cands = (ru.candidates || []).map((c) => {
        const m = meta[c.nyt_id] || {};
        const party = (m.party && m.party.nyt_id) || '';
        return { key: c.nyt_id, first: m.first_name || '', last: m.last_name || '', name: [m.first_name, m.last_name].filter(Boolean).join(' ') || c.nyt_id,
          party: party === 'GOP' ? 'REP' : party, votes: c.votes ? c.votes.total : 0 };
      });
      const won = (race.outcome && race.outcome.won) || [];
      const runoff = ((race.outcome && race.outcome.advanced_to_runoff) || []).length > 0;
      out[id] = entryFrom(byId.get(id), cands, {
        winnerIdx: won.map((k) => cands.findIndex((c) => c.key === k)).filter((i) => i >= 0),
        runoff, final: !!race.certified, reporting: ru.eevp, updated_at: ru.provider_updated_at || race.updated_at || null,
      });
    }
  }));
  return { races: out, errors };
}

const CNN_CHAMBER = { S: 'senate', H: 'house', G: 'governor' };
async function fetchCNN(byId, resolve) {
  const out = {}, errors = [];
  await Promise.all(['SG', 'HG', 'GG'].map(async (code) => {
    let d;
    try { d = await getJSON(CNN_URL(code)); } catch (e) { errors.push(`${code}: ${e.message}`); return; }
    for (const race of d || []) {
      if (race.contestType === 'HQ') continue; // unexpired-term specials; we track the full-term race
      const chamber = CNN_CHAMBER[race.raceType];
      const district = chamber === 'house' ? String(race.ecKey || '').split('-').pop() : null;
      const id = resolve(race.stateAbbreviation, chamber, district, race.contestType === 'SP');
      if (!id || out[id]) continue;
      const cands = (race.candidates || []).map((c) => ({ first: c.firstName || '', last: c.lastName || '', name: c.fullName || '', party: c.majorParty || '', votes: c.voteNum || 0, winner: !!c.winner, runoff: !!c.runoffCandidate }));
      const at = race.extractedAt ? (/[zZ]|[+-]\d\d:?\d\d$/.test(race.extractedAt) ? race.extractedAt : `${race.extractedAt}Z`) : null;
      out[id] = entryFrom(byId.get(id), cands, {
        winnerIdx: cands.map((c, i) => (c.winner ? i : -1)).filter((i) => i >= 0),
        runoff: cands.some((c) => c.runoff), reporting: race.percentReporting, updated_at: at,
      });
    }
  }));
  return { races: out, errors };
}

const FEEDS = { nyt: fetchNYT, cnn: fetchCNN };

/**
 * Pull live results for our races. `races` is a list of { race_id, dem, rep } (dem/rep a name or
 * { name }). The first feed is used for everything it covers; later feeds only fill races it missed.
 * Resolves to { races: { race_id: entry }, by: { race_id: feed }, sources: [...], errors: [...], fetched_at }.
 */
export async function fetchLive(races, { order = ['nyt', 'cnn'] } = {}) {
  const byId = new Map(races.map((r) => [r.race_id, r]));
  const resolve = makeResolver(races.map((r) => r.race_id));
  const merged = {}, by = {}, errors = [], used = [];
  for (const name of order) {
    if (Object.keys(merged).length >= byId.size) break;
    let res;
    try { res = await FEEDS[name](byId, resolve); } catch (e) { errors.push(`${name}: ${e.message}`); continue; }
    errors.push(...res.errors.map((m) => `${name} ${m}`));
    let n = 0;
    for (const [id, e] of Object.entries(res.races)) {
      if (merged[id]) continue;
      merged[id] = e; by[id] = name; n += 1;
    }
    if (n) used.push(name);
  }
  return { races: merged, by, sources: used, errors, fetched_at: new Date().toISOString() };
}

// ---------------------------------------------------------------------------
// Feed + manual overrides
// ---------------------------------------------------------------------------
/** True when a manual entry overrides anything. */
export function hasOverride(m) {
  return !!m && ((m.status && m.status !== 'pending') || isNum(m.reporting) || ['dem', 'rep', 'other'].some((k) => m.votes && isNum(m.votes[k])) || !!m.note);
}

/**
 * Lay manual entries over feed entries, field by field. Each merged entry gets `src`:
 * 'feed', 'manual' or 'mixed', and `feed` (which feed supplied it, if any).
 */
export function mergeResults(feed, feedBy, manual) {
  const out = {};
  const ids = new Set([...Object.keys(feed || {}), ...Object.keys(manual || {})]);
  for (const id of ids) {
    const a = feed && feed[id];
    const m = manual && manual[id];
    const over = hasOverride(m);
    if (!a && !over) continue;
    const e = a ? { ...a, votes: { ...a.votes } } : { status: 'pending', reporting: null, votes: { dem: null, rep: null, other: null }, winner: null, updated_at: null };
    let manualUsed = false;
    if (over) {
      if (m.status && m.status !== 'pending') { e.status = m.status; e.winner = m.winner || null; manualUsed = true; }
      if (isNum(m.reporting)) { e.reporting = m.reporting; manualUsed = true; }
      const mv = m.votes || {};
      // Field by field: a box left empty on the admin page keeps following the feed.
      for (const k of ['dem', 'rep', 'other']) {
        if (isNum(mv[k])) { e.votes[k] = mv[k]; manualUsed = true; delete e.candidates; }
      }
      if (m.note) e.note = m.note;
      if (m.updated_at && (!e.updated_at || m.updated_at > e.updated_at)) e.updated_at = m.updated_at;
    }
    e.src = !a ? 'manual' : manualUsed ? 'mixed' : 'feed';
    e.feed = a ? (feedBy && feedBy[id]) || null : null;
    out[id] = e;
  }
  return out;
}

/** Shares and margin of an entry: { total, dem, rep, other (all %), margin (D−R points) } or null. */
export function shares(e) {
  if (!e || !e.votes) return null;
  const d = e.votes.dem || 0, r = e.votes.rep || 0, o = e.votes.other || 0, tot = d + r + o;
  if (!(tot > 0)) return null;
  return { total: tot, dem: (100 * d) / tot, rep: (100 * r) / tot, other: (100 * o) / tot, margin: (100 * (d - r)) / tot };
}

export const isCalled = (e) => !!e && (e.status === 'called' || e.status === 'final') && !!e.winner;

// ---------------------------------------------------------------------------
// Paste parser for the admin page
// ---------------------------------------------------------------------------
/**
 * Read vote counts out of text copied from any results page (a state site, AP, a newspaper table).
 * Finds each candidate by last name, takes the largest whole number on that line or the next few
 * lines (before another candidate appears), and picks up "% reporting / of expected vote" and a
 * "total" line if present. Returns { dem, rep, other, reporting, found: [...] }.
 */
export function parsePasted(text, race) {
  const lines = String(text || '').split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  const ourNames = { dem: sideName(race.dem), rep: sideName(race.rep) };
  const lastOf = (n) => { const t = nameTokens(n); return t[t.length - 1] || null; };
  const lasts = { dem: lastOf(ourNames.dem), rep: lastOf(ourNames.rep) };
  const lineHas = (line, last) => !!last && nameTokens(line).includes(last);
  const anyName = (line) => Object.values(lasts).some((l) => lineHas(line, l));
  // The largest whole number on the candidate's own line; if that line has none (names and numbers in
  // separate rows), the next lines up to another candidate or a total.
  const votesNear = (i) => {
    for (let j = i; j < Math.min(lines.length, i + 4); j += 1) {
      if (j > i && (anyName(lines[j]) || /^total\b/i.test(lines[j]))) break;
      const cleaned = lines[j].replace(/\d+(\.\d+)?\s*%/g, ' ').replace(/\b\d{1,2}:\d\d\b/g, ' ');
      let best = null;
      for (const m of cleaned.matchAll(/\d{1,3}(?:,\d{3})+|\d+(?![.\d])/g)) {
        const n = Number(m[0].replace(/,/g, ''));
        if (Number.isFinite(n) && (best === null || n > best)) best = n;
      }
      if (best !== null) return best;
    }
    return null;
  };
  const out = { dem: null, rep: null, other: null, reporting: null, found: [] };
  for (const side of ['dem', 'rep']) {
    const i = lines.findIndex((l) => lineHas(l, lasts[side]));
    if (i >= 0) { out[side] = votesNear(i); out.found.push(`${side === 'dem' ? 'Democratic' : 'Republican'} side: “${lines[i].slice(0, 60)}”`); }
  }
  const totalLine = lines.findIndex((l) => /^total(\s+votes)?\b/i.test(l));
  if (totalLine >= 0) {
    const tot = votesNear(totalLine);
    if (isNum(tot) && tot >= (out.dem || 0) + (out.rep || 0)) out.other = tot - (out.dem || 0) - (out.rep || 0);
  }
  const joined = lines.join(' ');
  const pct = /(\d{1,3}(?:\.\d+)?)\s*%\s*(?:of\s+)?(?:the\s+)?(?:(?:est(?:imated|\.)?\s+)?(?:expected\s+)?votes?|reporting|in\b|counted|precincts)/i.exec(joined)
    || /(?:reporting|expected vote|votes? counted|precincts reporting)\D{0,12}(\d{1,3}(?:\.\d+)?)\s*%/i.exec(joined);
  if (pct) out.reporting = Math.min(100, Number(pct[1]));
  else {
    const frac = /(\d[\d,]*)\s*(?:of|\/)\s*(\d[\d,]*)\s*precincts/i.exec(joined);
    if (frac) { const a = Number(frac[1].replace(/,/g, '')), b = Number(frac[2].replace(/,/g, '')); if (b > 0) out.reporting = Math.round((1000 * a) / b) / 10; }
  }
  return out;
}
