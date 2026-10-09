"""Receipt reconciliation validates actual saved bytes and never repeats a POST."""

import asyncio
import hashlib
import json

import httpx
import pytest

from voxlush.core.config import Config, Endpoint
from voxlush.inference.client import PoolClient
from voxlush.pipeline.scheduler import Scheduler
from voxlush.store.store import Store
from test_inference import completion, sse
from test_reliability_final import SOURCE
from test_review_b02 import add

BODY = sse(
    completion(SOURCE, id="completion-fixture", usage={"prompt_tokens": 10, "completion_tokens": 20}),
    b"[DONE]",
)
ID = "a" * 32


def receipt(body=BODY, **changes):
    return {
        "schema": "pool.receipt.v1",
        "state": "settled",
        "request_id": ID,
        "request_sha256": "expected",
        "body_sha256": hashlib.sha256(body).hexdigest(),
        "upstream_posts": 1,
        "execution_state": "terminated",
        "finish_reason": "stop",
        "http_status": 200,
        "created_at": 1,
        "ended_at": 3,
        **changes,
    }


@pytest.mark.parametrize(
    "invalid",
    [
        "request_id",
        "request_sha256",
        "body_sha256",
        "upstream_posts",
        "execution_state",
        "finish_reason",
        "partial",
        "unavailable",
    ],
)
async def test_untrusted_or_partial_receipt_keeps_unknown(invalid):
    meta = receipt()
    body = BODY
    if invalid == "partial":
        body = sse({"choices": [{"delta": {"reasoning_content": "still thinking"}}]})
        meta["body_sha256"] = hashlib.sha256(body).hexdigest()
    elif invalid not in ("unavailable",):
        meta[invalid] = 2 if invalid == "upstream_posts" else "wrong"
    calls = []

    def handle(request):
        calls.append(request.method)
        if invalid == "unavailable":
            return httpx.Response(404)
        return httpx.Response(
            200, content=body if request.url.path.endswith("/body") else json.dumps(meta).encode()
        )

    client = PoolClient(transport=httpx.MockTransport(handle))
    try:
        result = await client.recover_receipt(
            Endpoint(base_url="http://fixture/v1", model="fixture", pool_receipts=True),
            ID,
            "author",
            "expected",
        )
        assert result is None
        assert set(calls) == {"GET"}
    finally:
        await client.close()


async def test_server_ignoring_receipt_mode_cannot_assert_single_execution():
    client = PoolClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=BODY)))
    try:
        result = await client.call(
            Endpoint(base_url="http://fixture/v1", model="fixture", pool_receipts=True), [], ID, "author"
        )
        assert result["execution_state"] == "execution_unknown"
        assert result["error_category"] == "pool_receipt_protocol_unconfirmed"
        assert not result["response_complete"]
    finally:
        await client.close()


@pytest.mark.parametrize(
    "status,ack,state,expected",
    [
        (503, True, "not_sent", "not_sent"),
        (503, False, "not_sent", "execution_unknown"),
        (503, True, None, "execution_unknown"),
        (409, True, "not_sent", "execution_unknown"),
        (502, True, None, "execution_unknown"),
    ],
)
async def test_only_acknowledged_admission_rejection_can_release_capacity(status, ack, state, expected):
    headers = {"X-Pool-Request-Id": ID, "X-Pool-Receipt-Version": "pool.receipt.v1"} if ack else {}
    if state:
        headers["X-Pool-Execution-State"] = state
    client = PoolClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(status, json={"error": {"message": "busy"}}, headers=headers)
        )
    )
    try:
        result = await client.call(
            Endpoint(base_url="http://fixture/v1", model="fixture", pool_receipts=True), [], ID, "author"
        )
        assert result["execution_state"] == expected
    finally:
        await client.close()


@pytest.mark.parametrize("priced", [False, True])
async def test_unknown_recovers_saved_original_after_restart_without_rebilling(tmp_path, priced):
    calls = []
    saved = {}
    available = False

    def handle(request):
        calls.append(request.method)
        if request.method == "POST":
            saved.update(
                id=request.headers["x-pool-request-id"], digest=hashlib.sha256(request.content).hexdigest()
            )
            return httpx.Response(
                200,
                content=sse({"choices": [{"delta": {"reasoning_content": "working"}}]}),
                headers={"X-Pool-Request-Id": saved["id"], "X-Pool-Receipt-Version": "pool.receipt.v1"},
            )
        if not available:
            return httpx.Response(404)
        meta = receipt(request_id=saved["id"], request_sha256=saved["digest"])
        return httpx.Response(
            200, content=BODY if request.url.path.endswith("/body") else json.dumps(meta).encode()
        )

    endpoint = Endpoint(
        base_url="http://fixture/v1",
        model="fixture",
        pool_receipts=True,
        cost_upper_bound=2,
        input_per_million=1 if priced else None,
        output_per_million=2 if priced else None,
    )
    store = Store(tmp_path / "data")
    store.create_campaign("review", "Receipt fixture", 2, 8, 2, {"natural": 1})
    store.set_campaign_state("review", "running")
    sample = add(store)
    store.db.execute("UPDATE campaigns SET sequence=request_limit")
    config = Config(data_root=store.root, author=endpoint, allow_live=True)
    scheduler = Scheduler(store, config, client=PoolClient(transport=httpx.MockTransport(handle)))
    claim = store.reserve(sample["sample_id"], 1, endpoint, 2, 8)
    try:
        await scheduler.network(claim, endpoint)
        before = store.one("SELECT * FROM attempts")
        original = (store.root / before["response_path"]).read_bytes()
        assert before["status"] == "outcome_unknown" and before["occupancy"] == 1
        assert store.campaign("review")["cost_unknown"] == 1
        await scheduler.stop()
        store.close()
        store.__init__(store.root)
        available = True
        scheduler = Scheduler(store, config, client=PoolClient(transport=httpx.MockTransport(handle)))
        await scheduler.recover_pool_receipts()
        await scheduler.recover_responses(pending_only=True)
        after = store.one("SELECT * FROM attempts")
        assert after["status"] == "complete" and after["occupancy"] == 0 and after["response_applied"] == 1
        assert after["attempt_id"] == before["attempt_id"] and after["revision"] == 1
        assert (store.root / before["response_path"]).read_bytes() == original
        assert after["response_path"] != before["response_path"]
        assert store.sample(sample["sample_id"])["stage"] == "build"
        assert store.sample(sample["sample_id"])["geometry_repairs"] == 0
        campaign = store.campaign("review")
        assert campaign["requests_used"] == 1 and campaign["request_limit"] == 8
        assert campaign["cost_unknown"] == (0 if priced else 1)
        assert campaign["reserved_cost"] == (0 if priced else 2)
        assert campaign["cost_known"] == pytest.approx(0.00005 if priced else 0)
        assert calls == ["POST", "GET", "GET"]
        result = json.loads((store.root / after["response_path"]).read_text())
        assert result["elapsed_ms"] == 2000
        assert not store.recover_receipt(after["attempt_id"], result, store.root / after["response_path"])
        assert store.campaign("review")["cost_known"] == campaign["cost_known"]
    finally:
        await scheduler.client.close()
        store.close()


async def test_receipt_poll_does_not_block_user_controls(tmp_path):
    event = asyncio.Event()

    async def handle(request):
        await event.wait()
        return httpx.Response(404)

    store = Store(tmp_path / "data")
    store.create_campaign("review", "Control fixture", 1, 8, 1, {"natural": 1})
    store.set_campaign_state("review", "running")
    config = Config(
        data_root=store.root,
        author=Endpoint(base_url="http://fixture/v1", model="fixture", pool_receipts=True),
    )
    scheduler = Scheduler(store, config, client=PoolClient(transport=httpx.MockTransport(handle)))

    async def delayed_poll():
        await event.wait()

    scheduler.recover_pool_receipts = delayed_poll
    try:
        await scheduler.tick()
        assert "reconcile" in scheduler.active.values()
        store.command(
            {"command_id": "pause", "campaign_id": "review", "action": "pause", "expected_config_revision": 1}
        )
        await asyncio.wait_for(scheduler.tick(), 1)
        assert store.campaign("review")["state"] == "paused"
    finally:
        event.set()
        await scheduler.stop()
        store.close()


async def test_receipt_poll_rotates_past_historical_untracked_unknowns(tmp_path):
    endpoint = Endpoint(base_url="http://fixture/v1", model="fixture", pool_receipts=True, provider_cap=32)
    store = Store(tmp_path / "data")
    store.create_campaign("review", "Poll fairness fixture", 32, 32, 32, {"natural": 1})
    store.set_campaign_state("review", "running")
    scheduler = Scheduler(store, Config(data_root=store.root, author=endpoint))
    queried = []

    async def recover(endpoint, attempt_id, role, expected_hash):
        queried.append(attempt_id)
        return None

    scheduler.client.recover_receipt = recover
    try:
        claims = [store.reserve(add(store)["sample_id"], 1, endpoint, 32, 32) for _ in range(17)]
        for index, claim in enumerate(claims):
            result = {"response_complete": False, "execution_state": "execution_unknown", "cost": None}
            store.settle(claim["attempt_id"], result)
            store.finish(claim, status="blocked", reason="outcome_unknown")
            request = store.root / claim["attempt"]["response_path"].replace(".json", ".request.json")
            scheduler.persist_json(
                request, {"pool_receipts": index == 16, "request_sha256": "expected"}, ledger=True
            )
        await scheduler.recover_pool_receipts()
        assert not queried
        scheduler.next_receipt_poll = 0
        await scheduler.recover_pool_receipts()
        assert queried == [claims[-1]["attempt_id"]]
        assert store.campaign("review")["requests_used"] == 17
        assert store.one("SELECT SUM(occupancy) n FROM attempts")["n"] == 17
    finally:
        await scheduler.client.close()
        store.close()
