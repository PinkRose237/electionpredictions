/**
 * field.js — the nomination contests (field.html): each party's candidates with status, primary polling,
 * nomination odds, general-election strength and fundraising; recent primary polls; market prices for
 * comparison; coverage; and the likeliest matchups.
 */
import { DASH, TOTAL_EV, loadJSON, fmt, isNum, h, probChip, partyClass, initChrome, renderUpdated, renderFooterMeta, showError, relativeTime } from './common.js';

let F = null, party = location.hash === '#R' ? 'R' : 'D';

async function main() {
  initChrome({ current: 'field' });
  const status = document.getElementById('status');
  try {
    const [summary, field] = await Promise.all([loadJSON('summary.json'), loadJSON('field.json')]);
    F = field;
    status.hidden = true;
    document.getElementById('app').hidden = false;
    renderUpdated(summary); renderFooterMeta(summary);
    const tabs = [...document.querySelectorAll('#party-tabs .tab')];
    const paintTabs = () => tabs.forEach((t) => t.setAttribute('aria-selected', t.dataset.party === party ? 'true' : 'false'));
    tabs.forEach((t) => t.addEventListener('click', () => { party = t.dataset.party; history.replaceState(null, '', `#${party}`); paintTabs(); draw(); }));
    paintTabs();
    draw();
    scenarios(field.scenarios || []);
  } catch (err) {
    console.error(err);
    showError(status, err);
  }
}

const STATUS = { declared: 'Declared', exploratory: 'Exploring', potential: 'Not declared' };

function draw() {
  const P = F.parties[party];
  const word = party === 'D' ? 'Democratic' : 'Republican';
  const root = document.getElementById('party');
  const named = P.candidates.filter((c) => isNum(c.p_nominee) || (c.primary_share || 0) >= 1 || c.status !== 'potential');
  const max = Math.max(...named.map((c) => c.p_nominee || 0), 0.01);
  const body = h('tbody');
  for (const c of named) {
    body.append(h('tr', {},
      h('td', {}, h('span', { class: `party-dot ${partyClass(party)}`, 'aria-hidden': 'true' }), h('strong', {}, c.name),
        c.experience ? h('div', { class: 'muted small' }, c.experience) : null),
      h('td', {}, h('span', { class: `chip status-${c.status || 'potential'}` }, STATUS[c.status] || 'Not declared'), c.home_state ? h('span', { class: 'muted small' }, ` ${c.home_state}`) : null),
      h('td', { class: 'num' }, isNum(c.primary_share) ? `${c.primary_share.toFixed(1)}%` : DASH),
      h('td', { class: 'num' }, isNum(c.p_nominee) ? fmt.pct(c.p_nominee, c.p_nominee < 0.01 ? 1 : 0) : DASH),
      h('td', { class: 'bar-cell' }, isNum(c.p_nominee) ? h('span', { class: `mini-bar ${partyClass(party)}`, style: { width: `${(c.p_nominee / max) * 100}%` } }) : null),
      h('td', { class: 'num' }, isNum(c.effect) ? fmt.signed(c.effect) : DASH),
      h('td', { class: 'num' }, isNum(c.p_win_if_nominee) ? probChip(party === 'D' ? c.p_win_if_nominee : 1 - c.p_win_if_nominee) : DASH),
      h('td', { class: 'num' }, isNum(c.receipts) ? fmt.money(c.receipts) : DASH)));
  }
  const other = P.other;
  const children = [
    h('div', { class: 'card' },
      h('h2', {}, `${word} nomination`),
      P.narrative ? h('p', { class: 'prose' }, P.narrative) : null,
      h('p', { class: 'card-sub' }, `Primary polling average from ${fmt.num(P.n_polls)} national primary polls (recent polls weigh more). Nomination odds are the forecast's; `
        + `${other ? `${fmt.pct(other.p)} goes to someone not listed. ` : ''}Strength is points of November margin versus an average nominee. `
        + `The last columns show the chance a Democrat wins the presidency if this candidate is the ${word} nominee, and money raised (FEC).`),
      h('div', { class: 'table-wrap' }, h('table', { class: 'races-table field-table' },
        h('thead', {}, h('tr', {}, h('th', {}, 'Candidate'), h('th', {}, 'Status'), h('th', { class: 'num' }, 'Primary polls'), h('th', { class: 'num' }, 'Nominee odds'), h('th', {}, ''),
          h('th', { class: 'num' }, 'Strength'), h('th', { class: 'num' }, 'Democrat wins if nominee'), h('th', { class: 'num' }, 'Raised'))), body))),
  ];
  children.push(h('div', { class: 'two-col section' }, primaryPolls(P), side(P)));
  root.replaceChildren(...children);
}

function primaryPolls(P) {
  const names = Object.keys(P.average || {}).slice(0, 7);
  const body = h('tbody');
  for (const p of P.polls.slice(0, 15)) {
    body.append(h('tr', {}, h('td', {}, p.pollster), h('td', {}, fmt.dateRange(p.start, p.end)),
      ...names.map((n) => h('td', { class: 'num' }, isNum(p.shares[n]) ? `${Math.round(p.shares[n])}` : DASH))));
  }
  return h('div', { class: 'card' }, h('h3', {}, 'Recent primary polls'),
    h('div', { class: 'table-wrap' }, h('table', { class: 'races-table compact' },
      h('thead', {}, h('tr', {}, h('th', {}, 'Pollster'), h('th', {}, 'Dates'), ...names.map((n) => h('th', { class: 'num' }, n.split(' ').slice(-1)[0])))), body)),
    P.aggregates && P.aggregates.length ? h('p', { class: 'table-note' }, 'Aggregators: ', P.aggregates.filter((a) => a.source !== 'Average').map((a) => {
      const top = Object.entries(a.shares).sort((x, y) => y[1] - x[1])[0];
      return `${a.source}${a.as_of ? ` (${fmt.dateShort(a.as_of)})` : ''}: ${top ? `${top[0]} ${top[1]}%` : ''}`;
    }).join(' · ')) : null);
}

function side(P) {
  const card = h('div', { class: 'card' });
  if (P.markets && P.markets.length) {
    const byOutcome = new Map();
    for (const m of P.markets) {
      if (!byOutcome.has(m.outcome)) byOutcome.set(m.outcome, {});
      byOutcome.get(m.outcome)[m.platform] = m.p;
    }
    const rows = [...byOutcome.entries()].slice(0, 8);
    card.append(h('h3', {}, 'Prediction markets'), h('p', { class: 'card-sub' }, 'For comparison only; markets are never an input to the forecast.'),
      h('table', { class: 'races-table compact' }, h('thead', {}, h('tr', {}, h('th', {}, 'Candidate'), h('th', { class: 'num' }, 'Polymarket'), h('th', { class: 'num' }, 'Kalshi'))),
        h('tbody', {}, ...rows.map(([n, v]) => h('tr', {}, h('td', {}, n), h('td', { class: 'num' }, fmt.pct(v.polymarket)), h('td', { class: 'num' }, fmt.pct(v.kalshi)))))));
  }
  if (P.news && P.news.length) {
    card.append(h('h3', {}, 'Recent coverage'), h('ul', { class: 'news-list' }, ...P.news.slice(0, 8).map((n) => h('li', {},
      h('a', { href: n.url, target: '_blank', rel: 'noopener' }, n.title), h('span', { class: 'news-meta' }, ` ${n.source || ''} · ${relativeTime(n.published)}`)))));
  }
  return card;
}

function scenarios(list) {
  const body = h('tbody');
  for (const s of list) {
    body.append(h('tr', {}, h('td', {}, `${s.dem} vs ${s.rep}`), h('td', { class: 'num' }, fmt.pct(s.p, 1)), h('td', { class: 'num' }, probChip(s.p_dem)),
      h('td', { class: 'num' }, `${fmt.num(s.dem_ev)}–${fmt.num(TOTAL_EV - s.dem_ev)}`), h('td', { class: 'num' }, fmt.margin(s.pv_margin))));
  }
  document.getElementById('scen').replaceChildren(h('table', { class: 'races-table' },
    h('thead', {}, h('tr', {}, h('th', {}, 'Matchup'), h('th', { class: 'num' }, 'Chance of matchup'), h('th', { class: 'num' }, 'Democrat wins'), h('th', { class: 'num' }, 'Expected EVs'), h('th', { class: 'num' }, 'Popular vote'))), body));
}

main();
