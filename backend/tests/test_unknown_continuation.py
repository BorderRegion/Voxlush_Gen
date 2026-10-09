"""Opt-in dispatch continuity never settles an unknown execution or its bill."""
import asyncio
import json
import time

import pytest

from voxlush.core.config import Config, Endpoint
from voxlush.pipeline.scheduler import Scheduler
from voxlush.store.store import Store
from test_review_b02 import add
from test_scheduler import complete_response


def configure(store, **changes):
    endpoint = Endpoint(base_url="http://fixture/v1", model="fixture", provider_cap=1,
                        cost_upper_bound=2)
    config = Config(data_root=store.root, author=endpoint, allow_live=True, global_api_cap=1,
                    unknown_execution_policy="continue_new_tasks", unknown_backoff_seconds=1,
                    **changes)
    store.bind_config(config)
    return config


@pytest.fixture
def store(tmp_path):
    value = Store(tmp_path / "data")
    value.create_campaign("review", "Continuity fixtures", 20, 100, 1, {"natural": 1})
    value.set_campaign_state("review", "running")
    yield value
    value.close()


def disconnect(store, endpoint):
    sample = add(store)
    claim = store.reserve(sample['sample_id'], 1, endpoint, 1, 8)
    assert claim
    store.settle(claim['attempt_id'], {'execution_state': 'execution_unknown',
                                     'response_complete': False, 'cost': None})
    store.finish(claim, status='blocked', reason='outcome_unknown')
    return claim


def end_cooldown(monkeypatch):
    now = time.time() + 2
    monkeypatch.setattr('voxlush.store.store.time.time', lambda: now)


def test_unknown_continues_only_after_cooldown_and_preserves_limits_and_ledger(store, monkeypatch):
    config = configure(store)
    claim = disconnect(store, config.author)
    before = store.one('SELECT * FROM attempts')
    healthy, waiting = add(store), add(store)
    assert store.reserve(healthy['sample_id'], 1, config.author, 1, 8) is None
    end_cooldown(monkeypatch)
    next_claim = store.reserve(healthy['sample_id'], 1, config.author, 1, 8)
    assert next_claim and next_claim['attempt_id'] != claim['attempt_id']
    assert store.reserve(waiting['sample_id'], 1, config.author, 1, 8) is None
    assert store.one('SELECT * FROM attempts WHERE attempt_id=?', (claim['attempt_id'],)) == before
    assert store.campaign('review')['requests_used'] == 2
    assert store.campaign('review')['reserved_cost'] == 4
    assert store.overview('review')['unknown_occupancy'] == 1
    assert store.overview('review')['active_requests'] == 1
    store.command({'command_id': 'no-replay', 'campaign_id': 'review', 'action': 'retry',
                   'expected_config_revision': store.campaign('review')['config_revision'],
                   'payload': {'sample_id': claim['sample_id']}})
    store.apply_commands()
    assert store.get_command('no-replay')['reason'] == 'attempt_outcome_unresolved'
    assert store.one('SELECT COUNT(*) n FROM assets')['n'] == 0


@pytest.mark.parametrize('limit', ['requests', 'money', 'rpm', 'tpm', 'pause', 'drain'])
def test_continuation_never_bypasses_budgets_rate_limits_or_user_controls(store, monkeypatch, limit):
    config = configure(store)
    disconnect(store, config.author)
    sample = add(store)
    end_cooldown(monkeypatch)
    if limit == 'requests':
        store.db.execute('UPDATE campaigns SET request_limit=1')
    elif limit == 'money':
        store.db.execute('UPDATE campaigns SET cost_limit=3')
    elif limit == 'rpm':
        config.author.rpm = 1
    elif limit == 'tpm':
        config.author.tpm = config.author.reservation_tokens
    else:
        store.set_campaign_state('review', 'paused' if limit == 'pause' else 'draining')
    assert store.reserve(sample['sample_id'], 1, config.author, 1, 8) is None
    assert store.campaign('review')['requests_used'] == 1
    assert store.campaign('review')['cost_unknown'] == 1
    assert store.campaign('review')['reserved_cost'] == 2


def test_restart_retains_cooldown_unknowns_and_switching_back_restores_isolation(store, monkeypatch):
    config = configure(store)
    claim = disconnect(store, config.author)
    before = store.one('SELECT * FROM attempts')
    sample = add(store)
    store.close()
    store.__init__(store.root)
    store.bind_config(config)
    assert store.reserve(sample['sample_id'], 1, config.author, 1, 8) is None
    end_cooldown(monkeypatch)
    store.bind_config(config.model_copy(update={'unknown_execution_policy': 'isolate_pool'}))
    assert store.reserve(sample['sample_id'], 1, config.author, 1, 8) is None
    store.bind_config(config)
    assert store.reserve(sample['sample_id'], 1, config.author, 1, 8)
    assert store.one('SELECT * FROM attempts WHERE attempt_id=?', (claim['attempt_id'],)) == before


def test_retry_after_applies_to_new_tasks_in_the_same_pool_after_restart(store, monkeypatch):
    config = configure(store)
    sample, healthy = add(store), add(store)
    claim = store.reserve(sample['sample_id'], 1, config.author, 1, 8)
    store.settle(claim['attempt_id'], {'execution_state': 'not_sent', 'error_category': 'rate_limited',
                                     'retry_after': 120, 'cost': 0})
    store.finish(claim, status='deferred', reason='rate_limited', delay=120)
    store.close()
    store.__init__(store.root)
    store.bind_config(config)
    end_cooldown(monkeypatch)
    assert store.reserve(healthy['sample_id'], 1, config.author, 1, 8) is None
    now = time.time() + 120
    monkeypatch.setattr('voxlush.store.store.time.time', lambda: now)
    assert store.reserve(healthy['sample_id'], 1, config.author, 1, 8)


def test_repeated_unknowns_do_not_accumulate_into_a_dispatch_deadlock(store, monkeypatch):
    config = configure(store)
    retained = []
    for _ in range(12):
        unknown = disconnect(store, config.author)
        retained.append(store.one('SELECT * FROM attempts WHERE attempt_id=?', (unknown['attempt_id'],)))
        end_cooldown(monkeypatch)
        sample = add(store)
        assert sample['sample_id'] in {r['sample_id'] for r in store.ready(['author'])}
        claim = store.reserve(sample['sample_id'], 1, config.author, 1, 8)
        assert claim
        store.settle(claim['attempt_id'], {'execution_state': 'terminated', 'cost': 1})
        store.finish(claim, status='rejected', reason='fixture_complete')
    assert store.campaign('review')['requests_used'] == 24
    assert store.campaign('review')['cost_unknown'] == 12
    assert store.campaign('review')['cost_known'] == 12
    assert store.campaign('review')['reserved_cost'] == 24
    for row in retained:
        assert store.one('SELECT * FROM attempts WHERE attempt_id=?', (row['attempt_id'],)) == row


@pytest.mark.parametrize('category', ['endpoint_auth', 'endpoint_configuration', 'endpoint_quota'])
async def test_unknown_does_not_hide_explicit_endpoint_failure(store, category):
    config = configure(store)
    scheduler = Scheduler(store, config)
    sample = add(store)
    claim = store.reserve(sample['sample_id'], 1, config.author, 1, 8)
    result = {'execution_state': 'execution_unknown', 'error_category': category, 'cost': None}
    try:
        store.settle(claim['attempt_id'], result)
        await scheduler.consume(claim, result)
        assert config.author.alias in scheduler.blocked_endpoints
        assert store.sample(sample['sample_id'])['reason_code'] == 'outcome_unknown'
        assert store.one('SELECT occupancy FROM attempts')['occupancy'] == 1
    finally:
        await scheduler.stop()


async def test_real_socket_disconnect_then_scheduler_dispatches_next_sample_after_restart(store, monkeypatch):
    posts = []

    async def handle(reader, writer):
        try:
            head = await reader.readuntil(b'\r\n\r\n')
            length = next(int(line.split(b':', 1)[1]) for line in head.split(b'\r\n')
                          if line.lower().startswith(b'content-length:'))
            posts.append(json.loads(await reader.readexactly(length)))
            if len(posts) == 1:
                return  # Actual TCP disconnect after receipt of the complete POST.
            body = complete_response()
            writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nContent-Length: '
                         + str(len(body)).encode() + b'\r\nConnection: close\r\n\r\n' + body)
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle, '127.0.0.1', 0)
    config = configure(store)
    config.author.base_url = f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1'
    scheduler = Scheduler(store, config)
    failed, healthy = add(store), add(store)
    store.db.execute('UPDATE campaigns SET sequence=request_limit')
    try:
        await scheduler.tick()
        await asyncio.gather(*scheduler.active)
        original = store.one('SELECT * FROM attempts')
        assert original['status'] == 'outcome_unknown'
        raw = (store.root / original['response_path']).read_bytes()
        await scheduler.stop()
        store.close()
        store.__init__(store.root)
        scheduler = Scheduler(store, config)
        end_cooldown(monkeypatch)
        await scheduler.tick()
        await asyncio.gather(*scheduler.active)
        assert len(posts) == 2, {'campaign': store.campaign('review'), 'healthy': store.sample(healthy['sample_id']),
                                 'cooldown': store.rows("SELECT * FROM meta WHERE key LIKE 'dispatch_after:%'"),
                                 'now': time.time(), 'active': list(scheduler.active.values())}
        assert store.sample(failed['sample_id'])['status'] == 'blocked'
        assert store.sample(healthy['sample_id'])['stage'] == 'build'
        assert store.one('SELECT * FROM attempts WHERE attempt_id=?', (original['attempt_id'],)) == original
        assert (store.root / original['response_path']).read_bytes() == raw
        assert store.one('SELECT COUNT(*) n FROM assets')['n'] == 0
        assert store.campaign('review')['requests_used'] == 2
    finally:
        await scheduler.stop()
        server.close()
        await server.wait_closed()
