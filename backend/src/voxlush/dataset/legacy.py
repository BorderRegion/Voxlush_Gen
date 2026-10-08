"""Read-only legacy inventory. Imported complete records remain unverified."""
from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterator

from .files import sha256


def _samples(source: Path) -> Iterator[Path]:
    if source.is_symlink():
        raise ValueError("symlink legacy source")
    if source.is_file():
        if source.name not in {"sample.json", "sample.json.gz"}:
            raise ValueError("legacy input must be a sample file or directory")
        yield source
        return
    for current, directories, names in os.walk(source, followlinks=False):
        directories.sort()
        names.sort()
        for name in directories + names:
            if (Path(current) / name).is_symlink():
                raise ValueError("legacy inventory refuses symlinks")
        # Compressed and uncompressed mirrors are one source record, not two assets.
        name = "sample.json.gz" if "sample.json.gz" in names else "sample.json" if "sample.json" in names else None
        if name:
            yield Path(current) / name


def _read(path: Path, limit: int = 128 * 1024 * 1024) -> dict:
    opener = gzip.open if path.name.endswith(".gz") else open
    with opener(path, "rb") as handle:
        content = handle.read(limit + 1)
    if len(content) > limit:
        raise ValueError("legacy sample exceeds bounded uncompressed limit")
    sample = json.loads(content)
    if not isinstance(sample, dict):
        raise ValueError("legacy sample must be an object")
    return sample


def import_legacy(source: Path | str, store: Any = None, *, dry_run: bool = True) -> dict:
    source = Path(source).absolute()
    if not source.exists():
        raise FileNotFoundError(source)
    if not dry_run and store is None:
        raise ValueError("Store is required for an actual legacy import")
    report = {"schema_version": "voxlush.legacy_inventory.v1", "dry_run": dry_run, "files_seen": 0, "samples": 0, "conflicts": 0, "missing_sources": 0, "missing_previews": 0, "invalid_coordinates": 0, "invalid_records": 0, "imported": 0, "already_registered": 0, "accepted_added": 0, "status": "legacy_complete_unverified", "coordinate_policy": "Preserve 256 cubed, Y up and north=-Z; incompatible records remain unverified.", "tag_policy": "Retain legacy declared/actual tags as original claims; no promotion to verified observed tags.", "examples": []}
    # IDs and digests only, never large voxel/source records; on-disk set for large inventories.
    import sqlite3
    seen = sqlite3.connect("")
    seen.execute("PRAGMA cache_size=-2048")
    seen.execute("CREATE TABLE seen(original_id TEXT PRIMARY KEY,digest TEXT)")
    try:
        for path in _samples(source):
            report["files_seen"] += 1
            try:
                data = _read(path)
                original_id = str(data.get("sample_id", path.parent.name))
                digest = sha256(path)
                previous = seen.execute("SELECT digest FROM seen WHERE original_id=?", (original_id,)).fetchone()
                if previous:
                    if previous[0] != digest:
                        report["conflicts"] += 1
                    # Register each immutable origin/revision separately, grouped by original ID.
                else:
                    report["samples"] += 1
                    seen.execute("INSERT INTO seen VALUES (?,?)", (original_id, digest))
                source_candidates = [path.parent / name for name in ("authored_source.py", "model_source.py", "build.py")]
                code = next((q for q in source_candidates if q.is_file() and not q.is_symlink()), None)
                previews = [q for q in path.parent.iterdir() if q.is_file() and q.name.lower().startswith("preview") and q.suffix.lower() in {".png", ".webp", ".jpg", ".jpeg"}]
                if code is None:
                    report["missing_sources"] += 1
                if len(previews) < 2:
                    report["missing_previews"] += 1
                grid = data.get("grid", [256, 256, 256])
                compatible = grid == [256, 256, 256] or isinstance(grid, dict) and grid.get("size") == [256, 256, 256] and grid.get("up") in {"Y", "+Y"} and grid.get("north") == "-Z"
                invalid = not compatible
                for block in data.get("blocks", []):
                    xyz = [block.get(axis) for axis in ("x", "y", "z")]
                    if any(type(value) is not int or not 0 <= value <= 255 for value in xyz) or not block.get("component_id"):
                        invalid = True
                        break
                if invalid:
                    report["invalid_coordinates"] += 1
                origin = str(path)
                sample_id = "legacy_" + hashlib.sha256((origin + "\0" + digest).encode()).hexdigest()[:24]
                record = {"sample_id": sample_id, "original_sample_id": original_id, "source_path": origin, "source_sha256": digest, "status": "legacy_complete_unverified", "record_kind": "legacy", "path": str(path.parent), "lineage_group": "legacy_" + hashlib.sha256(original_id.encode()).hexdigest()[:24], "coordinate_compatible": not invalid, "task": {"record_kind": "legacy", "sample_id": sample_id, "original_sample_id": original_id, "scene_type": "architecture", "quality_contract": "legacy_large_wooden_v1", "generation_mode": "legacy_import", "instruction": data.get("description", ""), "requested_tags": data.get("requested_tags", {}), "original_actual_tags": data.get("actual_tags", {}), "original_generator_claimed_tags": data.get("generator_claimed_tags", {}), "original_grid": grid, "original_source": str(code) if code else None, "original_sample_sha256": digest, "seed": data.get("seed", 0)}}
                if not dry_run:
                    inserted = store.register_legacy(record)
                    report["imported" if inserted else "already_registered"] += 1
                if len(report["examples"]) < 20:
                    report["examples"].append({"sample_id": sample_id, "original_sample_id": original_id, "relative_path": path.relative_to(source).as_posix() if source.is_dir() else path.name, "coordinate_compatible": not invalid, "has_source": code is not None, "preview_count": len(previews), "status": "legacy_complete_unverified"})
            except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError):
                report["invalid_records"] += 1
    finally:
        seen.close()
    return report
