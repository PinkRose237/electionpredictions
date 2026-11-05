/**
 * home.js — the results home page: control of each chamber, flips, races still counting, the latest
 * calls and how the forecast did. Data from results-data.js; refreshes every minute.
 */
import { CHAMBER_LABEL, fmt, isNum, h, raceHref, ratingPill, partyClass, lastName, initChrome, renderUpdated, renderFooterMeta, showError, relativeTime } from './common.js';
import { loadResults, keepFresh, tally, latestCalls, scorecard, displayName, sideParty } from './results-data.js';

const CHAMBERS = ['senate', 'house', 'governor'];
const PARTY_NAME = { dem: 'Democrats', rep: 'Republicans' };

async function main() {
  initChrome({ current: 'home' });
  const status = document.getElementById('status');
  let S;
  try {
    S = await loadResults();
  } catch (err) {
    console.error(err);
    showError(status, err, 'The results page needs data/races.json.');
    return;
  }
  if (S.summary) { renderUpdated(S.summary); renderFooterMeta(S.summary); }
  status.hidden = true;
  document.getElementById('home').hidden = false;
  render(S);
  keepFresh(S, render);
  setInterval(() => renderFreshness(S), 30e3);
}

function render(S) {
  const tallies = Object.fromEntries(CHAMBERS.map((ch) => [ch, tally(S, ch)]));
  renderHeadline(tallies);
  renderFreshness(S);
  renderOutcomes(tallies);
  renderCounting(S, tallies);
  renderLatest(S);
  renderScore(S);
}

function verdict(t, ch) {
  const name = ch === 'governor' ? 'a majority of governorships' : `the ${CHAMBER_LABEL[ch]}`;
  if (t.control) return { text: `${PARTY_NAME[t.control]} win ${name}`, party: t.control, final: true };
  const { d, r } = t.projected;
  if (d >= t.needed) return { text: `Democrats on track to win ${name}`, party: 'dem' };
  if (r >= t.needed) return { text: `Republicans on track to win ${name}`, party: 'rep' };
  return { text: `${CHAMBER_LABEL[ch]} too close to call`, party: null };
}

function renderHeadline(tallies) {
  const parts = CHAMBERS.map((ch) => verdict(tallies[ch], ch).text);
  const counting = CHAMBERS.reduce((n, ch) => n + tallies[ch].uncalled.length, 0);
  document.getElementById('headline').textContent = `${parts[0]}. ${parts[1]}. ${parts[2]}.` +
    (counting ? ` ${counting} race${counting === 1 ? ' is' : 's are'} still being counted.` : ' Every race has been called.');
}

function renderFreshness(S) {
  const el = document.getElementById('freshness');
  el.textContent = `${S.source === 'live' ? 'Live from the AP' : 'From the latest saved count'} · updated ${S.updatedAt ? relativeTime(S.updatedAt) : 'just now'} · refreshes every minute`;
}

function renderOutcomes(tallies) {
  const el = document.getElementById('outcomes');
  el.replaceChildren(...CHAMBERS.map((ch) => {
    const t = tallies[ch];
    const v = verdict(t, ch);
    const pct = (n) => `${(100 * n) / t.total}%`;
    const seg = (n, cls) => (n ? h('span', { class: `sb-seg ${cls}`, style: { width: pct(n) } }) : null);
    const f = t.forecast;
    return h('article', { class: `card sb-card outcome${v.final ? ` won ${v.party}` : ''}` },
      h('div', { class: 'sb-head' }, h('h2', {}, CHAMBER_LABEL[ch]), h('span', { class: 'sb-need' }, `${t.needed} for ${ch === 'governor' ? 'a majority' : 'control'}`)),
      h('div', { class: `verdict ${v.party ? partyClass(v.party === 'dem' ? 'D' : 'R') : ''}` }, v.final ? '✓ ' : '', v.text),
      h('div', { class: 'sb-nums' },
        h('div', { class: 'sb-side dem' }, h('span', { class: 'sb-big' }, String(t.dWon)), h('span', { class: 'sb-lbl' }, 'Democrats', t.dLead ? h('span', { class: 'sb-lead' }, ` +${t.dLead} leading`) : null)),
        h('div', { class: 'sb-side rep' }, h('span', { class: 'sb-big' }, String(t.rWon)), h('span', { class: 'sb-lbl' }, 'Republicans', t.rLead ? h('span', { class: 'sb-lead' }, ` +${t.rLead} leading`) : null))),
      h('div', { class: 'sb-bar', role: 'img', 'aria-label': `${t.dWon} Democratic, ${t.rWon} Republican, ${t.uncalled.length} uncalled` },
        seg(t.dWon, 'dem'), seg(t.dLead, 'dem lead'), seg(t.open + t.oWon, 'open'), seg(t.rLead, 'rep lead'), seg(t.rWon, 'rep'),
        h('span', { class: 'sb-mark', style: { left: pct(t.needed) } })),
      h('div', { class: 'sb-foot' },
        t.uncalled.length ? `${t.uncalled.length} still counting` : 'All races called',
        t.total !== t.up ? ` · ${t.total - t.up} seats not up` : '',
        f ? ` · forecast: ${fmt.pct(f.p_dem)} Democratic control, D ${Math.round(f.dem_seats.mean)} seats` : ''),
      t.flips.length ? h('div', { class: 'sb-flips' }, `${t.flips.length} flip${t.flips.length === 1 ? '' : 's'}: `,
        ...t.flips.slice(0, 10).flatMap((x, i) => [i ? ', ' : '', h('a', { href: raceHref(x.race.race_id), class: `flip ${partyClass(x.to)}` }, `${x.race.short} ${x.from}→${x.to}`)]),
        t.flips.length > 10 ? ` and ${t.flips.length - 10} more` : '') : null,
    );
  }));
}

function renderCounting(S, tallies) {
  const el = document.getElementById('counting');
  const all = CHAMBERS.flatMap((ch) => tallies[ch].uncalled);
  const order = { senate: 0, governor: 1, house: 2 };
  // Senate and governor races first, then the closest House seats.
  const list = [...all.filter((x) => x.race.chamber !== 'house').sort((a, b) => order[a.race.chamber] - order[b.race.chamber]),
    ...all.filter((x) => x.race.chamber === 'house')].slice(0, 14);
  el.replaceChildren(
    h('div', { class: 'card-head' }, h('h2', { id: 'h-counting' }, 'Still counting'),
      h('a', { class: 'small', href: 'results.html#counting' }, `All ${all.length} →`)),
    all.length ? h('ul', { class: 'count-list' }, ...list.map(({ race, st }) => {
      const lead = st.leader;
      const cand = lead && race[lead];
      return h('li', {},
        h('a', { class: 'cl-race', href: raceHref(race.race_id) }, race.short),
        ratingPill(race.label),
        st.kind === 'counting' && cand
          ? h('span', { class: `cl-lead ${partyClass(sideParty(race, lead))}` }, `${lastName(cand.name)} +${Math.abs(st.sh.margin).toFixed(1)}`)
          : h('span', { class: 'cl-lead muted' }, st.kind === 'runoff' ? 'Runoff' : 'No votes yet'),
        h('span', { class: 'cl-in muted num' }, st.e && isNum(st.e.reporting) ? `${Math.round(st.e.reporting)}% in` : ''),
        st.e && st.e.awaiting ? h('span', { class: 'cl-await muted' }, `${st.e.awaiting} of ${st.e.awaitingOf} called`) : null);
    })) : h('p', { class: 'muted' }, 'Every race has been called.'),
    h('p', { class: 'muted small' }, 'Some states take days or weeks to finish counting: mail ballots in California, Nevada and Washington arrive after election day, and Alaska and Maine run ranked-choice tabulations later in November.'),
  );
}

function renderLatest(S) {
  const el = document.getElementById('latest');
  const list = latestCalls(S).slice(0, 12);
  const clock = (iso) => new Date(iso).toLocaleString([], { weekday: 'short', hour: 'numeric', minute: '2-digit' });
  el.replaceChildren(
    h('div', { class: 'card-head' }, h('h2', { id: 'h-latest' }, 'Latest calls'), h('a', { class: 'small', href: 'calls.html' }, 'By outlet →')),
    list.length ? h('ol', { class: 'latest-list' }, ...list.map((c) => {
      const cand = c.race[c.st.winner];
      return h('li', {},
        h('span', { class: 'lc-time num' }, clock(c.at)),
        h('a', { class: 'lc-race', href: raceHref(c.race.race_id) }, c.race.short),
        h('span', { class: `lc-win ${partyClass(c.st.party)}` }, cand ? `${cand.name} (${c.st.party})` : 'Another candidate'),
        c.st.flip ? h('span', { class: `lc-flip ${partyClass(c.st.party)}` }, 'Flip') : null,
        h('span', { class: 'lc-who muted' }, `first: ${c.first} · ${c.n} of 4`));
    })) : h('p', { class: 'muted' }, 'No races confirmed yet.'),
  );
}

function renderScore(S) {
  const el = document.getElementById('score');
  const sc = scorecard(S);
  el.replaceChildren(
    h('div', { class: 'card-head' }, h('h2', { id: 'h-score' }, 'How the forecast did'), h('a', { class: 'small', href: 'scorecard.html' }, 'Full scorecard →')),
    h('div', { class: 'score-tiles' },
      h('div', { class: 'tile' }, h('b', {}, `${sc.hits} of ${sc.n}`), h('span', {}, 'called races went to the favorite')),
      h('div', { class: 'tile' }, h('b', {}, sc.brier !== null ? sc.brier.toFixed(3) : '—'), h('span', {}, 'Brier score (0 is perfect, 0.25 is a coin flip)')),
      sc.median !== null ? h('div', { class: 'tile' }, h('b', { class: sc.median > 0 ? 'dem-text' : 'rep-text' }, fmt.margin(sc.median)),
        h('span', {}, `typical miss on the margin (${sc.margins.length} races with 95%+ counted)`)) : null),
    sc.upsets.length ? h('div', {}, h('h3', { class: 'sub-h' }, 'Upsets'), h('ul', { class: 'check-list' }, ...sc.upsets.slice(0, 6).map((u) =>
      h('li', {}, h('a', { href: raceHref(u.race.race_id) }, u.race.short), ' ', ratingPill(u.race.label),
        ` ${displayName(u.race)}: the model gave the winner ${Math.round((1 - u.conf) * 100)}%`)))) : null,
  );
}

main();
