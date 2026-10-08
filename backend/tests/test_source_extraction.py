"""Regression for the complete live response with commentary after its code fence."""
import pytest

from voxlush.pipeline.prompts import extract_source
from voxlush.voxel.adapter import decode_source


def test_complete_leading_program_with_trailing_commentary_is_preserved():
    source = "C('rock', '岩', 'rock', 'rock', floor='ground')\nP(1, 2, 3, 'stone', 'rock')\n"
    response = "```python\r\n" + source.replace('\n', '\r\n') + "```\r\n\r\nThe rock has explicit ownership."
    assert extract_source(response) == source
    decode_source(extract_source(response))


@pytest.mark.parametrize('response', [
    '```python\nx = 1',
    '```python\nx = 1\n```\n```python\nx = 2\n```',
    '```javascript\nx = 1\n```',
    '```python\nx = 1\n```python',
    'An example:\n```python\nx = 1\n```',
    '```python\nfor\n```\nA complete program.',
])
def test_ambiguous_incomplete_or_invalid_program_is_rejected(response):
    with pytest.raises((ValueError, SyntaxError)):
        extract_source(response)


def test_fence_normalization_keeps_runtime_guards():
    with pytest.raises(ValueError, match='Cannot replace primitive state'):
        decode_source(extract_source('```python\nSEED = 42\n```\nAn explanation.'))
