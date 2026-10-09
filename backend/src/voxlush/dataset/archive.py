"""Verified, immutable local assets with an explicit file/DB commit boundary."""
from __future__ import annotations

import hashlib
import gzip
import json
import os
import re
import shutil
from datetime import datetime, timezone
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Iterator

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from .files import file_record, fsync_directory, identifier, json_bytes, safe_path, sha256, write_atomic

REQUIRED = (
    "authored_source.py", "build.py", "sample.json", "voxels.npz", "palette.json",
    "components.json", "geometry.json", "previews/view_a.webp", "previews/view_b.webp",
)
COORDINATES = {"up": "Y", "north": "-Z", "south": "+Z", "east": "+X", "west": "-X"}
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


def _composition(task, sample, geometry, review):
    from voxlush.themes.composition import requested_mode, validate_observation
    from voxlush.voxel.composition import measure
    mode = requested_mode(task)
    if mode is None:
        return {'requested_mode':None,'observed':None,'meets_requested':None,
                'reason':'natural_contract' if task.get('scene_type') == 'natural' else 'legacy_unspecified'}
    actual, violations = measure(sample,task)
    if actual != geometry.get('evidence',{}).get('composition') or violations:
        raise ValueError('composition geometry missing, failed or inconsistent with saved voxels')
    visual = validate_observation(mode,review.get('context_assessment'))
    if visual != review.get('context_assessment') or visual['meets_requested'] is not True:
        raise ValueError('composition image evidence missing, failed or inconsistent')
    return {'requested_mode':mode, 'observed':{'geometry':actual,'visual':visual},
            'meets_requested':True,'geometry_ref':'geometry.json','visual_ref':'review.json'}


def _version_record(report: dict, prefix: str) -> str | None:
    version, digest = report.get(prefix + "_version"), report.get(prefix + "_hash")
    if not isinstance(version, str) or not version or not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        return None
    return f"{version}@sha256:{digest}"


def _evidence_versions(geometry: dict, rendering: dict, review: dict) -> dict[str, str | None]:
    rubric_version, rubric_hash = review.get("rubric_version"), review.get("rubric_hash")
    rubric = f"{rubric_version}@sha256:{rubric_hash}" if (
        isinstance(rubric_version, str) and rubric_version
        and isinstance(rubric_hash, str) and SHA256_RE.fullmatch(rubric_hash)
    ) else None
    return {
        "runtime": _version_record(geometry, "runtime"),
        "material_catalog": _version_record(geometry, "materials"),
        "geometry": _version_record(geometry, "validator"),
        "renderer": _version_record(rendering, "renderer"),
        "rubric": rubric,
    }


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema = json.loads(files("voxlush.dataset.resources").joinpath("asset_manifest.schema.json").read_text())
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _validate_manifest(manifest: dict) -> None:
    try:
        _validator().validate(manifest)
    except ValidationError as exc:
        raise ValueError(f"invalid asset manifest: {exc.message}") from exc


def _manifest_observed_tags(tags: list) -> list:
    """Adapt the visual rubric's free-form tags without rewriting review evidence.

    Also applies when a persisted review resumes at archive after a restart.
    Deterministic/human key-value observations already use the manifest contract.
    """
    return [
        {**tag, "key": "visual_tag", "value": tag["tag"]}
        if isinstance(tag, dict) and tag.get("source") == "visual_review"
        and "tag" in tag and "key" not in tag and "value" not in tag
        else tag
        for tag in tags
    ]


def verify_asset(directory: Path) -> dict:
    """Read hashes and evidence; a manifest alone never proves an accepted asset."""
    directory = Path(directory)
    manifest = json.loads(safe_path(directory, "manifest.json").read_text())
    if manifest.get("lifecycle") == "accepted" and manifest.get("record_kind") != "production":
        raise ValueError("accepted asset is not geometry acceptance-eligible")
    _validate_manifest(manifest)
    identifier(manifest["sample_id"])
    identifier(manifest["campaign_id"])
    names = set()
    for record in manifest["files"]:
        if record["path"] in names:
            raise ValueError("duplicate manifest artifact path")
        names.add(record["path"])
        actual = file_record(directory, record["path"], record["kind"])
        if actual != record:
            raise ValueError(f"artifact integrity mismatch: {record['path']}")
    if not set(REQUIRED).issubset(names) or not {"brief.json", "review.json"}.issubset(names):
        raise ValueError("missing mandatory manifest artifacts")
    from voxlush.voxel.canonical import canonical_voxel_hash, from_sample, load_and_validate
    canonical = load_and_validate(directory)
    voxel_hash = canonical["canonical_voxel_hash"]
    if voxel_hash != manifest["hashes"]["canonical_voxel_sha256"]:
        raise ValueError("canonical voxel hash mismatch")
    if canonical["annotation_hash"] != manifest["hashes"]["annotation_sha256"]:
        raise ValueError("canonical annotation hash mismatch")
    sample = json.loads((directory / "sample.json").read_text())
    coordinates, blocks, owners, palette = from_sample(sample)
    if canonical_voxel_hash(coordinates, blocks, palette) != voxel_hash:
        raise ValueError("legacy sample and canonical arrays disagree")
    if "sample.json.gz" in names:
        with gzip.open(directory / "sample.json.gz", "rt") as handle:
            if json.load(handle) != sample:
                raise ValueError("compressed sample and canonical sample disagree")
    if sha256(directory / "authored_source.py") != manifest["hashes"]["source_sha256"]:
        raise ValueError("authored source hash mismatch")
    geometry = json.loads((directory / "geometry.json").read_text())
    if not geometry.get("passed") or geometry.get("canonical_voxel_hash") != voxel_hash:
        raise ValueError("geometry evidence failed or refers to different voxels")
    rendering = json.loads((directory / "render.json").read_text()) if "render.json" in names else None
    if rendering is not None and (rendering.get("passed") is not True or rendering.get("canonical_voxel_hash") != voxel_hash):
        raise ValueError("render evidence failed or refers to different voxels")
    review = json.loads((directory / "review.json").read_text())
    visual = manifest["quality"]["visual"]
    image_hashes = [sha256(directory / name) for name in ("previews/view_a.webp", "previews/view_b.webp")]
    from PIL import Image
    for name in ("previews/view_a.webp", "previews/view_b.webp"):
        with Image.open(directory / name) as picture:
            picture.verify()
    if visual["input_voxel_sha256"] != voxel_hash or visual["image_sha256"] != image_hashes:
        raise ValueError("visual evidence is not bound to current artifacts")
    if review.get("input_voxel_sha256") != voxel_hash or review.get("image_sha256") != image_hashes:
        raise ValueError("review provenance mismatch")
    brief = json.loads((directory/'brief.json').read_text())
    if brief.get('composition_mode') is not None or 'composition' in manifest:
        if brief.get('composition_mode') is not None:
            from voxlush.voxel.canonical import annotation_hash
            if annotation_hash(coordinates,owners,palette,sample['components'],
                               {'generator_declared':sample.get('generator_claimed_tags',[])}) != canonical['annotation_hash']:
                raise ValueError('composition sample ownership differs from canonical annotations')
        if manifest.get('composition') != _composition(brief,sample,geometry,review):
            raise ValueError('composition manifest evidence mismatch')
    if manifest["lifecycle"] == "accepted":
        evidence_versions = _evidence_versions(geometry, rendering or {}, review)
        if geometry.get("acceptance_eligible") is not True:
            raise ValueError("accepted asset is not geometry acceptance-eligible")
        if rendering is None or rendering.get("passed") is not True or rendering.get("canonical_voxel_hash") != voxel_hash:
            raise ValueError("accepted asset lacks bound passing render evidence")
        if any(value is None for value in evidence_versions.values()) or manifest["versions"] != evidence_versions:
            raise ValueError("accepted asset lacks complete build, render, or rubric provenance")
        if review.get("evidence_kind") not in {"live_model", "human"} or not review.get("profile_qualified") or review.get("status") != "pass":
            raise ValueError("accepted asset lacks qualified independent visual evidence")
    return manifest


class Archive:
    def __init__(self, data_root: Path | str):
        self.root = Path(data_root).absolute()
        if self.root.is_symlink():
            raise ValueError("symlink data root")
        self.root.mkdir(parents=True, exist_ok=True)

    def prepare(self, sample: dict, build_dir: Path, review: dict) -> dict:
        runtime_task = sample.get("task", sample)
        task = runtime_task.get("task_contract", runtime_task)
        review = dict(review)
        if "status" not in review and review.get("passed") is True:
            review["status"] = "pass"
        sid = identifier(sample.get("sample_id", task.get("sample_id")))
        campaign_id = identifier(sample.get("campaign_id", task.get("campaign_id")))
        revision = int(sample.get("revision", 1))
        if not 1 <= revision <= 999999:
            raise ValueError("invalid asset revision")
        build_dir = Path(build_dir)
        for name in REQUIRED:
            file_record(build_dir, name)
        from voxlush.voxel.canonical import load_and_validate
        canonical = load_and_validate(build_dir)
        geometry = json.loads((build_dir / "geometry.json").read_text())
        if not geometry.get("passed") or geometry.get("canonical_voxel_hash") != canonical["canonical_voxel_hash"]:
            raise ValueError("geometry failed or inconsistent")
        rendering = json.loads((build_dir / "render.json").read_text()) if (build_dir / "render.json").is_file() else {}
        if rendering and (rendering.get("passed") is not True or rendering.get("canonical_voxel_hash") != canonical["canonical_voxel_hash"]):
            raise ValueError("render evidence failed or inconsistent")
        images = [sha256(build_dir / name) for name in ("previews/view_a.webp", "previews/view_b.webp")]
        if review.get("input_voxel_sha256") != canonical["canonical_voxel_hash"] or review.get("image_sha256") != images:
            raise ValueError("stale or fabricated review evidence")
        if review.get("status") != "pass":
            raise ValueError("visual review did not pass")
        composition = _composition(task,json.loads((build_dir/'sample.json').read_text()),geometry,review)
        kind = sample.get("record_kind", task.get("record_kind", "production"))
        if kind not in {"production", "calibration", "fixture"}:
            raise ValueError("example/unknown records cannot be archived")
        qualified = bool(sample.get("profile_qualified", False) and review.get("profile_qualified", False))
        unique = bool(sample.get("is_unique", True))
        report_versions = _evidence_versions(geometry, rendering, review)
        if bool(review.get("rubric_version")) != bool(review.get("rubric_hash")) or (review.get("rubric_hash") is not None and not SHA256_RE.fullmatch(str(review["rubric_hash"]))):
            raise ValueError("invalid rubric version/hash provenance")
        render_qualified = rendering.get("passed") is True and rendering.get("canonical_voxel_hash") == canonical["canonical_voxel_hash"]
        accepted = (
            kind == "production" and geometry.get("acceptance_eligible") is True
            and render_qualified and all(report_versions.values())
            and qualified and unique and review.get("status") == "pass"
            and review.get("evidence_kind") in {"live_model", "human"}
        )
        source_hash = sha256(build_dir / "authored_source.py")
        key = {"sample": sid, "revision": revision, "task": task, "source": source_hash, "voxel": canonical["canonical_voxel_hash"], "annotation": canonical["annotation_hash"], "review": review, "accepted": accepted}
        commit_id = hashlib.sha256(json_bytes(key)).hexdigest()
        rel = f"assets/{hashlib.sha256(sid.encode()).hexdigest()[:2]}/{sid}/v{revision:04d}"
        final = safe_path(self.root, rel, must_exist=False)
        journal = safe_path(self.root, f"commits/{commit_id}.json", must_exist=False)
        if final.exists():
            manifest = verify_asset(final)
            if manifest["archive"]["commit_id"] != commit_id:
                raise ValueError("immutable asset revision conflict")
            record = self._record(manifest, rel, final)
            write_atomic(journal, json_bytes(record))
            return record
        stage = safe_path(self.root, f"staging/{sid}/v{revision:04d}-{commit_id[:12]}", must_exist=False)
        stage.mkdir(parents=True, exist_ok=True)
        names = list(REQUIRED)
        for optional in ("previews/contact.webp", "sample.json.gz", "runtime.py", "runtime_contract.txt", "runtime_provenance.json", "render.json"):
            candidate = safe_path(build_dir, optional, must_exist=False)
            if candidate.is_file():
                names.append(optional)
        # Frozen runtime bundles are small trusted inputs, not arbitrary work-directory copies.
        runtime = safe_path(build_dir, "runtime", must_exist=False)
        if runtime.is_dir():
            for path in sorted(runtime.rglob("*")):
                if path.is_symlink():
                    raise ValueError("symlink runtime bundle")
                if path.is_file():
                    names.append(path.relative_to(build_dir).as_posix())
        for name in names:
            destination = safe_path(stage, name, must_exist=False)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(safe_path(build_dir, name), destination)
        write_atomic(stage / "brief.json", json_bytes(task))
        write_atomic(stage / "review.json", json_bytes(review))
        names.extend(["brief.json", "review.json"])
        for filename,key in (('dedup.json','dedup_features'),('runtime_config.json','runtime_config_snapshot')):
            if sample.get(key):
                write_atomic(stage/filename,json_bytes(sample[key]))
                names.append(filename)
        if sample.get("repair_pairs"):
            write_atomic(stage / "repair_pairs.json", json_bytes(sample["repair_pairs"]))
            names.append("repair_pairs.json")
        versions = dict(report_versions)
        for name, version in sample.get("versions", {}).items():
            versions.setdefault(name, version)
        manifest = {
            "schema_version": "voxlush.asset.v1", "record_kind": kind, "sample_id": sid,
            "task_id": task.get("task_id", sid), "campaign_id": campaign_id, "revision": revision,
            "theme_seed_id": task["theme_seed_id"], "scene_type": task["scene_type"], "quality_contract": task["quality_contract"],
            "composition":composition,
            "lifecycle": "accepted" if accepted else ("duplicate" if not unique else "candidate"),
            "accepted_at": (sample.get("accepted_at") or datetime.now(timezone.utc).isoformat()) if accepted else None,
            "grid": [256, 256, 256], "coordinate_system": COORDINATES,
            "hashes": {"source_sha256": source_hash, "canonical_voxel_sha256": canonical["canonical_voxel_hash"], "annotation_sha256": canonical["annotation_hash"]},
            "versions": {key: versions.get(key) for key in ("runtime", "material_catalog", "geometry", "renderer", "rubric")},
            "files": [file_record(stage, name) for name in sorted(names)],
            "tags": {"sampling_tags": task.get("sampling_tags", {}), "requested_tags": task.get("requested_tags", {}), "generator_declared": sample.get("generator_declared", {}), "observed_tags": _manifest_observed_tags(sample.get("observed_tags", []))},
            "quality": {"geometry": {"status": "pass", "report_ref": "geometry.json"}, "visual": {"status": "pass", "report_ref": "review.json", "input_voxel_sha256": canonical["canonical_voxel_hash"], "image_sha256": images}},
            "archive": {"state": "committed", "commit_id": commit_id},
            "provenance": {"seed": task["seed"], "generation_mode": runtime_task.get("generation_mode", "direct"), "endpoint_alias": sample.get("endpoint_alias"), "requested_model": sample.get("requested_model"), "reported_model": sample.get("reported_model"), "request_refs": sample.get("request_refs", [])},
            "usage": {"model_requests": 0, "input_tokens": None, "output_tokens": None, "reasoning_tokens": None, "cost_known": None, "cost_unknown_reserved": None, "currency": None, **sample.get("usage", {})},
            "lineage": {"group_id": sample.get("lineage_group", task.get("lineage_group", task.get("lineage_group_id", sid))), "parent_sample_id": sample.get("parent_sample_id"), "duplicate_cluster_id": sample.get("duplicate_cluster_id"), "is_unique": unique},
            "split": "calibration" if kind == "calibration" else None,
            "license": sample.get("license", {"status": "unknown", "identifier": None}),
        }
        _validate_manifest(manifest)
        write_atomic(stage / "manifest.json", json_bytes(manifest))
        verify_asset(stage)
        record = self._record(manifest, rel, stage)
        # Journal exists before rename, so restart checks only unsettled commits.
        write_atomic(journal, json_bytes(record))
        for path in stage.rglob("*"):
            if path.is_file():
                with path.open("rb") as handle:
                    os.fsync(handle.fileno())
        fsync_directory(stage)
        final.parent.mkdir(parents=True, exist_ok=True)
        os.rename(stage, final)
        fsync_directory(final.parent)
        for path in final.rglob("*"):
            if path.is_file():
                path.chmod(0o444)
        return record

    @staticmethod
    def _record(manifest: dict, relative: str, path: Path) -> dict:
        return {"sample_id": manifest["sample_id"], "campaign_id": manifest["campaign_id"], "revision": manifest["revision"], "path": relative, "manifest_json": manifest, "manifest_sha256": sha256(path / "manifest.json"), "canonical_voxel_hash": manifest["hashes"]["canonical_voxel_sha256"], "annotation_hash": manifest["hashes"]["annotation_sha256"], "accepted_unique": manifest["lifecycle"] == "accepted", "commit_id": manifest["archive"]["commit_id"], "lineage_group": manifest["lineage"]["group_id"],
                **({'dedup_features':json.loads((path/'dedup.json').read_text())} if (path/'dedup.json').exists() else {})}

    def pending_commits(self) -> Iterator[dict]:
        directory = safe_path(self.root, "commits", must_exist=False)
        if not directory.exists():
            return
        for journal in sorted(directory.glob("*.json")):
            if journal.is_symlink():
                raise ValueError("symlink commit journal")
            record = json.loads(journal.read_text())
            path = safe_path(self.root, record["path"], must_exist=False)
            if path.exists():
                manifest = verify_asset(path)
                if manifest["archive"]["commit_id"] != record["commit_id"] or sha256(path / "manifest.json") != record["manifest_sha256"]:
                    raise ValueError("commit journal mismatch")
                yield record

    def acknowledge(self, commit_id: str) -> None:
        if len(commit_id) != 64 or any(c not in "0123456789abcdef" for c in commit_id):
            raise ValueError("invalid commit id")
        journal = safe_path(self.root, f"commits/{commit_id}.json", must_exist=False)
        journal.unlink(missing_ok=True)
        if journal.parent.exists():
            fsync_directory(journal.parent)
