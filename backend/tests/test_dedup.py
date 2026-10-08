"""Candidate geometry signatures are advisory and independent of materials."""
from __future__ import annotations

import numpy as np

from voxlush.dataset.dedup import ROTATIONS, feature_hashes, near_candidate_key


def test_candidate_signature_ignores_translation_rotation_and_materials():
    points = np.array(
        [[0, 0, 0], [1, 0, 0], [2, 0, 0], [0, 1, 0], [0, 1, 1], [2, 1, 1]],
        dtype=np.int16,
    )
    matrix = next(item for item in ROTATIONS if not np.array_equal(item, np.eye(3, dtype=np.int8)))
    rotated = points @ matrix.T + np.array([17, 4, 29])
    first, second = feature_hashes(points), feature_hashes(rotated)
    assert len(ROTATIONS) == 24
    assert first["translation_occupancy_sha256"] != second["translation_occupancy_sha256"]
    assert first["rotation_occupancy_sha256"] == second["rotation_occupancy_sha256"]
    assert first["geometry_quant_sha256"] == second["geometry_quant_sha256"]
    assert near_candidate_key(first) == near_candidate_key(second)
    assert first["candidate_only"] is True


def test_candidate_signature_rejects_duplicate_or_non_integral_coordinates():
    with np.testing.assert_raises(ValueError):
        feature_hashes([[0, 0, 0], [0, 0, 0]])
    with np.testing.assert_raises(ValueError):
        feature_hashes([[0.5, 0, 0]])
