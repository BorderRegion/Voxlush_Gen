"""Paid responses survive sample filesystem faults without another POST."""
import asyncio
import errno
from pathlib import Path

import pytest

from test_reliability_final import SOURCE, setup
from test_review_b02 import add
from voxlush.pipeline.scheduler import Scheduler
from voxlush.store.store import Store


@pytest.fixture
def store(tmp_path):
    value = Store(tmp_path/'data')
    value.create_campaign('review', 'Response recovery fixtures', 24, 120, 8, {'natural':1})
    value.set_campaign_state('review', 'running')
    yield value
    value.close()


async def test_saved_response_reapplies_after_local_path_repaired(store, fake_http):
    scheduler, posts = await setup(store, fake_http)
    bad = add(store)
    good = add(store)
    store.db.execute('UPDATE campaigns SET sequence=request_limit')
    claim = store.reserve(bad['sample_id'], 1, scheduler.config.author, 8, 8)
    path = scheduler.work_dir(claim)/'authored_source.py'
    path.mkdir(parents=True)  # A real sample-local path collision, not a broken disk.
    try:
        await scheduler.network(claim, scheduler.config.author)
        assert store.sample(bad['sample_id'])['reason_code'] == 'local_artifact_invalid'
        before = store.one('SELECT * FROM attempts WHERE attempt_id=?', (claim['attempt_id'],))
        assert before['status'] == 'complete' and before['response_applied'] == 0
        assert before['occupancy'] == 0
        assert not scheduler.storage_failed
        path.rmdir()
        store.db.execute('UPDATE samples SET next_ready_at=0')
        await scheduler.tick()
        await asyncio.gather(*scheduler.active)
        recovered = store.sample(bad['sample_id'])
        assert recovered['stage'] != 'author'
        assert Path(recovered['source_path']).read_text().strip() == SOURCE.strip()
        assert recovered['request_count'] == 1 and recovered['geometry_repairs'] == 0
        assert recovered['revision'] == 1
        assert store.sample(good['sample_id'])['stage'] == 'build'
        assert len(posts) == 2  # One per independent sample, no recovery inference.
        assert store.campaign('review')['requests_used'] == 2
        assert store.campaign('review')['cost_unknown'] == 2
        assert store.campaign('review')['reserved_cost'] == 4
        after = store.one('SELECT * FROM attempts WHERE attempt_id=?', (claim['attempt_id'],))
        assert after['response_applied'] == 1
        for key in ('result_json', 'finished_at', 'reserved_cost', 'billing_status'):
            assert after[key] == before[key]
    finally:
        await scheduler.client.close()


async def test_permanent_response_artifact_fault_is_bounded_across_restart(store, fake_http):
    scheduler, posts = await setup(store, fake_http)
    sample = add(store)
    store.db.execute('UPDATE campaigns SET sequence=request_limit')
    claim = store.reserve(sample['sample_id'], 1, scheduler.config.author, 8, 8)
    (scheduler.work_dir(claim)/'authored_source.py').mkdir(parents=True)
    try:
        await scheduler.network(claim, scheduler.config.author)
        for _ in range(8):
            store.db.execute('UPDATE samples SET next_ready_at=0')
            await scheduler.tick()
        blocked = store.sample(sample['sample_id'])
        assert blocked['reason_code'] == 'response_recovery_exhausted'
        assert blocked['local_retries'] == 3
        events = store.rows("SELECT * FROM events WHERE kind='local_failure'")
        assert len(events) == 3 and 'IsADirectoryError' in events[-1]['payload']
        await scheduler.client.close()
        store.close()
        store.__init__(store.root)
        scheduler = Scheduler(store, scheduler.config)
        await scheduler.start()
        await scheduler.stop()
        assert store.recover() == []  # Restart does not reset the retry budget.
        assert store.reserve(sample['sample_id'], 1, scheduler.config.author, 8, 8) is None
        assert len(posts) == 1
        # Explicit local retry after repairing the path still reuses the response.
        (scheduler.work_dir(claim)/'authored_source.py').rmdir()
        store.command({'command_id':'apply-saved', 'campaign_id':'review', 'action':'retry',
                       'expected_config_revision':1, 'payload':{'sample_id':sample['sample_id']}})
        store.apply_commands()
        for recovered, result in store.recover(pending_only=True):
            await scheduler.consume(recovered, result)
        assert store.sample(sample['sample_id'])['stage'] == 'build'
        assert store.campaign('review')['requests_used'] == 1
        assert len(posts) == 1
    finally:
        await scheduler.client.close()


@pytest.mark.parametrize('code', [errno.ENOSPC, errno.EROFS])
async def test_global_storage_error_during_response_recovery_stops_admission(store, fake_http, monkeypatch, code):
    scheduler, posts = await setup(store, fake_http)
    bad = add(store)
    add(store)
    store.db.execute('UPDATE campaigns SET sequence=request_limit')
    claim = store.reserve(bad['sample_id'], 1, scheduler.config.author, 8, 8)
    (scheduler.work_dir(claim)/'authored_source.py').mkdir(parents=True)
    try:
        await scheduler.network(claim, scheduler.config.author)
        def unavailable(*args, **kwargs):
            raise OSError(code, 'shared volume unavailable during response recovery')
        monkeypatch.setattr(Path, 'write_text', unavailable)
        store.db.execute('UPDATE samples SET next_ready_at=0')
        await scheduler.tick()
        await asyncio.gather(*scheduler.active)
        assert scheduler.storage_failed
        assert store.sample(bad['sample_id'])['reason_code'] == 'storage_unavailable'
        assert len(posts) == 1
        assert store.campaign('review')['requests_used'] == 1
        assert store.one('SELECT response_applied FROM attempts')['response_applied'] == 0
    finally:
        await scheduler.client.close()
