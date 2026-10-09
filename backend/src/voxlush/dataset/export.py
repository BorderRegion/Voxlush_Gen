"""Streaming, deterministic training releases; derived metadata never writes Store."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tarfile
from pathlib import Path
from typing import Any

from .archive import verify_asset
from .files import fsync_directory, identifier, json_bytes, relative_path, safe_path, sha256, write_atomic
from voxlush.themes.composition import export_selection
from voxlush.themes.planner import apportion

EXPORT_SCHEMA = "voxlush.release.v1"


def grouped_split(group: str) -> str:
    value = int(hashlib.sha256(("voxlush.split.v1\0" + group).encode()).hexdigest()[:16], 16) % 10000
    return "train" if value < 9000 else "val" if value < 9500 else "test"


def _manifest(row: dict) -> dict:
    value = row["manifest_json"]
    return json.loads(value) if isinstance(value, str) else value


def _instruction(brief: dict) -> str:
    nested = brief.get("brief", {})
    parts = [nested.get("instruction"), nested.get("design_focus")]
    return "。".join(part for part in parts if part) or brief.get("instruction", "")


def _find(connection: sqlite3.Connection, token: str) -> str:
    """Disk-backed union/find keeps grouping bounded for 100k+ metadata rows."""
    connection.execute("INSERT OR IGNORE INTO groups(token,parent) VALUES (?,?)", (token, token))
    current = token
    while True:
        parent = connection.execute("SELECT parent FROM groups WHERE token=?", (current,)).fetchone()[0]
        if parent == current:
            break
        current = parent
    connection.execute("UPDATE groups SET parent=? WHERE token=?", (current, token))
    return current


def _union(connection: sqlite3.Connection, tokens: list[str]) -> None:
    roots = sorted({_find(connection, token) for token in tokens})
    for root in roots[1:]:
        connection.execute("UPDATE groups SET parent=? WHERE token=?", (roots[0], root))


def _keys(manifest: dict, brief: dict) -> list[str]:
    lineage = manifest["lineage"]
    tokens = ["sample:" + manifest["sample_id"], "lineage:" + lineage["group_id"]]
    if lineage.get("parent_sample_id"):
        tokens.append("sample:" + lineage["parent_sample_id"])
    if lineage.get("duplicate_cluster_id"):
        tokens.append("cluster:" + lineage["duplicate_cluster_id"])
    if lineage.get("near_duplicate_cluster"):
        tokens.append("near-cluster:" + lineage["near_duplicate_cluster"])
    for key in ("source_sha256", "canonical_voxel_sha256"):
        if manifest["hashes"].get(key):
            tokens.append(key + ":" + manifest["hashes"][key])
    # A/B tasks with the same actual brief remain together; theme alone is not a lineage.
    content = {"instruction": _instruction(brief), **{
        key: brief.get(key) for key in ("theme_seed_id", "quality_contract", "quality_requirements", "requested_tags")
    }}
    if content["instruction"]:
        tokens.append("brief:" + hashlib.sha256(json_bytes(content)).hexdigest())
    return tokens


def _tar_add(archive: tarfile.TarFile, source: Path, name: str) -> int:
    size = source.stat().st_size
    info = tarfile.TarInfo(name)
    info.size, info.mtime, info.uid, info.gid = size, 0, 0, 0
    info.uname, info.gname, info.mode = "", "", 0o444
    with source.open("rb") as handle:
        archive.addfile(info, handle)
    return size


def export(
    store: Any, data_root: Path | str, campaign_id: str, output: Path | str,
    include_provisional: bool = False, *, shard_asset_limit: int = 512,
    shard_byte_limit: int = 512 * 1024 * 1024,
    composition_modes=None, composition_weights=None, composition_count=None,
) -> dict:
    """Capture one read-only release. Retrying a finalized output returns that release."""
    identifier(campaign_id)
    selection = export_selection(composition_modes,composition_weights,composition_count)
    if not 1 <= shard_asset_limit <= 10000 or shard_byte_limit < 10240:
        raise ValueError("invalid shard limits")
    data_root, output = Path(data_root).absolute(), Path(output).absolute()
    if output.is_symlink() or output.parent.is_symlink():
        raise ValueError("symlink export output")
    if output.exists():
        result = verify_release(output)
        if result["campaign_id"] != campaign_id or result["include_provisional"] != include_provisional:
            raise ValueError("immutable release configuration conflict")
        if any(result.get(key) != value for key,value in selection.items()):
            raise ValueError('immutable release composition conflict')
        return result
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = output.with_name("." + output.name + ".staging")
    if stage.is_symlink():
        raise ValueError("symlink export staging")
    stage.mkdir(exist_ok=True)
    spool = sqlite3.connect(stage / "export_spool.sqlite")
    spool.execute("PRAGMA cache_size=-4096")
    spool.executescript("CREATE TABLE IF NOT EXISTS assets(sample_id TEXT,revision INTEGER,path TEXT,manifest TEXT,status TEXT,group_token TEXT, PRIMARY KEY(sample_id,revision)); CREATE TABLE IF NOT EXISTS groups(token TEXT PRIMARY KEY,parent TEXT NOT NULL); CREATE TABLE IF NOT EXISTS options(key TEXT PRIMARY KEY,value TEXT NOT NULL);")
    options = {"campaign_id": campaign_id, "include_provisional": include_provisional, "shard_asset_limit": shard_asset_limit, "shard_byte_limit": shard_byte_limit, **selection}
    previous = spool.execute("SELECT value FROM options WHERE key='config'").fetchone()
    if previous and {**export_selection(),**json.loads(previous[0])} != options:
        spool.close()
        raise ValueError("export resume configuration conflict")
    spool.execute("INSERT OR IGNORE INTO options VALUES ('config',?)", (json_bytes(options).decode(),))
    try:
        if not spool.execute("SELECT value FROM options WHERE key='snapshot_complete'").fetchone():
            for index, raw in enumerate(store.iter_assets(campaign_id, include_provisional)):
                row = dict(raw)
                manifest = _manifest(row)
                if manifest["record_kind"] == "example":
                    raise ValueError("example manifests cannot be training data")
                accepted = bool(row.get("accepted_unique"))
                if accepted != (manifest["lifecycle"] == "accepted"):
                    raise ValueError("Store/manifest acceptance mismatch")
                if not accepted and not include_provisional:
                    continue
                context = manifest.get('composition',{})
                selected_modes = composition_modes or ([m for m,w in selection['composition_weights'].items() if w>0] if composition_weights is not None else None)
                if selected_modes and (context.get('requested_mode') not in selected_modes or context.get('meets_requested') is not True):
                    continue
                asset = safe_path(data_root, row["path"])
                verified = verify_asset(asset)
                if verified != manifest:
                    raise ValueError("Store/asset manifest mismatch")
                brief = json.loads((asset / "brief.json").read_text())
                tokens = _keys(manifest, brief)
                _union(spool, tokens)
                values = (manifest["sample_id"], manifest["revision"], row["path"], json_bytes(manifest).decode(), row.get("status", manifest["lifecycle"]), tokens[0])
                old = spool.execute("SELECT path,manifest,status,group_token FROM assets WHERE sample_id=? AND revision=?", values[:2]).fetchone()
                if old and tuple(old) != values[2:]:
                    raise ValueError("asset changed while resuming immutable snapshot")
                spool.execute("INSERT OR IGNORE INTO assets VALUES (?,?,?,?,?,?)", values)
                if index % 128 == 0:
                    spool.commit()
            spool.execute("INSERT OR REPLACE INTO options VALUES ('snapshot_complete','true')")
            spool.commit()
        return _write_release(spool, stage, output, data_root, options)
    finally:
        spool.close()


def _write_release(spool: sqlite3.Connection, stage: Path, output: Path, root: Path, options: dict) -> dict:
    selected = '1'
    if options['composition_weights'] is not None:
        quotas = apportion(options['composition_count'],options['composition_weights'])
        spool.execute('CREATE TEMP TABLE selected(sample_id TEXT,revision INTEGER,PRIMARY KEY(sample_id,revision))')
        for mode,count in quotas.items():
            available = spool.execute("SELECT COUNT(*) FROM assets WHERE json_extract(manifest,'$.composition.requested_mode')=?",(mode,)).fetchone()[0]
            if available < count:
                raise ValueError(f'composition quota unavailable: {mode} requires {count}, verified available {available}; no substitution')
            spool.execute("INSERT INTO selected SELECT sample_id,revision FROM assets WHERE json_extract(manifest,'$.composition.requested_mode')=? ORDER BY sample_id,revision LIMIT ?",(mode,count))
        selected = '(sample_id,revision) IN (SELECT sample_id,revision FROM selected)'
    source_file, index_file, repairs_file = (stage / name for name in ("source_sft.jsonl", "asset_index.jsonl", "repair_pairs.jsonl"))
    counts = {"assets": 0, "accepted": 0, "provisional": 0, "source_sft": 0, "repair_pairs": 0, "train": 0, "val": 0, "test": 0, "calibration": 0, "excluded": 0}
    shards: list[dict] = []
    archive: tarfile.TarFile | None = None
    shard_count = shard_size = 0
    input_digest = hashlib.sha256()
    composition_counts = {}
    rows = spool.execute(f"SELECT sample_id,revision,path,manifest,status,group_token FROM assets WHERE {selected} ORDER BY sample_id,revision")
    try:
        with source_file.open("wb") as source_out, index_file.open("wb") as index_out, repairs_file.open("wb") as repair_out:
            for sid, revision, rel, encoded, status, token in rows:
                manifest = json.loads(encoded)
                asset = safe_path(root, rel)
                group = _find(spool, token)
                kind = manifest["record_kind"]
                accepted = manifest["lifecycle"] == "accepted"
                split = grouped_split(group) if accepted else ("calibration" if kind == "calibration" else "excluded")
                counts["assets"] += 1
                counts["accepted" if accepted else "provisional"] += 1
                counts[split] += 1
                mode = manifest.get('composition',{}).get('requested_mode') or 'unspecified_or_natural'
                composition_counts[mode] = composition_counts.get(mode,0)+1
                input_digest.update(json_bytes({"id": sid, "revision": revision, "manifest_sha256": sha256(asset / "manifest.json"), "group": group, "split": split}))
                brief = json.loads((asset / "brief.json").read_text())
                source = (asset / "authored_source.py").read_text()
                prefix = f"assets/{sid}/v{revision:04d}"
                paths = {item["kind"]: prefix + "/" + item["path"] for item in manifest["files"]}
                components = json.loads((asset / "components.json").read_text())["components"]
                boxes = [item["geometry"]["bbox"] for item in components]
                dimensions = [max(box["max"][axis] for box in boxes) - min(box["min"][axis] for box in boxes) + 1 for axis in range(3)]
                materials = json.loads((asset / "palette.json").read_text())["block_states"]
                instruction = _instruction(brief)
                record = {"schema_version": "voxlush.asset_index.v1", "sample_id": sid, "revision": revision, "record_kind": kind, "status": status, "accepted_unique": accepted, "instruction": instruction, "split": split, "lineage_group": group, "dimensions": dimensions, "occupied_voxels": sum(item["geometry"]["voxel_count"] for item in components), "block_states": materials, "paths": paths, "tags": manifest["tags"], "quality": manifest["quality"], "provenance": manifest["provenance"], "hashes": manifest["hashes"], "license": manifest["license"]}
                record['composition'] = manifest.get('composition')
                index_out.write(json_bytes(record))
                # Provisional/fixture sources are explicitly excluded or calibration; consumers filter split.
                sft = {"schema_version": "voxlush.source_sft.v1", "sample_id": sid, "revision": revision, "record_kind": kind, "accepted": accepted, "split": split, "lineage_group": group, "instruction": instruction, "constraints": {"grid": manifest["grid"], "coordinate_system": manifest["coordinate_system"], "quality_contract": manifest["quality_contract"], "quality_requirements": brief.get("quality_requirements", {}), "runtime_version": manifest["versions"]["runtime"], "runtime_contract_ref": paths.get("runtime_contract")}, "target": source}
                sft['constraints']['composition_mode'] = manifest.get('composition',{}).get('requested_mode')
                source_out.write(json_bytes(sft))
                counts["source_sft"] += 1
                repairs_path = asset / "repair_pairs.json"
                if repairs_path.exists():
                    for pair in json.loads(repairs_path.read_text()):
                        if pair.get("lineage_group") != manifest["lineage"]["group_id"] or pair.get("after_source") != source:
                            raise ValueError("repair pair source/lineage mismatch")
                        if pair.get("before_geometry", {}).get("passed") is not False or pair.get("after_geometry", {}).get("passed") is not True:
                            raise ValueError("repair pair lacks real before/after checks")
                        repair_out.write(json_bytes({"schema_version": "voxlush.repair_pair.v1", "sample_id": sid, "revision": revision, "split": split, "record_kind": kind, **pair,
                                                     'composition_mode':manifest.get('composition',{}).get('requested_mode')}))
                        counts["repair_pairs"] += 1
                asset_names = sorted({item["path"] for item in manifest["files"]} | {"manifest.json"})
                size = sum(safe_path(asset, name).stat().st_size for name in asset_names)
                if archive is None or shard_count >= options["shard_asset_limit"] or (shard_count and shard_size + size > options["shard_byte_limit"]):
                    if archive is not None:
                        archive.close()
                        shards[-1].update({"assets": shard_count, "content_bytes": shard_size})
                    name = f"shard-{len(shards):05d}.tar"
                    archive = tarfile.open(stage / name, "w", format=tarfile.PAX_FORMAT)
                    shards.append({"path": name, "assets": 0, "content_bytes": 0, "oversize_asset": False})
                    shard_count = shard_size = 0
                if size > options["shard_byte_limit"]:
                    shards[-1]["oversize_asset"] = True
                for name in asset_names:
                    shard_size += _tar_add(archive, safe_path(asset, name), prefix + "/" + name)
                shard_count += 1
            if archive is not None:
                archive.close()
                archive = None
                shards[-1].update({"assets": shard_count, "content_bytes": shard_size})
    finally:
        if archive is not None:
            archive.close()
    for shard in shards:
        shard.update({"sha256": sha256(stage / shard["path"]), "bytes": (stage / shard["path"]).stat().st_size})
    card = {"schema_version": "voxlush.dataset_card.v1", "counts": counts, "quality_method": "Canonical arrays, applicable geometry contract and evidence-bound independent visual review; production acceptance requires qualified model profile.", "split_method": "SHA256 90/5/5 grouped by lineage, duplicate cluster, source, exact geometry and same brief; calibration/fixtures excluded from blind splits.", "limitations": ["Repository license does not establish asset rights. Per-asset license status is preserved.", "Calibration/provisional/fixture rows never count as accepted; excluded/calibration splits must not be merged into train/val/test.", "Software and offline transport tests do not qualify a model profile."], "source": "Immutable Store snapshot and individually verified assets", "shards": shards}
    write_atomic(stage / "dataset_card.json", json_bytes(card))
    write_atomic(stage / "shard_index.json", json_bytes({"schema_version": "voxlush.shards.v1", "items": shards}))
    release = {"schema_version": EXPORT_SCHEMA, **options, "input_sha256": input_digest.hexdigest(), "counts": counts, "leakage_check": "pass", "files": [{"kind": name.split(".")[0], "path": name, "sha256": sha256(stage / name), "bytes": (stage / name).stat().st_size} for name in sorted(["source_sft.jsonl", "asset_index.jsonl", "repair_pairs.jsonl", "dataset_card.json", "shard_index.json"] + [item["path"] for item in shards])]}
    # Empty JSONL is meaningful when no verified repair pair/assets exists.
    release["files"] = [{"kind": record["kind"], "path": record["path"], "sha256": record["sha256"], "bytes": record["bytes"]} for record in release["files"]]
    release['composition_counts'] = composition_counts
    write_atomic(stage / "release_manifest.json", json_bytes(release))
    verify_release(stage)
    # Spool is an implementation detail, never part of the finalized release.
    spool.commit()
    spool.close()
    (stage / "export_spool.sqlite").unlink()
    for name in ("export_spool.sqlite-journal", "export_spool.sqlite-wal", "export_spool.sqlite-shm"):
        (stage / name).unlink(missing_ok=True)
    for path in stage.iterdir():
        if path.is_file():
            with path.open("rb") as handle:
                os.fsync(handle.fileno())
    fsync_directory(stage)
    os.rename(stage, output)
    fsync_directory(output.parent)
    return release


def verify_release(directory: Path | str) -> dict:
    directory = Path(directory)
    manifest = json.loads(safe_path(directory, "release_manifest.json").read_text())
    if manifest.get("schema_version") != EXPORT_SCHEMA:
        raise ValueError("unsupported release schema")
    paths = set()
    for item in manifest["files"]:
        if item["path"] in paths:
            raise ValueError("duplicate release file")
        paths.add(item["path"])
        path = safe_path(directory, item["path"])
        if path.stat().st_size != item["bytes"] or sha256(path) != item["sha256"]:
            raise ValueError("release file integrity mismatch")
    required = {"source_sft.jsonl", "asset_index.jsonl", "repair_pairs.jsonl", "dataset_card.json", "shard_index.json"}
    if not required.issubset(paths):
        raise ValueError("incomplete release")
    connection = sqlite3.connect("")
    connection.execute("PRAGMA cache_size=-4096")
    connection.execute("CREATE TABLE seen(group_id TEXT PRIMARY KEY,split TEXT)")
    counts = {"assets": 0, "accepted": 0, "provisional": 0, "train": 0, "val": 0, "test": 0, "calibration": 0, "excluded": 0}
    composition_counts = {}
    selection = export_selection(manifest.get('composition_modes'),manifest.get('composition_weights'),manifest.get('composition_count'))
    try:
        with (directory / "asset_index.jsonl").open() as handle:
            for line in handle:
                record = json.loads(line)
                group, split = record["lineage_group"], record["split"]
                if record["record_kind"] != "production" and split in {"train", "val", "test"} or not record["accepted_unique"] and split in {"train", "val", "test"}:
                    raise ValueError("unqualified record leaked into training splits")
                old = connection.execute("SELECT split FROM seen WHERE group_id=?", (group,)).fetchone()
                if old and old[0] != split and split in {"train", "val", "test"} and old[0] in {"train", "val", "test"}:
                    raise ValueError("lineage leakage across splits")
                connection.execute("INSERT OR IGNORE INTO seen VALUES (?,?)", (group, split))
                counts["assets"] += 1
                counts[split] += 1
                counts["accepted" if record["accepted_unique"] else "provisional"] += 1
                context = record.get('composition') or {}
                mode = context.get('requested_mode')
                key = mode or 'unspecified_or_natural'
                composition_counts[key] = composition_counts.get(key,0)+1
                if selection['composition_modes'] and (mode not in selection['composition_modes'] or context.get('meets_requested') is not True):
                    raise ValueError('release composition filter mismatch')
                if selection['composition_weights'] is not None and context.get('meets_requested') is not True:
                    raise ValueError('release mixed composition has unverified context')
        for key, value in counts.items():
            if manifest["counts"][key] != value:
                raise ValueError("release count mismatch")
        if 'composition_counts' in manifest and composition_counts != manifest['composition_counts']:
            raise ValueError('release composition count mismatch')
        if selection['composition_weights'] is not None:
            quotas = {k:v for k,v in apportion(selection['composition_count'],selection['composition_weights']).items() if v}
            if composition_counts != quotas:
                raise ValueError('release composition quota mismatch')
    finally:
        connection.close()
    shard_index = json.loads((directory / "shard_index.json").read_text())
    for shard in shard_index["items"]:
        if shard["path"] not in paths:
            raise ValueError("unregistered release shard")
        path = safe_path(directory, shard["path"])
        if path.stat().st_size != shard["bytes"] or sha256(path) != shard["sha256"]:
            raise ValueError("shard index integrity mismatch")
        with tarfile.open(path, "r|") as archive:
            for member in archive:
                relative_path(member.name)
                if not member.isfile() or not member.name.startswith("assets/"):
                    raise ValueError("unsafe shard member")
    return manifest
