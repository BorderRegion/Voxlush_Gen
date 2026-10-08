"""Live-run repair feedback must retain the actionable end of a traceback."""
import json

from voxlush.pipeline.prompts import author_messages


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
