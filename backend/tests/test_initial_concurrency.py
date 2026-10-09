import asyncio
import time

import pytest

from voxlush.core.config import Config, Endpoint
from voxlush.pipeline.scheduler import Scheduler
from voxlush.store.store import Store
from voxlush.themes.planner import runtime_task, task_for


@pytest.mark.parametrize('initial,global_cap,campaign_cap,provider_cap,expected', [
    (256, 256, 256, 256, 256), (16, 16, 16, 16, 16), (16, 4, 16, 16, 4),
    (16, 16, 3, 16, 3), (16, 16, 16, 2, 2), (16, 0, 16, 16, 0),
])
async def test_explicit_starting_concurrency_keeps_all_dispatch_limits(
        tmp_path, fake_http, initial, global_cap, campaign_cap, provider_cap, expected):
    # Actual loopback sockets stay open without a complete response. No paid calls.
    url, requests = await fake_http(
        b'data: {"choices":[{"delta":{"reasoning_content":"working"}}]}\n\n', hold_open=True)
    store = Store(tmp_path / 'data')
    endpoint = Endpoint(base_url=url, model='fixture', provider_cap=provider_cap)
    config = Config(data_root=store.root, allow_live=True, author=endpoint,
                    initial_api_cap=initial, global_api_cap=global_cap)
    scheduler = Scheduler(store, config)
    try:
        campaign = store.create_campaign('cap', 'Explicit concurrency', 512, 1024, campaign_cap, {'natural': 1})
        store.set_campaign_state('cap', 'running')
        for sequence in range(max(32, expected)):
            store.add_sample(runtime_task(task_for(campaign, 'geology', sequence, 'fixture')))
        assert not config.is_qualified()
        for _ in range(150):
            await scheduler.tick()
            await asyncio.sleep(.03)
            if len(requests) == expected:
                break
        assert len(requests) == expected
        assert store.campaign('cap')['requests_used'] == expected
        assert store.one('SELECT COALESCE(SUM(occupancy),0) n FROM attempts')['n'] == expected
        assert store.campaign('cap')['accepted_unique'] == 0
    finally:
        await scheduler.stop(timeout=0)
        store.close()


async def test_default_start_and_backoff_do_not_change_quality_identity(tmp_path):
    store = Store(tmp_path / 'data')
    config = Config(data_root=store.root, global_api_cap=32,
                    author=Endpoint(base_url='http://fixture.invalid', model='fixture'))
    scheduler = Scheduler(store, config)
    try:
        assert scheduler.cap() == 8
        selected = config.model_copy(update={'initial_api_cap': 16})
        assert selected.profile_hash() == config.profile_hash()
        assert selected.snapshot()['initial_api_cap'] == 16
        scheduler.adaptive_cap = 16
        scheduler.window_started = time.monotonic() - 121
        scheduler.window_results = [{'error_category': 'rate_limited'}] * 30
        scheduler.adapt()
        assert scheduler.cap() == 11
        scheduler.window_started = time.monotonic() - 121
        scheduler.window_results = [{'response_complete': True}] * 30
        scheduler.adapt()
        assert scheduler.cap() == 11  # Qualification still gates automatic growth.
    finally:
        await scheduler.client.close()
        store.close()
