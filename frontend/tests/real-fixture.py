"""Disposable real Store/scheduler/sandbox backend; no model endpoints or paid calls."""
import os
import tempfile
import traceback
from pathlib import Path

import uvicorn

from voxlush.api.app import create_app
from voxlush.core.config import Config
from voxlush.dataset.archive import Archive
from voxlush.store.store import Store


ISLANDS = """
O('islands','群岛','islands','landscape')
C('island_a','岩岛','rock island','rock',floor='ground',parent_id='islands')
B(10,17,10,13,10,17,'stone','island_a')
C('island_b','岩岛','rock island','terrain',floor='ground',parent_id='islands')
B(30,37,10,13,30,37,'grass_block','island_b')
"""

_prepare = Archive.prepare


def _trace_prepare(self, sample, build_dir, review):
    try:
        return _prepare(self, sample, build_dir, review)
    except Exception:
        traceback.print_exc()
        raise


Archive.prepare = _trace_prepare

with tempfile.TemporaryDirectory(prefix="voxlush-browser-real-") as directory:
    root = Path(directory)
    source = root / "source.py"
    source.write_text(ISLANDS)
    store = Store(root)
    store.create_campaign("browser_real", "REAL LOCAL FIXTURE / 非生产资产", 3, 10, 0, {"natural": 1})
    store.add_sample({
        "sample_id": "browser_real_islands", "campaign_id": "browser_real",
        "seed": 17, "theme_seed_id": "islands_local_fixture", "theme_family_id": "islands",
        "scene_type": "natural", "quality_contract": "landscape", "generation_mode": "direct",
        "instruction": "本地集成测试：两个具有组件归属的岩岛。未调用模型，不作为正式合格资产。",
        "requested_tags": {"fixture": True}, "sampling_tags": {}, "quality_requirements": {},
        "record_kind": "fixture",
    }, str(source))
    store.set_campaign_state("browser_real", "running", "local_fixture")
    store.close()
    # The local-only token is intentionally scoped to this disposable test server.
    os.environ["VOXLUSH_BROWSER_TEST_TOKEN"] = "offline-browser-test-token"
    config = Config(data_root=root, port=8068, auth_token_env="VOXLUSH_BROWSER_TEST_TOKEN", allow_live=False)
    uvicorn.run(create_app(config), host="127.0.0.1", port=8068, log_level="warning")
