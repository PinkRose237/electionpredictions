/**
 * polls.js — polls and fundamentals (polls.html): the national environment, candidates' polling strength,
 * every national and state trial heat with its weight, presidential approval and the economy.
 */
import { DASH, loadJSON, fmt, isNum, h, stateHref, contestName, initChrome, renderUpdated, renderFooterMeta, showError } from './common.js';

async function main() {
  initChrome({ current: 'polls' });
  const status = document.getElementById('status');
  try {
    const [summary, P] = await Promise.all([loadJSON('summary.json'), loadJSON('polls.json')]);
    status.hidden = true;
    document.getElementById('app').hidden = false;
    renderUpdated(summary); renderFooterMeta(summary);
    env(P.environment); strength(P.strengths || {}); national(P.national); state(P.state); approval(P.approval); economy(P.economy);
    midterm(P.midterm_2026); house(P.house_effects || {});
  } catch (err) {
    console.error(err);
    showError(status, err);
  }
}

function kv(k, v, sub) {
  return h('div', {}, h('dt', {}, k), h('dd', {}, v, sub ? h('span', { class: 'muted small' }, ` · ${sub}`) : null));
}

function env(E) {
  const np = E.national_polls || {};
  document.getElementById('env').append(h('h2', {}, 'National environment'),
    h('div', { class: 'generic-big', style: { color: E.environment >= 0 ? 'var(--dem)' : 'var(--rep)' } }, fmt.margin(E.environment)),
    h('dl', { class: 'kv' },
      kv('From national polls', isNum(E.polls) ? fmt.margin(E.polls) : 'no polls', np.n ? `${np.n} polls (effective ${fmt.dec(np.n_eff, 0)}), ±${fmt.dec(np.g_sd, 1)}` : ''),
      kv('From approval and the economy', fmt.margin(E.fundamentals), `White House party margin ${fmt.signed(E.incumbent_party_margin)}`),
      kv('Weight on polls', fmt.pct(E.poll_weight)),
      kv('Adjustment', fmt.signed(E.adjustment || 0))),
    h('p', { class: 'card-sub' }, 'The poll figure is the margin for an average-strength matchup: a regression over every national trial heat separates the overall environment from each candidate\'s own strength.'));
}

function strength(S) {
  const rows = Object.entries(S).sort((a, b) => (a[1].party || '').localeCompare(b[1].party || '') || b[1].strength - a[1].strength);
  const body = h('tbody');
  for (const [name, s] of rows) {
    body.append(h('tr', {}, h('td', {}, h('span', { class: `party-dot ${s.party === 'D' ? 'dem' : 'rep'}`, 'aria-hidden': 'true' }), name),
      h('td', { class: 'num' }, fmt.signed(s.strength)), h('td', { class: 'num' }, `±${fmt.dec(s.sd, 1)}`), h('td', { class: 'num' }, String(s.n_polls))));
  }
  document.getElementById('strength').append(h('h2', {}, 'Polling strength'),
    h('p', { class: 'card-sub' }, 'Points each candidate runs ahead (+) or behind (−) an average-strength nominee of their party in national trial heats, shrunk toward zero when polling is thin.'),
    h('table', { class: 'races-table compact' }, h('thead', {}, h('tr', {}, h('th', {}, 'Candidate'), h('th', { class: 'num' }, 'Strength'), h('th', { class: 'num' }, 'Uncertainty'), h('th', { class: 'num' }, 'Polls'))), body));
}

function pollTable(list, withContest) {
  const body = h('tbody');
  for (const p of list) {
    body.append(h('tr', {},
      withContest ? h('td', {}, h('a', { href: stateHref(p.contest) }, contestName(p.contest))) : null,
      h('td', {}, p.pollster, p.sponsor ? h('span', { class: 'muted small' }, ` (${p.sponsor})`) : null),
      h('td', {}, fmt.dateRange(p.start, p.end)),
      h('td', { class: 'num' }, p.n ? `${fmt.num(p.n)} ${p.pop || ''}` : (p.pop || DASH)),
      h('td', {}, `${p.dem} ${fmt.pts(p.dem_pct, 0)}`, h('span', { class: 'vs' }, ' – '), `${p.rep} ${fmt.pts(p.rep_pct, 0)}`,
        isNum(p.other_pct) ? h('span', { class: 'muted small' }, ` · others ${fmt.pts(p.other_pct, 0)}`) : null),
      h('td', { class: 'num' }, h('span', { class: p.margin >= 0 ? 'dem-text' : 'rep-text' }, fmt.margin(p.margin))),
      h('td', { class: 'num' }, isNum(p.weight) ? fmt.dec(p.weight, 2) : h('span', { class: 'muted' }, '0'))));
  }
  return h('table', { class: 'races-table' }, h('thead', {}, h('tr', {}, withContest ? h('th', {}, 'Contest') : null, h('th', {}, 'Pollster'), h('th', {}, 'Dates'),
    h('th', { class: 'num' }, 'Sample'), h('th', {}, 'Result'), h('th', { class: 'num' }, 'Margin'), h('th', { class: 'num' }, 'Weight'))), body);
}

function national(list) {
  document.getElementById('nat-note').textContent = `${list.length} polls of named matchups. Weight reflects recency, sample size, population, pollster record and sponsorship.`;
  document.getElementById('national').replaceChildren(pollTable(list, false));
}

function state(list) {
  document.getElementById('state').replaceChildren(list.length ? pollTable(list, true) : h('p', { class: 'muted' }, 'No state polls yet.'));
}

function approval(list) {
  const avg = list.find((a) => a.source === 'Average');
  const body = h('tbody', {}, ...list.filter((a) => a.source !== 'Average').map((a) => h('tr', {}, h('td', {}, a.source), h('td', { class: 'num' }, fmt.pts(a.approve)), h('td', { class: 'num' }, fmt.pts(a.disapprove)), h('td', { class: 'num' }, fmt.signed(a.net)))));
  document.getElementById('approval').append(...[h('h2', {}, 'Presidential approval'),
    avg ? h('div', { class: 'generic-big', style: { color: avg.net >= 0 ? 'var(--ink)' : 'var(--rep)' } }, `${fmt.signed(avg.net)} net`) : null,
    h('p', { class: 'card-sub' }, `The sitting president's job approval: the White House party defends an open seat in 2028.${avg ? ` Average as of ${fmt.date(avg.as_of)}.` : ''}`),
    h('table', { class: 'races-table compact' }, h('thead', {}, h('tr', {}, h('th', {}, 'Aggregator'), h('th', { class: 'num' }, 'Approve'), h('th', { class: 'num' }, 'Disapprove'), h('th', { class: 'num' }, 'Net'))), body)].filter(Boolean));
}

function economy(E) {
  const I = E.indicators || {};
  document.getElementById('economy').append(h('h2', {}, 'The economy'),
    h('div', { class: 'generic-big' }, `${fmt.signed(E.index)}`),
    h('p', { class: 'card-sub' }, 'Economic index: points of White House-party margin implied by inflation, the unemployment trend and real wage growth (0 = an ordinary economy).'),
    h('dl', { class: 'kv' },
      kv('Inflation (12 months)', isNum(I.inflation) ? `${I.inflation.toFixed(1)}%` : DASH),
      kv('Unemployment', isNum(I.unemployment) ? `${I.unemployment.toFixed(1)}%` : DASH, isNum(I.unemployment_change) ? `${fmt.signed(I.unemployment_change)} over 12 months` : ''),
      kv('Real hourly earnings (12 months)', isNum(I.real_wage_growth) ? `${fmt.signed(I.real_wage_growth)}%` : DASH),
      kv('Latest data', I.as_of || DASH, 'Bureau of Labor Statistics')));
}

function midterm(M) {
  const root = document.getElementById('midterm');
  root.append(h('h2', {}, 'The 2026 midterms'));
  if (!M) { root.append(h('p', { class: 'muted' }, 'Results not available.')); return; }
  const hv = M.house_vote, seats = M.seats;
  root.append(
    h('div', { class: 'generic-big', style: { color: hv.margin >= 0 ? 'var(--dem)' : 'var(--rep)' } }, fmt.margin(hv.margin)),
    h('p', { class: 'card-sub' }, `National House popular vote, November 3, 2026 (raw count across all 435 races, so uncontested seats count as cast): Democrats ${hv.dem_pct}%, Republicans ${hv.rep_pct}%. The most recent national test of the parties; the forecast weighs it when judging the national environment.`),
    h('dl', { class: 'kv' },
      kv('House seats', `D ${seats.house.D} · R ${seats.house.R}`, seats.house.counting ? `${seats.house.counting} still counting` : ''),
      kv('Senate seats up', `D ${seats.senate.D} · R ${seats.senate.R}`, seats.senate.counting ? `${seats.senate.counting} still counting` : ''),
      kv('Governorships up', `D ${seats.governor.D} · R ${seats.governor.R}`, seats.governor.counting ? `${seats.governor.counting} still counting` : ''),
      kv('Results as of', fmt.dateTime(M.as_of))));
}

function house(H) {
  const rows = Object.entries(H).sort((a, b) => Math.abs(b[1].effect) - Math.abs(a[1].effect));
  const root = document.getElementById('house');
  root.append(h('h2', {}, 'Pollster house effects'),
    h('p', { class: 'card-sub' }, 'How far each firm\'s national trial heats run from the consensus once candidates and timing are accounted for (D+ = more Democratic). Estimated for firms with two or more polls and removed before averaging.'));
  if (!rows.length) { root.append(h('p', { class: 'muted' }, 'Not enough repeat pollsters yet.')); return; }
  root.append(h('table', { class: 'races-table compact' }, h('thead', {}, h('tr', {}, h('th', {}, 'Pollster'), h('th', { class: 'num' }, 'House effect'), h('th', { class: 'num' }, 'Polls'))),
    h('tbody', {}, ...rows.map(([name, x]) => h('tr', {}, h('td', {}, name), h('td', { class: 'num' }, fmt.margin(x.effect)), h('td', { class: 'num' }, String(x.n_polls)))))));
}

main();
