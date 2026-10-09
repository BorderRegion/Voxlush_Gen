"""Liveness regressions: real loopback transport and isolated local resources."""
import asyncio
import errno
import json

import pytest

from voxlush.core.config import Config, Endpoint
from voxlush.pipeline.scheduler import Scheduler
from voxlush.pipeline import scheduler as module
from voxlush.voxel import sandbox
from test_review_b02 import add
from voxlush.store.store import Store
from test_inference import completion, sse

SOURCE = "O('land','地','land','landscape')\nC('rock','岩','rock','rock',floor='ground',parent_id='land')\nB(1,4,1,4,1,4,'stone','rock')\n"


@pytest.fixture
def store(tmp_path):
    value = Store(tmp_path / 'data')
    value.create_campaign('review', 'Reliability fixtures', 24, 120, 8, {'natural': 1})
    value.set_campaign_state('review', 'running')
    yield value
    value.close()


async def setup(store, fake_http):
    url, posts = await fake_http(sse(completion(SOURCE), b'[DONE]'))
    endpoint = Endpoint(base_url=url, model='fixture', cost_upper_bound=2)
    scheduler = Scheduler(store, Config(data_root=store.root, author=endpoint, allow_live=True))
    return scheduler, posts


async def tick(scheduler):
    await scheduler.tick()
    await asyncio.gather(*scheduler.active)


async def test_historical_terminal_render_failure_does_not_block_other_campaign(store, fake_http):
    scheduler, posts = await setup(store, fake_http)
    bad = add(store)
    store.finish(store.claim(bad['sample_id'], 1), stage='render', status='blocked', reason='render_failed')
    store.create_campaign('healthy', 'Healthy', 2, 8, 2, {'natural': 1})
    store.set_campaign_state('healthy', 'running')
    good = add(store, 'healthy')
    store.db.execute('UPDATE campaigns SET sequence=request_limit')
    try:
        await tick(scheduler)
        assert len(posts) == 1
        assert store.sample(good['sample_id'])['stage'] == 'build'
        assert store.sample(bad['sample_id'])['status'] == 'blocked'
    finally:
        await scheduler.client.close()


@pytest.mark.parametrize('code', [errno.ENOENT, errno.ENOTDIR, errno.EACCES])
async def test_sample_file_fault_is_local_and_never_author_repair(store, fake_http, monkeypatch, code):
    scheduler, posts = await setup(store, fake_http)
    source = store.root/'source.py'
    source.write_text(SOURCE)
    bad = add(store, source=source)
    good = add(store)
    store.db.execute('UPDATE campaigns SET sequence=request_limit')
    def broken(*args, **kwargs):
        raise OSError(code, 'isolated sample artifact fault')
    monkeypatch.setattr(module, 'build', broken)
    try:
        await scheduler.local(store.claim(bad['sample_id'], 1))
        assert not scheduler.storage_failed
        after = store.sample(bad['sample_id'])
        assert after['geometry_repairs'] == 0 and after['revision'] == 1
        assert after['status'] == 'blocked'
        await tick(scheduler)
        assert len(posts) == 1 and store.sample(good['sample_id'])['stage'] == 'build'
        assert store.rows("SELECT * FROM events WHERE sample_id=? AND kind='local_failure'", (bad['sample_id'],))
    finally:
        await scheduler.client.close()


@pytest.mark.parametrize('code', [errno.ENOSPC, errno.EROFS, errno.EIO])
async def test_shared_storage_failure_blocks_paid_dispatch(store, fake_http, monkeypatch, code):
    scheduler, posts = await setup(store, fake_http)
    source = store.root/'source.py'
    source.write_text(SOURCE)
    sample = add(store, source=source)
    add(store)
    def broken(*args, **kwargs):
        raise OSError(code, 'shared volume fault')
    monkeypatch.setattr(module, 'build', broken)
    try:
        await scheduler.local(store.claim(sample['sample_id'], 1))
        await tick(scheduler)
        assert scheduler.storage_failed and not posts
        assert store.sample(sample['sample_id'])['geometry_repairs'] == 0
    finally:
        await scheduler.client.close()


async def test_sandbox_outage_and_automatic_recovery_keep_source_budget(store, fake_http, monkeypatch):
    scheduler, posts = await setup(store, fake_http)
    source = store.root/'source.py'
    source.write_text(SOURCE)
    sample = add(store, source=source)
    healthy = add(store)
    store.db.execute('UPDATE campaigns SET sequence=request_limit')
    real_image_info = sandbox.image_info
    calls = []
    def unavailable(*args, **kwargs):
        calls.append(1)
        raise sandbox.SandboxError('sandbox_unavailable', 'injected daemon outage')
    monkeypatch.setattr(sandbox, 'image_info', unavailable)
    try:
        await scheduler.local(store.claim(sample['sample_id'], 1))
        await tick(scheduler)
        assert not posts
        count = len(calls)
        for _ in range(4):
            await tick(scheduler)
        assert len(calls) == count  # Cooldown probes, no task retry storm.
        monkeypatch.setattr(sandbox, 'image_info', real_image_info)
        scheduler.next_resource_probe = 0
        await tick(scheduler)
        state = store.sample(sample['sample_id'])
        assert state['stage'] == 'render'
        assert state['source_path'] == str(source) and state['revision'] == 1
        assert state['geometry_repairs'] == state['request_count'] == 0
        assert store.sample(healthy['sample_id'])['stage'] == 'build'
        assert len(posts) == 1  # Healthy independent author, never the outage sample.
    finally:
        await scheduler.client.close()


@pytest.mark.parametrize('action,expected', [(None,'running'),('pause','paused'),('drain','draining'),('emergency_stop','paused')])
async def test_normal_shutdown_preserves_user_intent(store, fake_http, action, expected):
    scheduler, posts = await setup(store, fake_http)
    sample = add(store)
    store.db.execute('UPDATE campaigns SET sequence=request_limit')
    if action:
        store.command({'command_id':'intent','campaign_id':'review','action':action,'expected_config_revision':1})
        store.apply_commands()
    await scheduler.stop()
    assert store.campaign('review')['state'] == expected
    store.close()
    store.__init__(store.root)
    restarted = Scheduler(store, scheduler.config)
    try:
        await restarted.start()
        for _ in range(100):
            if posts or action:
                break
            await asyncio.sleep(.01)
        await restarted.stop()
        assert store.campaign('review')['state'] == expected
        assert len(posts) == (1 if action is None else 0)
        assert store.sample(sample['sample_id'])['revision'] == 1
    finally:
        await restarted.client.close()


async def test_restart_keeps_unknown_identity_cost_and_pool_isolation(store, fake_http):
    url, posts = await fake_http(None)
    endpoint = Endpoint(base_url=url, model='fixture', cost_upper_bound=2)
    config = Config(data_root=store.root, author=endpoint, allow_live=True)
    scheduler = Scheduler(store, config)
    sample = add(store)
    add(store)
    store.db.execute('UPDATE campaigns SET sequence=request_limit')
    claim = store.reserve(sample['sample_id'], 1, endpoint, 8, 8)
    await scheduler.network(claim, endpoint)
    before = store.one('SELECT * FROM attempts')
    campaign = store.campaign('review')
    await scheduler.stop()
    store.close()
    store.__init__(store.root)
    restarted = Scheduler(store, config)
    try:
        await restarted.start()
        await asyncio.sleep(.25)
        await restarted.stop()
        after = store.one('SELECT * FROM attempts')
        assert len(posts) == 1 and after == before
        for key in ('requests_used','reserved_cost','cost_unknown','cost_known'):
            assert store.campaign('review')[key] == campaign[key]
        assert store.campaign('review')['state'] == 'running'
    finally:
        await restarted.client.close()


@pytest.mark.parametrize('action', [None, 'pause', 'drain', 'emergency_stop'])
async def test_legacy_shutdown_respects_queued_user_control(store, fake_http, action):
    scheduler, posts = await setup(store, fake_http)
    add(store)
    store.db.execute('UPDATE campaigns SET sequence=request_limit')
    store.set_campaign_state('review', 'draining', 'shutdown')
    if action:
        store.command({'command_id':'queued-control','campaign_id':'review','action':action,'expected_config_revision':1})
    try:
        await scheduler.start()
        await asyncio.sleep(.1)
        await scheduler.stop()
        expected = 'running' if action is None else 'draining' if action == 'drain' else 'paused'
        assert store.campaign('review')['state'] == expected
        assert len(posts) == int(action is None)
    finally:
        await scheduler.client.close()


async def test_permanent_renderer_failure_exhausts_locally_without_global_stop(store, fake_http, monkeypatch):
    scheduler, posts = await setup(store, fake_http)
    bad = add(store)
    store.finish(store.claim(bad['sample_id'],1), stage='render', changes={'build_path':str(store.root/'broken')})
    def broken(*args, **kwargs):
        raise FileNotFoundError(errno.ENOENT, 'missing one saved voxel artifact')
    monkeypatch.setattr(module, 'render', broken)
    try:
        for _ in range(3):
            store.db.execute('UPDATE samples SET next_ready_at=0')
            await scheduler.local(store.claim(bad['sample_id'],1))
        assert store.sample(bad['sample_id'])['status'] == 'blocked'
        assert store.sample(bad['sample_id'])['local_retries'] == 3
        assert store.sample(bad['sample_id'])['geometry_repairs'] == 0
        good = add(store)
        store.db.execute('UPDATE campaigns SET sequence=request_limit')
        await tick(scheduler)
        assert len(posts) == 1 and not scheduler.storage_failed
        assert store.sample(good['sample_id'])['stage'] == 'build'
    finally:
        await scheduler.client.close()


async def test_resource_probe_cannot_retry_one_permanent_task_forever(store, fake_http, monkeypatch):
    scheduler, posts = await setup(store, fake_http)
    source = store.root/'source.py'
    source.write_text(SOURCE)
    bad = add(store, source=source)
    store.db.execute('UPDATE campaigns SET sequence=request_limit')
    calls=[]
    def broken(*args, **kwargs):
        calls.append(1)
        raise sandbox.SandboxError('sandbox_unavailable','task-local container launch failure')
    monkeypatch.setattr(module,'build',broken)
    try:
        await scheduler.local(store.claim(bad['sample_id'],1))
        for _ in range(6):
            scheduler.next_resource_probe=0
            await tick(scheduler)
        state=store.sample(bad['sample_id'])
        assert len(calls) == 4 and state['reason_code']=='sandbox_recovery_exhausted'
        assert state['request_count']==state['geometry_repairs']==0
        assert not posts and not scheduler.sandbox_fault
    finally:
        await scheduler.client.close()


async def test_preflight_missing_preview_does_not_loop_or_charge_author(store, fake_http):
    scheduler, posts = await setup(store, fake_http)
    sample=add(store)
    store.finish(store.claim(sample['sample_id'],1),stage='review',changes={'build_path':str(store.root/'missing')})
    endpoint=scheduler.config.author
    claim=store.reserve(sample['sample_id'],1,endpoint,8,8)
    try:
        await scheduler.network(claim,endpoint)
        state=store.sample(sample['sample_id'])
        assert state['reason_code']=='local_artifact_invalid'
        assert state['revision']==1 and state['geometry_repairs']==0
        assert store.recover()==[]
        attempt=store.one('SELECT * FROM attempts')
        assert attempt['settled_cost']==0 and attempt['occupancy']==0 and attempt['response_applied']==1
        assert not scheduler.storage_failed and not posts
    finally:
        await scheduler.client.close()


async def test_crash_recovery_consumes_saved_paid_result_once(store, fake_http):
    scheduler, posts=await setup(store,fake_http)
    sample=add(store)
    store.db.execute('UPDATE campaigns SET sequence=request_limit')
    endpoint=scheduler.config.author
    claim=store.reserve(sample['sample_id'],1,endpoint,8,8)
    result=await scheduler.client.call(endpoint,[],claim['attempt_id'],'author')
    path=store.root/claim['attempt']['response_path']
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result))
    await scheduler.client.close()  # Simulate crash before settle/consume; no stop().
    store.close()
    store.__init__(store.root)
    restarted=Scheduler(store,scheduler.config)
    try:
        await restarted.start()
        await restarted.stop()
        assert len(posts)==store.campaign('review')['requests_used']==1
        assert store.sample(sample['sample_id'])['stage']=='build'
        assert store.one('SELECT * FROM attempts')['occupancy']==0
        assert store.campaign('review')['state']=='running'
    finally:
        await restarted.client.close()


@pytest.mark.parametrize('verdict,issues', [('gray',['Roof junction is hidden']),('pass',['Floating roof']),('fail',[])])
async def test_uncertain_or_inconsistent_review_never_redraws_source(store, verdict, issues):
    from test_dataset import artifact_fixture
    sample=add(store)
    directory=store.root/'review-fixture'
    artifact_fixture(directory,sample['sample_id'])
    store.finish(store.claim(sample['sample_id'],1),stage='review',changes={'build_path':str(directory)})
    scheduler=Scheduler(store,Config(data_root=store.root))
    result={'response_complete':True,'content':json.dumps({'verdict':verdict,'issues':issues,'observed_tags':[]})}
    try:
        for _ in range(2):
            await scheduler.consume(store.claim(sample['sample_id'],1),result)
        after=store.sample(sample['sample_id'])
        assert after['status']=='awaiting_review'
        assert after['revision']==1 and after['visual_repairs']==after['geometry_repairs']==0
        assert after['reason_code']==('review_uncertain' if verdict=='gray' else 'review_format_exhausted')
    finally:
        await scheduler.client.close()


@pytest.mark.parametrize('tag', [
    {'tag':'stone','evidence':'Visible rock','confidence':True},
    {'tag':'stone','evidence':['in image'],'confidence':.8},
    {'tag':'stone','evidence':'   ','confidence':.8},
])
def test_visual_evidence_rejects_non_evidence_values(tag):
    from voxlush.pipeline.prompts import parse_review
    with pytest.raises(ValueError):
        parse_review(json.dumps({'verdict':'pass','issues':[],'observed_tags':[tag]}),'a'*64,['b'*64])
