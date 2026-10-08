import httpx
import pytest
import pytest_asyncio

from voxlush.api.app import create_app
from voxlush.core.config import Config


@pytest_asyncio.fixture
async def api(tmp_path):
    app = create_app(Config(data_root=tmp_path / "data", global_api_cap=2), start_scheduler=False)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                                     base_url="http://127.0.0.1") as client:
            yield client


@pytest.mark.parametrize("cap", ["2", None, True, -1, 513])
async def test_invalid_cap_payload_is_rejected_without_server_error(api, cap):
    result = await api.post("/api/v1/commands", json={"command_id": "bad-cap", "campaign_id": "debug",
        "action": "set_cap", "expected_config_revision": 1, "payload": {"api_cap": cap}})
    assert result.status_code == 422, result.text


async def test_nonfinite_scene_weight_is_rejected_at_api_boundary(api):
    result = await api.post("/api/v1/campaigns", content='{"campaign_id":"debug","name":"Debug",'
        '"target":1,"request_limit":1,"api_cap":0,"scene_weights":{"natural":1e309}}',
        headers={"Content-Type": "application/json"})
    assert result.status_code == 422, result.text


@pytest.mark.parametrize("field", ['"cost_upper_bound":1e309', '"parameters":{"temperature":1e309}'])
async def test_config_validation_rejects_nonfinite_endpoint_values(api, field):
    result = await api.post("/api/v1/config/validate", content='{"author":{"base_url":"http://127.0.0.1/v1",'
        '"model":"fixture",' + field + '}}', headers={"Content-Type": "application/json"})
    assert result.status_code == 200
    assert not result.json()["valid"]
