"""Storage-only regressions; no model calls or invented quality evidence."""
import gzip
import json
import tarfile

import pytest

from test_dataset import AssetStore, artifact_fixture
from voxlush.dataset import Archive, backup, export, restore_backup, verify_asset, verify_release
from voxlush.dataset.compact import compact_work
from voxlush.dataset.files import file_record, json_bytes, sha256
from voxlush.dataset.sample_io import read_sample, read_sample_bytes, write_sample_bytes
from voxlush.store.store import OwnerBusy, Store


def test_lossless_deterministic_compression_and_plain_compatibility(tmp_path):
    raw = json_bytes({"name": "真实体素", "blocks": [{"x": 1, "component_id": "主楼"}] * 500})
    (tmp_path / "sample.json").write_bytes(raw)
    assert read_sample_bytes(tmp_path) == raw
    path = write_sample_bytes(tmp_path, raw)
    first = path.read_bytes()
    assert len(first) < len(raw) / 10
    assert (tmp_path / "sample.json").read_bytes() == raw
    write_sample_bytes(tmp_path, raw)
    assert first == path.read_bytes()
    (tmp_path / "sample.json").unlink()
    assert read_sample_bytes(tmp_path) == raw
    assert read_sample(tmp_path) == json.loads(raw)


@pytest.mark.parametrize("content", [b"bad gzip", gzip.compress(b"{}")[:-3]])
def test_corrupt_compressed_sample_never_falls_back_silently(tmp_path, content):
    (tmp_path / "sample.json.gz").write_bytes(content)
    (tmp_path / "sample.json").write_text("{}")
    with pytest.raises(ValueError, match="compressed"):
        read_sample(tmp_path)


def test_decompression_limit_and_symlinks(tmp_path):
    path = write_sample_bytes(tmp_path, b" " * 500 + b"{}")
    with pytest.raises(ValueError, match="size limit"):
        read_sample(tmp_path, limit=64)
    path.unlink()
    path.symlink_to(tmp_path / "other")
    with pytest.raises(ValueError, match="symlink"):
        read_sample(tmp_path)


def test_new_archive_gzip_only_old_archive_plain_only_and_export(tmp_path):
    record, review = artifact_fixture(tmp_path / "build")
    root = tmp_path / "data"
    archive = Archive(root)
    row = archive.prepare(record, tmp_path / "build", review)
    asset = root / row["path"]
    manifest = verify_asset(asset)
    assert (asset / "sample.json.gz").is_file() and not (asset / "sample.json").exists()
    assert read_sample_bytes(asset) == (tmp_path / "build/sample.json").read_bytes()
    row["status"] = "provisional_pass"
    release = export(AssetStore([row]), root, "dataset-fixture", tmp_path / "release", True)
    assert verify_release(tmp_path / "release") == release
    index = json.loads((tmp_path / "release/asset_index.jsonl").read_text())
    assert index["paths"]["sample"].endswith("sample.json.gz")
    with tarfile.open(next((tmp_path / "release").glob("*.tar"))) as shard:
        packed = shard.extractfile(index["paths"]["sample"]).read()
    assert gzip.decompress(packed) == read_sample_bytes(asset)
    # Recreate the previous on-disk layout on an isolated fixture, never live data.
    (asset / "sample.json").write_bytes(gzip.decompress(packed))
    (asset / "sample.json.gz").unlink()
    manifest["files"] = [file_record(asset, "sample.json") if f["path"] == "sample.json.gz" else f
                         for f in manifest["files"]]
    (asset / "manifest.json").chmod(0o644)
    (asset / "manifest.json").write_bytes(json_bytes(manifest))
    assert verify_asset(asset) == manifest
    # Unlisted side files must not override the bytes signed by the old manifest.
    write_sample_bytes(asset, b"{}")
    assert verify_asset(asset) == manifest


def test_resume_old_partial_archive_drops_only_staged_redundant_files(tmp_path, monkeypatch):
    from voxlush.dataset import archive as module
    record, review = artifact_fixture(tmp_path / "build")
    archive = Archive(tmp_path / "data")
    rename = module.os.rename
    def interrupted(*args):
        raise OSError("rename interrupted")
    monkeypatch.setattr(module.os, "rename", interrupted)
    with pytest.raises(OSError, match="interrupted"):
        archive.prepare(record, tmp_path / "build", review)
    stage = next((tmp_path / "data/staging/fixture-one").iterdir())
    # Previous releases left these alongside the same deterministic commit.
    (stage / "sample.json").write_bytes((tmp_path / "build/sample.json").read_bytes())
    (stage / "previews/contact.webp").write_bytes(b"old optional derivative")
    monkeypatch.setattr(module.os, "rename", rename)
    row = archive.prepare(record, tmp_path / "build", review)
    final = tmp_path / "data" / row["path"]
    verify_asset(final)
    assert not (final / "sample.json").exists()
    assert not (final / "previews/contact.webp").exists()
    assert (tmp_path / "build/sample.json").is_file()


def test_compaction_preserves_ledger_archives_registered_paths_and_restart(tmp_path):
    root = tmp_path / "data"
    store = Store(root)
    try:
        store.create_campaign("storage", "Storage", 100, 200, 8, {"natural": 1})
        with store.transaction() as db:
            db.execute("UPDATE campaigns SET requests_used=7,cost_known=3,cost_unknown=2")
        before = store.campaign("storage")
        directory = root / "work/sample/v0001"
        record, review = artifact_fixture(directory)
        raw = (directory / "sample.json").read_bytes()
        row = Archive(root).prepare(record, directory, review)
        asset = root / row["path"]
        immutable = {p.relative_to(asset).as_posix():sha256(p) for p in asset.rglob("*") if p.is_file()}
        published = root / "work/published"
        published.mkdir()
        (published / "sample.json").write_bytes(raw)
        store.register_artifact(None, published / "sample.json", "sample.json", sha256(published / "sample.json"))
        assert compact_work(store)["eligible"] == 1
        assert (directory / "sample.json").exists()
        result = compact_work(store, apply=True)
        assert result["converted"] == 1 and result["skipped_registered"] == 1 and not result["errors"]
        assert store.campaign("storage") == before
        assert compact_work(store, apply=True)["converted"] == 0
        assert read_sample_bytes(directory) == raw
        assert (published / "sample.json").read_bytes() == raw
        assert immutable == {p.relative_to(asset).as_posix():sha256(p) for p in asset.rglob("*") if p.is_file()}
        backup(store, root, tmp_path / "backup")
    finally:
        store.close()
    restore_backup(tmp_path / "backup", tmp_path / "restored")
    restored = Store(tmp_path / "restored")
    try:
        assert restored.campaign("storage")["requests_used"] == 7
        assert restored.campaign("storage")["cost_unknown"] == 2
        assert read_sample_bytes(restored.root / "work/sample/v0001") == raw
        verify_asset(restored.root / row["path"])
    finally:
        restored.close()


def test_compaction_refuses_busy_or_running_production(tmp_path):
    store = Store(tmp_path)
    try:
        with pytest.raises(OwnerBusy):
            Store(tmp_path)
        store.create_campaign("s", "s", 1, 10, 1, {"natural": 1})
        store.set_campaign_state("s", "running")
        with pytest.raises(ValueError, match="pause/drain"):
            compact_work(store, apply=True)
    finally:
        store.close()


@pytest.mark.parametrize("interrupted", [False, True])
def test_compaction_recovers_interruption_but_preserves_conflicting_original(tmp_path, interrupted):
    store = Store(tmp_path)
    try:
        directory = tmp_path / "work/s"
        directory.mkdir(parents=True)
        original = b'{"complete": true}\n'
        (directory / "sample.json").write_bytes(original)
        write_sample_bytes(directory, original if interrupted else b"{}")
        result = compact_work(store, apply=True)
        assert result["converted"] == int(interrupted)
        if interrupted:
            assert read_sample_bytes(directory) == original
        else:
            assert len(result["errors"]) == 1
            assert (directory / "sample.json").read_bytes() == original
    finally:
        store.close()


def test_failed_write_keeps_original_work_file(tmp_path, monkeypatch):
    from voxlush.dataset import compact
    store = Store(tmp_path)
    try:
        directory = tmp_path / "work/s"
        directory.mkdir(parents=True)
        original = b'{"keep":true}'
        (directory / "sample.json").write_bytes(original)
        def fail(*args):
            raise OSError("write interrupted")
        monkeypatch.setattr(compact, "write_sample_bytes", fail)
        result = compact_work(store, apply=True)
        assert len(result["errors"]) == 1 and result["converted"] == 0
        assert (directory / "sample.json").read_bytes() == original
    finally:
        store.close()
