"""One HTTP adapter, no hidden POST retries; termination evidence is explicit."""
from __future__ import annotations
import asyncio
import json
import os
import time
from dataclasses import asdict, dataclass, field
import httpx
from voxlush.core.config import Endpoint

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
                    if response.status_code >= 400:
                        raw = await response.aread()
                        r.raw = raw[:65536].decode(errors="replace")
                        if response.status_code == 429:
                            r.error_category = "rate_limited"
                            try:
                                r.retry_after = max(0,min(3600,float(response.headers.get("retry-after","5"))))
                            except ValueError:
                                from email.utils import parsedate_to_datetime
                                try:
                                    r.retry_after = max(0,min(3600,parsedate_to_datetime(response.headers["retry-after"]).timestamp()-time.time()))
                                except (ValueError,KeyError,TypeError):
                                    r.retry_after = 5
                        elif response.status_code in (401,403):
                            r.error_category = "endpoint_auth"
                        elif response.status_code in (400,404,422):
                            r.error_category = "endpoint_configuration"
                        elif response.status_code >= 500:
                            r.error_category = "service_busy"
                        else:
                            r.error_category = "provider_error"
                    elif endpoint.stream:
                        await self._stream(response,endpoint,r,start)
                    else:
                        data = await response.aread()
                        if len(data)>16*1024*1024:
                            raise ValueError("response byte limit")
                        r.raw = data.decode()
                        obj = json.loads(r.raw)
                        self._consume(obj,r,stream=False)
                        r.response_complete = bool(r.content.strip()) and r.finish_reason == "stop" and not obj.get("error")
                        if not r.response_complete:
                            r.error_category = "incomplete_response"
        except (httpx.ConnectError,httpx.ConnectTimeout,httpx.PoolTimeout):
            r.error_category = "not_sent"
        except (httpx.ReadError,httpx.WriteError,httpx.ReadTimeout,httpx.WriteTimeout,httpx.RemoteProtocolError,TimeoutError,asyncio.CancelledError):
            r.error_category = "outcome_unknown"
        except (ValueError,KeyError,TypeError,IndexError):
            r.error_category = "malformed_response"
        r.elapsed_ms = (time.monotonic()-start)*1000
        if r.usage and endpoint.input_per_million is not None and endpoint.output_per_million is not None:
            inp,out = r.usage.get("prompt_tokens"),r.usage.get("completion_tokens")
            if isinstance(inp,int) and isinstance(out,int) and inp >= 0 and out >= 0:
                r.cost = (inp*endpoint.input_per_million+out*endpoint.output_per_million)/1_000_000
                r.billing_status = "actual"
        return asdict(r)

    def _consume(self,obj,r,stream=True):
        if obj.get("error"):
            r.error_category = "provider_error"
            return
        r.request_id = obj.get("id",r.request_id)
        r.reported_model = obj.get("model",r.reported_model)
        if obj.get("usage"):
            r.usage = obj["usage"]
        for choice in obj.get("choices",[]):
            if choice.get("index",0) != 0:
                continue
            data = choice.get("delta",{}) if stream else choice.get("message",{})
            content = data.get("content")
            if isinstance(content,str) and content:
                if r.first_content_at is None:
                    r.first_content_at = time.time()
                r.content += content
            if choice.get("finish_reason"):
                r.finish_reason = choice["finish_reason"]

    async def _stream(self,response,endpoint,r,start):
        lines = response.aiter_lines().__aiter__()
        done = False
        event = []
        last_content = start
        raw = []
        size = 0
        while True:
            timeout = ((last_content+endpoint.idle_timeout) if r.content else (start+endpoint.first_content_timeout))-time.monotonic()
            if timeout <= 0:
                raise TimeoutError("no effective content progress")
            try:
                line = await asyncio.wait_for(anext(lines),timeout)
            except StopAsyncIteration:
                break
            size += len(line.encode())+1
            if size>16*1024*1024:
                raise ValueError("response byte limit")
            raw.append(line)
            if line.startswith("data:"):
                event.append(line[5:].lstrip())
            elif not line and event:
                data = "\n".join(event)
                event = []
                if data == "[DONE]":
                    done = True
                    continue
                before = len(r.content)
                self._consume(json.loads(data),r)
                if len(r.content)>before:
                    last_content = time.monotonic()
        r.raw = "\n".join(raw)
        r.response_complete = (bool(r.content.strip()) and r.finish_reason == "stop" and
            (done or endpoint.completion == "finish") and not r.error_category and not event)
        if not r.response_complete and not r.error_category:
            r.error_category = "incomplete_response"
