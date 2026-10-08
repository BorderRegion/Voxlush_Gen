"""One versioned primitive, isolated execution and category-aware evidence contract."""

from __future__ import annotations

import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

import numpy as np

from . import canonical, sandbox
from .resources import legacy_quality, legacy_wooden
from .resources.legacy_render import COLORS

RESOURCES = Path(__file__).parent / "resources"
VERSION = "voxlush-geometry-v1"
MAX_SOURCE_BYTES = 256 * 1024
FROZEN_WOODEN = {
    "minimum_main_voxels": 12000,
    "minimum_footprint_bbox_area": 1800,
    "minimum_wood_fraction": 0.65,
    "minimum_rooms": 8,
    "minimum_roof_regions": 3,
    "minimum_window_instances": 16,
    "minimum_interior_wall_instances": 6,
    "minimum_components": 100,
}
CONTRACTS = {"inhabited", "exterior", "landscape", "ruin", "mixed", "legacy_large_wooden_v1"}
METADATA = {"MODEL_SPEC", "DESCRIPTION", "REQUESTED_TAGS", "ACTUAL_TAGS"}
INTERNAL_NAMES = {"SPEC", "ROOT", "V", "D", "A", "finish", "Path", "os", "json", "re"} | {
    node.name for node in ast.parse((RESOURCES / "builder_core.txt").read_text()).body
    if isinstance(node, ast.FunctionDef) and node.name.startswith('_')
}
PROTECTED = INTERNAL_NAMES | {"SEED", "C", "P", "B", "W", "G", "K", "O", "rng", "random"}
BANNED = {
    "open",
    "eval",
    "exec",
    "compile",
    "getattr",
    "setattr",
    "delattr",
    "globals",
    "locals",
    "vars",
    "dir",
    "input",
    "breakpoint",
    "help",
    "exit",
    "quit",
    "type",
    "object",
    "super",
    "memoryview",
}
OBJECT_HELPER = """
def O(oid, zh, en, kind='object'):
    if not isinstance(oid,str) or not oid or oid in SPEC['objects'] or oid in D or oid=='building_01':
        raise ValueError('Object IDs must be unique')
    SPEC['objects'][oid]={'id':oid,'name':en,'name_zh':zh,'kind':kind,'annotation_source':'generator_declared'}
    return oid
"""


def versions() -> dict:
    def digest(names):
        h = hashlib.sha256()
        for name in names:
            path = Path(__file__) if name == "adapter.py" else RESOURCES / name
            h.update(name.encode() + b"\0" + path.read_bytes())
        return h.hexdigest()

    return {
        "validator_version": VERSION,
        "validator_hash": digest(["adapter.py", "legacy_quality.py", "legacy_wooden.py"]),
        "runtime_version": "voxlush-primitives-v1",
        "runtime_hash": digest(["builder_core.txt"]),
        "renderer_version": "legacy-orthographic-webp-v1",
        "renderer_hash": digest(["legacy_render.py", "sandbox_worker.py"]),
        "materials_version": "legacy-colors-v1",
        "materials_hash": hashlib.sha256(canonical.json_bytes(COLORS)).hexdigest(),
    }


def primitive_contract() -> str:
    signatures = []
    tree = ast.parse((RESOURCES / "builder_core.txt").read_text() + OBJECT_HELPER)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in {"C", "P", "B", "W", "G", "K", "O"}:
            signatures.append(node.name + "(" + ast.unparse(node.args) + ")")
    return (
        """voxlush-primitives-v1. Write complete free-form Python geometry; no main guard or finish call.
Optional top-level literal MODEL_SPEC dict (name_en, name_zh, use, floors, spaces, features),
DESCRIPTION {zh,en}, ACTUAL_TAGS list. These are generator declarations, not observed labels.
floors is an integer: 0..256 for landscape, 1..256 for architectural contracts.
Allowed imports: math, random, collections. Maximum source size: 256 KiB UTF-8.
Ordinary local names including '_' and '_helper' are allowed.
Use the supplied SEED (read-only integer) and rng, e.g. height = rng.randint(6, 12).
Never reassign SEED/rng, reseed rng, overwrite primitives, or access private attributes/reflection.
X east, Y up, Z south; integer occupied coordinates 0..255; max 600000 voxels.
Materials accept full states such as minecraft:oak_log[axis=x]; namespace/properties are
preserved in authoritative arrays. Only known base blocks are accepted; unknown states fail.
Every occupied P/B must specify component_id; P/B with material None clears voxels.
C defines semantic ownership, never draws geometry; floor is mandatory, parent is an existing
object/component or building_01. Each separate door/window/column needs its own component ID.
Every C call, including natural terrain/rock, needs a non-None floor such as 'ground'.
Example: C('rock_a', '岩体', 'rock mass', 'rock', floor='ground'). MODEL_SPEC.floors=0 does not replace this.
O declares an object only; natural/multiple objects use C(...,parent_id=object_id).
B bounds are inclusive. W wall_id is the EXISTING owner of the real wall, cardinal axis,
plane/depth must cover actual wall thickness, opening width/height >=3 inclusive.
glazing=None gives an open door; entry is standing air at floor top+1 with two clear voxels.
Draw walls before W; later strokes must not refill apertures. G is a generic gable stroke,
K a hollow octagonal cone stroke; all positions and dimensions are chosen by your program.
spaces=[{id,kind:'enclosed'|'open_gallery'|'porch'|'terrace',air_bbox:{min:[x,y,z],max:[x,y,z]},
entry:[x,y,z],component_ids:[...]}] must describe actual walkable interiors, not invented boxes.
features=[{id,component_ids:[...]}] refer to actually occupied owners.
Signatures (extracted from the actual runtime):\n"""
        + "\n".join(signatures)
        + "\nRead-only runtime names (never assign, define, or use as function arguments): "
        + ", ".join(sorted(PROTECTED))
        + ". Runtime internals must not be accessed: " + ", ".join(sorted(INTERNAL_NAMES)) + "."
        + "\nMaterial names: "
        + ", ".join(sorted(COLORS))
        + "\nCategories: foundation,slab,exterior_wall,interior_wall,roof,door,window,column,beam,stair,decoration,environment,furniture,terrain,rock,cave,vegetation,water,path,ruin,object."
    )


def decode_source(source: str) -> tuple[dict, str]:
    if not isinstance(source, str) or len(source.encode()) > MAX_SOURCE_BYTES:
        raise ValueError("Source exceeds the 256 KiB authoring limit")
    source = source.strip()
    if source.startswith("```"):
        match = re.fullmatch(r"```(?:python)?\s*\n([\s\S]*)\n```", source)
        if not match:
            raise ValueError("Response must contain one complete Python program")
        source = match[1]
    tree = ast.parse(source)
    metadata = {}
    body = []
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in METADATA
        ):
            key = node.targets[0].id
            if key in metadata:
                raise ValueError("Repeated metadata literal: " + key)
            metadata[key] = ast.literal_eval(node.value)
        else:
            body.append(node)
    tree.body = body
    for node in ast.walk(tree):
        if isinstance(node, (ast.Global, ast.Nonlocal, ast.ClassDef, ast.Delete)):
            raise ValueError("Global mutation, class introspection and deletion are unsupported")
        if isinstance(node, ast.Import):
            if any(
                a.name not in {"math", "random", "collections"} or (a.asname and a.asname in PROTECTED)
                for a in node.names
            ):
                raise ValueError("Only math/random/collections imports are allowed")
        if isinstance(node, ast.ImportFrom):
            if (
                node.level
                or node.module not in {"math", "random", "collections"}
                or any(
                    a.name.startswith("_") or a.name == "*" or (a.asname or a.name) in PROTECTED
                    for a in node.names
                )
            ):
                raise ValueError("Private, wildcard and external imports are unsupported")
        if isinstance(node, ast.Attribute) and (
            node.attr.startswith("_")
            or node.attr
            in {
                "gi_frame",
                "gi_code",
                "cr_frame",
                "cr_code",
                "ag_frame",
                "ag_code",
                "f_globals",
                "f_locals",
                "f_builtins",
                "f_back",
                "f_code",
                "tb_frame",
                "tb_next",
            }
            or node.attr.startswith("co_")
        ):
            raise ValueError("Private/frame introspection is unsupported")
        if isinstance(node, ast.Name):
            if (
                node.id.startswith("__")
                or node.id in BANNED
                or node.id in INTERNAL_NAMES | METADATA
            ):
                raise ValueError("Reserved or unsafe author name: " + node.id)
            if isinstance(node.ctx, (ast.Store, ast.Del)) and node.id in PROTECTED:
                raise ValueError("Cannot replace primitive state: " + node.id)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
            node.name in PROTECTED or node.name.startswith("__")
        ):
            raise ValueError("Cannot replace primitives")
        if isinstance(node, ast.arg) and (node.arg in PROTECTED or node.arg.startswith("__")):
            raise ValueError("Reserved function argument")
        # Binding forms without ast.Name(Store), plus mutation of exposed state.
        bindings = []
        if isinstance(node, ast.alias):
            bindings = [node.asname or node.name]
            if node.name == 'random' and node.asname in (None, 'random'):
                bindings = []  # The allowed module import is not a replacement.
        elif isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)):
            bindings = [node.name] if node.name else []
        elif isinstance(node, ast.MatchMapping) and node.rest:
            bindings = [node.rest]
        if any(name in PROTECTED or name.startswith('__') for name in bindings):
            raise ValueError('Cannot replace primitive state')
        module_seed = isinstance(node,ast.Attribute) and node.attr == 'seed' and isinstance(node.value,ast.Name) and node.value.id == 'random'
        if isinstance(node, ast.Attribute) and (isinstance(node.ctx,ast.Store) or
                (node.attr in {'seed','setstate'} and not module_seed)):
            raise ValueError('Cannot mutate runtime attributes or random seed')
    for name in ("MODEL_SPEC", "DESCRIPTION"):
        if name in metadata and not isinstance(metadata[name], dict):
            raise ValueError(name + " must be a literal object")
    for name in ("REQUESTED_TAGS", "ACTUAL_TAGS"):
        if name in metadata and (
            not isinstance(metadata[name], list) or any(not isinstance(t, str) for t in metadata[name])
        ):
            raise ValueError(name + " must be a literal string list")
    return metadata, ast.unparse(tree)


def validate_model(model: dict, contract: str | None = None) -> None:
    """Bound model-declared geometry before the trusted host validator traverses it."""
    if not isinstance(model, dict):
        raise ValueError("MODEL_SPEC must be an object")
    for name in ("name_en", "name_zh", "use", "style"):
        if name in model and (not isinstance(model[name], str) or len(model[name]) > 8192):
            raise ValueError("Invalid text metadata: " + name)
    minimum_floors = 0 if contract == "landscape" else 1
    if "floors" in model and (type(model["floors"]) is not int or not minimum_floors <= model["floors"] <= 256):
        raise ValueError(f"floors must be an integer in {minimum_floors}..256")
    for key, limit in (("spaces", 256), ("features", 1024)):
        values = model.get(key, [])
        if not isinstance(values, list) or len(values) > limit:
            raise ValueError(key + " exceeds the metadata budget")
        seen = set()
        for item in values:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("id"), str)
                or not item["id"]
                or item["id"] in seen
            ):
                raise ValueError("Invalid or repeated " + key + " ID")
            seen.add(item["id"])
            members = item.get("component_ids", [])
            if not isinstance(members, list) or any(not isinstance(cid, str) for cid in members):
                raise ValueError("Invalid component references in " + key)
            if key == "spaces":
                box = item.get("air_bbox", {})
                low, high, entry = box.get("min", []), box.get("max", []), item.get("entry", [])
                if any(
                    not isinstance(vector, list)
                    or len(vector) != 3
                    or any(type(value) is not int or not 0 <= value < 256 for value in vector)
                    for vector in (low, high, entry)
                ) or any(high[i] < low[i] for i in range(3)):
                    raise ValueError("Space boxes and standing entries must stay inside the integer grid")


def inspect(sample: dict, task: dict) -> dict:
    contract = task.get("quality_contract", "inhabited")
    if contract not in CONTRACTS:
        raise ValueError("Unknown quality contract: " + str(contract))
    phase = task.get("phase", "final")
    violations = []
    warnings = []
    evidence = {}
    try:
        validate_model(sample["task_spec"], contract)
        coords, bi, ci, palette = canonical.from_sample(sample)
    except (ValueError, KeyError, TypeError) as exc:
        return {
            "passed": False,
            "violations": [{"rule": "invalid_canonical_geometry", "detail": str(exc)}],
            "contract": contract,
            "phase": phase,
            **versions(),
        }
    components = sample.get("components", [])
    ids = [c.get("id") for c in components]
    owners = Counter(b["component_id"] for b in sample["blocks"])
    grouped = {}
    for block in sample["blocks"]:
        grouped.setdefault(block["component_id"], []).append(block)
    cs = {c["id"]: c for c in components}
    object_ids = {o["id"] for o in sample.get("objects", [])}
    allowed_parents = {"building_01", *cs, *object_ids}
    if len(ids) != len(set(ids)):
        violations.append({"rule": "duplicate_component_id"})
    if set(owners) != set(ids):
        violations.append({"rule": "invalid_material_or_owner"})
    for c in components:
        owned_blocks = grouped.get(c["id"], [])
        points = np.array([[b[k] for k in ("x", "y", "z")] for b in owned_blocks])
        if not len(points):
            violations.append({"rule": "empty_component", "component_id": c["id"]})
            continue
        bbox = {"min": points.min(axis=0).tolist(), "max": points.max(axis=0).tolist()}
        if (
            c.get("geometry", {}).get("voxel_count") != len(points)
            or c["geometry"].get("bbox") != bbox
            or c.get("materials") != sorted({b["type"] for b in owned_blocks})
        ):
            violations.append({"rule": "component_statistics_mismatch", "component_id": c["id"]})
        if c.get("parent_id") not in allowed_parents or c.get("parent_id") == c["id"]:
            violations.append({"rule": "invalid_component_parent", "component_id": c["id"]})
        ancestor = c.get("parent_id")
        visited = {c["id"]}
        while ancestor in cs:
            if ancestor in visited:
                violations.append({"rule": "cyclic_component_parent", "component_id": c["id"]})
                break
            visited.add(ancestor)
            ancestor = cs[ancestor].get("parent_id")
    if any(b["type"] not in COLORS for b in sample["blocks"]):
        violations.append({"rule": "material_not_allowlisted"})
    if not violations:
        if contract in {"inhabited", "legacy_large_wooden_v1"}:
            architectural = legacy_quality.inspect(sample, legacy=False)
            violations += architectural["violations"]
            warnings += architectural.get("warnings", [])
            evidence["architecture"] = architectural.get("evidence", {})
        else:
            # Retain real ownership, aperture, room/headroom and feature checks. Natural/ruined
            # contexts permit islands and absence of constructed slabs; never call legacy=True.
            architectural = legacy_quality.inspect(sample, legacy=False)
            applicable = [
                v
                for v in architectural["violations"]
                if v["rule"]
                not in {"missing_floor_semantics", "disconnected_geometry", "foundation_dominates"}
            ]
            violations += applicable
            warnings += architectural.get("warnings", [])
            evidence["category_geometry"] = architectural.get("evidence", {})
    req = dict(task.get("quality_requirements") or {})
    if contract == "legacy_large_wooden_v1" and not any(
        v["rule"] == "invalid_material_or_owner" for v in violations
    ):
        req = {**req, **{key: max(value, req.get(key, value)) for key, value in FROZEN_WOODEN.items()}}
        wooden, metrics = legacy_wooden.inspect(sample, {"quality_requirements": req})
        if phase == "skeleton":
            decorative = {
                "meaningful_components",
                "interior_partitions",
                "meaningful_roof_regions",
                "real_glazed_window_instances",
            }
            wooden = [v for v in wooden if v["rule"] not in decorative]
        violations += wooden
        evidence["wooden"] = metrics
    space_ids = {s.get("id") for s in sample["task_spec"].get("spaces", [])}
    feature_ids = {s.get("id") for s in sample["task_spec"].get("features", [])}
    for key, available in [
        ("required_space_ids", space_ids),
        ("required_feature_ids", feature_ids),
        ("required_component_ids", set(ids)),
    ]:
        missing = sorted(set(req.get(key, [])) - available)
        if missing:
            violations.append({"rule": key + "_missing", "missing_ids": missing})
    for key, actual in [
        ("minimum_voxels", len(coords)),
        ("minimum_components", len(components)),
        ("minimum_rooms", len(space_ids)),
    ]:
        if key in req and actual < req[key] and not (phase == "skeleton" and key == "minimum_components"):
            violations.append({"rule": key, "actual": actual, "required": req[key]})
    evidence.update(
        voxels=len(coords),
        components=len(components),
        dimensions=(coords.max(axis=0) - coords.min(axis=0) + 1).tolist(),
        categories=dict(Counter(c["category"] for c in components)),
        semantic_source="generator_declared",
        independently_verified=False,
    )
    return {
        "passed": not violations,
        "violations": violations,
        "violation_count": len(violations),
        "warnings": warnings,
        "evidence": evidence,
        "contract": contract,
        "phase": phase,
        "acceptance_eligible": phase == "final" and not violations,
        "effective_requirements": req,
        **versions(),
    }


def build(source: str, task: dict, destination: Path, config: dict | None = None) -> dict:
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    if any((destination / name).exists() for name in ("sample.json", "voxels.npz", "geometry.json")):
        raise ValueError("Build destination must be a fresh revision")
    (destination / "authored_source.py").write_text(source, encoding="utf-8")
    try:
        metadata, body = decode_source(source)
        model = metadata.get("MODEL_SPEC", {})
        validate_model(model, task.get("quality_contract"))
        spec = {
            "name_en": "Authored voxel scene",
            "name_zh": "独立体素场景",
            "use": task.get("instruction", ""),
            "style": "",
            "floors": 0 if task.get("quality_contract") == "landscape" else 1,
            "spaces": [],
            "features": [],
            "objects": {},
            "allowed_accessories": [],
            **model,
            "sample_id": task["sample_id"],
            "seed": int(task["seed"]),
            "grid": [256, 256, 256],
            "dataset_collection": "Voxlush_Gen",
            "asset_type": task.get("scene_type", "architecture"),
            "allowlisted_block_types": sorted(COLORS),
            "generation": {"explicit_component_ids": True},
        }
        if not isinstance(spec["objects"], dict) or spec["objects"]:
            raise ValueError("Use O for object declarations; MODEL_SPEC.objects must be empty")
        combined = (
            "SPEC=" + repr(spec) + "\nDESCRIPTION=" + repr(metadata.get("DESCRIPTION", {"zh": "", "en": ""}))
        )
        combined += (
            "\nREQUESTED_TAGS="
            + repr(task.get("requested_tags", []))
            + "\nACTUAL_TAGS="
            + repr(metadata.get("ACTUAL_TAGS", []))
            + "\n"
        )
        combined += (
            (RESOURCES / "builder_core.txt").read_text() + OBJECT_HELPER + "\n" + body + "\nfinish()\n"
        )
        (destination / "build.py").write_text(combined, encoding="utf-8")
        artifacts, execution = sandbox.run(combined.encode(), config=config, seed=spec["seed"])
        if "sample.json" not in artifacts:
            raise sandbox.SandboxError("sandbox_missing_sample")
        sample = json.loads(artifacts["sample.json"])
        for name, content in artifacts.items():
            if name != "probe.json":
                (destination / name).write_bytes(content)
        annotations = {
            "schema_version": "voxlush.components.v1",
            "components": sample["components"],
            "objects": sample.get("objects", []),
            "generator_claimed_tags": sample.get("generator_claimed_tags", []),
        }
        (destination / "components.json").write_bytes(canonical.json_bytes(annotations) + b"\n")
        hashes = canonical.save(destination, sample)
        report = inspect(sample, task)
        report.update(hashes)
        report["execution"] = execution
        report["source_hash"] = hashlib.sha256(source.encode()).hexdigest()
        report["build_hash"] = canonical.hash_file(destination / "build.py")
    except (ValueError, TypeError, KeyError, SyntaxError, sandbox.SandboxError) as exc:
        report = {
            "passed": False,
            "acceptance_eligible": False,
            "contract": task.get("quality_contract"),
            "phase": task.get("phase", "final"),
            "violations": [{"rule": getattr(exc, "reason", "source_or_build_invalid"), "detail": str(exc)}],
            **versions(),
        }
    (destination / "geometry.json").write_bytes(canonical.json_bytes(report) + b"\n")
    return report


def render(destination: Path, config: dict | None = None) -> dict:
    destination = Path(destination)
    identity = canonical.load_and_validate(destination)
    sample = json.loads((destination / "sample.json").read_text())
    for block in sample["blocks"]:
        state = canonical.normalize_block_state(block.get("block_state", block["type"]))
        if block["type"] not in COLORS or state.split("[", 1)[0] != "minecraft:" + block["type"]:
            raise ValueError("Unsupported render block state; no material substitution is allowed")
    coords, bi, _, palette = canonical.from_sample(sample)
    if canonical.canonical_voxel_hash(coords, bi, palette) != identity["canonical_voxel_hash"]:
        raise ValueError("Render input differs from authoritative voxel arrays")
    artifacts, execution = sandbox.run(
        (destination / "sample.json").read_bytes(), mode="render", config=config, seed=sample["seed"]
    )
    names = ("previews/view_a.webp", "previews/view_b.webp", "previews/contact.webp")
    if set(artifacts) != set(names):
        raise sandbox.SandboxError("render_missing_artifacts")
    (destination / "previews").mkdir(exist_ok=True)
    for name, content in artifacts.items():
        (destination / name).write_bytes(content)
    report = {
        "passed": True,
        "source": "saved_authoritative_voxels",
        "canonical_voxel_hash": identity["canonical_voxel_hash"],
        "image_hashes": {name: canonical.hash_file(destination / name) for name in names},
        "execution": execution,
        **versions(),
    }
    (destination / "render.json").write_bytes(canonical.json_bytes(report) + b"\n")
    return report


def doctor(config: dict | None = None) -> dict:
    probe = """import json,os,socket
from pathlib import Path
result={'uid':os.getuid(),'network_unreachable':False,'root_readonly':False,'input_readonly':False}
try:
    socket.create_connection(('1.1.1.1',443),timeout=.3)
except OSError:
    result['network_unreachable']=True
try:
    Path('/root_probe').write_text('x')
except OSError:
    result['root_readonly']=True
try:
    Path('/input/modified').write_text('x')
except OSError:
    result['input_readonly']=True
Path('/output/probe.json').write_text(json.dumps(result))
"""
    try:
        artifacts, evidence = sandbox.run(probe.encode(), mode="probe", config=config)
        checks = json.loads(artifacts["probe.json"])
        return {
            "ready": checks
            == {"uid": 10001, "network_unreachable": True, "root_readonly": True, "input_readonly": True},
            "checks": checks,
            "evidence": evidence,
            **versions(),
        }
    except sandbox.SandboxError as exc:
        return {"ready": False, "reason_code": exc.reason, "detail": exc.detail, **versions()}
