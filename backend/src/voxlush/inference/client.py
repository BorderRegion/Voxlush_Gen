"""One HTTP adapter, no hidden POST retries; termination evidence is explicit."""
from __future__ import annotations
import asyncio
import json
import math
import os
import re
import time
from dataclasses import asdict, dataclass, field
import httpx
from voxlush.core.config import Endpoint

MAX_RESPONSE_BYTES = 16 * 1024 * 1024


def provider_error(error):
    if isinstance(error,dict) and any(isinstance(error.get(key),str) and
                                    error[key] in {"insufficient_quota", "billing_hard_limit_reached"}
                                    for key in ("code", "type")):
        return "endpoint_quota"
    return "provider_error"


def retry_delay(value):
    try:
        delay = float(value)
        if not math.isfinite(delay):
            return 5
    except ValueError:
        from email.utils import parsedate_to_datetime
        try:
            delay = parsedate_to_datetime(value).timestamp() - time.time()
        except (ValueError,TypeError,OverflowError):
            return 5
    return max(0,min(3600,delay))


async def read_bounded(response, limit, *, truncate=False):
    chunks, size = [], 0
    async for chunk in response.aiter_bytes():
        if size + len(chunk) > limit:
            if truncate:
                chunks.append(chunk[:limit-size])
                break
            raise ValueError("response byte limit")
        chunks.append(chunk)
        size += len(chunk)
    return b"".join(chunks)


async def bounded_lines(response):
    """Bound bytes before buffering a line, including an unterminated SSE line."""
    fragments, size, trailing_cr = [], 0, False
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > MAX_RESPONSE_BYTES:
            raise ValueError("response byte limit")
        if trailing_cr and chunk.startswith(b"\n"):
            chunk = chunk[1:]
        trailing_cr = chunk.endswith(b"\r")
        parts = re.split(br"(\r\n|\r|\n)", chunk)
        for index in range(0, len(parts), 2):
            if parts[index]:
                fragments.append(parts[index])
            if index + 1 < len(parts):
                yield b"".join(fragments).decode("utf-8", errors="replace")
                fragments.clear()
    if fragments:
        yield b"".join(fragments).decode("utf-8", errors="replace")

@dataclass
class ModelResult:
    request_id: str | None = None
    attempt_id: str | None = None
    role: str | None = None
    endpoint_alias: str | None = None
    requested_model: str | None = None
    reported_model: str | None = None
    response_complete: bool = False
    finish_reason: str | None = None
    content: str = ""
    usage: dict = field(default_factory=dict)
    billing_status: str = "unknown"
    cost: float | None = None
    first_content_at: float | None = None
    first_reasoning_at: float | None = None
    reasoning_content_characters: int = 0
    elapsed_ms: float = 0
    error_category: str | None = None
    retry_after: float | None = None
    raw: str = ""

class PoolClient:
    def __init__(self, max_connections=512, transport=None):
        self.client = httpx.AsyncClient(
            limits=httpx.Limits(max_connections=max_connections,max_keepalive_connections=min(64,max_connections)),
            transport=transport, follow_redirects=False)

    async def close(self):
        await self.client.aclose()

    async def call(self, endpoint: Endpoint, messages: list, attempt_id: str, role: str) -> dict:
        start = time.monotonic()
        r = ModelResult(attempt_id=attempt_id,role=role,endpoint_alias=endpoint.alias,requested_model=endpoint.model)
        headers = {"Content-Type":"application/json"}
        key = os.getenv(endpoint.api_key_env)
        if key:
            headers["Authorization"] = "Bearer " + key
        payload = {**endpoint.parameters,"model":endpoint.model,"messages":messages,"stream":endpoint.stream}
        url = endpoint.base_url.rstrip("/") + "/chat/completions"
        try:
            async with asyncio.timeout(endpoint.total_timeout):
                async with self.client.stream("POST",url,json=payload,headers=headers,
                    timeout=httpx.Timeout(connect=endpoint.connect_timeout,read=endpoint.idle_timeout,write=endpoint.connect_timeout,pool=endpoint.connect_timeout)) as response:
                    r.request_id = response.headers.get("x-request-id")
                    if response.status_code >= 300:
                        if response.status_code == 429:
                            r.error_category = "rate_limited"
                        elif response.status_code in (401,403):
                            r.error_category = "endpoint_auth"
                        elif response.status_code == 402:
                            r.error_category = "endpoint_quota"
                        elif 300 <= response.status_code < 400 or response.status_code in (400,404,422):
                            r.error_category = "endpoint_configuration"
                        elif response.status_code >= 500:
                            r.error_category = "service_busy"
                        else:
                            r.error_category = "provider_error"
                        if response.status_code == 429 or (response.status_code >= 500 and "retry-after" in response.headers):
                            r.retry_after = retry_delay(response.headers.get("retry-after","5"))
                        r.raw = (await read_bounded(response,65536,truncate=True)).decode(errors="replace")
                        try:
                            error_body = json.loads(r.raw)
                            if isinstance(error_body,dict) and provider_error(error_body.get("error")) == "endpoint_quota":
                                r.error_category = "endpoint_quota"
                        except ValueError:
                            pass
                    elif endpoint.stream:
                        await self._stream(response,endpoint,r,start)
                    else:
                        data = await read_bounded(response,MAX_RESPONSE_BYTES)
                        r.raw = data.decode()
                        obj = json.loads(r.raw)
                        self._consume(obj,r,stream=False)
                        r.response_complete = bool(r.content.strip()) and r.finish_reason == "stop" and not obj.get("error")
                        if not r.response_complete:
                            r.error_category = r.error_category or "incomplete_response"
        except (httpx.ConnectError,httpx.ConnectTimeout,httpx.PoolTimeout):
            r.error_category = "not_sent"
        except (httpx.ReadError,httpx.WriteError,httpx.ReadTimeout,httpx.WriteTimeout,httpx.RemoteProtocolError,TimeoutError,asyncio.CancelledError):
            r.error_category = r.error_category or "outcome_unknown"
        except (ValueError,KeyError,TypeError,IndexError):
            r.error_category = "malformed_response"
        r.elapsed_ms = (time.monotonic()-start)*1000
        if r.usage and endpoint.input_per_million is not None and endpoint.output_per_million is not None:
            inp,out = r.usage.get("prompt_tokens"),r.usage.get("completion_tokens")
            if type(inp) is int and type(out) is int and inp >= 0 and out >= 0:
                try:
                    cost = (inp*endpoint.input_per_million+out*endpoint.output_per_million)/1_000_000
                    if not math.isfinite(cost):
                        raise ValueError("nonfinite usage cost")
                    r.cost, r.billing_status = cost, "actual"
                except (ValueError,OverflowError):
                    r.response_complete = False
                    r.error_category = "malformed_response"
        return asdict(r)

    def _consume(self,obj,r,stream=True):
        if not isinstance(obj,dict):
            raise ValueError("response must be a JSON object")
        if obj.get("error"):
            r.error_category = provider_error(obj["error"])
            return
        r.request_id = obj.get("id",r.request_id)
        r.reported_model = obj.get("model",r.reported_model)
        usage = obj.get("usage")
        if usage is not None:
            if not isinstance(usage,dict):
                raise ValueError("usage must be an object")
            for key in ("prompt_tokens", "completion_tokens"):
                if key in usage and (type(usage[key]) is not int or usage[key] < 0):
                    raise ValueError("usage tokens must be nonnegative integers")
            if usage.get("completion_tokens_details") is not None and not isinstance(usage["completion_tokens_details"],dict):
                raise ValueError("completion token details must be an object")
            r.usage = usage
        choices = obj.get("choices",[])
        if not isinstance(choices,list):
            raise ValueError("choices must be an array")
        for choice in choices:
            if not isinstance(choice,dict):
                raise ValueError("choice must be an object")
            if choice.get("index",0) != 0:
                continue
            data = choice.get("delta",{}) if stream else choice.get("message",{})
            if data is None:
                data = {}
            if not isinstance(data,dict):
                raise ValueError("message/delta must be an object")
            reasoning = data.get("reasoning_content")
            if isinstance(reasoning,str) and reasoning:
                if r.first_reasoning_at is None:
                    r.first_reasoning_at = time.time()
                # Raw SSE retains reasoning; it must never enter executable content.
                r.reasoning_content_characters += len(reasoning)
            content = data.get("content")
            if isinstance(content,str) and content:
                if r.first_content_at is None:
                    r.first_content_at = time.time()
                r.content += content
            if choice.get("finish_reason"):
                r.finish_reason = choice["finish_reason"]

    async def _stream(self,response,endpoint,r,start):
        lines = bounded_lines(response).__aiter__()
        done = False
        event = []
        last_progress = start
        raw = []
        try:
            while True:
                has_progress = bool(r.content) or r.reasoning_content_characters > 0
                deadline = last_progress+endpoint.idle_timeout if has_progress else start+endpoint.first_content_timeout
                timeout = deadline-time.monotonic()
                if timeout <= 0:
                    raise TimeoutError("no answer or reasoning progress")
                try:
                    line = await asyncio.wait_for(anext(lines),timeout)
                except StopAsyncIteration:
                    break
                raw.append(line)
                if line.startswith("data:"):
                    event.append(line[5:].lstrip())
                elif not line and event:
                    data = "\n".join(event)
                    event = []
                    if data == "[DONE]":
                        done = True
                        break
                    before = len(r.content) + r.reasoning_content_characters
                    self._consume(json.loads(data),r)
                    if len(r.content) + r.reasoning_content_characters > before:
                        last_progress = time.monotonic()
                    if endpoint.completion == "finish" and r.finish_reason:
                        break
        finally:
            r.raw = "\n".join(raw)
        r.response_complete = (bool(r.content.strip()) and r.finish_reason == "stop" and
            (done or endpoint.completion == "finish") and not r.error_category and not event)
        if not r.response_complete and not r.error_category:
            # A proxy may close HTTP cleanly while upstream generation is still
            # running. EOF alone cannot release execution occupancy or authorize
            # another POST; require semantic termination even for a failed answer.
            r.error_category = "incomplete_response" if done or r.finish_reason else "outcome_unknown"
