"""Event arithmetic, revision provenance, failure recovery and exported history (offline)."""
from copy import deepcopy
from datetime import date
from math import exp

import pytest

from electionpredictions import hegseth, llm
from electionpredictions.db import rows, upsert
from electionpredictions.model.hegseth import BACKGROUND, INITIAL_RATES, RATE_BOUNDS, TERM_END, forecast, probabilities, validate_rates

TODAY = date(2026, 11, 9)


def test_competing_risks_agree_with_analytic_firing_only():
    rates = dict(firing=0.01, resignation=0, impeachment=0, conviction=0)
    p = probabilities(30, rates)
    assert p['fired'] == pytest.approx(1 - exp(-0.3))
    assert p['forced_exit'] == p['any_exit'] == p['fired']
    assert p['impeached'] == p['removed'] == 0
    assert p['still_serving'] + p['any_exit'] == pytest.approx(1)


def test_removal_requires_impeachment_and_obeys_two_stage_process():
    rates = dict(firing=0, resignation=0, impeachment=0.02, conviction=0.02)
    p = probabilities(30, rates)
    assert p['impeached'] == pytest.approx(1 - exp(-0.6))
    assert p['removed'] == pytest.approx(1 - exp(-0.6) * (1 + 0.6))
    assert probabilities(30, dict(rates, impeachment=0))['removed'] == 0
    assert probabilities(30, rates, status='impeached')['removed'] == pytest.approx(1 - exp(-0.6))


def test_horizons_coherent_monotonic_and_deterministic():
    hs = forecast(TODAY, INITIAL_RATES, TODAY)
    assert hs == forecast(TODAY, INITIAL_RATES, TODAY)
    assert [h['days'] for h in hs] == [30, 90, (TERM_END - TODAY).days]
    for h in hs:
        p = h['probabilities']
        assert all(0 <= v <= 1 for v in p.values())
        assert p['forced_exit'] == pytest.approx(p['fired'] + p['removed'])
        assert p['any_exit'] + p['still_serving'] == pytest.approx(1)
        assert p['any_exit'] == pytest.approx(p['forced_exit'] + p['resigned'])
        assert p['removed'] <= p['impeached']
        assert all(h['sensitivity'][k][0] <= v <= h['sensitivity'][k][1] for k, v in p.items())
    for key in ('forced_exit', 'fired', 'impeached', 'removed', 'resigned', 'any_exit'):
        assert [h['probabilities'][key] for h in hs] == sorted(h['probabilities'][key] for h in hs)


def test_firing_competes_with_senate_removal():
    low = probabilities(90, INITIAL_RATES)
    high = probabilities(90, dict(INITIAL_RATES, firing=0.1))
    assert high['fired'] > low['fired']
    assert high['removed'] < low['removed']
    assert high['impeached'] < low['impeached']


@pytest.mark.parametrize('state,key', [('fired', 'fired'), ('resigned', 'resigned'), ('removed', 'removed')])
def test_verified_outcome_is_absorbing(state, key):
    p = probabilities(800, INITIAL_RATES, status=state)
    assert p[key] == 1 and p['still_serving'] == 0
    assert probabilities(30, INITIAL_RATES, status='fired', was_impeached=True)['impeached'] == 1
    assert probabilities(30, INITIAL_RATES, status='fired')['impeached'] == 0


def test_stale_review_reverts_to_background_and_deadlines_stop_at_term():
    stale = forecast(date(2027, 3, 1), INITIAL_RATES, TODAY)[0]
    assert stale['probabilities'] == probabilities(30, BACKGROUND, elevated_days=0)
    near_end = forecast(date(2029, 1, 15), INITIAL_RATES, TODAY)
    assert all(h['days'] == 5 and h['deadline'] == '2029-01-20' for h in near_end)
    assert all(h['days'] == 0 for h in forecast(TERM_END, INITIAL_RATES, TODAY))


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), '0.1', None, True])
def test_invalid_rates_rejected(bad):
    with pytest.raises(ValueError):
        validate_rates(dict(INITIAL_RATES, firing=bad))
    bounded = validate_rates(dict(INITIAL_RATES, impeachment=999))
    assert bounded['impeachment'] == RATE_BOUNDS['impeachment'][1]


def _headline(db, *, url='https://example.com/hegseth'):
    upsert(db, 'hegseth_news', [dict(url=url, title='Hegseth faces impeachment pressure', source='Test',
                                    published='2026-11-09T10:00:00+00:00', fetched_at='2026-11-09T11:00:00+00:00')], keys=['url'])
    db.commit()


def test_revision_is_bounded_cited_deduplicated_and_isolated(db, monkeypatch):
    _headline(db)
    calls = []
    monkeypatch.setattr(llm, 'available', lambda: True)

    def respond(*args, **kwargs):
        calls.append(args)
        return dict(rates=dict(INITIAL_RATES, firing=0.05), summary='The model raises firing risk.',
                    reasons={'firing': dict(reason='Pressure on the secretary increased.', urls=['https://example.com/hegseth'])}), 'test-model'

    monkeypatch.setattr(llm, 'ask_json_with', respond)
    hegseth.update(db, today=TODAY, fetch_news=False)
    assert hegseth._latest(db)['rates']['firing'] == INITIAL_RATES['firing'] * 2
    hegseth.update(db, today=TODAY, fetch_news=False)
    assert len(calls) == 1
    assert rows(db, 'SELECT count(*) n FROM hegseth_reviews')[0]['n'] == 2
    assert rows(db, 'SELECT count(*) n FROM hegseth_history')[0]['n'] == 1
    assert rows(db, 'SELECT count(*) n FROM news')[0]['n'] == 0
    assert rows(db, 'SELECT count(*) n FROM model_specs')[0]['n'] == 0


@pytest.mark.parametrize('response', [
    dict(rates=dict(INITIAL_RATES, firing=0.04), summary='Change', reasons={}),
    dict(rates=dict(INITIAL_RATES, firing=0.04), summary='Change',
         reasons={'firing': dict(reason='Claim', urls=['https://invented.test/'])}),
    dict(rates=dict(INITIAL_RATES, firing=float('nan')), summary='Bad'),
    dict(rates={}),
])
def test_failed_review_keeps_prior_rates_and_review_date(db, monkeypatch, response):
    _headline(db)
    monkeypatch.setattr(llm, 'available', lambda: True)
    monkeypatch.setattr(llm, 'ask_json_with', lambda *a, **kw: (deepcopy(response), 'bad'))
    result = hegseth.update(db, today=TODAY, fetch_news=False)
    assert result['warnings']
    assert hegseth._latest(db)['rates'] == INITIAL_RATES
    assert hegseth._latest(db)['reviewed_at'].startswith(hegseth.SEED_DATE)
    assert rows(db, "SELECT ok FROM runs WHERE stage='hegseth'")[0]['ok'] == 0


def test_collection_failure_preserves_evidence_and_exports_stale_state(db, monkeypatch, tmp_path):
    _headline(db)
    monkeypatch.setattr(hegseth.news, 'fetch', lambda *a, **kw: [])
    monkeypatch.setattr(llm, 'available', lambda: False)
    result = hegseth.update(db, today=TODAY)
    assert result['warnings']
    out = hegseth.export(db, tmp_path, today=date(2026, 11, 12))
    assert out['news'] and out['review_stale']
    assert out['status']['state'] == 'serving' and out['last_update']['ok'] == 0
    assert len(out['history']) == 1 and len(out['horizons']) == 3
    assert (tmp_path / 'hegseth.json').exists()


def test_future_and_old_headlines_are_excluded(db):
    for day in ('2026-11-10', '2026-09-01'):
        upsert(db, 'hegseth_news', [dict(url='https://example.com/' + day, title='Hegseth', source='Test',
                                       published=day, fetched_at='2026-11-09')], keys=['url'])
    assert hegseth.evidence(db, TODAY) == []


def test_offline_update_seeds_persistent_review_and_never_calls_network(db, monkeypatch, tmp_path):
    def fail(*a, **kw):
        pytest.fail('Offline update attempted network')
    monkeypatch.setattr(hegseth.news, 'fetch', fail)
    monkeypatch.setattr(llm, 'ask_json_with', fail)
    hegseth.update(db, today=TODAY, fetch_news=False, revise=False)
    payload = hegseth.export(db, tmp_path, today=TODAY)
    assert payload['model_version'] == 1 and len(payload['reviews']) == 1
    assert payload['history'][0]['horizons'] == payload['horizons']


def test_no_history_is_created_before_tracking_begins(db, tmp_path):
    result = hegseth.update(db, today=date(2026, 11, 5), fetch_news=False, revise=False)
    assert result['review'] == 'Tracking has not begun.'
    payload = hegseth.export(db, tmp_path, today=date(2026, 11, 5))
    assert payload['available'] is False
    assert rows(db, 'SELECT count(*) n FROM hegseth_history')[0]['n'] == 0


def test_partial_feed_failure_keeps_good_items_and_prior_evidence(db, monkeypatch):
    _headline(db)
    def fetch(query, **kwargs):
        if query == hegseth.QUERIES[0]:
            raise RuntimeError('Feed unavailable')
        return [dict(url='https://example.com/new', title='Hegseth faces House debate', source='Test',
                     published='2026-11-09T12:00:00+00:00')]
    monkeypatch.setattr(hegseth.news, 'fetch', fetch)
    result = hegseth.update(db, today=TODAY, revise=False)
    assert result['headlines'] == 1 and result['warnings']
    assert len(hegseth.evidence(db, TODAY)) == 2


def test_new_evidence_waits_six_hours_after_a_successful_review(db, monkeypatch):
    _headline(db)
    monkeypatch.setattr(llm, 'available', lambda: True)
    calls = []
    def respond(*args, **kwargs):
        calls.append(1)
        return dict(rates=INITIAL_RATES, summary='The evidence supports retaining the rates.', reasons={}), 'model'
    monkeypatch.setattr(llm, 'ask_json_with', respond)
    hegseth.update(db, today=TODAY, fetch_news=False)
    _headline(db, url='https://example.com/another')
    hegseth.update(db, today=TODAY, fetch_news=False)
    assert len(calls) == 1
