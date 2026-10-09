"""Real HTTP/Store/scheduler regressions for review b02c362, no external calls."""
import asyncio
import errno
import json

import pytest

from voxlush.core.config import Config, Endpoint
from voxlush.core.files import digest
from voxlush.inference import client as inference
from voxlush.pipeline.scheduler import Scheduler
from voxlush.store.store import Store
from voxlush.themes.planner import SEEDS, runtime_task, task_for
from voxlush.voxel import sandbox
from test_inference import completion, reasoning, sse


def add(store, campaign="review", *, two_stage=False, source=None, composition_mode=None):
    c = store.campaign(campaign)
    seed = next(s for s in SEEDS if s['scene_type']=='architecture' and s['suggested_scale']=='L') if composition_mode else next(s for s in SEEDS if s['id']=='geology_03')
    task = runtime_task(task_for(c, seed['family_id'], c["sequence"], "fixture", seed_id=seed['id'], composition_mode=composition_mode))
    if two_stage:
        task.update(generation_mode="two_stage", phase="skeleton")
    return store.add_sample(task, source_path=str(source) if source else None)


@pytest.fixture
def store(tmp_path):
    value = Store(tmp_path / "data")
    value.create_campaign("review", "Boundary fixtures", 24, 120, 8, {"natural": 1})
    value.set_campaign_state("review", "running")
    yield value
    value.close()


@pytest.mark.parametrize("failure", ["json", "shape", "limit"])
async def test_n01_unterminated_malformed_stream_never_repairs(store, fake_http, monkeypatch, failure):
    body = sse(reasoning()) + (b'data: {bad\n\n' if failure == "json" else sse({"choices": [None]}))
    if failure == "limit":
        monkeypatch.setattr(inference, "MAX_RESPONSE_BYTES", 128)
        body = sse(reasoning()) + b"x" * 256
    url, posts = await fake_http(body)
    endpoint = Endpoint(base_url=url, model="fixture", cost_upper_bound=2)
    scheduler = Scheduler(store, Config(data_root=store.root, allow_live=True, author=endpoint))
    sample = add(store)
    store.db.execute("UPDATE campaigns SET sequence=request_limit")
    claim = store.reserve(sample['sample_id'], 1, endpoint, 8, 8)
    try:
        await scheduler.network(claim, endpoint)
        attempt = store.one("SELECT * FROM attempts")
        result = json.loads((store.root / attempt['response_path']).read_text())
        assert result['error_category'] == 'malformed_response'
        assert attempt['occupancy'] == 1
        assert result['execution_state'] == 'execution_unknown'
        assert store.sample(sample['sample_id'])['reason_code'] == 'outcome_unknown'
        assert store.sample(sample['sample_id'])['revision'] == 1
        await scheduler.tick()
        await asyncio.gather(*scheduler.active)
        assert len(posts) == store.campaign('review')['requests_used'] == 1
        assert store.campaign('review')['reserved_cost'] == 2
        assert store.campaign('review')['cost_unknown'] == 1
    finally:
        await scheduler.client.close()


@pytest.mark.parametrize("ending", ['stop', 'length', 'bad_usage', 'bad_usage_same_event', 'replaced_bad_usage'])
async def test_n01_termination_is_independent_of_validity_and_billing(store, fake_http, ending):
    events = [completion(content='x=1', finish='length' if ending == 'length' else 'stop')]
    if ending == 'bad_usage':
        events.append({'usage': []})
    elif ending == 'bad_usage_same_event':
        events[0]['usage'] = []
    elif ending == 'replaced_bad_usage':
        events[0]['usage'] = {'prompt_tokens': 5, 'completion_tokens': 10}
        events.append({'usage': []})
    events.append(b'[DONE]')
    url, posts = await fake_http(sse(*events))
    endpoint = Endpoint(base_url=url, model='fixture', cost_upper_bound=2, input_per_million=1, output_per_million=2)
    scheduler = Scheduler(store, Config(data_root=store.root, author=endpoint))
    sample = add(store)
    claim = store.reserve(sample['sample_id'], 1, endpoint, 8, 8)
    try:
        await scheduler.network(claim, endpoint)
        attempt = store.one('SELECT * FROM attempts')
        result = json.loads((store.root/attempt['response_path']).read_text())
        assert result['execution_state'] == 'terminated'
        assert result['cost'] is None
        assert attempt['status'] == 'complete' and attempt['occupancy'] == 0
        assert store.campaign('review')['cost_unknown'] == 1
        assert not store.settle(claim['attempt_id'], result)
        assert store.recover() == []
        assert store.sample(sample['sample_id'])['stage'] == ('build' if ending == 'stop' else 'author')
        assert len(posts) == 1
    finally:
        await scheduler.client.close()


@pytest.mark.parametrize('first_failure', [None, 'geometry', 'syntax'])
@pytest.mark.parametrize('composition_mode', [None, 'pure_target', 'light_context'])
async def test_n02_skeleton_repairs_then_refine_once_across_restart(store, fake_http, monkeypatch, first_failure, composition_mode):
    url, posts = await fake_http(sse(completion('x=1'), b'[DONE]'))
    endpoint = Endpoint(base_url=url, model='fixture')
    config = Config(data_root=store.root, author=endpoint)
    scheduler = Scheduler(store, config)
    sample = add(store, two_stage=True, composition_mode=composition_mode)
    immutable = json.dumps(sample['task'], sort_keys=True)
    phases = []

    def build(source, task, destination, config=None):
        phases.append(task['phase'])
        return {'passed': not (first_failure == 'geometry' and len(phases) == 1),
                'violations': [{'rule': 'fixture_missing_geometry'}]}

    monkeypatch.setattr('voxlush.pipeline.scheduler.build', build)
    try:
        if first_failure == 'syntax':
            claim = store.reserve(sample['sample_id'], 1, endpoint, 8, 8)
            result = {'response_complete': True, 'content': 'for', 'execution_state': 'terminated'}
            store.settle(claim['attempt_id'], result)
            await scheduler.consume(claim, result)
        for _ in range(4):
            await scheduler.client.close()
            store.close()
            store.__init__(store.root)
            scheduler = Scheduler(store, config)
            current = store.sample(sample['sample_id'])
            claim = store.reserve(current['sample_id'], current['revision'], endpoint, 8, 8)
            assert claim
            await scheduler.network(claim, endpoint)
            await scheduler.client.close()
            # New state owner, same persistent DB, at each response/build boundary.
            store.close()
            store.__init__(store.root)
            scheduler = Scheduler(store, config)
            current = store.sample(sample['sample_id'])
            await scheduler.local(store.claim(current['sample_id'], current['revision']))
            current = store.sample(sample['sample_id'])
            if current['stage'] == 'render':
                break
            assert current['stage'] in {'author', 'refine'}
        assert phases == (['skeleton', 'skeleton', 'final'] if first_failure == 'geometry' else ['skeleton', 'final'])
        sent = [json.loads(p['messages'][1]['content']) for p in posts]
        assert all(p['task']['composition_mode'] == composition_mode for p in sent)
        assert sum(p['phase'] == 'refinement' for p in sent) == 1
        assert all(p['task']['phase'] == 'skeleton' for p in sent[:-1])
        assert current['creative_phase'] == 'final'
        assert json.dumps(current['task'], sort_keys=True) == immutable
        # Final repairs keep final phase and never add a second refine.
        claim = store.claim(current['sample_id'], current['revision'])
        scheduler.repair(claim, {'issues': ['fixture final defect']}, visual=True)
        await scheduler.client.close()
        store.close()
        store.__init__(store.root)
        scheduler = Scheduler(store, config)
        repaired = store.sample(sample['sample_id'])
        await scheduler.network(store.reserve(repaired['sample_id'], repaired['revision'], endpoint, 8, 8), endpoint)
        repaired = store.sample(sample['sample_id'])
        await scheduler.local(store.claim(repaired['sample_id'], repaired['revision']))
        assert store.sample(sample['sample_id'])['stage'] == 'render'
        assert json.loads(posts[-1]['messages'][1]['content'])['task']['phase'] == 'final'
        assert json.loads(posts[-1]['messages'][1]['content'])['task']['composition_mode'] == composition_mode
    finally:
        await scheduler.client.close()


@pytest.mark.parametrize('reason', ['sandbox_unavailable', 'sandbox_image_version_mismatch', 'storage'])
async def test_n03_environment_does_not_spend_author_repairs(store, fake_http, monkeypatch, reason):
    source = store.root/'source.py'
    source.write_text("O('islands','群岛','islands','landscape')\nC('rock','岩','rock','rock',floor='ground',parent_id='islands')\nB(10,17,10,13,10,17,'stone','rock')\n")
    sample = add(store, source=source)
    store.db.execute('UPDATE samples SET source_hash=? WHERE sample_id=?', (digest(source), sample['sample_id']))
    url, posts = await fake_http(sse(completion('x=1'), b'[DONE]'))
    endpoint = Endpoint(base_url=url, model='fixture')
    scheduler = Scheduler(store, Config(data_root=store.root, author=endpoint, allow_live=True))
    add(store)
    store.db.execute('UPDATE campaigns SET sequence=request_limit')
    original = sandbox.image_info

    def unavailable(*args, **kwargs):
        if reason == 'storage':
            raise OSError(errno.ENOSPC, 'injected storage full')
        raise sandbox.SandboxError(reason)

    monkeypatch.setattr(sandbox, 'image_info', unavailable)
    try:
        await scheduler.local(store.claim(sample['sample_id'], 1))
        after = store.sample(sample['sample_id'])
        assert after['stage'] == 'build'
        assert after['status'] == ('deferred' if reason == 'sandbox_unavailable' else 'blocked')
        assert after['revision'] == 1 and after['geometry_repairs'] == 0
        assert after['source_hash'] == digest(source)
        assert store.campaign('review')['requests_used'] == 0
        assert not store.rows('SELECT * FROM family_health')
        if reason == 'storage':
            assert scheduler.storage_failed
            await scheduler.tick()
            await asyncio.gather(*scheduler.active)
            assert posts == []
        if reason == 'sandbox_unavailable':
            monkeypatch.setattr(sandbox, 'image_info', original)
            store.db.execute('UPDATE samples SET next_ready_at=0')
            await scheduler.local(store.claim(sample['sample_id'], 1))
            after = store.sample(sample['sample_id'])
            assert after['stage'] == 'render' and after['revision'] == 1
            assert after['geometry_repairs'] == 0
            assert store.campaign('review')['requests_used'] == 0
    finally:
        await scheduler.client.close()


async def test_n04_full_campaign_does_not_hide_other_ready_work(store, fake_http):
    url, posts = await fake_http(sse(completion('x=1'), b'[DONE]'))
    endpoint = Endpoint(base_url=url, model='fixture', provider_cap=8)
    store.db.execute("UPDATE campaigns SET api_cap=1 WHERE campaign_id='review'")
    busy = add(store)
    assert store.reserve(busy['sample_id'], 1, endpoint, 8, 8)
    for _ in range(64):
        add(store)
    store.create_campaign('other', 'Other', 1, 10, 8, {'natural': 1})
    store.set_campaign_state('other', 'running')
    other = add(store, 'other')
    store.db.execute('UPDATE campaigns SET sequence=request_limit')
    scheduler = Scheduler(store, Config(data_root=store.root, allow_live=True, global_api_cap=8, author=endpoint))
    try:
        assert [s['sample_id'] for s in store.ready(['author'], limit=64)] == [other['sample_id']]
        await scheduler.tick()
        await asyncio.gather(*scheduler.active)
        assert len(posts) == 1
        assert store.sample(other['sample_id'])['stage'] == 'build'
        assert store.campaign('review')['requests_used'] == 1
    finally:
        await scheduler.client.close()


@pytest.mark.parametrize('status', [200, 502, 504])
async def test_pool_interruption_has_no_termination_receipt(store, fake_http, status):
    error = {'error': {'type': 'pool_error', 'message': 'upstream stream interrupted'}}
    body = sse(reasoning(), error) if status == 200 else json.dumps(error).encode()
    url, posts = await fake_http(body, status=status)
    endpoint = Endpoint(base_url=url, model='fixture')
    scheduler = Scheduler(store, Config(data_root=store.root, author=endpoint, allow_live=True))
    sample = add(store)
    store.db.execute('UPDATE campaigns SET sequence=request_limit')
    try:
        await scheduler.network(store.reserve(sample['sample_id'], 1, endpoint, 8, 8), endpoint)
        await scheduler.tick()
        await asyncio.gather(*scheduler.active)
        assert store.one('SELECT status,occupancy FROM attempts') == {'status': 'outcome_unknown', 'occupancy': 1}
        assert store.sample(sample['sample_id'])['revision'] == 1
        assert len(posts) == 1
    finally:
        await scheduler.client.close()


def test_nonempty_v2_migration_preserves_briefs_ledgers_and_blocks_ambiguous_phase(tmp_path):
    from voxlush.store import sqlite
    from voxlush.store.migrations import migrate_v2
    from voxlush.store.store import SCHEMA
    root = tmp_path/'v2'
    root.mkdir()
    db = sqlite.connect(root/'runtime.db')
    db.row_factory = sqlite.Row
    db.executescript(SCHEMA)
    db.execute("INSERT INTO meta VALUES('schema','1')")
    migrate_v2(db)
    db.execute("INSERT INTO campaigns(campaign_id,name,state,target,request_limit,api_cap,scene_weights,requests_used,reserved_cost,cost_unknown,created_at,updated_at) VALUES('old','Old','running',24,100,8,'{}',3,6,3,1,1)")
    brief = json.dumps({'generation_mode': 'two_stage', 'phase': 'skeleton', 'instruction': 'immutable'})
    for sid, revision, stage, status in [('skeleton',1,'build','ready'), ('ambiguous',2,'author','blocked'), ('refined',3,'author','ready'), ('refine_ready',2,'refine','ready'), ('settled',2,'archive','provisional_pass')]:
        db.execute("INSERT INTO samples(sample_id,campaign_id,theme_seed_id,family_id,scene_type,task_json,revision,stage,status,last_progress_at,updated_at,created_at,lineage_group,attempt_id) VALUES(?,'old','seed','family','architecture',?,?,?,?,1,1,1,?,?)", (sid,brief,revision,stage,status,sid,sid))
    for sid, role, status, occupancy in [('ambiguous','author','complete',0), ('refined','refine','complete',0), ('unknown','author','outcome_unknown',1)]:
        db.execute("INSERT INTO attempts(attempt_id,sample_id,campaign_id,revision,lease_token,role,endpoint_alias,status,reserved_cost,billing_status,response_path,started_at,occupancy) VALUES(?,?,'old',2,'lease',?,'pool',?,2,'unknown_reserved','old.json',1,?)", (sid,sid,role,status,occupancy))
    db.close()
    for _ in range(2):
        store = Store(root)
        try:
            assert store.recover() == []
            rows = {r['sample_id']: r for r in store.rows('SELECT * FROM samples')}
            assert rows['skeleton']['creative_phase'] == 'skeleton'
            assert rows['ambiguous']['reason_code'] == 'phase_recovery_required'
            assert all(rows[s]['creative_phase'] == 'final' for s in ('refined','refine_ready','settled'))
            assert all(r['task_json'] == brief for r in rows.values())
            c = store.campaign('old')
            assert (c['requests_used'], c['reserved_cost'], c['cost_unknown']) == (3,6,3)
            assert store.one("SELECT occupancy FROM attempts WHERE attempt_id='unknown'")['occupancy'] == 1
            store.command({'command_id':'retry-phase','campaign_id':'old','action':'retry','expected_config_revision':1,'payload':{'sample_id':'ambiguous'}})
            store.apply_commands(8)
            assert store.get_command('retry-phase')['reason'] == 'phase_recovery_required'
            assert store.one('PRAGMA integrity_check')['integrity_check'] == 'ok'
        finally:
            store.close()


async def test_n03_environment_retry_exhaustion_backpressures_network(store, fake_http, monkeypatch):
    source = store.root/'source.py'
    source.write_text("O('land','地形','land','landscape')\nC('rock','岩','rock','rock',floor='ground',parent_id='land')\nP(1,1,1,'stone','rock')\n")
    sample = add(store, source=source)
    url, posts = await fake_http(sse(completion('x=1'), b'[DONE]'))
    endpoint = Endpoint(base_url=url, model='fixture')
    scheduler = Scheduler(store, Config(data_root=store.root, author=endpoint, allow_live=True))
    add(store)
    store.db.execute('UPDATE campaigns SET sequence=request_limit')

    def fail(*args, **kwargs):
        raise sandbox.SandboxError('sandbox_unavailable')

    monkeypatch.setattr(sandbox, 'image_info', fail)
    try:
        for _ in range(3):
            store.db.execute('UPDATE samples SET next_ready_at=0')
            await scheduler.local(store.claim(sample['sample_id'], 1))
        state = store.sample(sample['sample_id'])
        assert state['status'] == 'blocked' and state['local_retries'] == 3
        await scheduler.tick()
        await asyncio.gather(*scheduler.active)
        assert posts == [] and scheduler.backpressure
        assert state['revision'] == 1 and state['geometry_repairs'] == 0
        assert not store.rows('SELECT * FROM family_health')
    finally:
        await scheduler.client.close()


@pytest.mark.parametrize('source', ['for', "O('land','地','land','landscape')\nC('rock','岩','rock','rock',floor='ground',parent_id='land')\nP(1,1,1,'stone','rock')\n"])
async def test_n03_actual_bad_source_or_geometry_still_gets_finite_author_repair(store, source):
    path = store.root/'bad.py'
    path.write_text(source)
    sample = add(store, source=path)
    # Exercise a real geometry requirement with an insufficient one-voxel source.
    task = sample['task']
    task['record_kind'] = 'calibration'
    task['quality_requirements'] = {'minimum_voxels': 10}
    store.db.execute('UPDATE samples SET task_json=? WHERE sample_id=?', (json.dumps(task),sample['sample_id']))
    scheduler = Scheduler(store, Config(data_root=store.root, geometry_repairs=1))
    try:
        await scheduler.local(store.claim(sample['sample_id'], 1))
        state = store.sample(sample['sample_id'])
        assert state['stage'] == 'author' and state['geometry_repairs'] == 1
        claim = store.claim(sample['sample_id'], state['revision'])
        scheduler.repair(claim, {'rule': 'second_real_defect'})
        assert store.sample(sample['sample_id'])['status'] == 'rejected'
    finally:
        await scheduler.client.close()


async def test_real_repaired_asset_survives_local_retry_restart_and_exports_pairs(store, fake_http, monkeypatch):
    from voxlush.dataset import export, verify_release
    from voxlush.pipeline import scheduler as module

    header = "O('land','地','land','landscape')\nC('rock','岩','rock','rock',floor='ground',parent_id='land')\n"
    bad = header + "P(1,1,1,'stone','rock')\n"
    good = header + "B(1,4,1,4,1,4,'stone','rock')\n"
    url, posts = await fake_http(sse(completion(good), b'[DONE]'))
    endpoint = Endpoint(base_url=url, model='fixture')
    config = Config(data_root=store.root, author=endpoint)
    scheduler = Scheduler(store, config)
    sample = add(store)
    task = sample['task']
    task['quality_requirements'] = {'minimum_voxels': 10}
    store.db.execute('UPDATE samples SET task_json=? WHERE sample_id=?', (json.dumps(task),sample['sample_id']))
    try:
        # Explicit local source fixture; only the repair uses loopback HTTP.
        claim = store.claim(sample['sample_id'], 1)
        await scheduler.consume(claim, {'response_complete': True, 'execution_state': 'terminated', 'content': bad})
        await scheduler.local(store.claim(sample['sample_id'], 1))
        assert store.sample(sample['sample_id'])['geometry_repairs'] == 1
        await scheduler.network(store.reserve(sample['sample_id'], 2, endpoint, 8, 8), endpoint)
        image_info = sandbox.image_info

        def unavailable(*args, **kwargs):
            raise sandbox.SandboxError('sandbox_unavailable')

        monkeypatch.setattr(sandbox, 'image_info', unavailable)
        await scheduler.local(store.claim(sample['sample_id'], 2))
        monkeypatch.setattr(sandbox, 'image_info', image_info)
        await scheduler.client.close()
        store.close()
        store.__init__(store.root)
        scheduler = Scheduler(store, config)
        store.db.execute('UPDATE samples SET next_ready_at=0')
        await scheduler.local(store.claim(sample['sample_id'], 2))
        state = store.sample(sample['sample_id'])
        assert state['stage'] == 'render' and 'retry-build-' in state['build_path']
        actual_render = module.render

        def render_unavailable(*args, **kwargs):
            raise RuntimeError('Injected recoverable renderer failure')

        monkeypatch.setattr(module, 'render', render_unavailable)
        await scheduler.local(store.claim(sample['sample_id'], 2))
        assert store.sample(sample['sample_id'])['reason_code'] == 'render_failed'
        # Unrelated local work progresses while this rendering is deferred.
        path = store.root/'other.py'
        path.write_text(good)
        other = add(store, source=path)
        await scheduler.local(store.claim(other['sample_id'], 1))
        assert store.sample(other['sample_id'])['stage'] == 'render'
        monkeypatch.setattr(module, 'render', actual_render)
        store.db.execute('UPDATE samples SET next_ready_at=0')
        await scheduler.local(store.claim(sample['sample_id'], 2))
        await scheduler.local(store.claim(sample['sample_id'], 2))
        state = store.sample(sample['sample_id'])
        assert state['status'] == 'provisional_pass'
        assert state['geometry_repairs'] == 1 and len(posts) == 1
        release = store.root/'release'
        report = export(store,store.root,'review',release,True)
        verify_release(release)
        assert report['counts']['repair_pairs'] == 1
        pair = json.loads((release/'repair_pairs.jsonl').read_text())
        assert pair['before_source'] == bad and pair['after_source'] == good
        assert pair['before_geometry']['passed'] is False and pair['after_geometry']['passed'] is True
    finally:
        await scheduler.client.close()
