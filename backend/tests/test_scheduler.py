import asyncio
import json
import time

import pytest

from voxlush.core.config import Config, Endpoint
from voxlush.core.files import atomic_json
from voxlush.inference.client import PoolClient
from voxlush.pipeline.scheduler import Scheduler
from voxlush.pipeline import scheduler as scheduler_module
from voxlush.store.store import OwnerBusy, Store
from voxlush.themes.planner import FAMILIES, runtime_task, task_for


def complete_response():
    response = {"choices":[{"delta":{"content":"P(1,2,3,'stone','rock')"},"finish_reason":"stop"}],
                "usage":{"prompt_tokens":1,"completion_tokens":1}}
    return b"data: " + json.dumps(response).encode() + b"\n\ndata: [DONE]\n\n"


def setup(store, endpoint):
    campaign = store.create_campaign("debug", "Debug fixture", 2, 10, 2, {"natural": 1})
    store.set_campaign_state("debug", "running")
    family_id = next(fid for fid, family in FAMILIES.items() if family["scene_type"] == "natural")
    sample = store.add_sample(runtime_task(task_for(campaign, family_id, 0, "fixture")))
    config = Config(data_root=store.root, allow_live=True, global_api_cap=2, author=endpoint)
    claim = store.reserve(sample["sample_id"], 1, endpoint, 2, 8)
    assert claim
    return config, claim


class BrokenClient:
    async def call(self, *args):
        raise RuntimeError("Injected unexpected transport failure")

    async def close(self):
        pass


async def test_unexpected_client_failure_reconciles_the_reserved_attempt(tmp_path):
    store = Store(tmp_path / "data")
    endpoint = Endpoint(base_url="http://127.0.0.1:1/v1", model="fixture", cost_upper_bound=1)
    try:
        config, claim = setup(store, endpoint)
        scheduler = Scheduler(store, config, client=BrokenClient())
        await scheduler.network(claim, endpoint)
        attempt = store.one("SELECT * FROM attempts WHERE attempt_id=?", (claim["attempt_id"],))
        assert attempt["status"] == "outcome_unknown"
        assert attempt["occupancy"] == 1  # Unknown upstream work remains reserved.
        assert store.campaign("debug")["cost_unknown"] == 1
        assert store.sample(claim["sample_id"])["reason_code"] == "outcome_unknown"
        assert json.loads((store.root / attempt["response_path"]).read_text())["error_category"] == "outcome_unknown"
    finally:
        store.close()


async def test_preflight_failure_releases_slot_without_unknown_billing(tmp_path):
    store = Store(tmp_path / "data")
    endpoint = Endpoint(base_url="http://127.0.0.1:1/v1", model="fixture", cost_upper_bound=1)
    try:
        config, claim = setup(store, endpoint)
        claim["source_path"] = str(tmp_path / "missing-source.py")
        scheduler = Scheduler(store, config, client=BrokenClient())
        await scheduler.network(claim, endpoint)
        attempt = store.one("SELECT * FROM attempts WHERE attempt_id=?", (claim["attempt_id"],))
        assert attempt["status"] == "complete"
        assert attempt["occupancy"] == 0
        assert attempt["settled_cost"] == 0
        assert store.campaign("debug")["cost_unknown"] == 0
        assert store.campaign("debug")["reserved_cost"] == 0
    finally:
        store.close()


@pytest.mark.parametrize("status", [429, 503])
async def test_busy_endpoint_defers_sample_and_releases_slot_without_semantic_repair(tmp_path, fake_http, status):
    url, requests = await fake_http(b'{"error":{"message":"busy"}}', status=status, headers={"Retry-After": "30"})
    store = Store(tmp_path / "data")
    endpoint = Endpoint(base_url=url, model="fixture")
    scheduler = None
    try:
        config, claim = setup(store, endpoint)
        scheduler = Scheduler(store, config)
        before = time.time()
        await scheduler.network(claim, endpoint)
        sample = store.sample(claim["sample_id"])
        assert sample["status"] == "deferred"
        assert sample["next_ready_at"] >= before + 30
        assert sample["geometry_repairs"] == 0
        assert store.one("SELECT SUM(occupancy) n FROM attempts")["n"] == 0
        assert len(requests) == 1
    finally:
        if scheduler:
            await scheduler.client.close()
        store.close()


@pytest.mark.parametrize("status,body,reason", [
    (401, b'{}', "endpoint_auth"),
    (400, b'{}', "endpoint_configuration"),
    (402, b'{}', "endpoint_quota"),
    (429, b'{"error":{"code":"insufficient_quota"}}', "endpoint_quota"),
])
async def test_bad_endpoint_is_isolated_without_repair_loop(tmp_path, fake_http, status, body, reason):
    url, requests = await fake_http(body, status=status)
    store = Store(tmp_path / "data")
    endpoint = Endpoint(base_url=url, model="fixture")
    scheduler = None
    try:
        config, claim = setup(store, endpoint)
        scheduler = Scheduler(store, config)
        await scheduler.network(claim, endpoint)
        sample = store.sample(claim["sample_id"])
        assert sample["status"] == "blocked"
        assert sample["reason_code"] == reason
        assert endpoint.alias in scheduler.blocked_endpoints
        assert sample["geometry_repairs"] == 0
        assert len(requests) == 1
    finally:
        if scheduler:
            await scheduler.client.close()
        store.close()


def test_single_store_owner_and_stale_callback_are_enforced(tmp_path):
    store = Store(tmp_path / "data")
    try:
        with pytest.raises(OwnerBusy):
            Store(store.root)
        _, claim = setup(store, Endpoint(base_url="http://127.0.0.1:1/v1", model="fixture"))
        assert store.finish(claim, stage="author", changes={"revision": 2})
        new = store.claim(claim["sample_id"], 2)
        assert new
        assert not store.finish(claim, status="rejected")
        assert store.sample(claim["sample_id"])["lease_token"] == new["lease_token"]
    finally:
        store.close()


@pytest.mark.parametrize("cap", [0, 1, 2, 8, 32])
def test_reservations_never_exceed_cap(tmp_path, cap):
    store = Store(tmp_path / "data")
    try:
        endpoint = Endpoint(base_url="http://127.0.0.1:1/v1", model="fixture", provider_cap=cap)
        campaign = store.create_campaign("debug", "Cap fixture", cap+1, 100, cap, {"natural": 1})
        store.set_campaign_state("debug", "running")
        family_id = next(fid for fid, family in FAMILIES.items() if family["scene_type"] == "natural")
        for sequence in range(cap+1):
            sample = store.add_sample(runtime_task(task_for(campaign, family_id, sequence, "fixture")))
            claim = store.reserve(sample["sample_id"], 1, endpoint, cap, 8)
            assert bool(claim) == (sequence < cap)
        assert store.one("SELECT COALESCE(SUM(occupancy),0) n FROM attempts")["n"] == cap
        assert store.campaign("debug")["requests_used"] == cap
    finally:
        store.close()


async def test_fresh_live_campaign_dispatches_from_scheduler_tick(tmp_path, fake_http):
    url, requests = await fake_http(complete_response())
    store = Store(tmp_path / "data")
    endpoint = Endpoint(base_url=url, model="fixture", provider_cap=1)
    scheduler = Scheduler(store, Config(data_root=store.root, allow_live=True, global_api_cap=1, author=endpoint))
    try:
        campaign = store.create_campaign("fresh", "Fresh live campaign", 1, 2, 1, {"natural":1})
        store.set_campaign_state("fresh", "running")
        sample = store.add_sample(runtime_task(task_for(campaign, "geology", 0, "calibration")))
        # Fresh samples have no reason code; SQLite comparisons with NULL must
        # still count zero duplicates, and must not block the first dispatch.
        coverage = store.coverage("fresh")
        assert coverage["totals"]["active"] == 1
        assert coverage["totals"]["duplicate"] == 0
        await scheduler.tick()
        assert len(scheduler.active) == 1
        await asyncio.gather(*scheduler.active)
        assert len(requests) == 1
        assert store.sample(sample["sample_id"])["stage"] == "build"
        assert store.campaign("fresh")["state"] == "running"
    finally:
        await scheduler.stop()
        store.close()


async def test_adding_visual_endpoint_resumes_waiting_reviews(tmp_path):
    store = Store(tmp_path / "data")
    endpoint = Endpoint(base_url="http://127.0.0.1:1/v1", model="fixture", supports_images=True)
    scheduler = Scheduler(store, Config(data_root=store.root, allow_live=True, visual=endpoint))
    try:
        campaign = store.create_campaign("debug", "Review fixture", 1, 10, 1, {"natural": 1})
        store.set_campaign_state("debug", "running")
        family_id = next(fid for fid, family in FAMILIES.items() if family["scene_type"] == "natural")
        sample = store.add_sample(runtime_task(task_for(campaign, family_id, 0, "fixture")))
        claim = store.claim(sample["sample_id"], 1)
        store.finish(claim, stage="review", status="awaiting_review", reason="awaiting_visual")
        await scheduler.start()
        assert store.sample(sample["sample_id"])["status"] == "ready"
        assert store.campaign("debug")["requests_used"] == 0
    finally:
        await scheduler.stop()
        store.close()


async def test_durable_response_recovers_after_restart_without_second_post(tmp_path, fake_http):
    url, requests = await fake_http(complete_response())
    store = Store(tmp_path / "data")
    endpoint = Endpoint(base_url=url, model="fixture", cost_upper_bound=1, input_per_million=1, output_per_million=2)
    config, claim = setup(store, endpoint)
    client = PoolClient()
    try:
        result = await client.call(endpoint, [{"role": "user", "content": "Crash recovery fixture"}], claim["attempt_id"], "author")
        assert result["response_complete"]
        atomic_json(store.root / claim["attempt"]["response_path"], result)
    finally:
        await client.close()
        store.close()
    # Response is durable, but neither billing nor the stage transition committed.
    store = Store(config.data_root)
    scheduler = Scheduler(store, config)
    try:
        await scheduler.start()
        sample = store.sample(claim["sample_id"])
        assert sample["stage"] == "build" and sample["status"] == "ready"
        campaign = store.campaign("debug")
        assert campaign["requests_used"] == 1
        assert campaign["cost_known"] == .000003
        assert campaign["reserved_cost"] == 0
        assert len(requests) == 1
    finally:
        await scheduler.stop()
        store.close()


@pytest.mark.parametrize("failure", ["request", "complete_response", "unknown_response"])
async def test_persistent_response_storage_failure_settles_and_stops_paid_dispatch(tmp_path, fake_http, monkeypatch, failure):
    url, requests = await fake_http(None if failure == "unknown_response" else complete_response())
    store = Store(tmp_path / "data")
    endpoint = Endpoint(base_url=url, model="fixture", cost_upper_bound=1, input_per_million=1, output_per_million=2)
    config, claim = setup(store, endpoint)
    scheduler = Scheduler(store, config)
    # A second campaign shares the same storage and must stop as well.
    store.create_campaign("other", "Storage fixture", 1, 10, 2, {"natural": 1})
    store.set_campaign_state("other", "running")
    original_write = scheduler_module.atomic_json

    def broken_write(path, value):
        if failure != "request" and path.name.endswith(".request.json"):
            return original_write(path, value)
        raise OSError("Injected persistent disk write failure")

    try:
        monkeypatch.setattr(scheduler_module, "atomic_json", broken_write)
        await scheduler.network(claim, endpoint)
        attempt = store.one("SELECT * FROM attempts WHERE attempt_id=?", (claim["attempt_id"],))
        unknown = failure == "unknown_response"
        assert attempt["status"] == ("outcome_unknown" if unknown else "complete")
        assert attempt["occupancy"] == int(unknown)
        assert attempt["settled_cost"] == (None if unknown else .000003 if failure == "complete_response" else 0)
        campaign = store.campaign("debug")
        assert campaign["cost_unknown"] == int(unknown)
        assert campaign["reserved_cost"] == int(unknown)
        sample = store.sample(claim["sample_id"])
        assert sample["status"] == "blocked"
        assert sample["reason_code"] == ("outcome_unknown" if unknown else "storage_unavailable")
        assert all(c["state"] == "blocked" and c["reason_code"] == "storage_unavailable" for c in store.campaigns())
        assert len(requests) == int(failure != "request")

        # Even a resume command cannot bypass the storage failure within this owner.
        monkeypatch.setattr(scheduler_module, "atomic_json", original_write)
        store.command({"command_id":"resume-storage", "campaign_id":"debug", "action":"resume",
                       "expected_config_revision":1})
        await scheduler.tick()
        assert store.campaign("debug")["state"] == "blocked"
        assert scheduler.cap() == 0
        assert not scheduler.active
        assert len(requests) == int(failure != "request")
    finally:
        await scheduler.client.close()
        store.close()


@pytest.mark.parametrize("cancelled", [False, True])
async def test_failed_finish_preserves_complete_response_and_other_work_continues(tmp_path, fake_http, monkeypatch, cancelled):
    url, requests = await fake_http(complete_response())
    store = Store(tmp_path / "data")
    endpoint = Endpoint(base_url=url, model="fixture", cost_upper_bound=1, input_per_million=1, output_per_million=2)
    config, claim = setup(store, endpoint)
    scheduler = Scheduler(store, config)
    consume = scheduler.consume

    async def failed_finish(*args):
        if cancelled:
            import asyncio
            raise asyncio.CancelledError()
        raise RuntimeError("Injected finish callback failure")

    try:
        monkeypatch.setattr(scheduler, "consume", failed_finish)
        await scheduler.network(claim, endpoint)
        result = json.loads((store.root / claim["attempt"]["response_path"]).read_text())
        assert result["response_complete"] and result["cost"] == .000003
        attempt = store.one("SELECT * FROM attempts WHERE attempt_id=?", (claim["attempt_id"],))
        assert attempt["status"] == "complete" and attempt["occupancy"] == 0
        assert store.sample(claim["sample_id"])["reason_code"] == "finish_callback_failed"
        assert store.campaign("debug")["state"] == "running"

        monkeypatch.setattr(scheduler, "consume", consume)
        family_id = claim["family_id"]
        sample = store.add_sample(runtime_task(task_for(store.campaign("debug"), family_id, 1, "fixture")))
        next_claim = store.reserve(sample["sample_id"], 1, endpoint, 2, 8)
        await scheduler.network(next_claim, endpoint)
        assert store.sample(sample["sample_id"])["stage"] == "build"
        assert len(requests) == 2
        assert store.campaign("debug")["cost_known"] == .000006
        assert store.campaign("debug")["cost_unknown"] == 0
    finally:
        await scheduler.client.close()
        store.close()


async def test_post_disconnect_keeps_unknown_budget_and_rejects_retry(tmp_path, fake_http):
    url, requests = await fake_http(None)
    store = Store(tmp_path / "data")
    endpoint = Endpoint(base_url=url, model="fixture", cost_upper_bound=1)
    config, claim = setup(store, endpoint)
    scheduler = Scheduler(store, config)
    try:
        await scheduler.network(claim, endpoint)
        attempt = store.one("SELECT * FROM attempts WHERE attempt_id=?", (claim["attempt_id"],))
        assert attempt["status"] == "outcome_unknown" and attempt["occupancy"] == 1
        assert attempt["settled_cost"] is None
        assert store.campaign("debug")["cost_unknown"] == 1
        assert store.campaign("debug")["reserved_cost"] == 1
        store.command({"command_id":"retry-unknown", "campaign_id":"debug", "action":"retry",
                       "expected_config_revision":1, "payload":{"sample_id":claim["sample_id"]}})
        store.apply_commands()
        assert store.get_command("retry-unknown")["reason"] == "attempt_outcome_unresolved"
        assert len(requests) == 1
    finally:
        await scheduler.client.close()
        store.close()


async def test_readonly_store_retains_response_and_stops_dispatch_until_recovery(tmp_path, fake_http):
    url, requests = await fake_http(complete_response())
    store = Store(tmp_path / "data")
    endpoint = Endpoint(base_url=url, model="fixture", cost_upper_bound=1, input_per_million=1, output_per_million=2)
    config, claim = setup(store, endpoint)
    scheduler = Scheduler(store, config)
    try:
        store.db.execute("PRAGMA query_only=ON")
        await scheduler.network(claim, endpoint)
        assert scheduler.cap() == 0
        result = json.loads((store.root / claim["attempt"]["response_path"]).read_text())
        assert result["response_complete"]
        store.db.execute("PRAGMA query_only=OFF")
        for recovered, response in store.recover():
            await scheduler.consume(recovered, response)
        assert store.sample(claim["sample_id"])["stage"] == "build"
        assert store.campaign("debug")["cost_known"] == .000003
        assert store.campaign("debug")["cost_unknown"] == 0
        assert len(requests) == 1
    finally:
        store.db.execute("PRAGMA query_only=OFF")
        await scheduler.client.close()
        store.close()
