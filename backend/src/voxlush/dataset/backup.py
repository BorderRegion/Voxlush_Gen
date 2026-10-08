"""Consistent SQLite online backups plus immutable artifact snapshots."""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Iterator

from .files import fsync_directory, json_bytes, safe_path, sha256, write_atomic


def _tree(root: Path, relative: str) -> Iterator[tuple[str, Path]]:
    directory = safe_path(root, relative, must_exist=False)
    if not directory.exists():
        return
    for current, directories, names in os.walk(directory, followlinks=False):
        directories.sort()
        names.sort()
        for name in directories + names:
            if (Path(current) / name).is_symlink():
                raise ValueError("backup source contains symlink")
        for name in names:
            path = Path(current) / name
            if path.is_file():
                yield path.relative_to(root).as_posix(), path


def backup(store: Any, data_root: Path | str, output: Path | str, *, hardlink: bool = False) -> dict:
    root, output = Path(data_root).absolute(), Path(output).absolute()
    if output.is_symlink() or output.parent.is_symlink() or root.is_symlink():
        raise ValueError("symlink backup path")
    if output.exists():
        return verify_backup(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = output.with_name("." + output.name + ".staging")
    if stage.exists():
        raise ValueError("incomplete backup staging exists; retain it for diagnosis or choose a new backup output")
    stage.mkdir()
    # The Store guard holds its single-writer lock throughout mutable file
    # capture; its DB backup rejects running attempts/leases and campaigns.
    guard = store.backup_snapshot() if hasattr(store, "backup_snapshot") else nullcontext()
    with guard:
        store.backup_db(stage / "runtime.db")
        records = [{"path": "runtime.db", "bytes": (stage / "runtime.db").stat().st_size, "sha256": sha256(stage / "runtime.db")}]
        for directory in ("assets", "runtimes", "releases", "runs", "commits", "work", "staging"):
            for relative, path in _tree(root, directory):
                destination = safe_path(stage, relative, must_exist=False)
                destination.parent.mkdir(parents=True, exist_ok=True)
                # Hardlinking is opt-in and limited to immutable files.
                if hardlink and directory in {"assets", "runtimes", "releases"} and path.stat().st_mode & 0o222 == 0:
                    try:
                        os.link(path, destination)
                    except OSError:
                        shutil.copyfile(path, destination)
                else:
                    shutil.copyfile(path, destination)
                records.append({"path": relative, "bytes": destination.stat().st_size, "sha256": sha256(destination)})
    manifest = {"schema_version": "voxlush.backup.v1", "database_method": "sqlite_online_backup", "original_root": str(root), "hardlink_immutable": hardlink, "files": sorted(records, key=lambda item: item["path"])}
    write_atomic(stage / "backup_manifest.json", json_bytes(manifest))
    verify_backup(stage)
    fsync_directory(stage)
    os.rename(stage, output)
    fsync_directory(output.parent)
    return manifest


def verify_backup(directory: Path | str) -> dict:
    directory = Path(directory)
    manifest = json.loads(safe_path(directory, "backup_manifest.json").read_text())
    if manifest.get("schema_version") != "voxlush.backup.v1" or manifest.get("database_method") != "sqlite_online_backup":
        raise ValueError("unsupported backup format")
    seen = set()
    for item in manifest["files"]:
        if item["path"] in seen:
            raise ValueError("duplicate backup path")
        seen.add(item["path"])
        path = safe_path(directory, item["path"])
        if not path.is_file() or path.stat().st_size != item["bytes"] or sha256(path) != item["sha256"]:
            raise ValueError("backup integrity mismatch")
    if "runtime.db" not in seen:
        raise ValueError("backup missing runtime database")
    # Read-only integrity check cannot migrate, checkpoint, or modify the backup.
    connection = sqlite3.connect(f"file:{directory / 'runtime.db'}?mode=ro&immutable=1", uri=True)
    try:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("backup SQLite integrity failure")
    finally:
        connection.close()
    return manifest


def restore_backup(source: Path | str, destination: Path | str) -> dict:
    """Restore into a new independent root, never overwrite a running data root."""
    source, destination = Path(source).absolute(), Path(destination).absolute()
    manifest = verify_backup(source)
    if destination.exists():
        raise ValueError("restore destination must not exist")
    if destination.parent.is_symlink():
        raise ValueError("symlink restore destination")
    destination.mkdir(parents=True)
    for record in manifest["files"]:
        path = safe_path(destination, record["path"], must_exist=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(safe_path(source, record["path"]), path)
        if record["path"].startswith(("assets/", "runtimes/", "releases/")):
            path.chmod(0o444)
    # Rebase through the only authorized state writer. Older non-Store
    # backup fixtures have no scheduler tables and need no path migration.
    tables = sqlite3.connect(f"file:{destination / 'runtime.db'}?mode=ro", uri=True)
    try:
        has_store = tables.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='samples'").fetchone() is not None
    finally:
        tables.close()
    if has_store:
        from voxlush.store.store import Store
        restored_store = Store(destination)
        try:
            restored_store.rebase_paths(manifest.get("original_root", str(source)), destination)
        finally:
            restored_store.close()
    # Retain an auditable restoration receipt outside the active DB.
    receipt = {"schema_version": "voxlush.restore.v1", "backup_manifest_sha256": sha256(source / "backup_manifest.json"), "original_root": manifest.get("original_root"), "restored_root": str(destination), "files": len(manifest["files"]), "database_integrity": "ok", "paths_rebased": has_store}
    write_atomic(destination / "restore_receipt.json", json_bytes(receipt))
    fsync_directory(destination)
    return receipt
