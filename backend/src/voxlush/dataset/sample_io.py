"""Lossless voxel JSON storage. Old plain assets remain readable and immutable."""
from __future__ import annotations

import gzip
import json
import zlib
from pathlib import Path

from .files import safe_path, write_atomic

SAMPLE_NAMES = ("sample.json.gz", "sample.json")
# Matches the sandbox's absolute output ceiling; limits decompression as well.
MAX_SAMPLE_BYTES = 256 * 1024**2


def _read(path: Path, limit: int) -> bytes:
    opener = gzip.open if path.name.endswith(".gz") else open
    try:
        with opener(path, "rb") as handle:
            data = handle.read(limit + 1)
    except (gzip.BadGzipFile, EOFError, zlib.error) as exc:
        raise ValueError("invalid compressed sample") from exc
    if len(data) > limit:
        raise ValueError("sample exceeds uncompressed size limit")
    return data


def read_sample_bytes(directory: Path, *, names=None, limit=MAX_SAMPLE_BYTES) -> bytes:
    """When verifying an archive, only read files actually bound by its manifest."""
    found = []
    for name in SAMPLE_NAMES:
        if names is not None and name not in names:
            continue
        path = safe_path(Path(directory), name, must_exist=False)
        if path.is_file():
            found.append(_read(path, limit))
    if not found:
        raise FileNotFoundError(f"missing sample.json.gz or sample.json in {directory}")
    if len(found) == 2 and found[0] != found[1] and json.loads(found[0]) != json.loads(found[1]):
        raise ValueError("compressed sample and plain sample disagree")
    return found[0]


def read_sample(directory: Path, *, names=None, limit=MAX_SAMPLE_BYTES) -> dict:
    sample = json.loads(read_sample_bytes(directory, names=names, limit=limit))
    if not isinstance(sample, dict):
        raise ValueError("sample must be a JSON object")
    return sample


def write_sample_bytes(directory: Path, data: bytes) -> Path:
    """Write a deterministic gzip, verify exact bytes, never delete a plain source."""
    if len(data) > MAX_SAMPLE_BYTES:
        raise ValueError("sample exceeds uncompressed size limit")
    path = safe_path(Path(directory), SAMPLE_NAMES[0], must_exist=False)
    write_atomic(path, gzip.compress(data, compresslevel=6, mtime=0))
    if _read(path, MAX_SAMPLE_BYTES) != data:
        raise ValueError("compressed sample roundtrip mismatch")
    return path
