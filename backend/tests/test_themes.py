import json
from pathlib import Path

import pytest

from voxlush.themes.planner import CATALOG, FAMILIES, SEEDS, runtime_task, task_for


def test_catalog_contract_and_runtime_mapping():
    schema_path = Path(__file__).parents[2] / "schemas" / "task.schema.json"
    packaged_schema_path = Path(__file__).parents[1] / "src" / "voxlush" / "themes" / "task.schema.json"
    assert json.loads(schema_path.read_text()) == json.loads(packaged_schema_path.read_text())
    assert len(FAMILIES) == 32
    assert len(SEEDS) == 256

    family_sequence = {}
    seen = set()
    for spec in SEEDS:
        sequence = family_sequence.get(spec["family_id"], 0)
        family_sequence[spec["family_id"]] = sequence + 1
        contract = task_for({"campaign_id": f'theme-contract-{spec["id"]}'}, spec["family_id"], sequence, "fixture")
        runtime = runtime_task(contract)
        assert contract["theme_seed_id"] == spec["id"]
        assert contract["requested_tags"] == {"theme": spec["name_zh"]}
        assert isinstance(contract["requested_tags"], dict)
        assert contract["bounds"]["scale_class"] == spec["suggested_scale"]
        assert runtime["generation_mode"] == (
            "two_stage" if spec["suggested_scale"] in {"L", "XL"} else "direct"
        )
        assert runtime["task_contract"] == contract
        seen.add(contract["task_id"])

        if spec["quality_contract"] == "landscape":
            assert contract["scene_type"] == "natural"
            assert contract["interior_requirement"] == "not_required"

    assert len(seen) == len(SEEDS)


def test_task_for_rejects_unknown_family_and_record_kind():
    campaign = {"campaign_id": "theme-contract-test"}
    with pytest.raises(ValueError, match="unknown theme family"):
        task_for(campaign, "unknown-family", 0)

    family_id = CATALOG["families"][0]["id"]
    with pytest.raises(ValueError, match="invalid task record kind"):
        task_for(campaign, family_id, 0, "untrusted")
