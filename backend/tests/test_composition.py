"""Context control evidence. Model verdicts here are explicit test doubles, never live quality."""
import json
from collections import Counter

import pytest
from fastapi.testclient import TestClient

from voxlush.api.app import create_app
from voxlush.api.models import CampaignCreate, ExportCreate
from voxlush.core.config import Config
from voxlush.dataset import Archive, backup, export, restore_backup, verify_asset, verify_release
from voxlush.dataset.files import sha256
from voxlush.pipeline.prompts import author_messages, parse_review, review_messages
from voxlush.pipeline.scheduler import Scheduler
from voxlush.store.store import Store
from voxlush.themes.composition import MODES, validate_weights
from voxlush.themes.planner import FAMILIES, SEEDS, runtime_task, task_for
from voxlush.voxel.adapter import build, inspect, render
from voxlush.voxel.composition import measure

from test_voxel import HOUSE, ISLANDS
from test_dataset import AssetStore


def task(mode, sid='context-fixture', contract='inhabited'):
    return {'sample_id':sid,'campaign_id':'composition','theme_seed_id':'test_01',
            'scene_type':'natural' if contract == 'landscape' else 'architecture',
            'quality_contract':contract,'composition_mode':mode,'seed':47,'phase':'final',
            'record_kind':'fixture','requested_tags':{'theme':'geometry regression fixture'}}


def assessment(mode='pure_target', focus='dominant'):
    return {'observed_mode':mode,'building_focus':focus,'extraneous_environment':False,
            'evidence':'TEST DOUBLE: building occupies both fixture views; no independent aesthetic claim.',
            'confidence':.8}


def review_text(context=None):
    result = {'verdict':'pass','issues':[],'observed_tags':[]}
    if context is not None:
        result['context_assessment'] = context
    return json.dumps(result)


@pytest.mark.parametrize('weights',[{}, {'wrong':1}, {'pure_target':-1}, {'pure_target':float('nan')},
                                  {'pure_target':float('inf')}, {'pure_target':0}])
def test_invalid_weights(weights):
    with pytest.raises(ValueError):
        validate_weights(weights)
    with pytest.raises(ValueError):
        CampaignCreate(campaign_id='c',name='c',target=10,request_limit=20,api_cap=2,composition_weights=weights)


def test_planner_propagates_modes_across_direct_skeleton_refine_repair():
    for scale in ('S','L'):
        seed = next(s for s in SEEDS if s['scene_type']=='architecture' and s['suggested_scale']==scale)
        for mode in MODES:
            nested = task_for({'campaign_id':'c'},seed['family_id'],0,seed_id=seed['id'],composition_mode=mode)
            runtime = runtime_task(nested)
            assert runtime['composition_mode'] == runtime['task_contract']['composition_mode'] == mode
            assert runtime['generation_mode'] == ('two_stage' if scale=='L' else 'direct')
            for source,feedback,refine in [(None,None,False),('original code',{'issues':['fixture']},False),('skeleton',None,True)]:
                prompt = author_messages(runtime,source,feedback,refine)
                content = json.loads(prompt[-1]['content'])
                assert content['task']['composition_mode'] == mode
                assert content['scene_composition']
                if mode=='pure_target':
                    for phrase in ('focus on the building itself','avoid extraneous surroundings','minimal non-building content','no large decorative environment unless functionally necessary'):
                        assert phrase in content['scene_composition'].lower()
    with pytest.raises(ValueError):
        task_for({'campaign_id':'c'},'geology',0,composition_mode='pure_target')


def test_composite_themes_keep_their_context_and_multi_building_requirements(tmp_path):
    store = Store(tmp_path/'data')
    try:
        c = store.create_campaign('mixed','Mixed themes',100,500,2,{'architecture':.7,'hybrid':.3})
        rows = store.composition_coverage('mixed')['items']
        hybrid = {r['composition_mode']:r['target'] for r in rows if r['scene_type']=='hybrid'}
        assert hybrid == {'contextual':20,'environment_rich':10}
        assert task_for(c,'settlement',0)['composition_mode']=='contextual'
        with pytest.raises(ValueError):
            task_for(c,'settlement',0,composition_mode='pure_target')
        with pytest.raises(ValueError,match='incompatible'):
            task_for(c,'leisure',0,seed_id='leisure_06',composition_mode='pure_target')
        # Every architecture family still has creative briefs for every mode.
        for family in FAMILIES.values():
            if family['scene_type']=='architecture':
                for mode in MODES:
                    sid = store.next_seed('mixed',family['id'],mode)
                    assert task_for(c,family['id'],0,seed_id=sid,composition_mode=mode)['composition_mode']==mode
        with pytest.raises(ValueError,match='hybrid themes'):
            store.create_campaign('invalid','Invalid',10,50,2,{'hybrid':1},composition_weights={'pure_target':1})
        with pytest.raises(ValueError,match='hybrid themes'):
            CampaignCreate(campaign_id='c',name='c',target=10,request_limit=20,api_cap=2,
                           scene_weights={'hybrid':1},composition_weights={'pure_target':1})
    finally:
        store.close()


def synthetic_scene(environment_columns=0, category='terrain'):
    # A deliberately tiny measurement fixture, not an architecture quality fixture.
    return {'components':[{'id':'wall','category':'exterior_wall'},{'id':'env','category':category}],
            'blocks':[{'x':x,'y':y,'z':10,'component_id':'wall'} for x in range(10,20) for y in range(10,20)] +
                     [{'x':x,'y':10,'z':0,'component_id':'env'} for x in range(environment_columns)]}


def test_counts_occupied_context_and_wide_thin_ground_without_trusting_volume():
    data, failures = measure(synthetic_scene(),task('pure_target'))
    assert data['voxel_counts']['subject'] == 100 and not failures
    data, failures = measure(synthetic_scene(20),task('pure_target'))
    assert {f['rule'] for f in failures} == {'composition_context_voxels','composition_context_extent'}
    assert data['context_fraction'] == pytest.approx(20/120)
    # A thin path can be cheap in voxels yet dominate framing/footprint.
    _, failures = measure(synthetic_scene(5,'path'),task('pure_target'))
    assert {f['rule'] for f in failures} == {'composition_context_extent'}
    assert not measure(synthetic_scene(5,'path'),task('light_context'))[1]
    assert not measure(synthetic_scene(200),task('contextual'))[1]
    # Calling distant scenery decoration/foundation does not make it the subject.
    for category in ('decoration','foundation','object'):
        data, failures = measure(synthetic_scene(100,category),task('pure_target'))
        assert data['voxel_counts']['unclassified'] == 100 and failures
    natural = measure(synthetic_scene(200),task(None,contract='landscape'))[0]
    assert natural['applicable'] is False and natural['meets_requested'] is None


def test_visual_evidence_missing_uncertain_and_false_pass_are_not_author_success():
    with pytest.raises(ValueError,match='context evidence'):
        parse_review(review_text(),'a'*64,['b'*64],task=task('pure_target'))
    mismatched = parse_review(review_text(assessment('environment_rich','incidental')),'a'*64,['b'*64],task=task('pure_target'))
    assert not mismatched['passed'] and mismatched['status']=='fail'
    assert mismatched['context_assessment']['requested_mode']=='pure_target'
    assert mismatched['context_assessment']['observed_mode']=='environment_rich'
    uncertain = parse_review(review_text(assessment(None,'unclear')),'a'*64,['b'*64],task=task('pure_target'))
    assert uncertain['status']=='gray'
    assert parse_review(review_text(assessment('pure_target')),'a'*64,['b'*64],task=task('light_context'))['passed']
    assert parse_review(review_text(),'a'*64,['b'*64],task=task(None,contract='landscape'))['passed']


def test_quota_debt_survives_failed_duplicate_tasks_and_restart(tmp_path):
    root = tmp_path/'data'
    store = Store(root)
    c = store.create_campaign('composition','Test quotas',10,100,2,{'architecture':1},composition_weights={'pure_target':.4,'contextual':.6})
    store.set_campaign_state('composition','running')
    family = next(k for k,v in FAMILIES.items() if v['scene_type']=='architecture')
    # Simulated state outcomes exercise scheduler arithmetic; not claimed as real archives.
    for n in range(9):
        mode = 'contextual' if n<6 else 'pure_target'
        s = store.add_sample(runtime_task(task_for(c,family,n,composition_mode=mode)))
        claim = store.claim(s['sample_id'],1)
        status,reason = ('provisional_pass',None) if n<6 else ('rejected','duplicate' if n==8 else 'repair_exhausted')
        store.finish(claim,status=status,reason=reason)
    assert store.next_composition('composition','architecture',qualified=False)=='pure_target'
    rows = {r['composition_mode']:r for r in store.composition_coverage('composition',diagnostics=True)['items']}
    assert rows['pure_target']['candidate_debt']==4
    assert rows['contextual']['candidate_debt']==0 and rows['contextual']['debt']==6
    assert rows['pure_target']['duplicate']==1
    assert store.campaign('composition')['accepted_unique']==0
    before = store.composition_coverage('composition',diagnostics=True)
    store.close()
    store = Store(root)
    try:
        assert store.composition_coverage('composition',diagnostics=True)==before
        assert store.next_composition('composition','architecture',qualified=False)=='pure_target'
        assert len(store.list_samples('composition',composition_mode='pure_target')['items'])==3
    finally:
        store.close()


async def test_scheduler_fills_actual_distribution_under_unequal_yield(tmp_path):
    store = Store(tmp_path/'data')
    c = store.create_campaign('composition','Deficit planning',20,200,2,{'architecture':1})
    store.set_campaign_state('composition','running')
    scheduler = Scheduler(store,Config(data_root=store.root))
    results = Counter()
    try:
        for _ in range(100):
            c = store.campaign('composition')
            before = c['sequence']
            scheduler.plan(c)
            c = store.campaign('composition')
            if c['sequence']==before:
                break
            s = store.one("SELECT sample_id FROM samples WHERE status='ready' ORDER BY created_at DESC LIMIT 1")
            sample = store.sample(s['sample_id'])
            mode = sample['composition_mode']
            results[mode] += 1
            claim = store.claim(sample['sample_id'],1)
            # Pure target needs two independent tasks per usable output.
            failed = mode=='pure_target' and results[mode]%2==1
            store.finish(claim,status='rejected' if failed else 'provisional_pass',reason='test_quality_failure' if failed else None)
        rows = {r['composition_mode']:r for r in store.composition_coverage('composition')['items']}
        assert {m:rows[m]['provisional'] for m in MODES} == dict(zip(MODES,(8,6,4,2),strict=True))
        assert results['pure_target']==16
        assert all(rows[m]['accepted']==0 for m in MODES)
    finally:
        await scheduler.stop()
        store.close()


def test_schema_v3_additive_migration_preserves_history(tmp_path):
    # Manufacture a v3 fixture from the current schema; actual migrations use the same DDL.
    from voxlush.store import sqlite
    from voxlush.store.store import SCHEMA
    from voxlush.store.migrations import migrate_v3
    root=tmp_path/'data'
    root.mkdir()
    db=sqlite.connect(root/'runtime.db',isolation_level=None)
    db.row_factory=sqlite.Row
    db.executescript(SCHEMA)
    db.execute("INSERT INTO meta VALUES('schema','1')")
    migrate_v3(db)
    db.execute("INSERT INTO campaigns(campaign_id,name,target,request_limit,api_cap,scene_weights,created_at,updated_at,requests_used,cost_unknown) VALUES('old','old',10,100,2,'{\"architecture\":1}',1,1,9,1)")
    old=task(None,'old')
    old['record_kind']='production'
    db.execute("INSERT INTO samples(sample_id,campaign_id,theme_seed_id,family_id,scene_type,task_json,stage,status,last_progress_at,updated_at,created_at,lineage_group,request_count) VALUES('old','old','old','old','architecture',?,'author','blocked',1,1,1,'old',9)",(json.dumps(old),))
    db.execute("INSERT INTO attempts(attempt_id,sample_id,campaign_id,revision,lease_token,role,endpoint_alias,status,billing_status,response_path,started_at) VALUES('unknown','old','old',1,'l','author','pool','outcome_unknown','unknown','retained.json',1)")
    db.close()
    store=Store(root)
    try:
        assert store.campaign('old')['composition_weights'] is None
        assert store.sample('old')['task']==old
        assert store.sample('old')['composition_mode'] is None
        assert store.campaign('old')['requests_used']==9
        assert store.one("SELECT occupancy FROM attempts WHERE attempt_id='unknown'")['occupancy']==1
        assert store.composition_coverage('old')['items'][0]['composition_mode'] is None
        assert store.one("SELECT value FROM meta WHERE key='schema'")['value']=='4'
    finally:
        store.close()


@pytest.fixture(scope='module')
def real_context_builds(tmp_path_factory):
    root=tmp_path_factory.mktemp('composition-real')
    result={}
    for mode in ('pure_target','contextual'):
        source=HOUSE
        if mode=='contextual':
            source += "\nC('grounds','地面','surrounding ground','terrain',floor='ground')\nB(0,34,9,9,0,34,'grass_block','grounds')\n"
        t=task(mode,mode)
        directory=root/mode
        report=build(source,t,directory)
        assert report['passed'],report['violations']
        assert render(directory)['passed']
        result[mode]=(t,directory,report)
    yield result


def test_real_saved_voxel_context_limits_and_natural_contract(real_context_builds,tmp_path):
    for mode,(t,directory,report) in real_context_builds.items():
        sample=json.loads((directory/'sample.json').read_text())
        assert inspect(sample,t)['passed']
        if mode=='contextual':
            changed=inspect(sample,{**t,'composition_mode':'pure_target'})
            assert not changed['passed']
            assert any(v['rule']=='composition_context_voxels' for v in changed['violations'])
        messages,images=review_messages(t,directory)
        assert len(images)==2
        assert sum(part['type']=='image_url' for part in messages[-1]['content'])==2
        assert report['evidence']['composition']['measurement_source']=='final_occupied_voxels'
    natural=build(ISLANDS,task(None,contract='landscape'),tmp_path/'natural')
    assert natural['passed']
    assert not natural['evidence']['composition']['applicable']


def test_context_archive_verification_filtered_mixed_exports_and_idempotence(real_context_builds,tmp_path):
    root=tmp_path/'assets'
    rows=[]
    for mode,(t,directory,report) in real_context_builds.items():
        images=[sha256(directory/'previews'/f'view_{v}.webp') for v in ('a','b')]
        review=parse_review(review_text(assessment(mode)),report['canonical_voxel_hash'],images,task=t)
        review.update(evidence_kind='fixture_mock',profile_qualified=False)
        record={'sample_id':mode,'campaign_id':'composition','revision':1,'task':t,'record_kind':'fixture'}
        archive=Archive(root)
        with pytest.raises(ValueError,match='context evidence'):
            archive.prepare(record,directory,{k:v for k,v in review.items() if k!='context_assessment'})
        item=archive.prepare(record,directory,review)
        assert archive.prepare(record,directory,review)==item
        assert not item['accepted_unique']
        manifest=verify_asset(root/item['path'])
        assert manifest['composition']['requested_mode']==mode
        assert manifest['composition']['meets_requested'] is True
        assert not manifest['composition']['observed']['geometry']['independent_semantics_verified']
        rows.append({**item,'status':'provisional_pass'})
    store=AssetStore(rows)
    pure=export(store,root,'composition',tmp_path/'pure',True,composition_modes=['pure_target'])
    assert pure['composition_counts']=={'pure_target':1}
    assert pure['counts']['excluded']==1 and pure['counts']['accepted']==0
    assert export(store,root,'composition',tmp_path/'pure',True,composition_modes=['pure_target'])==pure
    with pytest.raises(ValueError,match='composition conflict'):
        export(store,root,'composition',tmp_path/'pure',True,composition_modes=['contextual'])
    kwargs={'composition_weights':{'pure_target':1,'contextual':1},'composition_count':2}
    mixed=export(store,root,'composition',tmp_path/'mixed',True,**kwargs)
    assert mixed['composition_counts']=={'pure_target':1,'contextual':1}
    assert verify_release(tmp_path/'mixed')==mixed
    sft=[json.loads(line) for line in (tmp_path/'mixed'/'source_sft.jsonl').read_text().splitlines()]
    assert {s['constraints']['composition_mode'] for s in sft}=={'pure_target','contextual'}
    with pytest.raises(ValueError,match='quota unavailable'):
        export(store,root,'composition',tmp_path/'shortage',True,**{**kwargs,'composition_count':4})
    # Manifest-only edits cannot relabel a saved immutable asset.
    path=root/rows[0]['path']/'manifest.json'
    manifest=json.loads(path.read_text())
    manifest['composition']['requested_mode']='environment_rich'
    path.chmod(0o644)
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='composition manifest'):
        verify_asset(path.parent)


def test_api_filters_configuration_and_export_idempotency(tmp_path):
    app=create_app(Config(data_root=tmp_path),start_scheduler=False)
    with TestClient(app) as client:
        payload={'campaign_id':'c','name':'c','target':10,'request_limit':50,'api_cap':0,'composition_weights':{'pure_target':1,'contextual':1}}
        assert client.post('/api/v1/campaigns',json=payload).status_code==200
        store=app.state.store
        c=store.campaign('c')
        fid=next(k for k,v in FAMILIES.items() if v['scene_type']=='architecture')
        for n,mode in enumerate(('pure_target','contextual')):
            store.add_sample(runtime_task(task_for(c,fid,n,composition_mode=mode)))
        page=client.get('/api/v1/samples',params={'campaign_id':'c','composition_mode':'pure_target'}).json()
        assert len(page['items'])==1 and page['items'][0]['composition_mode']=='pure_target'
        assert client.get('/api/v1/samples?composition_mode=invalid').status_code==422
        coverage=client.get('/api/v1/coverage?campaign_id=c').json()['composition']
        assert sum(r['tasks'] for r in coverage['items'])==2
        e={'export_id':'filtered','campaign_id':'c','include_provisional':False,'composition_modes':['pure_target']}
        assert client.post('/api/v1/exports',json=e).status_code==200
        assert client.post('/api/v1/exports',json=e).status_code==200
        assert client.post('/api/v1/exports',json={**e,'composition_modes':['contextual']}).status_code==409
    with pytest.raises(ValueError):
        ExportCreate(export_id='x',campaign_id='c',composition_modes=['pure_target'],composition_weights={'pure_target':1},composition_count=10)


def test_composition_backup_restore_keeps_quota_evidence_and_filtered_export(real_context_builds,tmp_path):
    root = tmp_path/'data'
    store = Store(root)
    store.create_campaign('composition','Backup',2,10,0,{'architecture':1},composition_weights={'pure_target':1,'contextual':1})
    store.set_campaign_state('composition','running')
    try:
        for mode,(t,directory,report) in real_context_builds.items():
            store.add_sample(t)
            claim = store.claim(mode,1)
            review = parse_review(review_text(assessment(mode)),report['canonical_voxel_hash'],
                                  [sha256(directory/'previews'/f'view_{v}.webp') for v in ('a','b')],task=t)
            review.update(evidence_kind='fixture_mock',profile_qualified=False)
            store.record_review(claim,review)
            store.commit_asset(claim,Archive(root).prepare(store.sample(mode),directory,review))
        before = store.composition_coverage('composition',diagnostics=True)
        campaign = store.campaign('composition')
        assert campaign['accepted_unique']==0 and campaign['provisional_pass']==2
        store.create_export('filtered','composition',True,composition_modes=['pure_target'])
        store.set_campaign_state('composition','paused')
        backup(store,root,tmp_path/'backup')
    finally:
        store.close()
    restore_backup(tmp_path/'backup',tmp_path/'restored')
    restored = Store(tmp_path/'restored')
    try:
        assert restored.composition_coverage('composition',diagnostics=True)==before
        assert restored.campaign('composition')['composition_weights']==campaign['composition_weights']
        assert json.loads(restored.one('SELECT composition_selection FROM exports')['composition_selection'])['composition_modes']==['pure_target']
        release = export(restored,restored.root,'composition',tmp_path/'restored-export',True,composition_modes=['pure_target'])
        assert release['composition_counts']=={'pure_target':1}
        assert release['counts']['accepted']==0
    finally:
        restored.close()
