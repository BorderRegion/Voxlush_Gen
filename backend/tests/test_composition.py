"""Context control evidence. Model verdicts here are explicit test doubles, never live quality."""
import json
from collections import Counter

import pytest
from fastapi.testclient import TestClient

from voxlush.api.app import create_app
from voxlush.api.models import CampaignCreate, ExportCreate
from voxlush.core.config import Config, Endpoint
from voxlush.dataset import Archive, backup, export, restore_backup, verify_asset, verify_release
from voxlush.dataset.files import sha256
from voxlush.pipeline.prompts import author_messages, parse_review, review_messages
from voxlush.pipeline.scheduler import Scheduler
from voxlush.store.store import Store
from voxlush.themes.composition import MODES, eligible_composition, validate_observation, validate_weights
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
    assert not parse_review(review_text(assessment('pure_target')),'a'*64,['b'*64],task=task('light_context'))['passed']
    assert parse_review(review_text(),'a'*64,['b'*64],task=task(None,contract='landscape'))['passed']


@pytest.mark.parametrize('requested',MODES)
@pytest.mark.parametrize('observed',MODES)
def test_actual_class_is_separate_from_permission_ceiling(requested,observed):
    review = parse_review(review_text(assessment(observed)),'a'*64,['b'*64],task=task(requested))
    context = review['context_assessment']
    assert context['within_requested_allowance'] == (MODES.index(observed)<=MODES.index(requested))
    assert context['matches_requested_class'] == (observed==requested)
    assert review['passed'] == context['meets_requested'] == (observed==requested)
    assert context['observed_mode']==observed and context['requested_mode']==requested


def test_category_variation_uncertainty_and_building_quality_are_not_relabelled():
    for mode in MODES:
        observation = validate_observation(mode,assessment(None,'unclear'))
        assert observation['matches_requested_class'] is None and observation['meets_requested'] is None
        assert validate_observation(mode,assessment(mode,'incidental'))['meets_requested'] is False
        assert validate_observation(mode,{**assessment(mode),'extraneous_environment':True})['meets_requested'] is False
    # Within-class variety is allowed, including co-primary buildings in contextual scenes.
    assert validate_observation('contextual',assessment('contextual','co_primary'))['meets_requested'] is True
    assert validate_observation('light_context',assessment('light_context','co_primary'))['meets_requested'] is False


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
        # Synthetic quota arithmetic: no fixture is a claimed model asset.
        store.db.execute('UPDATE samples SET composition_eligible=1 WHERE sample_id=?',(s['sample_id'],))
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
            store.db.execute('UPDATE samples SET composition_eligible=1 WHERE sample_id=?',(sample['sample_id'],))
        rows = {r['composition_mode']:r for r in store.composition_coverage('composition')['items']}
        assert {m:rows[m]['provisional'] for m in MODES} == dict(zip(MODES,(8,6,4,2),strict=True))
        assert results['pure_target']==16
        assert all(rows[m]['accepted']==0 for m in MODES)
    finally:
        await scheduler.stop()
        store.close()


async def test_compliant_surplus_cannot_replace_another_class_or_stall_coverage(tmp_path):
    store = Store(tmp_path/'data')
    c = store.create_campaign('composition','Quota surplus',2,50,0,{'architecture':1},
                              composition_weights={'pure_target':1,'contextual':1})
    store.set_campaign_state('composition','running')
    # Synthetic, qualified-state arithmetic. Both family totals are full, all in pure mode.
    for n,family in enumerate(r for r in store.coverage('composition')['items'] if r['target']):
        sample = store.add_sample(runtime_task(task_for(c,family['family_id'],n,composition_mode='pure_target')))
        store.finish(store.claim(sample['sample_id'],1),status='accepted')
        store.db.execute('UPDATE samples SET composition_eligible=1 WHERE sample_id=?',(sample['sample_id'],))
    store.db.execute("UPDATE campaigns SET accepted_unique=2 WHERE campaign_id='composition'")
    scheduler = Scheduler(store,Config(data_root=store.root,allow_live=True,disk_reserve_bytes=0,
        author=Endpoint(base_url='http://127.0.0.1:1/v1',model='unused-fixture')))
    try:
        assert store.coverage('composition')['totals']['debt']==0
        scheduler.loss_control()
        assert store.campaign('composition')['state']=='running'
        store.set_campaign_state('composition','degraded','coverage_debt')
        await scheduler.tick()
        assert store.campaign('composition')['state']=='running'
        ready = store.rows("SELECT composition_mode FROM samples WHERE status='ready'")
        assert ready==[{'composition_mode':'contextual'}]
        assert store.campaign('composition')['requests_used']==0
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
        assert store.one("SELECT value FROM meta WHERE key='schema'")['value']=='5'
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


def historical_context_asset(root,directory,t,observed,monkeypatch):
    """Construct a v1 archive test double, including v1's permissive bug."""
    from voxlush.dataset import archive as archive_module
    report = json.loads((directory/'geometry.json').read_text())
    images = [sha256(directory/'previews'/f'view_{v}.webp') for v in ('a','b')]
    old = validate_observation(t['composition_mode'],assessment(observed),historical=True)
    review = parse_review(review_text(assessment(t['composition_mode'])),report['canonical_voxel_hash'],images,task=t)
    review.update(context_assessment=old,evidence_kind='fixture_mock',profile_qualified=False)
    record = {'sample_id':t['sample_id'],'campaign_id':'composition','revision':1,'task':t,'record_kind':'fixture'}
    original = archive_module._composition
    with monkeypatch.context() as patch:
        patch.setattr(archive_module,'_composition',lambda *a,**kw:original(*a,historical=True))
        item = Archive(root).prepare(record,directory,review)
    return {**item,'status':'provisional_pass'}, review, record


@pytest.mark.parametrize('requested,observed',[
    ('contextual','pure_target'),('contextual','environment_rich'),
    ('environment_rich','pure_target'),('environment_rich','contextual')])
def test_old_archive_integrity_is_preserved_but_cannot_fill_or_export_wrong_class(real_context_builds,tmp_path,monkeypatch,requested,observed):
    import sqlite3
    import shutil
    from voxlush.dataset.files import json_bytes
    from voxlush.themes.composition import COMPLIANCE_VERSION
    from voxlush.dataset.export import _write_release
    original_task,original_dir,_ = real_context_builds['contextual']
    directory = tmp_path/'build'
    shutil.copytree(original_dir,directory)
    t = {**original_task,'composition_mode':requested}
    report = json.loads((directory/'geometry.json').read_text())
    report['evidence']['composition'] = measure(json.loads((directory/'sample.json').read_text()),t)[0]
    (directory/'geometry.json').write_bytes(json_bytes(report))
    root = tmp_path/'data'
    bad,review,record = historical_context_asset(root,directory,t,observed,monkeypatch)
    path = root/bad['path']
    before = {str(p.relative_to(path)):sha256(p) for p in path.rglob('*') if p.is_file()}
    old_manifest = verify_asset(path)
    assert old_manifest['composition']['meets_requested'] is True  # original v1 evidence retained
    assert not eligible_composition(old_manifest['composition'])
    # Paid, complete v1 review is reusable only if its actual class matches.
    with pytest.raises(ValueError,match='requested class'):
        Archive(tmp_path/'new').prepare(record,directory,review)
    for name,selection in [('all',{}),('filtered',{'composition_modes':[requested]})]:
        result = export(AssetStore([bad]),root,'composition',tmp_path/name,True,**selection)
        assert result['counts']['assets']==0 and result['composition_counts']=={}
    with pytest.raises(ValueError,match='quota unavailable'):
        export(AssetStore([bad]),root,'composition',tmp_path/'mixed-bad',True,
               composition_weights={requested:1},composition_count=1)

    # A staged pre-fix snapshot must not bypass the new admission check.
    output = tmp_path/'resume'
    stage = tmp_path/'.resume.staging'
    stage.mkdir()
    db = sqlite3.connect(stage/'export_spool.sqlite')
    db.executescript('CREATE TABLE options(key TEXT PRIMARY KEY,value TEXT); CREATE TABLE assets(sample_id TEXT,revision INTEGER,path TEXT,manifest TEXT,status TEXT,group_token TEXT,PRIMARY KEY(sample_id,revision)); CREATE TABLE groups(token TEXT PRIMARY KEY,parent TEXT);')
    options = {'campaign_id':'composition','include_provisional':True,'shard_asset_limit':512,
               'shard_byte_limit':512*1024*1024,'composition_modes':None,'composition_weights':None,'composition_count':None}
    db.execute("INSERT INTO options VALUES('config',?)",(json.dumps(options),))
    db.execute("INSERT INTO options VALUES('snapshot_complete','true')")
    db.execute('INSERT INTO assets VALUES(?,?,?,?,?,?)',(t['sample_id'],1,str(bad['path']),json.dumps(old_manifest),'provisional_pass','sample:'+t['sample_id']))
    db.commit()
    with pytest.raises(ValueError,match='composition policy'):
        export(AssetStore([]),root,'composition',output,True)
    with pytest.raises(ValueError,match='actual composition mismatch'):
        _write_release(db,stage,output,root,{**options,'composition_policy':COMPLIANCE_VERSION})
    db.close()

    # A release carrying a v1 false pass is detected even with matching file hashes.
    result = export(AssetStore([]),root,'composition',tmp_path/'release-check',True)
    release_path = tmp_path/'release-check'
    row = {'lineage_group':'fixture','split':'excluded','record_kind':'fixture','accepted_unique':False,
           'composition':old_manifest['composition']}
    index = release_path/'asset_index.jsonl'
    index.write_bytes(json_bytes(row))
    for item in result['files']:
        if item['path']=='asset_index.jsonl':
            item.update(bytes=index.stat().st_size,sha256=sha256(index))
    (release_path/'release_manifest.json').write_bytes(json_bytes(result))
    with pytest.raises(ValueError,match='actual composition mismatch'):
        verify_release(release_path)
    assert before == {str(p.relative_to(path)):sha256(p) for p in path.rglob('*') if p.is_file()}


def test_legacy_matching_review_reused_without_model_call(real_context_builds,tmp_path,monkeypatch):
    t,directory,_ = real_context_builds['contextual']
    item,review,record = historical_context_asset(tmp_path/'old',directory,t,'contextual',monkeypatch)
    assert eligible_composition(item['manifest_json']['composition'])
    new = Archive(tmp_path/'new').prepare(record,directory,review)
    assert new['manifest_json']['composition']==item['manifest_json']['composition']
    result = export(AssetStore([item]),tmp_path/'old','composition',tmp_path/'matching',True,
                    composition_weights={'contextual':1},composition_count=1)
    assert result['composition_counts']=={'contextual':1}


@pytest.mark.parametrize('accepted',[False,True])
async def test_v4_migration_preserves_history_but_reopens_actual_quota_debt(tmp_path,monkeypatch,accepted):
    from voxlush.store import store as store_module
    from voxlush.store.migrations import migrate_v4
    from voxlush.dataset.files import json_bytes
    root = tmp_path/'data'
    # Start with genuine v4 DDL, not a downgraded v5 database.
    with monkeypatch.context() as patch:
        patch.setattr(store_module,'migrate',migrate_v4)
        store = Store(root)
        c = store.create_campaign('composition','Old classes',2,50,0,{'architecture':1},composition_weights={'contextual':1})
        store.set_campaign_state('composition','running')
        fid = next(k for k,v in FAMILIES.items() if v['scene_type']=='architecture')
        originals = []
        for n,observed in enumerate(('pure_target','environment_rich')):
            s = store.add_sample(runtime_task(task_for(c,fid,n,composition_mode='contextual')))
            claim = store.claim(s['sample_id'],1)
            visual = validate_observation('contextual',assessment(observed),historical=True)
            context = {'requested_mode':'contextual','meets_requested':True,'observed':{
                'geometry':{'requested_mode':'contextual','meets_requested':True},'visual':visual}}
            manifest = {'composition':context,'lineage':{'group_id':s['sample_id'],'is_unique':True},'lifecycle':'accepted' if accepted else 'candidate'}
            store.record_review(claim,{'status':'pass','context_assessment':visual})
            # Metadata migration fixture only, not a real archive or visual assessment.
            status = 'accepted' if accepted else 'provisional_pass'
            store.finish(claim,status=status)
            store.db.execute('INSERT INTO assets VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (s['sample_id']+':v0001',s['sample_id'],1,'composition','fixture-'+str(n),json.dumps(manifest),str(n)*64,None,int(accepted),1,status,s['sample_id'],n+1))
            counter = 'accepted_unique' if accepted else 'provisional_pass'
            store.db.execute(f"UPDATE campaigns SET {counter}={counter}+1 WHERE campaign_id='composition'")
            originals.append(store.one('SELECT * FROM assets WHERE sample_id=?',(s['sample_id'],)))
        store.db.execute("INSERT INTO attempts(attempt_id,sample_id,campaign_id,revision,lease_token,role,endpoint_alias,status,billing_status,response_path,started_at) VALUES('unknown',?,'composition',1,'l','author','pool','outcome_unknown','unknown','retained.json',1)",(s['sample_id'],))
        store.db.execute("UPDATE campaigns SET requests_used=7,cost_unknown=1,cost_known=2.5 WHERE campaign_id='composition'")
        before_campaign = store.campaign('composition')
        before_unknown = store.one("SELECT * FROM attempts WHERE attempt_id='unknown'")
        store.close()
    store = Store(root)
    scheduler = None
    try:
        assert store.campaign('composition')==before_campaign
        assert store.one("SELECT * FROM attempts WHERE attempt_id='unknown'")==before_unknown
        assert store.rows('SELECT * FROM assets ORDER BY created_at')==originals
        assert all(s['status']==status for s in store.rows('SELECT status FROM samples'))
        row = store.composition_coverage('composition',diagnostics=True)['items'][0]
        assert row['candidate_debt']==2 and row['provisional']==0 and row['ineligible_archives']==2
        assert row['visual_reviewed']==2 and row['visual_pass']==0
        assert row['failures']==[{'reason_code':'composition_class_unverified','count':2}]
        assert store.coverage('composition')['totals']['provisional']==0
        scheduler = Scheduler(store,Config(data_root=root,allow_live=True,disk_reserve_bytes=0,
            author=Endpoint(base_url='http://127.0.0.1:1/v1',model='unused-fixture')))
        # Zero campaign API cap guarantees no POST. Tick must not complete from old counters.
        await scheduler.tick()
        assert store.campaign('composition')['state']=='running'
        assert store.campaign('composition')['requests_used']==7
        planned = store.one("SELECT sample_id FROM samples WHERE status='ready'")
        assert planned
        # A manually submitted legacy false-pass manifest is rejected at the DB boundary too.
        claim = store.claim(planned['sample_id'],1)
        record = {**originals[0],'manifest_json':json.loads(originals[0]['manifest_json'])}
        with pytest.raises(ValueError,match='actual composition'):
            store.commit_asset(claim,record)
        assert store.composition_coverage('composition')['items'][0]['provisional']==0
        assert json_bytes(store.one("SELECT * FROM attempts WHERE attempt_id='unknown'"))==json_bytes(before_unknown)
    finally:
        if scheduler:
            await scheduler.stop()
        store.close()
