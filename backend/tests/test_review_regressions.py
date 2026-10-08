"""Review bb556101 regressions against the real Store and scheduler.

Terminal geometry outcomes in planner tests are injected fixture outcomes;
loopback transport and filesystem evidence are never model qualification.
"""
import asyncio
import json
import random

import pytest

from voxlush.core.config import Config, Endpoint
from voxlush.core.files import atomic_json
from voxlush.pipeline.scheduler import Scheduler
from voxlush.store.store import Store
from voxlush.themes.planner import runtime_task, task_for
from voxlush.voxel.adapter import decode_source
from test_dataset import artifact_fixture
from test_scheduler import complete_response


@pytest.fixture
def store(tmp_path):
    value = Store(tmp_path / "data")
    value.create_campaign("review", "Review fixtures", 8000, 20000, 128, {"natural": 1})
    value.set_campaign_state("review", "running")
    yield value
    value.close()


def add(store, family="geology", campaign="review"):
    c = store.campaign(campaign)
    return store.add_sample(runtime_task(task_for(c, family, c["sequence"], "fixture")))


def end(store, sample, status):
    claim = store.claim(sample["sample_id"], sample["revision"])
    assert claim
    assert store.finish(claim, status=status)


async def test_r01_productive_family_survives_historical_rejections(store):
    config = Config(author=Endpoint(base_url="http://author.invalid", model="fixture"))
    scheduler = Scheduler(store, config)
    try:
        for sequence in range(508):
            end(store, add(store), "rejected" if sequence % 64 == 0 else "accepted")
        # All other families have their target reserved. Only geology can be planned.
        for family in store.coverage("review")["items"]:
            if family["family_id"] != "geology" and family["target"]:
                for _ in range(family["target"]):
                    end(store, add(store, family["family_id"]), "accepted")
        before = store.campaign("review")["sequence"]
        scheduler.plan(store.campaign("review"))
        assert store.campaign("review")["sequence"] == before + 1
    finally:
        await scheduler.client.close()


async def test_r03_independent_endpoint_capacity(store):
    config = Config(global_api_cap=128,
                    author=Endpoint(base_url="http://author.invalid", model="fixture", provider_cap=128),
                    visual=Endpoint(alias="visual", base_url="http://visual.invalid", model="fixture", provider_cap=2))
    scheduler = Scheduler(store, config)
    try:
        scheduler.adaptive_cap = 128
        assert scheduler.cap() == 128
        config.visual.provider_cap = 0
        assert scheduler.cap() == 128
    finally:
        await scheduler.client.close()


@pytest.mark.parametrize("boundary", ["saved", "settled", "consume", "finish"])
async def test_r04_original_response_is_consumed_after_callback_failure(store, fake_http, monkeypatch, boundary):
    url, posts = await fake_http(complete_response())
    endpoint = Endpoint(base_url=url, model="fixture", input_per_million=1, output_per_million=2)
    config = Config(data_root=store.root, author=endpoint)
    scheduler = Scheduler(store, config)
    sample = add(store)
    claim = store.reserve(sample["sample_id"], 1, endpoint, 8, 8)
    original_settle, original_consume, original_finish = store.settle, scheduler.consume, store.finish

    def failed(*args, **kwargs):
        raise RuntimeError("injected local response callback fault")

    async def failed_consume(*args):
        failed()

    try:
        if boundary in ("saved", "settled"):
            def settle(*args):
                if boundary == "settled":
                    original_settle(*args)
                failed()
            monkeypatch.setattr(store, "settle", settle)
        elif boundary == "consume":
            monkeypatch.setattr(scheduler, "consume", failed_consume)
        else:
            monkeypatch.setattr(store, "finish", failed)
        await scheduler.network(claim, endpoint)
        monkeypatch.setattr(store, "settle", original_settle)
        monkeypatch.setattr(store, "finish", original_finish)
        monkeypatch.setattr(scheduler, "consume", original_consume)
        for recovered, response in store.recover():
            await scheduler.consume(recovered, response)
        assert store.sample(sample["sample_id"])["stage"] == "build"
        assert store.sample(sample["sample_id"])["revision"] == 1
        assert store.campaign("review")["requests_used"] == 1
        assert store.campaign("review")["cost_known"] == .000003
        assert len(posts) == 1
        assert store.recover() == []
    finally:
        await scheduler.client.close()


async def test_r05_bad_review_retries_same_artifacts(store, tmp_path):
    sample = add(store)
    directory = store.root / "work" / sample["sample_id"]
    _, review = artifact_fixture(directory, sample["sample_id"])
    claim = store.claim(sample["sample_id"], 1)
    store.finish(claim, stage="review", changes={"build_path":str(directory)})
    scheduler = Scheduler(store, Config(data_root=store.root))
    try:
        claim = store.claim(sample["sample_id"], 1)
        await scheduler.consume(claim, {"response_complete":True, "content":"invalid JSON"})
        after = store.sample(sample["sample_id"])
        assert after["stage"] == "review" and after["revision"] == 1
        assert after["visual_repairs"] == 0
        assert after["build_path"] == str(directory)
        assert not (directory / "review.json").exists()
        assert review["input_voxel_sha256"] == json.loads((directory / "geometry.json").read_text())["canonical_voxel_hash"]
    finally:
        await scheduler.client.close()


@pytest.mark.parametrize("reverse", [False, True])
async def test_r06_production_plan_covers_all_natural_seeds(store, reverse):
    with store.transaction() as db:
        db.execute("UPDATE campaigns SET target=64 WHERE campaign_id='review'")
    scheduler = Scheduler(store, Config(author=Endpoint(base_url="http://author.invalid", model="fixture")))
    selected = []
    try:
        for _ in range(8):
            for _ in range(8):
                scheduler.plan(store.campaign("review"))
            ready = store.ready(["author"])
            if reverse:
                random.Random(17).shuffle(ready)
            for sample in ready:
                selected.append(sample["theme_seed_id"])
                end(store, sample, "accepted")
        assert len(selected) == len(set(selected)) == 64
    finally:
        await scheduler.client.close()


@pytest.mark.parametrize('offsets', [(0, 0), (0, 12)])
async def test_r07_r12_concurrent_archives_agree_on_variant_status(store, offsets):
    scheduler = Scheduler(store, Config(data_root=store.root, archive_workers=2))
    claims = []
    for offset in offsets:
        sample = add(store)
        directory = store.root / "work" / sample["sample_id"]
        _, review = artifact_fixture(directory, sample["sample_id"], offset)
        atomic_json(directory / "review.json", review)
        claim = store.claim(sample["sample_id"], 1)
        store.finish(claim, stage="archive", changes={"build_path":str(directory), "review_json":json.dumps(review)})
        claims.append(store.claim(sample["sample_id"], 1))
    try:
        await asyncio.gather(*(scheduler.local(claim) for claim in claims))
        rows = store.rows("SELECT * FROM assets ORDER BY created_at")
        assert len(rows) == 2
        assert [r["status"] for r in rows] == ["provisional_pass", "rejected"]
        assert store.campaign("review")["provisional_pass"] == 1
        for row in rows:
            from pathlib import Path
            manifest = json.loads((store.root / Path(row["path"]) / "manifest.json").read_text())
            assert manifest == json.loads(row["manifest_json"])
            assert (manifest["lifecycle"] == "duplicate") == (row["status"] == "rejected")
            assert manifest["lineage"]["group_id"] == row["lineage_group"]
    finally:
        await scheduler.client.close()


def test_r08_safe_local_names():
    decode_source("def _draw(_count):\n    for _ in range(_count):\n        P(rng.randrange(10),2,3,'stone','rock')\n_draw(3)")


def test_r11_capacity_changes_preserve_quality_identity():
    first = Config(author=Endpoint(base_url="http://author.invalid", model="fixture"))
    second = first.model_copy(deep=True)
    second.author.provider_cap = 2
    second.author.rpm = 120
    assert first.profile_hash() == second.profile_hash()
    second.author.parameters["temperature"] = .1
    assert first.profile_hash() != second.profile_hash()


def test_r13_network_filter_precedes_limit_and_local_drain_survives(store):
    for _ in range(64):
        add(store)
    store.set_campaign_state("review", "blocked", "budget_exhausted")
    store.create_campaign("healthy", "Healthy fixture", 1, 10, 1, {"natural":1})
    store.set_campaign_state("healthy", "running")
    sample = add(store, campaign="healthy")
    assert [r["sample_id"] for r in store.ready(["author"], limit=64)] == [sample["sample_id"]]
    claim = store.claim(sample["sample_id"], 1)
    store.finish(claim, stage="build")
    store.set_campaign_state("healthy", "draining")
    assert store.ready(["build"], allow_network=False)[0]["sample_id"] == sample["sample_id"]


def test_r02_unknown_capacity_coordination_keeps_financial_reservations(store):
    endpoint = Endpoint(base_url='http://uncertain.invalid',model='fixture',provider_cap=8,cost_upper_bound=2)
    independent = Endpoint(base_url='http://independent.invalid',model='fixture',provider_cap=8,alias='independent')
    claims = [store.reserve(add(store)['sample_id'],1,endpoint,8,8) for _ in range(8)]
    for claim in claims:
        store.settle(claim['attempt_id'],{'error_category':'outcome_unknown','cost':None})
        store.finish(claim,status='blocked',reason='outcome_unknown')
    other = add(store)
    # A literal full global authorization cannot be exceeded by guessing that a
    # timed-out server has stopped. Additional independent authorized room can run.
    assert store.reserve(other['sample_id'],1,independent,8,8) is None
    assert store.reserve(other['sample_id'],1,endpoint,16,8) is None
    assert store.reserve(other['sample_id'],1,independent,16,8)
    before = store.campaign('review')
    store.command({'command_id':'confirm','campaign_id':'review','action':'reconcile_execution',
                   'expected_config_revision':1,'payload':{'attempt_id':claims[0]['attempt_id'],'outcome':'cancelled','evidence':'fixture pool cancellation receipt #1'}})
    store.apply_commands()
    after = store.campaign('review')
    assert store.get_command('confirm')['status'] == 'applied'
    assert after['reserved_cost'] == before['reserved_cost'] == 16
    assert after['cost_unknown'] == before['cost_unknown'] == 8
    assert after['requests_used'] == before['requests_used']
    assert store.one('SELECT occupancy FROM attempts WHERE attempt_id=?',(claims[0]['attempt_id'],))['occupancy'] == 0
    store.command({'command_id':'no-repost','campaign_id':'review','action':'retry',
                   'expected_config_revision':1,'payload':{'sample_id':claims[0]['sample_id']}})
    store.apply_commands()
    assert store.get_command('no-repost')['reason'] == 'attempt_outcome_unresolved'


def test_r02_server_contract_deadline_and_unknown_survive_restart(tmp_path, monkeypatch):
    import time
    root = tmp_path/'restart'
    store = Store(root)
    store.create_campaign('review','Review',20,20,4,{'natural':1})
    store.set_campaign_state('review','running')
    endpoint = Endpoint(base_url='http://fixture.invalid',model='fixture',cost_upper_bound=3,
                        server_max_execution_seconds=30,execution_contract_ref='fixture contract: stopped within 30s of dispatch')
    sample = add(store)
    claim = store.reserve(sample['sample_id'],1,endpoint,4,8)
    assert claim
    start = time.time()
    store.close()
    store = Store(root)
    try:
        store.recover()
        store.reconcile_deadlines()
        assert store.one('SELECT occupancy FROM attempts')['occupancy'] == 1
        monkeypatch.setattr(time,'time',lambda:start+31)
        store.reconcile_deadlines()
        assert store.one('SELECT occupancy FROM attempts')['occupancy'] == 0
        assert store.campaign('review')['cost_unknown'] == 1
        assert store.campaign('review')['reserved_cost'] == 3
    finally:
        store.close()


async def test_r01_cooldown_allows_one_probe_and_success_resets_streak(store, monkeypatch):
    import time
    scheduler = Scheduler(store,Config(author=Endpoint(base_url='http://fixture.invalid',model='fixture'),theme_cooldown_seconds=10))
    try:
        for _ in range(8):
            end(store,add(store),'rejected')
        family = next(i for i in store.coverage('review')['items'] if i['family_id']=='geology')
        assert not scheduler.family_available(family)
        now = time.time()
        monkeypatch.setattr(time,'time',lambda:now+11)
        assert scheduler.family_available(family)
        probe = add(store)
        family['active'] = 1
        assert not scheduler.family_available(family)
        end(store,probe,'provisional_pass')
        family = next(i for i in store.coverage('review')['items'] if i['family_id']=='geology')
        assert family['consecutive_failures'] == 0
        assert scheduler.family_available(family)
        assert family['rejected'] == 8
    finally:
        await scheduler.client.close()


def test_r03_shared_pool_counts_roles_together(store):
    author = Endpoint(base_url='http://pool.invalid',model='writer',provider_cap=2,capacity_pool='shared')
    visual = Endpoint(base_url='http://vision.invalid',model='reviewer',provider_cap=2,capacity_pool='shared',alias='visual')
    assert store.reserve(add(store)['sample_id'],1,author,128,8)
    assert store.reserve(add(store)['sample_id'],1,visual,128,8)
    assert store.reserve(add(store)['sample_id'],1,author,128,8) is None
    assert store.reserve(add(store)['sample_id'],1,visual,128,8) is None


@pytest.mark.parametrize('content',['[]','null','{}','not json'])
async def test_r05_format_retries_are_bounded_and_real_defects_can_repair(store, content):
    sample = add(store)
    directory = store.root/'work'/sample['sample_id']
    artifact_fixture(directory,sample['sample_id'])
    claim = store.claim(sample['sample_id'],1)
    store.finish(claim,stage='review',changes={'build_path':str(directory)})
    scheduler = Scheduler(store,Config())
    try:
        for _ in range(2):
            claim = store.claim(sample['sample_id'],1)
            await scheduler.consume(claim,{'response_complete':True,'content':content})
        after = store.sample(sample['sample_id'])
        assert after['status']=='awaiting_review' and after['revision']==1
        assert after['reason_code']=='review_format_exhausted'
        assert after['visual_repairs']==0
        # A separate asset with concrete visual defects is still repairable.
        other = add(store)
        claim = store.claim(other['sample_id'],1)
        store.finish(claim,stage='review',changes={'build_path':str(directory)})
        claim = store.claim(other['sample_id'],1)
        await scheduler.consume(claim,{'response_complete':True,'content':json.dumps({'verdict':'fail','issues':['floating entrance visible in view a']})})
        assert store.sample(other['sample_id'])['stage']=='author'
        assert store.sample(other['sample_id'])['revision']==2
    finally:
        await scheduler.client.close()


@pytest.mark.parametrize('source',[
    'SEED=9','rng=0','rng.seed(4)','import math as P','from math import sqrt as rng',
    'x=().__class__','open("file")','__import__("os")','def helper(SEED): pass',
    'try:\n    pass\nexcept Exception as rng:\n    pass',
    'match 1:\n    case SEED: pass',
    '_state=0','_blocks()',"Path('x').write_text('bad')",'os.getcwd()',
    'random=rng\nrandom.seed(3)','alias=rng\nalias.seed(3)','def random(): pass',
])
def test_r08_unsafe_state_and_reflection_still_rejected(source):
    with pytest.raises(ValueError):
        decode_source(source)


def test_r08_one_source_size_limit_and_bounded_feedback():
    from voxlush.pipeline.prompts import extract_source, author_messages
    from voxlush.voxel.adapter import MAX_SOURCE_BYTES
    source = '#'+('a'*(MAX_SOURCE_BYTES-2))+'\n'
    decode_source(extract_source(source))
    with pytest.raises(ValueError):
        extract_source(source+'#x')
    evidence = {'violations':[{'code':'unsupported','component_id':'wall','position':[2,3,4],'message':'bad'*2000} for _ in range(1000)]}
    message = json.loads(author_messages({},feedback=evidence)[1]['content'])
    assert len(json.dumps(message['current_evidence']).encode()) < 8000
    assert message['current_evidence']['violations'][0]['position'] == [2,3,4]
    assert len(evidence['violations']) == 1000


async def test_r11_immutable_config_history_and_sample_binding(store):
    cfg = Config(author=Endpoint(base_url='http://private.invalid',model='fixture',parameters={'secret':'PRIVATE_VALUE'}))
    scheduler = Scheduler(store,cfg)
    try:
        sample = add(store)
        initial_hash = sample['runtime_config_hash']
        snapshot = store.one('SELECT * FROM config_snapshots WHERE config_hash=?',(initial_hash,))
        assert 'PRIVATE_VALUE' not in snapshot['config_json'] and 'private.invalid' not in snapshot['config_json']
        store.command({'command_id':'tune','campaign_id':'review','action':'set_cap','expected_config_revision':1,'payload':{'api_cap':4}})
        store.apply_commands()
        history = store.rows('SELECT * FROM config_history ORDER BY revision')
        assert len(history) == 2
        assert json.loads(history[0]['campaign_json'])['api_cap'] == 128
        assert json.loads(history[1]['campaign_json'])['api_cap'] == 4
        changed = cfg.model_copy(deep=True)
        changed.author.parameters={'temperature':.2}
        store.bind_config(changed)
        assert store.sample(sample['sample_id'])['runtime_config_hash'] == initial_hash
        assert add(store)['runtime_config_hash'] != initial_hash
        assert store.campaign('review')['config_revision'] == 3
    finally:
        await scheduler.client.close()


def test_r08_natural_floor_metadata_and_supplied_rng():
    from voxlush.voxel.adapter import validate_model
    validate_model({'floors':0},'landscape')
    for contract in ('inhabited','exterior','legacy_large_wooden_v1'):
        with pytest.raises(ValueError):
            validate_model({'floors':0},contract)
    with pytest.raises(ValueError):
        validate_model({'floors':False},'landscape')
    decode_source('import random\nrandom.seed(SEED)\nx = rng.randint(1, 9)')


def test_r04_recovery_drains_more_than_one_bounded_batch(store):
    endpoint = Endpoint(base_url='http://fixture.invalid',model='fixture')
    for _ in range(1025):
        claim = store.reserve(add(store)['sample_id'],1,endpoint,128,8)
        response = {'response_complete':True,'content':'x=1','cost':0}
        path = store.one('SELECT response_path FROM attempts WHERE attempt_id=?',(claim['attempt_id'],))['response_path']
        atomic_json(store.root/path,response)
        store.settle(claim['attempt_id'],response)
        store.finish(claim,status='blocked',reason='response_pending',response_applied=False)
    with store.transaction() as db:
        db.execute("UPDATE samples SET status='running',lease_owner='previous-owner',lease_token='previous-lease'")
    first = store.recover()
    assert len(first)==1024
    for claim,_ in first:
        assert store.finish(claim,stage='build')
    second = store.recover(pending_only=True)
    assert len(second)==1
    assert store.finish(second[0][0],stage='build')
    # Current-owner active requests must not be mistaken for restart leftovers.
    assert store.reserve(add(store)['sample_id'],1,endpoint,128,8)
    assert store.recover(pending_only=True)==[]


def test_r03_legacy_capacity_mapping_disambiguates_roles(store):
    author = Endpoint(base_url='http://author.invalid',model='fixture',alias='shared-alias')
    visual = Endpoint(base_url='http://visual.invalid',model='fixture',alias='shared-alias')
    first = store.reserve(add(store)['sample_id'],1,author,128,8)
    other = add(store)
    local = store.claim(other['sample_id'],1)
    store.finish(local,stage='review')
    second = store.reserve(other['sample_id'],1,visual,128,8)
    with store.transaction() as db:
        db.execute("UPDATE attempts SET capacity_group='legacy:shared-alias'")
    store.bind_config(Config(author=author,visual=visual))
    assert store.one('SELECT capacity_group FROM attempts WHERE attempt_id=?',(first['attempt_id'],))['capacity_group']==author.capacity_key()
    assert store.one('SELECT capacity_group FROM attempts WHERE attempt_id=?',(second['attempt_id'],))['capacity_group']==visual.capacity_key()


def test_r07_independent_accounting_ignores_variants_but_not_coarse_collisions(store):
    """Synthetic Store accounting records, not qualified model/asset evidence.

    The disk/manifest/export test below separately exercises real fixture archives.
    """
    import numpy as np
    from voxlush.dataset.dedup import feature_hashes
    from voxlush.voxel.canonical import canonical_voxel_hash
    base = np.array([[0,0,0],[40,5,30],[5,1,7],[8,3,9]])
    near = base.copy()
    near[2,0] = 3  # Same coarse signature, different exact geometry.
    yaw = base[:,[2,1,0]] * [1,1,-1] + [0,0,40]
    inverted = base * [1,-1,-1] + [0,5,30]
    assert feature_hashes(base)['geometry_quant_sha256']==feature_hashes(near)['geometry_quant_sha256']
    assert feature_hashes(base)['rotation_occupancy_sha256']==feature_hashes(inverted)['rotation_occupancy_sha256']
    lineage = None
    for index,(coords,material,derived) in enumerate([
        (base,'stone',False),(base+10,'stone',True),(yaw,'stone',True),
        (base,'granite',True),(base*2,'stone',True),  # explicit lineage revision
        (near,'stone',False),(inverted,'stone',False),
    ]):
        sample = add(store)
        features = feature_hashes(coords)
        geometry_hash = canonical_voxel_hash(coords,np.zeros(len(coords),dtype=int),{'block_states':['minecraft:'+material]})
        group = lineage if index==4 else sample['lineage_group']
        duplicate = store.variant_of(geometry_hash,features,group)
        assert bool(duplicate)==derived
        if duplicate:
            group = duplicate['lineage_group']
        claim = store.claim(sample['sample_id'],1)
        manifest = {'lineage':{'group_id':group,'is_unique':not derived},'lifecycle':'duplicate' if derived else 'accepted'}
        store.commit_asset(claim,{'path':'synthetic-accounting-only','canonical_voxel_hash':geometry_hash,
                                 'manifest_json':manifest,'dedup_features':features,'accepted_unique':not derived})
        if index==0:
            lineage = group
        assert store.campaign('review')['accepted_unique']==(1 if index<5 else index-3)
    assert store.one("SELECT COUNT(DISTINCT lineage_group) n FROM assets")['n']==3


async def archive_fixture(store, scheduler):
    sample = add(store)
    directory = store.root/'work'/sample['sample_id']
    _,review = artifact_fixture(directory,sample['sample_id'])
    atomic_json(directory/'review.json',review)
    claim = store.claim(sample['sample_id'],1)
    store.finish(claim,stage='archive',changes={'build_path':str(directory),'review_json':json.dumps(review)})
    await scheduler.local(store.claim(sample['sample_id'],1))
    return store.one('SELECT * FROM assets WHERE sample_id=?',(sample['sample_id'],))


async def test_r07_archive_export_preserve_fixture_lineage(store):
    from voxlush.dataset import export, verify_asset, verify_release
    scheduler = Scheduler(store,Config(data_root=store.root))
    try:
        first = await archive_fixture(store,scheduler)
        second = await archive_fixture(store,scheduler)
        assert first['lineage_group']==second['lineage_group']
        assert second['status']=='rejected'
        for row in (first,second):
            manifest = verify_asset(store.root/row['path'])
            assert manifest==json.loads(row['manifest_json'])
            assert manifest['lineage']['group_id']==row['lineage_group']
            assert bool(row['accepted_unique'])==(manifest['lifecycle']=='accepted')
        output = store.root/'releases'/'variants-fixture'
        release = export(store,store.root,'review',output,include_provisional=True)
        assert release==verify_release(output)
        records = [json.loads(line) for line in (output/'asset_index.jsonl').read_text().splitlines()]
        # Rejected variants remain archived but are excluded from training export.
        assert len(records)==1 and records[0]['sample_id']==first['sample_id']
        assert len({r['lineage_group'] for r in records})==1
        assert release['counts']['accepted']==store.campaign('review')['accepted_unique']==0
        assert all(r['split']=='excluded' for r in records)
    finally:
        await scheduler.client.close()


async def test_nonempty_backup_restores_assets_failed_and_unknown_requests(store,tmp_path):
    from voxlush.dataset import backup,restore_backup,verify_asset,verify_backup
    scheduler = Scheduler(store,Config(data_root=store.root))
    try:
        asset = await archive_fixture(store,scheduler)
        endpoint = Endpoint(base_url='http://fixture.invalid',model='fixture',cost_upper_bound=3)
        for error in ('provider_rejected','outcome_unknown'):
            claim = store.reserve(add(store)['sample_id'],1,endpoint,128,8)
            result = {'response_complete':False,'error_category':error,'cost':None}
            path = store.one('SELECT response_path FROM attempts WHERE attempt_id=?',(claim['attempt_id'],))['response_path']
            atomic_json(store.root/path,result)
            store.settle(claim['attempt_id'],result)
            store.finish(claim,status='blocked',reason=error)
        before = store.campaign('review')
        store.set_campaign_state('review','paused')
        backup(store,store.root,tmp_path/'backup')
        verify_backup(tmp_path/'backup')
        restore_backup(tmp_path/'backup',tmp_path/'restored')
        restored = Store(tmp_path/'restored')
        try:
            assert verify_asset(restored.root/asset['path'])==json.loads(asset['manifest_json'])
            assert restored.recover()==[]
            after = restored.campaign('review')
            for key in ('requests_used','cost_known','cost_unknown','reserved_cost','accepted_unique','provisional_pass'):
                assert before[key]==after[key]
            assert restored.one("SELECT COUNT(*) n FROM attempts WHERE status='outcome_unknown' AND occupancy=1")['n']==1
            assert restored.one('SELECT COUNT(*) n FROM assets')['n']==1
        finally:
            restored.close()
    finally:
        await scheduler.client.close()


async def test_r02_r11_authenticated_reconciliation_and_config_history(tmp_path,monkeypatch):
    import httpx
    from voxlush.api.app import create_app
    monkeypatch.setenv('VOXLUSH_ADMIN_TOKEN','fixture-admin')
    cfg = Config(data_root=tmp_path/'api',author=Endpoint(base_url='http://private.invalid',model='fixture',parameters={'token':'fixture-secret'}))
    app = create_app(cfg,start_scheduler=False)
    async with app.router.lifespan_context(app):
        store = app.state.store
        store.create_campaign('review','Review',10,10,4,{'natural':1})
        store.set_campaign_state('review','running')
        claim = store.reserve(add(store)['sample_id'],1,cfg.author,4,8)
        store.settle(claim['attempt_id'],{'error_category':'outcome_unknown','cost':None})
        store.finish(claim,status='blocked',reason='outcome_unknown')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1') as client:
            assert (await client.get('/api/v1/config/history?campaign_id=review')).status_code==401
            client.headers['Authorization']='Bearer fixture-admin'
            history = await client.get('/api/v1/config/history?campaign_id=review')
            assert history.status_code==200 and len(history.json()['items'])==1
            assert 'private.invalid' not in history.text and 'fixture-secret' not in history.text
            command = {'command_id':'confirm','campaign_id':'review','action':'reconcile_execution',
                       'expected_config_revision':1,'payload':{'attempt_id':claim['attempt_id'],'outcome':'completed','evidence':''}}
            assert (await client.post('/api/v1/commands',json=command)).status_code==422
            command['payload']['evidence']='fixture service terminal receipt'
            assert (await client.post('/api/v1/commands',json=command)).status_code==200
            store.apply_commands()
            result = await client.get('/api/v1/commands/confirm')
            assert result.json()['status']=='applied'
            assert store.one('SELECT occupancy FROM attempts')['occupancy']==0
            assert store.campaign('review')['cost_unknown']==1


@pytest.mark.parametrize('unavailable',['zero_cap','unknown'])
async def test_r02_r03_unavailable_visual_prefix_does_not_starve_author(store,fake_http,unavailable):
    url,posts = await fake_http(complete_response())
    author = Endpoint(base_url=url,model='fixture')
    visual = Endpoint(alias='visual',base_url='http://visual.invalid',model='fixture',supports_images=True,
                      provider_cap=0 if unavailable=='zero_cap' else 2)
    for index in range(65):
        sample = add(store)
        claim = store.claim(sample['sample_id'],1)
        store.finish(claim,stage='review')
        if index==0 and unavailable=='unknown':
            claim = store.reserve(sample['sample_id'],1,visual,4,8)
            store.settle(claim['attempt_id'],{'error_category':'outcome_unknown','cost':None})
            store.finish(claim,status='blocked',reason='outcome_unknown')
    wanted = add(store)
    scheduler = Scheduler(store,Config(data_root=store.root,allow_live=True,global_api_cap=4,author=author,visual=visual))
    try:
        await scheduler.tick()
        await asyncio.gather(*scheduler.active)
        assert len(posts)==1
        assert store.sample(wanted['sample_id'])['stage']=='build'
    finally:
        await scheduler.client.close()


def test_nonempty_v1_migration_preserves_ledger_and_builds_seed_stats(tmp_path):
    from voxlush.store.store import SCHEMA
    from voxlush.store import sqlite
    root = tmp_path/'migration'
    root.mkdir()
    db = sqlite.connect(root/'runtime.db')
    db.executescript(SCHEMA)
    db.execute("INSERT INTO meta VALUES('schema','1')")
    db.execute("INSERT INTO campaigns(campaign_id,name,target,request_limit,api_cap,scene_weights,requests_used,reserved_cost,cost_unknown,created_at,updated_at) VALUES('old','Old',10,20,4,'{\"natural\":1}',1,3,1,1,1)")
    db.execute("INSERT INTO samples(sample_id,campaign_id,theme_seed_id,family_id,scene_type,task_json,stage,status,last_progress_at,updated_at,created_at,lineage_group,attempt_id) VALUES('sample','old','geology_01','geology','natural','{}','author','blocked',1,1,1,'sample','attempt')")
    db.execute("INSERT INTO attempts(attempt_id,sample_id,campaign_id,revision,lease_token,role,endpoint_alias,status,reserved_cost,billing_status,response_path,started_at,occupancy) VALUES('attempt','sample','old',1,'lease','author','author','outcome_unknown',3,'unknown_reserved','old.json',1,1)")
    db.close()
    store = Store(root)
    try:
        assert store.one("SELECT value FROM meta WHERE key='schema'")['value']=='2'
        assert store.campaign('old')['reserved_cost']==3
        assert store.campaign('old')['requests_used']==1
        attempt = store.one('SELECT * FROM attempts')
        assert attempt['occupancy']==1 and attempt['response_applied']==0
        assert attempt['capacity_group']=='legacy:author'
        assert store.one('SELECT planned FROM seed_stats')['planned']==1
        assert store.one('PRAGMA integrity_check')['integrity_check']=='ok'
    finally:
        store.close()


@pytest.mark.parametrize('corrupt',[False,True])
def test_r04_missing_or_corrupt_settled_response_blocks_without_rebilling(store,corrupt):
    endpoint = Endpoint(base_url='http://fixture.invalid',model='fixture',cost_upper_bound=2)
    claim = store.reserve(add(store)['sample_id'],1,endpoint,128,8)
    response = {'response_complete':True,'content':'x=1','cost':1}
    store.settle(claim['attempt_id'],response)
    store.finish(claim,status='blocked',reason='finish_callback_failed',response_applied=False)
    path = store.root/claim['attempt']['response_path']
    if corrupt:
        atomic_json(path,[])
    assert store.recover()==[]
    assert store.sample(claim['sample_id'])['reason_code']=='response_unavailable'
    assert store.recover(pending_only=True)==[]
    assert store.campaign('review')['cost_known']==1
    assert store.campaign('review')['cost_unknown']==0
    atomic_json(path,response)
    store.command({'command_id':'consume-restored','campaign_id':'review','action':'retry',
                   'expected_config_revision':1,'payload':{'sample_id':claim['sample_id']}})
    store.apply_commands()
    recovered = store.recover(pending_only=True)
    assert len(recovered)==1
    store.finish(recovered[0][0],stage='build')
    assert store.campaign('review')['requests_used']==1
