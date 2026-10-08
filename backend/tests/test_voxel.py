"""Real local builds and hashes; no model responses or paid network calls."""

import gzip
import io
import json
import os
import tarfile
import zipfile

import numpy as np
import pytest

from voxlush.voxel import canonical, sandbox
from voxlush.voxel.adapter import (
    FROZEN_WOODEN,
    build,
    decode_source,
    doctor,
    inspect,
    primitive_contract,
    render,
)

HOUSE = """
MODEL_SPEC={'name_en':'Local geometric fixture','name_zh':'本地几何样例','spaces':[{'id':'room_01','air_bbox':{'min':[11,11,11],'max':[23,16,23]},'entry':[17,11,24],'component_ids':['floor']} ]}
C('floor','楼板','floor','slab',floor='ground')
B(10,24,10,10,10,24,'oak_planks','floor')
for cid,side,x0,x1,z0,z1 in [('north','north',10,24,10,10),('south','south',10,24,24,24),('west','west',10,10,11,23),('east','east',24,24,11,23)]:
    C(cid,'墙',cid,'exterior_wall',floor='ground',orientation=side,thickness_voxels=1)
    B(x0,x1,11,16,z0,z1,'oak_planks',cid)
W('door','门','door','south','south',24,16,18,11,14,glazing=None,depth=1,floor='ground')
G('roof','屋顶','roof',9,25,9,25,17,20,m='oak_planks')
"""
ISLANDS = """
O('islands','群岛','islands','landscape')
C('island_a','岩岛','rock island','rock',floor='ground',parent_id='islands')
B(10,17,10,13,10,17,'stone','island_a')
C('island_b','岩岛','rock island','terrain',floor='ground',parent_id='islands')
B(30,37,10,13,30,37,'grass_block','island_b')
"""
CAVE = """
O('cave_object','洞穴','cave','landscape')
C('cave_shell','岩洞','cave shell','cave',floor='ground',parent_id='cave_object')
B(10,20,10,20,10,20,'stone','cave_shell')
B(12,18,11,17,10,17,None)
"""
RUIN = """
C('ruined_a','断墙','broken wall','ruin',floor='ground')
B(10,12,10,17,10,12,'stone_bricks','ruined_a')
C('ruined_b','散落岩石','fallen stone','rock',floor='ground')
B(18,20,10,11,10,12,'stone','ruined_b')
"""


def task(contract="inhabited", seed=17):
    return {
        "sample_id": "fixture_001",
        "seed": seed,
        "scene_type": "architecture" if contract == "inhabited" else "natural",
        "quality_contract": contract,
        "requested_tags": {"purpose": "fixture"},
        "phase": "final",
        "quality_requirements": {},
    }


@pytest.fixture
def isolation():
    try:
        sandbox.image_info()
    except sandbox.SandboxError as exc:
        pytest.skip("Real isolated runtime is not prepared: " + str(exc))


def test_canonical_identity_states_and_annotation_independence():
    coords = np.array([[2, 3, 4], [1, 3, 4]], dtype=np.int64)
    palette = {"block_states": ["oak_log[axis=x]", "stone"], "component_ids": ["a", "b"]}
    bi = np.array([0, 1])
    ci = np.array([0, 1])
    original = canonical.canonical_voxel_hash(coords, bi, palette)
    swapped = {"block_states": ["minecraft:stone", "minecraft:oak_log[axis=x]"], "component_ids": ["renamed"]}
    assert original == canonical.canonical_voxel_hash(coords[::-1], np.array([0, 1]), swapped)
    changed = {"block_states": ["oak_log[axis=y]", "stone"], "component_ids": ["a", "b"]}
    assert original != canonical.canonical_voxel_hash(coords, bi, changed)
    assert canonical.annotation_hash(coords, ci, palette, []) != canonical.annotation_hash(
        coords, ci[::-1], palette, []
    )
    assert (
        canonical.normalize_block_state("oak_log[waterlogged=false,axis=x]")
        == "minecraft:oak_log[axis=x,waterlogged=false]"
    )
    with pytest.raises(ValueError, match="Duplicate"):
        canonical.canonicalize(np.array([[1, 2, 3], [1, 2, 3]]), bi, ci, palette)
    with pytest.raises(ValueError):
        canonical.canonicalize(coords.astype(float), bi, ci, palette)


def test_contract_is_complete_and_protects_trusted_state():
    contract = primitive_contract()
    for signature in ("C(", "P(", "B(", "W(", "G(", "K(", "O("):
        assert signature in contract
    assert "wall_id" in contract and "floor top+1" in contract
    for source in (
        "import os",
        "C=lambda *x:None",
        "SPEC['seed']=1",
        "x=().__class__",
        "def bad(C): pass",
        "from math import sqrt as P",
    ):
        with pytest.raises(ValueError):
            decode_source(source)
    decode_source('import math\nfor x in range(4):\n    P(x,3,4,"stone","rock")')


def test_metadata_cannot_trigger_unbounded_host_geometry(tmp_path):
    source = "MODEL_SPEC={'spaces':[{'id':'bad','air_bbox':{'min':[0,0,0],'max':[1000000000,1,1]},'entry':[0,0,0]}]}"
    report = build(source, task(), tmp_path)
    assert not report["passed"]
    assert "inside the integer grid" in report["violations"][0]["detail"]


def test_canonical_load_rejects_oversized_ndarray_before_allocation(tmp_path):
    (tmp_path / "palette.json").write_text(json.dumps({"block_states": ["stone"], "component_ids": ["a"]}))
    stream = io.BytesIO()
    np.lib.format.write_array_header_1_0(
        stream, {"descr": "<u2", "fortran_order": False, "shape": (1000000000, 3)}
    )
    with zipfile.ZipFile(tmp_path / "voxels.npz", "w") as archive:
        archive.writestr("coords.npy", stream.getvalue())
        for key in ("block_index", "component_index"):
            vector = io.BytesIO()
            np.save(vector, np.array([0], dtype=np.uint32))
            archive.writestr(key + ".npy", vector.getvalue())
    with pytest.raises(ValueError, match="oversized"):
        canonical.load(tmp_path)


def test_real_build_render_repeat_and_roundtrip(tmp_path, isolation):
    first = build(HOUSE, task(), tmp_path / "first")
    second = build(HOUSE, task(), tmp_path / "second")
    assert first["passed"], first
    assert second["passed"], second
    assert first["canonical_voxel_hash"] == second["canonical_voxel_hash"]
    assert first["annotation_hash"] == second["annotation_hash"]
    checked = canonical.load_and_validate(tmp_path / "first")
    assert checked["canonical_voxel_hash"] == first["canonical_voxel_hash"]
    previews_a = render(tmp_path / "first")
    previews_b = render(tmp_path / "second")
    assert previews_a["image_hashes"] == previews_b["image_hashes"]
    assert all((tmp_path / "first" / name).stat().st_size > 1000 for name in previews_a["image_hashes"])
    # Rendering rejects changed JSON instead of reviewing different geometry from arrays.
    sample_path = tmp_path / "first/sample.json"
    sample = json.loads(sample_path.read_text())
    sample["blocks"][0]["type"] = "stone"
    sample["blocks"][0]["block_state"] = "minecraft:stone"
    sample_path.write_text(json.dumps(sample))
    with pytest.raises(ValueError, match="differs"):
        render(tmp_path / "first")


def test_real_runtime_preserves_log_axis_states(tmp_path, isolation):
    source = (
        "C('rock','原木','log','object',floor='ground')\nB(1,2,1,2,1,2,'minecraft:oak_log[axis=x]','rock')"
    )
    a = build(source, task("landscape"), tmp_path / "x")
    b = build(source.replace("axis=x", "axis=y"), task("landscape"), tmp_path / "y")
    assert a["passed"] and b["passed"], (a, b)
    assert a["canonical_voxel_hash"] != b["canonical_voxel_hash"]
    assert canonical.load(tmp_path / "x")[3]["block_states"] == ["minecraft:oak_log[axis=x]"]
    assert render(tmp_path / "x")["passed"]


@pytest.mark.parametrize("source,contract", [(ISLANDS, "landscape"), (CAVE, "landscape"), (RUIN, "ruin")])
def test_real_natural_and_ruin_contracts(tmp_path, isolation, source, contract):
    report = build(source, task(contract), tmp_path)
    assert report["passed"], report
    assert report["evidence"]["categories"].get("slab", 0) == 0
    assert render(tmp_path)["passed"]


def test_opening_overdraw_and_frozen_legacy_gate(tmp_path, isolation):
    overdraw = HOUSE + "B(17,17,11,13,24,24,'oak_planks','south')\n"
    report = build(overdraw, task(), tmp_path / "overdraw")
    assert not report["passed"]
    assert any(v["rule"] == "opening_filled_by_later_geometry" for v in report["violations"])
    legacy_task = task("legacy_large_wooden_v1")
    legacy_task["quality_requirements"] = {key: 0 for key in FROZEN_WOODEN}
    legacy = build(HOUSE, legacy_task, tmp_path / "legacy")
    assert not legacy["passed"]
    assert legacy["effective_requirements"] == FROZEN_WOODEN
    assert {"wooden_main_voxels", "declared_actual_room_spaces"} <= {v["rule"] for v in legacy["violations"]}
    final = task()
    final["quality_requirements"]["required_space_ids"] = ["required_kept_room"]
    report = build(HOUSE, final, tmp_path / "removed_room")
    assert any(v["rule"] == "required_space_ids_missing" for v in report["violations"])
    skeleton = task()
    skeleton["phase"] = "skeleton"
    skeleton_report = build(HOUSE, skeleton, tmp_path / "skeleton")
    assert skeleton_report["passed"] and not skeleton_report["acceptance_eligible"]


def test_tar_boundary_rejects_symlinks_and_path_traversal():
    for name, kind in [("../../secret", tarfile.REGTYPE), ("sample.json", tarfile.SYMTYPE)]:
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as archive:
            info = tarfile.TarInfo(name)
            info.type = kind
            info.linkname = "/etc/passwd"
            archive.addfile(info)
        with pytest.raises(sandbox.SandboxError):
            sandbox.unpack(stream.getvalue(), 4096)


def test_actual_isolation_host_secret_network_root_and_recovery(tmp_path, isolation):
    assert doctor()["ready"]
    sentinel = tmp_path / "host-secret"
    sentinel.write_text("not mounted")
    probe = f"""import json,os,socket
from pathlib import Path
result={{'host_visible':Path({str(sentinel)!r}).exists(),'docker_socket':Path('/var/run/docker.sock').exists(),'uid':os.getuid()}}
Path('/output/probe.json').write_text(json.dumps(result))
"""
    artifacts, _ = sandbox.run(probe.encode(), mode="probe")
    assert json.loads(artifacts["probe.json"]) == {
        "host_visible": False,
        "docker_socket": False,
        "uid": 10001,
    }
    attacks = [
        (b"while True: pass", {"build_timeout_seconds": 0.8}, "sandbox_timeout"),
        (b"x=bytearray(800*1024*1024)", {"sandbox_memory_mb": 64}, "sandbox_execution_failed"),
        (
            b'from pathlib import Path\nfor i in range(100): Path(f"/tmp/f{i}").write_bytes(b"x"*1024*1024)',
            {},
            "sandbox_execution_failed",
        ),
        (b'print("x"*2000000)', {}, "sandbox_output_limit"),
    ]
    for source, limits, reason in attacks:
        with pytest.raises(sandbox.SandboxError) as raised:
            sandbox.run(source, mode="probe", config=limits)
        assert raised.value.reason == reason, raised.value
    assert build(HOUSE, task(), tmp_path / "after_attacks")["passed"]


def test_private_saved_wooden_failures_are_retained():
    archive_path = os.environ.get("VOXLUSH_PRIVATE_REGRESSION_ARCHIVE")
    if not archive_path:
        pytest.skip("Private archive is optional and never distributed in the repository")
    prefix = "voxel_dataset_review_20261006/reference/examples/wooden/"
    with zipfile.ZipFile(archive_path) as archive:
        for sample_id in ("sample_000918", "sample_001009", "sample_001041"):
            sample = json.loads(gzip.decompress(archive.read(prefix + sample_id + "/sample.json.gz")))
            brief = json.loads(archive.read(prefix + sample_id + "/design_brief.json"))
            case = task("legacy_large_wooden_v1")
            case["quality_requirements"] = brief["quality_requirements"]
            report = inspect(sample, case)
            assert not report["passed"], sample_id
            assert report["violations"], sample_id
