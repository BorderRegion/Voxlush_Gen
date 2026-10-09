"""Live-run repair feedback must retain the actionable end of a traceback."""
import json

import pytest

from voxlush.pipeline.prompts import author_messages
from voxlush.voxel.adapter import build


def test_author_repair_keeps_root_cause_and_bounded_context():
    root_cause = 'ValueError: Aperture axis must name a cardinal side: door_entry'
    trace = 'sandbox_execution_failed: Traceback (most recent call last):\n' + (
        '  File "/output/build.py", line 399, in generated_helper\n' * 80
    ) + root_cause
    evidence = {'passed': False, 'violations': [
        {'rule': 'sandbox_execution_failed', 'detail': trace}
    ]}
    messages = author_messages({'phase': 'skeleton'}, source='x = 1', feedback=evidence)
    feedback = json.loads(messages[1]['content'])['current_evidence']
    detail = feedback['violations'][0]['detail']
    assert root_cause in detail
    assert detail.startswith('sandbox_execution_failed: Traceback')
    assert len(detail) <= 600
    assert len(json.dumps(feedback).encode()) <= 8000
    assert evidence['violations'][0]['detail'] == trace


@pytest.mark.parametrize('metadata,path,expected', [
    ({'spaces':['reading hall']}, 'MODEL_SPEC.spaces[0]', 'must be an object'),
    ({'features':['gable roof']}, 'MODEL_SPEC.features[0]', 'must be an object'),
    ({'spaces':[{'id':'hall','air_bbox':[]}]}, 'MODEL_SPEC.spaces[0].air_bbox', 'must be an object'),
])
def test_malformed_metadata_reaches_author_as_specific_feedback(tmp_path, metadata, path, expected):
    report = build('MODEL_SPEC = ' + repr(metadata),
                   {'sample_id':'metadata_fixture','seed':1,'quality_contract':'inhabited'}, tmp_path/'build')
    assert not report['passed']
    assert report['violations'][0]['rule'] == 'source_or_build_invalid'
    messages = author_messages({'phase':'final'}, source='MODEL_SPEC = '+repr(metadata), feedback=report)
    detail = json.loads(messages[1]['content'])['current_evidence']['violations'][0]['detail']
    assert path in detail and expected in detail


async def test_malformed_space_box_gets_author_repair_not_local_retry(tmp_path):
    from voxlush.core.config import Config
    from voxlush.pipeline.scheduler import Scheduler
    from voxlush.store.store import Store
    from test_review_b02 import add
    store=Store(tmp_path/'data')
    store.create_campaign('review','Metadata fixture',1,8,1,{'natural':1})
    store.set_campaign_state('review','running')
    source=tmp_path/'source.py'
    source.write_text("MODEL_SPEC={'spaces':[{'id':'hall','air_bbox':[]}]}")
    sample=add(store,source=source)
    scheduler=Scheduler(store,Config(data_root=store.root))
    try:
        await scheduler.local(store.claim(sample['sample_id'],1))
        after=store.sample(sample['sample_id'])
        assert after['stage']=='author' and after['geometry_repairs']==1
        assert after['local_retries']==0 and not scheduler.storage_failed
        assert store.one('SELECT COUNT(*) n FROM attempts')['n']==0
    finally:
        await scheduler.client.close()
        store.close()
