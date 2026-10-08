"""Small, shared filesystem boundaries for immutable data (never follow links)."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
from typing import Any

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


def identifier(value: str) -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise ValueError("invalid identifier")
    return value


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if not value or "\\" in value or path.is_absolute() or any(part in {".", ".."} for part in value.split("/")):
        raise ValueError("unsafe relative artifact path")
    return path


def safe_path(root: Path, value: str, *, must_exist: bool = True) -> Path:
    """Reject a symlink at any component, including a leaf or missing ancestor."""
    rel = relative_path(value)
    root = root.absolute()
    current = root
    if current.is_symlink():
        raise ValueError("symlink data root")
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("symlink artifact path")
    if must_exist and not current.exists():
        raise FileNotFoundError(current)
    if not current.resolve(strict=False).is_relative_to(root.resolve()):
        raise ValueError("artifact outside data root")
    return current


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_atomic(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def file_record(root: Path, name: str, kind: str | None = None) -> dict:
    path = safe_path(root, name)
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"empty or non-file artifact: {name}")
    return {"kind": kind or name.split(".")[0], "path": name, "sha256": sha256(path), "bytes": path.stat().st_size}
