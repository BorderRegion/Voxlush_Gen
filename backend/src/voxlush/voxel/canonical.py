"""Canonical occupied arrays. Geometry hashes never depend on component names."""

from __future__ import annotations

import hashlib
import json
import re
import struct
import zipfile
from pathlib import Path
from typing import Any

import numpy as np

GRID = (256, 256, 256)
FORMAT = "voxlush.voxels.v1"


def json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def normalize_block_state(state: str | dict) -> str:
    if isinstance(state, dict):
        name = state.get("Name", state.get("name"))
        props = state.get("Properties", state.get("properties", {}))
    elif isinstance(state, str):
        match = re.fullmatch(r"([a-z0-9_.:-]+)(?:\[([^\]]*)\])?", state.strip())
        if not match:
            raise ValueError("Invalid block state")
        name = match[1]
        entries = match[2].split(",") if match[2] else []
        props = {}
        for entry in entries:
            parts = entry.split("=")
            if len(parts) != 2 or parts[0] in props:
                raise ValueError("Duplicate or invalid block property")
            props[parts[0]] = parts[1]
    else:
        raise ValueError("Block state must be a string or object")
    if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9_.:-]+", name):
        raise ValueError("Invalid block name")
    if ":" not in name:
        name = "minecraft:" + name
    if name.count(":") != 1 or not isinstance(props, dict):
        raise ValueError("Invalid block namespace/properties")
    if any(
        not isinstance(k, str)
        or not isinstance(v, str)
        or not re.fullmatch(r"[a-z0-9_.-]+", k)
        or not re.fullmatch(r"[a-z0-9_.-]+", v)
        for k, v in props.items()
    ):
        raise ValueError("Invalid block property")
    return name + ("[" + ",".join(k + "=" + props[k] for k in sorted(props)) + "]" if props else "")


def canonicalize(
    coords: Any, block_index: Any, component_index: Any, palette: dict
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    coords = np.asarray(coords)
    bi = np.asarray(block_index)
    ci = np.asarray(component_index)
    if coords.ndim != 2 or coords.shape[1] != 3 or len(coords) == 0 or len(coords) > 600000:
        raise ValueError("Expected nonempty N by 3 occupied coordinates within resource budget")
    if not np.issubdtype(coords.dtype, np.integer) or np.any(coords < 0) or np.any(coords >= 256):
        raise ValueError("Coordinates must be integers in 0..255")
    if (
        bi.shape != (len(coords),)
        or ci.shape != (len(coords),)
        or not np.issubdtype(bi.dtype, np.integer)
        or not np.issubdtype(ci.dtype, np.integer)
    ):
        raise ValueError("Palette indices must be integer vectors matching coordinates")
    states = [normalize_block_state(s) for s in palette["block_states"]]
    owners = palette["component_ids"]
    if any(not isinstance(c, str) or not c for c in owners) or len(set(owners)) != len(owners):
        raise ValueError("Component IDs must be unique strings")
    if np.any(bi < 0) or np.any(bi >= len(states)) or np.any(ci < 0) or np.any(ci >= len(owners)):
        raise ValueError("Unresolved palette reference")
    order = np.lexsort((coords[:, 2], coords[:, 1], coords[:, 0]))
    result_coords = np.asarray(coords[order], dtype="<u2")
    if np.any(np.all(result_coords[1:] == result_coords[:-1], axis=1)):
        raise ValueError("Duplicate occupied coordinate")
    used_states = sorted({states[int(i)] for i in bi})
    used_owners = sorted({owners[int(i)] for i in ci})
    state_map = {s: i for i, s in enumerate(used_states)}
    owner_map = {c: i for i, c in enumerate(used_owners)}
    result_bi = np.array([state_map[states[int(i)]] for i in bi[order]], dtype="<u4")
    result_ci = np.array([owner_map[owners[int(i)]] for i in ci[order]], dtype="<u4")
    return (
        result_coords,
        result_bi,
        result_ci,
        {"schema_version": FORMAT, "block_states": used_states, "component_ids": used_owners},
    )


def canonical_voxel_hash(coords: Any, block_index: Any, palette: dict, grid: tuple = GRID) -> str:
    if tuple(grid) != GRID:
        raise ValueError("Unsupported grid")
    owners = np.zeros(len(coords), dtype=np.uint32)
    canonical_palette = {**palette, "component_ids": ["irrelevant"]}
    coords, bi, _, p = canonicalize(coords, block_index, owners, canonical_palette)
    palette_bytes = json_bytes(p["block_states"])
    h = hashlib.sha256(FORMAT.encode() + b"\0")
    h.update(struct.pack("<3H", *grid))
    h.update(struct.pack("<Q", len(palette_bytes)))
    h.update(palette_bytes)
    h.update(struct.pack("<Q", len(coords)))
    h.update(coords.tobytes(order="C"))
    h.update(bi.tobytes(order="C"))
    return h.hexdigest()


def annotation_hash(
    coords: Any, component_index: Any, palette: dict, components: list, tags: dict | None = None
) -> str:
    coords = np.asarray(coords)
    order = np.lexsort((coords[:, 2], coords[:, 1], coords[:, 0]))
    ownership = [palette["component_ids"][int(i)] for i in np.asarray(component_index)[order]]
    return hashlib.sha256(
        json_bytes(
            {
                "format": "voxlush.annotations.v1",
                "coords": coords[order].tolist(),
                "ownership": ownership,
                "components": sorted(components, key=lambda c: c["id"]),
                "tags": tags or {},
            }
        )
    ).hexdigest()


def from_sample(sample: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    blocks = sample["blocks"]
    states = sorted(
        {normalize_block_state(b["block_state"] if "block_state" in b else b["type"]) for b in blocks}
    )
    owners = sorted({b["component_id"] for b in blocks})
    si = {s: i for i, s in enumerate(states)}
    oi = {c: i for i, c in enumerate(owners)}
    coords = [[b[k] for k in ("x", "y", "z")] for b in blocks]
    bi = [si[normalize_block_state(b["block_state"] if "block_state" in b else b["type"])] for b in blocks]
    ci = [oi[b["component_id"]] for b in blocks]
    return canonicalize(coords, bi, ci, {"block_states": states, "component_ids": owners})


def save(destination: Path, sample: dict) -> dict:
    coords, bi, ci, palette = from_sample(sample)
    np.savez_compressed(destination / "voxels.npz", coords=coords, block_index=bi, component_index=ci)
    (destination / "palette.json").write_bytes(json_bytes(palette) + b"\n")
    hashes = {
        "canonical_voxel_hash": canonical_voxel_hash(coords, bi, palette),
        "annotation_hash": annotation_hash(
            coords,
            ci,
            palette,
            sample["components"],
            {"generator_declared": sample.get("generator_claimed_tags", [])},
        ),
    }
    loaded = load(destination)
    if canonical_voxel_hash(loaded[0], loaded[1], loaded[3]) != hashes["canonical_voxel_hash"]:
        raise ValueError("Canonical artifact roundtrip mismatch")
    return hashes


def load(destination: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    destination = Path(destination)
    if (destination / "palette.json").stat().st_size > 16 * 1024**2:
        raise ValueError("Palette exceeds the artifact budget")
    palette = json.loads((destination / "palette.json").read_text())
    # Bound decompression and ndarray allocation before NumPy loads untrusted artifacts.
    expected_names = {"coords.npy", "block_index.npy", "component_index.npy"}
    with zipfile.ZipFile(destination / "voxels.npz") as container:
        infos = container.infolist()
        if len(infos) != 3 or {i.filename for i in infos} != expected_names:
            raise ValueError("Unexpected canonical array fields")
        for info in infos:
            if info.file_size > 600000 * 3 * 8 + 16384:
                raise ValueError("Canonical array exceeds the artifact budget")
            with container.open(info) as handle:
                version = np.lib.format.read_magic(handle)
                reader = {
                    (1, 0): np.lib.format.read_array_header_1_0,
                    (2, 0): np.lib.format.read_array_header_2_0,
                }.get(version)
                if reader is None:
                    raise ValueError("Unsupported ndarray representation")
                shape, fortran_order, dtype = reader(handle, max_header_size=16384)
                if (
                    not shape
                    or not 0 < shape[0] <= 600000
                    or shape != ((shape[0], 3) if info.filename == "coords.npy" else (shape[0],))
                    or fortran_order
                    or not np.issubdtype(dtype, np.integer)
                    or dtype.itemsize > 8
                    or handle.tell() + int(np.prod(shape)) * dtype.itemsize != info.file_size
                ):
                    raise ValueError("Invalid or oversized canonical ndarray")
    with np.load(destination / "voxels.npz", allow_pickle=False) as archive:
        if set(archive.files) != {"coords", "block_index", "component_index"}:
            raise ValueError("Unexpected canonical array fields")
        return canonicalize(archive["coords"], archive["block_index"], archive["component_index"], palette)


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_and_validate(destination: Path) -> dict:
    """Recompute public identity from the authoritative arrays and annotations."""
    destination = Path(destination)
    coords, bi, ci, palette = load(destination)
    annotations = json.loads((destination / "components.json").read_text(encoding="utf-8"))
    components = annotations["components"]
    ids = [c["id"] for c in components]
    if len(set(ids)) != len(ids) or set(ids) != set(palette["component_ids"]):
        raise ValueError("Component annotations must exactly resolve occupied owners")
    ordering = np.argsort(ci, kind="stable")
    groups = np.split(ordering, np.flatnonzero(np.diff(ci[ordering])) + 1)
    by_id = {palette["component_ids"][int(ci[group[0]])]: coords[group] for group in groups}
    for c in components:
        points = by_id[c["id"]]
        expected = {"min": points.min(axis=0).tolist(), "max": points.max(axis=0).tolist()}
        if c.get("geometry", {}).get("voxel_count") != len(points) or c["geometry"].get("bbox") != expected:
            raise ValueError("Component statistics do not match canonical geometry")
    return {
        "canonical_voxel_hash": canonical_voxel_hash(coords, bi, palette),
        "annotation_hash": annotation_hash(
            coords,
            ci,
            palette,
            components,
            {"generator_declared": annotations.get("generator_claimed_tags", [])},
        ),
        "voxel_count": len(coords),
        "dimensions": (coords.max(axis=0) - coords.min(axis=0) + 1).tolist(),
        "hashes": {
            name: hash_file(destination / name) for name in ("voxels.npz", "palette.json", "components.json")
        },
    }
