"""Offline, restartable lossless compaction of mutable work files only."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from .files import fsync_directory, safe_path, sha256
from .sample_io import MAX_SAMPLE_BYTES, read_sample_bytes, write_sample_bytes


def compact_work(store, *, apply=False):
    """Caller must own Store exclusively; never change a published artifact path."""
    result = {"apply": apply, "converted": 0, "eligible": 0, "skipped_registered": 0,
              "saved_bytes": 0, "files": [], "errors": []}
    with store.backup_snapshot():
        root = safe_path(store.root, "work", must_exist=False)
        if not root.exists():
            return result
        registered = {r["path"] for r in store.rows("SELECT path FROM artifacts")}
        for current, directories, files in os.walk(root, followlinks=False):
            directories.sort()
            for name in directories + files:
                if (Path(current) / name).is_symlink():
                    raise ValueError("symlink work artifact")
            if "sample.json" not in files:
                continue
            relative = (Path(current) / "sample.json").relative_to(store.root).as_posix()
            path = safe_path(store.root, relative)
            if relative in registered or "manifest.json" in files:
                result["skipped_registered"] += 1
                continue
            result["eligible"] += 1
            if not apply:
                continue
            try:
                before = path.stat().st_size
                if before > MAX_SAMPLE_BYTES:
                    raise ValueError("sample exceeds uncompressed size limit")
                original = path.read_bytes()
                identity = hashlib.sha256(original).hexdigest()
                compressed = safe_path(path.parent, "sample.json.gz", must_exist=False)
                # A previous interrupted run may already have published the gzip.
                if compressed.exists():
                    if read_sample_bytes(path.parent, names={"sample.json.gz"}) != original:
                        raise ValueError("existing compressed sample differs; original retained")
                    after = 0  # gzip already occupied disk before this operation.
                else:
                    write_sample_bytes(path.parent, original)
                    after = compressed.stat().st_size
                if sha256(path) != identity:
                    raise ValueError("sample changed during compaction; original retained")
                path.unlink()
                fsync_directory(path.parent)
                result["converted"] += 1
                result["saved_bytes"] += before - after
                result["files"].append({"path":relative,"uncompressed_sha256":identity,
                                        "before_bytes":before,"gzip_bytes":compressed.stat().st_size})
            except (OSError, ValueError) as exc:
                result["errors"].append({"path":relative,"error":str(exc)})
    return result
