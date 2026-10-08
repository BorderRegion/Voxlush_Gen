"""Material independent geometry fingerprints used to find near duplicate candidates.

These fingerprints are intentionally a review aid.  They never reject or merge an
asset by themselves; the Store keeps the immutable sample/revision identity and
the visual/geometry evidence remains authoritative.
"""
from __future__ import annotations

import hashlib
import itertools
import json
from pathlib import Path
from typing import Any

import numpy as np


SCHEMA = "voxlush.dedup_features.v1"


def _rotations() -> tuple[np.ndarray, ...]:
    """Return the 24 proper cube rotations as signed permutation matrices."""
    values: list[np.ndarray] = []
    for permutation in itertools.permutations(range(3)):
        for signs in itertools.product((-1, 1), repeat=3):
            matrix = np.zeros((3, 3), dtype=np.int8)
            for row, axis in enumerate(permutation):
                matrix[row, axis] = signs[row]
            if int(round(np.linalg.det(matrix))) == 1:
                values.append(matrix)
    return tuple(values)


ROTATIONS = _rotations()


def _points(coords: Any) -> np.ndarray:
    points = np.asarray(coords)
    if points.ndim != 2 or points.shape[1] != 3 or len(points) == 0 or len(points) > 600_000:
        raise ValueError("coordinates must be a nonempty N by 3 array within the resource budget")
    if not np.issubdtype(points.dtype, np.integer):
        raise ValueError("coordinates must be integral")
    points = np.asarray(points, dtype=np.int64)
    if len(np.unique(points, axis=0)) != len(points):
        raise ValueError("duplicate occupied coordinates")
    return points


def _normal(points: np.ndarray) -> np.ndarray:
    points = points - points.min(axis=0)
    return points[np.lexsort((points[:, 2], points[:, 1], points[:, 0]))].astype("<i4", copy=False)


def _digest(points: np.ndarray) -> str:
    normal = _normal(points)
    payload = normal.tobytes(order="C")
    return hashlib.sha256(b"voxlush.occupancy.v1\0" + len(normal).to_bytes(8, "little") + payload).hexdigest()


def _rotation_digest(points: np.ndarray) -> str:
    digests = []
    for matrix in ROTATIONS:
        transformed = points @ matrix.T
        normal = _normal(transformed)
        digests.append(normal.tobytes(order="C"))
    payload = min(digests)
    return hashlib.sha256(b"voxlush.occupancy.rotation.v1\0" + len(points).to_bytes(8, "little") + payload).hexdigest()


def _quantized_digest(points: np.ndarray, bins: int = 16) -> str:
    """Hash coarse occupancy in normalized bounding-box coordinates.

    Quantization deliberately permits nearby edits to share a candidate key;
    use the exact rotation hash for an exact duplicate check.
    """
    if not 2 <= bins <= 64:
        raise ValueError("quantization bins must be in 2..64")
    candidates = []
    for matrix in ROTATIONS:
        normal = _normal(points @ matrix.T)
        dimensions = normal.max(axis=0) + 1
        # Map voxel centres into a fixed cube. ``maximum`` keeps one-cell
        # objects valid and avoids division by zero on thin dimensions.
        scale = np.maximum(dimensions.astype(np.float64), 1.0)
        quantized = np.floor(normal.astype(np.float64) * bins / scale).astype(np.int16)
        quantized = np.clip(quantized, 0, bins - 1)
        quantized = quantized[np.lexsort((quantized[:, 2], quantized[:, 1], quantized[:, 0]))]
        unique = np.unique(quantized, axis=0)
        candidates.append(json.dumps({"bins": bins, "dimensions": sorted(dimensions.tolist()), "occupied": unique.tolist()}, separators=(",", ":"), sort_keys=True).encode())
    payload = min(candidates)
    return hashlib.sha256(b"voxlush.geometry.quant.v1\0" + payload).hexdigest()


def feature_hashes(coords: Any, *, quantization_bins: int = 16) -> dict[str, Any]:
    """Compute stable, translation/rotation/material independent candidate features."""
    points = _points(coords)
    normal = _normal(points)
    dimensions = sorted((normal.max(axis=0) + 1).astype(int).tolist())
    return {
        "schema_version": SCHEMA,
        "translation_occupancy_sha256": _digest(points),
        "rotation_occupancy_sha256": _rotation_digest(points),
        "geometry_quant_sha256": _quantized_digest(points, quantization_bins),
        "quantization_bins": quantization_bins,
        "occupied_voxels": len(points),
        "normalized_dimensions": dimensions,
        "candidate_only": True,
    }


def near_candidate_key(features: dict[str, Any]) -> str:
    """Return an index key; matching keys create candidates, never decisions."""
    required = ("geometry_quant_sha256", "occupied_voxels", "normalized_dimensions")
    if any(key not in features for key in required):
        raise ValueError("incomplete dedup features")
    payload = {key: features[key] for key in required}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def features_from_asset(directory: Path | str) -> dict[str, Any]:
    """Load canonical occupied coordinates from an already verified asset."""
    from voxlush.voxel.canonical import load

    coords, _, _, _ = load(Path(directory))
    return feature_hashes(coords)
