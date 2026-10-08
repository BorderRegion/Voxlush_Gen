"""Filesystem/export fault fixtures; these are not live visual qualification tests."""
from __future__ import annotations

import gzip
import json
import sqlite3
from pathlib import Path

import pytest
from PIL import Image

from voxlush.dataset import Archive, backup, export, import_legacy, restore_backup, verify_asset, verify_backup, verify_release
from voxlush.dataset.export import _find, _keys, _union
from voxlush.dataset.files import json_bytes, safe_path, sha256
from voxlush.pipeline.prompts import RUBRIC_HASH, RUBRIC_VERSION, parse_review
from voxlush.store.store import Store
from voxlush.voxel import sandbox
from voxlush.voxel.adapter import build, render
from voxlush.voxel.canonical import save


def artifact_fixture(directory: Path, sid: str = "fixture-one", offset: int = 0) -> tuple[dict, dict]:
    directory.mkdir(parents=True)
    component = {"id": "rock", "geometry": {"bbox": {"min": [offset, 0, 0], "max": [offset + 1, 1, 1]}, "voxel_count": 8}}
    sample = {"sample_id": sid, "components": [component], "blocks": [{"x": x + offset, "y": y, "z": z, "type": "minecraft:stone", "component_id": "rock"} for x in range(2) for y in range(2) for z in range(2)]}
    (directory / "sample.json").write_bytes(json_bytes(sample))
    (directory / "components.json").write_bytes(json_bytes({"schema_version": "voxlush.components.v1", "components": [component]}))
    hashes = save(directory, sample)
    (directory / "geometry.json").write_bytes(json_bytes({"passed": True, "violations": [], **hashes}))
    (directory / "authored_source.py").write_text("# Explicit filesystem test fixture, no production model output.\nP(0,0,0,'stone',component_id='rock')\n")
    (directory / "build.py").write_text("# File-boundary test fixture only\n")
    (directory / "previews").mkdir()
    for name in ("view_a.webp", "view_b.webp"):
        Image.new("RGB", (8, 8), (110, 105, 99)).save(directory / "previews" / name, "WEBP")
    review = {"status": "pass", "evidence_kind": "fixture_mock", "profile_qualified": False, "input_voxel_sha256": hashes["canonical_voxel_hash"], "image_sha256": [sha256(directory / "previews" / name) for name in ("view_a.webp", "view_b.webp")]}
    record = {"sample_id": sid, "revision": 1, "campaign_id": "dataset-fixture", "record_kind": "fixture", "task": {"sample_id": sid, "campaign_id": "dataset-fixture", "seed": 23, "instruction": "Explicit filesystem test fixture", "scene_type": "natural", "quality_contract": "landscape", "theme_seed_id": "rocks_01", "generation_mode": "direct"}}
    return record, review


class AssetStore:
    def __init__(self, rows):
        self.rows = rows

    def iter_assets(self, campaign_id, include_provisional=False):
        yield from self.rows


def test_fixture_archive_is_never_accepted_and_commit_recoverable(tmp_path):
    record, review = artifact_fixture(tmp_path / "build")
    archive = Archive(tmp_path / "data")
    committed = archive.prepare(record, tmp_path / "build", review)
    assert not committed["accepted_unique"]
    assert committed["manifest_json"]["lifecycle"] == "candidate"
    assert list(archive.pending_commits()) == [committed]
    assert archive.prepare(record, tmp_path / "build", review) == committed
    archive.acknowledge(committed["commit_id"])
    assert list(archive.pending_commits()) == []


def test_stale_review_and_immutable_revision_conflict(tmp_path):
    record, review = artifact_fixture(tmp_path / "build")
    archive = Archive(tmp_path / "data")
    stale = {**review, "input_voxel_sha256": "0" * 64}
    with pytest.raises(ValueError, match="stale"):
        archive.prepare(record, tmp_path / "build", stale)
    archive.prepare(record, tmp_path / "build", review)
    (tmp_path / "build" / "authored_source.py").write_text("# changed fixture source\n")
    with pytest.raises(ValueError, match="immutable"):
        archive.prepare(record, tmp_path / "build", review)


def test_production_mock_cannot_be_accepted(tmp_path):
    record, review = artifact_fixture(tmp_path / "build")
    record.update(record_kind="production", profile_qualified=True)
    review["profile_qualified"] = True
    asset = Archive(tmp_path / "data").prepare(record, tmp_path / "build", review)
    assert not asset["accepted_unique"]


def test_archive_requires_consistent_render_and_rubric_provenance(tmp_path):
    record, review = artifact_fixture(tmp_path / "build")
    (tmp_path / "build" / "render.json").write_bytes(json_bytes({"passed": True, "canonical_voxel_hash": "0" * 64}))
    with pytest.raises(ValueError, match="render evidence"):
        Archive(tmp_path / "data").prepare(record, tmp_path / "build", review)

    (tmp_path / "build" / "render.json").unlink()
    invalid_review = {**review, "rubric_version": RUBRIC_VERSION, "rubric_hash": "bad"}
    with pytest.raises(ValueError, match="rubric version/hash"):
        Archive(tmp_path / "data").prepare(record, tmp_path / "build", invalid_review)


def test_fixture_cannot_be_promoted_to_accepted_lifecycle(tmp_path):
    record, review = artifact_fixture(tmp_path / "build")
    asset = Archive(tmp_path / "data").prepare(record, tmp_path / "build", review)
    manifest_path = tmp_path / "data" / asset["path"] / "manifest.json"
    manifest_path.chmod(0o644)
    manifest = json.loads(manifest_path.read_text())
    manifest["lifecycle"] = "accepted"
    manifest["accepted_at"] = "2026-10-08T00:00:00+00:00"
    manifest_path.write_bytes(json_bytes(manifest))
    with pytest.raises(ValueError, match="acceptance-eligible"):
        verify_asset(manifest_path.parent)


def test_parse_review_records_rubric_identity():
    content = json.dumps({"verdict": "pass", "issues": [], "observed_tags": []})
    review = parse_review(content, "a" * 64, ["b" * 64, "c" * 64])
    assert review["rubric_version"] == RUBRIC_VERSION
    assert review["rubric_hash"] == RUBRIC_HASH


@pytest.mark.parametrize("name", ["../../outside", "/etc/passwd", "previews/../passwd", "..\\passwd"])
def test_artifact_path_traversal_is_rejected(tmp_path, name):
    with pytest.raises(ValueError):
        safe_path(tmp_path, name, must_exist=False)


def test_symlink_and_canonical_mirror_tampering(tmp_path):
    record, review = artifact_fixture(tmp_path / "build")
    archive = Archive(tmp_path / "data")
    (tmp_path / "build" / "sample.json.gz").write_bytes(gzip.compress(b"{}", mtime=0))
    with pytest.raises(ValueError, match="compressed sample"):
        archive.prepare(record, tmp_path / "build", review)
    link = tmp_path / "linked"
    link.symlink_to(tmp_path / "build", target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        archive.prepare(record, link, review)


def test_export_is_deterministic_and_fixture_split_excluded(tmp_path):
    record, review = artifact_fixture(tmp_path / "build")
    root = tmp_path / "data"
    asset = Archive(root).prepare(record, tmp_path / "build", review)
    asset["status"] = "provisional_pass"
    store = AssetStore([asset])
    first = export(store, root, "dataset-fixture", tmp_path / "release-a", include_provisional=True)
    second = export(store, root, "dataset-fixture", tmp_path / "release-b", include_provisional=True)
    assert first == second
    assert first["counts"]["accepted"] == 0
    assert first["counts"]["excluded"] == 1
    assert first["counts"]["repair_pairs"] == 0
    assert verify_release(tmp_path / "release-a") == first
    index = json.loads((tmp_path / "release-a" / "asset_index.jsonl").read_text())
    assert index["dimensions"] == [2, 2, 2]
    assert index["split"] == "excluded"
    assert export(store, root, "dataset-fixture", tmp_path / "empty-release")["counts"]["assets"] == 0


def test_source_and_geometry_and_lineage_groups_join(tmp_path):
    record, review = artifact_fixture(tmp_path / "build")
    manifest = Archive(tmp_path / "data").prepare(record, tmp_path / "build", review)["manifest_json"]
    other = json.loads(json.dumps(manifest))
    other["sample_id"] = "fixture-two"
    other["lineage"]["group_id"] = "different-label"
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE groups(token TEXT PRIMARY KEY,parent TEXT)")
    _union(connection, _keys(manifest, record["task"]))
    _union(connection, _keys(other, {**record["task"], "instruction": "A different explicit fixture brief"}))
    assert _find(connection, "sample:fixture-one") == _find(connection, "sample:fixture-two")
    connection.close()


def test_archive_integrity_detects_corrupt_bytes(tmp_path):
    record, review = artifact_fixture(tmp_path / "build")
    asset = Archive(tmp_path / "data").prepare(record, tmp_path / "build", review)
    path = tmp_path / "data" / asset["path"] / "authored_source.py"
    path.chmod(0o644)
    path.write_text("# corrupt\n")
    with pytest.raises(ValueError, match="integrity"):
        verify_asset(path.parent)


def test_backup_restore_uses_sqlite_snapshot_and_preserves_assets(tmp_path):
    record, review = artifact_fixture(tmp_path / "build")
    root = tmp_path / "data"
    asset = Archive(root).prepare(record, tmp_path / "build", review)
    database = sqlite3.connect(root / "runtime.db")
    database.execute("PRAGMA journal_mode=WAL")
    database.execute("CREATE TABLE test_counts(n INTEGER)")
    database.execute("INSERT INTO test_counts VALUES(1)")
    database.commit()

    class BackupStore:
        def backup_db(self, destination):
            target = sqlite3.connect(destination)
            try:
                database.backup(target)
            finally:
                target.close()

    backup(BackupStore(), root, tmp_path / "backup")
    verify_backup(tmp_path / "backup")
    restore_backup(tmp_path / "backup", tmp_path / "restored")
    verify_asset(tmp_path / "restored" / asset["path"])
    restored = sqlite3.connect(tmp_path / "restored" / "runtime.db")
    assert restored.execute("SELECT n FROM test_counts").fetchone()[0] == 1
    restored.close()
    database.close()
    with pytest.raises(ValueError, match="must not exist"):
        restore_backup(tmp_path / "backup", tmp_path / "restored")


def test_real_build_render_archive_export_backup_restore(tmp_path):
    try:
        sandbox.image_info()
    except sandbox.SandboxError as exc:
        pytest.skip("Real isolated runtime is not prepared: " + str(exc))

    root = tmp_path / "data"
    work = root / "work"
    build_dir = work / "fixture-build"
    source = """
O('islands','群岛','islands','landscape')
C('island_a','岩岛','rock island','rock',floor='ground',parent_id='islands')
B(10,17,10,13,10,17,'stone','island_a')
"""
    task = {
        "sample_id": "local-fixture",
        "task_id": "local-fixture",
        "campaign_id": "local-fixture-campaign",
        "theme_seed_id": "island_01",
        "theme_family_id": "islands",
        "seed": 41,
        "scene_type": "natural",
        "quality_contract": "landscape",
        "generation_mode": "direct",
        "instruction": "Build a small island fixture",
        "requested_tags": {"landform": "island"},
        "quality_requirements": {},
        "phase": "final",
        "lineage_group": "local-fixture",
    }
    report = build(source, task, build_dir)
    assert report["passed"] and report["acceptance_eligible"]
    rendered = render(build_dir)
    assert rendered["passed"]
    record, review = artifact_fixture(tmp_path / "evidence-fixture", "review-fixture")
    del record
    review = {
        "status": "pass",
        "evidence_kind": "fixture_mock",
        "profile_qualified": False,
        "input_voxel_sha256": report["canonical_voxel_hash"],
        "image_sha256": [sha256(build_dir / f"previews/view_{view}.webp") for view in ("a", "b")],
    }
    (work / "source.py").write_text(source)
    (root / "staging").mkdir(parents=True)
    (root / "staging" / "work-item.json").write_text("fixture staging evidence")

    archived = Archive(root).prepare(
        {"sample_id": task["sample_id"], "campaign_id": task["campaign_id"], "record_kind": "fixture", "task": task},
        build_dir,
        review,
    )
    assert archived["manifest_json"]["record_kind"] == "fixture"
    assert archived["manifest_json"]["lifecycle"] == "candidate"

    store = Store(root)
    try:
        store.create_campaign(task["campaign_id"], "Fixture campaign", 1, 1, 1, {"natural": 1})
        store.add_sample(task, source_path=str(work / "source.py"))
        store.set_campaign_state(task["campaign_id"], "running")
        with pytest.raises(ValueError, match="pause/drain"):
            backup(store, root, tmp_path / "active-backup")

        claim = store.claim(task["sample_id"], 1)
        assert claim
        store.finish(claim, stage="archive", changes={"build_path": str(build_dir)})
        claim = store.claim(task["sample_id"], 1)
        assert claim
        store.commit_asset(claim, archived)
        store.set_campaign_state(task["campaign_id"], "paused")

        release_path = root / "releases" / "local-fixture-release"
        release = export(store, root, task["campaign_id"], release_path, include_provisional=True)
        assert release["counts"]["accepted"] == 0
        assert release["counts"]["excluded"] == 1

        backup(store, root, tmp_path / "local-backup")
        verify_backup(tmp_path / "local-backup")
    finally:
        store.close()

    restored_root = tmp_path / "restored-local"
    restore_backup(tmp_path / "local-backup", restored_root)
    restored_asset = restored_root / archived["path"]
    assert verify_asset(restored_asset)["record_kind"] == "fixture"
    assert verify_release(restored_root / "releases" / "local-fixture-release")["counts"]["excluded"] == 1
    assert (restored_root / "work" / "source.py").read_text() == source
    assert (restored_root / "staging" / "work-item.json").read_text() == "fixture staging evidence"
    restored_store = Store(restored_root)
    try:
        restored_sample = restored_store.sample(task["sample_id"])
        assert restored_sample["source_path"] == str(restored_root / "work" / "source.py")
        assert restored_sample["build_path"] == str(restored_root / "work" / "fixture-build")
        assert restored_store.campaign(task["campaign_id"])["state"] == "paused"
    finally:
        restored_store.close()


def test_legacy_dry_run_then_double_import_remains_unverified(tmp_path):
    record, _ = artifact_fixture(tmp_path / "legacy" / "sample_01")
    sample_file = tmp_path / "legacy" / "sample_01" / "sample.json"
    sample = json.loads(sample_file.read_text())
    sample["grid"] = {"size": [256, 256, 256], "up": "+Y", "north": "-Z"}
    sample_file.write_bytes(json_bytes(sample))
    originals = sha256(sample_file)

    class LegacyStore:
        def __init__(self):
            self.records = {}

        def register_legacy(self, value):
            if value["sample_id"] in self.records:
                return False
            self.records[value["sample_id"]] = value
            return True

    store = LegacyStore()
    assert import_legacy(tmp_path / "legacy")["imported"] == 0
    first = import_legacy(tmp_path / "legacy", store, dry_run=False)
    second = import_legacy(tmp_path / "legacy", store, dry_run=False)
    assert first["imported"] == second["already_registered"] == 1
    assert second["accepted_added"] == 0
    assert next(iter(store.records.values()))["status"] == "legacy_complete_unverified"
    assert sha256(sample_file) == originals
