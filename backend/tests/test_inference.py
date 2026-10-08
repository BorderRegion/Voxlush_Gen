import json

import pytest

from voxlush.core.config import Endpoint
from voxlush.inference import client as inference
from voxlush.inference.client import PoolClient


def sse(*events):
    return b"".join(b"data: " + (event if isinstance(event, bytes) else json.dumps(event).encode()) + b"\n\n" for event in events)


def completion(content="P(1,2,3,'stone','rock')", finish="stop", **extra):
    return {"choices": [{"delta": {"content": content}, "finish_reason": finish}], **extra}


async def call(url, **settings):
    endpoint = Endpoint(**{"base_url": url, "model": "local-fixture", "total_timeout": .8,
                           "first_content_timeout": .5, "idle_timeout": .5, **settings})
    client = PoolClient()
    try:
        return await client.call(endpoint, [{"role": "user", "content": "Local transport fixture"}], "a", "author")
    finally:
        await client.close()


async def test_done_closes_stream_without_waiting_for_socket_eof(fake_http):
    url, requests = await fake_http(sse(completion(), b"[DONE]"), hold_open=True)
    result = await call(url)
    assert result["response_complete"], result
    assert result["error_category"] is None
    assert len(requests) == 1


@pytest.mark.parametrize("hold_open", [False, True])
async def test_explicit_finish_contract_does_not_require_done(fake_http, hold_open):
    url, _ = await fake_http(sse(completion()), hold_open=hold_open)
    assert (await call(url, completion="finish"))["response_complete"]


async def test_usage_after_finish_is_collected_before_done(fake_http):
    usage = {"prompt_tokens": 12, "completion_tokens": 24}
    url, _ = await fake_http(sse(completion(), {"choices": [], "usage": usage}, b"[DONE]"))
    result = await call(url, input_per_million=1, output_per_million=2)
    assert result["response_complete"]
    assert result["usage"] == usage
    assert result["cost"] == .00006


@pytest.mark.parametrize("newline", [b"\r\n", b"\r", b"\n"])
async def test_chunk_boundaries_preserve_utf8_and_sse_delimiters(fake_http, newline):
    body = b"data: " + json.dumps(completion("中文源码"), ensure_ascii=False).encode() + b"\n\ndata: [DONE]\n\n"
    body = body.replace(b"\n", newline)
    url, _ = await fake_http([body[i:i+1] for i in range(len(body))])
    result = await call(url)
    assert result["response_complete"], result
    assert result["content"] == "中文源码"


async def test_nonstream_quota_error_is_preserved(fake_http):
    url, _ = await fake_http(b'{"error":{"code":"insufficient_quota"}}')
    result = await call(url, stream=False, completion="nonstream")
    assert not result["response_complete"]
    assert result["error_category"] == "endpoint_quota"


@pytest.mark.parametrize("events", [
    [completion()],
    [completion(finish="length"), b"[DONE]"],
    [completion(content=""), b"[DONE]"],
    [{"choices": [{"delta": {"reasoning_content": "Thinking"}, "finish_reason": "stop"}]}, b"[DONE]"],
    [completion(), {"error": {"message": "provider failed after content"}}, b"[DONE]"],
])
async def test_incomplete_or_failed_stream_is_never_executable(fake_http, events):
    url, _ = await fake_http(sse(*events))
    result = await call(url)
    assert not result["response_complete"]
    assert result["error_category"] in {"incomplete_response", "provider_error"}


@pytest.mark.parametrize("value", [None, [], {"choices": [None]}, {"choices": [{"message": []}]},
    {"choices": [{"message": {"content": "P(1,2,3,'stone','rock')"}, "finish_reason": "stop"}], "usage": [1]}])
async def test_malformed_json_shapes_return_a_result_instead_of_crashing(fake_http, value):
    url, _ = await fake_http(json.dumps(value).encode(), headers={"Content-Type": "application/json"})
    result = await call(url, stream=False, completion="nonstream", input_per_million=1, output_per_million=1)
    assert not result["response_complete"]
    assert result["error_category"] == "malformed_response"


@pytest.mark.parametrize("stream", [False, True])
async def test_response_byte_limit_is_enforced_while_reading(fake_http, monkeypatch, stream):
    monkeypatch.setattr(inference, "MAX_RESPONSE_BYTES", 1024, raising=False)
    body = sse(completion("x" * 2048), b"[DONE]") if stream else json.dumps({
        "choices": [{"message": {"content": "x" * 2048}, "finish_reason": "stop"}]}).encode()
    url, _ = await fake_http(body)
    settings = {} if stream else {"stream": False, "completion": "nonstream"}
    result = await call(url, **settings)
    assert not result["response_complete"]
    assert result["error_category"] == "malformed_response"


async def test_disconnect_after_post_is_unknown_and_is_not_retried(fake_http):
    url, requests = await fake_http(None)
    result = await call(url)
    assert result["error_category"] == "outcome_unknown"
    assert result["cost"] is None
    assert len(requests) == 1


def reasoning(text="Thinking"):
    return {"choices": [{"index": 0, "delta": {"reasoning_content": text}}]}


@pytest.mark.parametrize("body", [b"", sse(reasoning()), sse(completion(finish=None)),
                                  sse(reasoning()) + b'data: {"choices":'])
async def test_clean_eof_without_semantic_end_retains_unknown_outcome(fake_http, body):
    url, requests = await fake_http(body)
    result = await call(url)
    assert not result["response_complete"]
    assert result["error_category"] == "outcome_unknown"
    assert result["finish_reason"] is None
    assert result["cost"] is None
    assert len(requests) == 1


@pytest.mark.parametrize("parameters", [{}, {"reasoning_effort": "max"}, {"thinking": {"type": "enabled"}}])
async def test_reasoning_keeps_stream_alive_until_complete_answer(fake_http, parameters):
    chunks = [sse(reasoning("规划")) for _ in range(5)]
    chunks += [sse(completion(), b"[DONE]")]
    url, requests = await fake_http(chunks, chunk_delay=.1)
    result = await call(url, first_content_timeout=.3, idle_timeout=.3, total_timeout=2,
                        parameters=parameters)
    assert result["response_complete"], result
    assert result["content"] == completion()["choices"][0]["delta"]["content"]
    assert result["reasoning_content_characters"] == 10
    assert result["first_reasoning_at"] < result["first_content_at"]
    assert {key: value for key, value in requests[0].items() if key not in {"model", "messages", "stream"}} == parameters
    assert len(requests) == 1


def test_stream_policy_change_invalidates_profile(monkeypatch):
    from voxlush.core.config import Config
    from voxlush import inference as policy
    config = Config()
    previous_hash = config.profile_hash()
    monkeypatch.setattr(policy, "STREAM_POLICY_VERSION", "different-policy")
    assert config.profile_hash() != previous_hash


async def test_continuous_reasoning_still_obeys_total_deadline(fake_http):
    url, requests = await fake_http([sse(reasoning()) for _ in range(30)], chunk_delay=.04)
    result = await call(url, first_content_timeout=.2, idle_timeout=.2, total_timeout=.4)
    assert result["error_category"] == "outcome_unknown"
    assert not result["response_complete"]
    assert result["reasoning_content_characters"] > len("Thinking")
    assert result["first_content_at"] is None
    assert result["content"] == ""
    assert result["cost"] is None
    assert result["elapsed_ms"] < 800
    assert len(requests) == 1


async def test_stalled_reasoning_obeys_idle_deadline(fake_http):
    url, requests = await fake_http(sse(reasoning()), hold_open=True)
    result = await call(url, first_content_timeout=.6, idle_timeout=.15, total_timeout=1)
    assert result["error_category"] == "outcome_unknown"
    assert not result["response_complete"]
    assert result["reasoning_content_characters"] == len("Thinking")
    assert result["content"] == ""
    assert result["elapsed_ms"] < 450
    assert len(requests) == 1


@pytest.mark.parametrize("after_reasoning", [False, True])
@pytest.mark.parametrize("heartbeat", [b": heartbeat\n\n", sse(reasoning("")),
                                      sse({"choices": [{"delta": {"role": "assistant"}}]})])
async def test_heartbeats_do_not_extend_first_or_idle_deadline(fake_http, after_reasoning, heartbeat):
    chunks = ([sse(reasoning())] if after_reasoning else []) + [heartbeat] * 15
    chunks += [sse(completion(), b"[DONE]")]
    url, requests = await fake_http(chunks, chunk_delay=.04)
    result = await call(url, first_content_timeout=.2, idle_timeout=.2, total_timeout=1.5)
    assert result["error_category"] == "outcome_unknown"
    assert not result["response_complete"]
    assert result["content"] == ""
    assert result["elapsed_ms"] < 600
    assert len(requests) == 1
