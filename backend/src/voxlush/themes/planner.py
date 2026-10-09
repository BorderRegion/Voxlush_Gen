"""Deficit quotas select creative briefs, never geometry templates."""
import hashlib
import json
import math
from importlib.resources import files

from jsonschema import Draft202012Validator
from voxlush.themes.composition import MODES, requested_mode, scene_weights

CATALOG = json.loads(files("voxlush.themes").joinpath("catalog.json").read_text())
FAMILIES = {f["id"]: f for f in CATALOG["families"]}
SEEDS = CATALOG["seeds"]
TASK_SCHEMA = json.loads(files("voxlush.themes").joinpath("task.schema.json").read_text())
TASK_VALIDATOR = Draft202012Validator(TASK_SCHEMA)

def apportion(total: int, weights: dict) -> dict:
    positive = {k: max(0, v) for k, v in weights.items()}
    denominator = sum(positive.values())
    if not denominator:
        raise ValueError("scene weights must contain positive mass")
    quotas = {k: total * v / denominator for k, v in positive.items()}
    result = {k: math.floor(v) for k, v in quotas.items()}
    for k in sorted(quotas, key=lambda k: (-(quotas[k] - result[k]), k))[:total - sum(result.values())]:
        result[k] += 1
    return result

def family_targets(target: int, scene_weights: dict) -> dict:
    result = {}
    for scene, count in apportion(target, scene_weights).items():
        members = {k: 1 for k, f in FAMILIES.items() if f["scene_type"] == scene}
        result.update(apportion(count, members))
    return result

def task_for(campaign: dict, family_id: str, sequence: int, record_kind="calibration", seed_id=None,
             composition_mode=None) -> dict:
    scene = FAMILIES.get(family_id, {}).get('scene_type')
    if composition_mode is None and scene != 'natural' and campaign.get('composition_weights'):
        weights = scene_weights(campaign['composition_weights'], scene)
        composition_mode = max(weights, key=weights.get)
    seeds = [s for s in SEEDS if s["family_id"] == family_id
             and (composition_mode is None or composition_mode in s.get('composition_modes', MODES))]
    if not seeds:
        raise ValueError(f"unknown theme family: {family_id}")
    if record_kind not in {"production", "calibration", "fixture", "example"}:
        raise ValueError(f"invalid task record kind: {record_kind}")
    spec = next((s for s in seeds if s['id'] == seed_id), None) if seed_id else seeds[sequence % len(seeds)]
    if spec is None:
        raise ValueError('theme seed is incompatible with requested composition mode')
    sid = hashlib.sha256(f'{campaign["campaign_id"]}:{sequence}'.encode()).hexdigest()[:24]
    task = {
        "schema_version": "voxlush.task.v1",
        "record_kind": record_kind,
        "task_id": sid,
        "campaign_id": campaign["campaign_id"],
        "theme_seed_id": spec["id"],
        "scene_type": spec["scene_type"],
        "composition_mode": composition_mode,
        "quality_contract": spec["quality_contract"],
        "seed": sequence,
        "brief": {
            "language": "zh-CN",
            "instruction": spec["name_zh"],
            "design_focus": spec["design_focus"],
        },
        "bounds": {"grid": [256, 256, 256], "scale_class": spec["suggested_scale"]},
        "interior_requirement": (
            "usable_declared_spaces" if spec["quality_contract"] in {"inhabited", "legacy_large_wooden_v1"}
            else "not_required" if spec["quality_contract"] == "landscape"
            else "scoped_by_object"
        ),
        "requested_tags": {"theme": spec["name_zh"]},
        "sampling_tags": {"family_id": family_id, "scale_class": spec["suggested_scale"]},
        "lineage_group_id": sid,
    }
    requested_mode(task)
    errors = sorted(TASK_VALIDATOR.iter_errors(task), key=lambda error: list(error.path))
    if errors:
        raise ValueError(f"planner produced invalid task: {errors[0].message}")
    return task


def runtime_task(task: dict) -> dict:
    """Adapt a validated v1 task contract to the runtime fields used by the pipeline."""
    errors = sorted(TASK_VALIDATOR.iter_errors(task), key=lambda error: list(error.path))
    if errors:
        raise ValueError(f"invalid v1 task: {errors[0].message}")
    brief = task["brief"]
    scale = task["bounds"]["scale_class"]
    generation_mode = "two_stage" if scale in {"L", "XL"} else "direct"
    return {
        "schema_version": task["schema_version"],
        "sample_id": task["task_id"],
        "task_id": task["task_id"],
        "campaign_id": task["campaign_id"],
        "theme_seed_id": task["theme_seed_id"],
        "theme_family_id": task["sampling_tags"]["family_id"],
        "seed": task["seed"],
        "scene_type": task["scene_type"],
        "composition_mode": requested_mode(task),
        "quality_contract": task["quality_contract"],
        "generation_mode": generation_mode,
        "instruction": f'{brief["instruction"]}。{brief["design_focus"]}',
        "brief": brief,
        "bounds": task["bounds"],
        "interior_requirement": task["interior_requirement"],
        "requested_tags": task["requested_tags"],
        "sampling_tags": task["sampling_tags"],
        "quality_requirements": {},
        "phase": "skeleton" if generation_mode == "two_stage" else "final",
        "record_kind": task["record_kind"],
        "lineage_group": task.get("lineage_group_id", task["task_id"]),
        "task_contract": task,
    }
