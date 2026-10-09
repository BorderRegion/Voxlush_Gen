import ast
import hashlib
import json
import os
import socket
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit  # noqa: F401 - extracted Handler globals
import queue  # noqa: F401 - extracted response_chunks globals
import logging
import requests
import pytest
import pool_receipts

BASE = Path(os.environ["VOXLUSH_POOL_PATCHED_DIR"]) if os.getenv("VOXLUSH_POOL_PATCHED_DIR") else None
if BASE is None:
    pytest.skip("requires private pinned pool source and prepared release", allow_module_level=True)
ORIGINAL = Path(os.environ["VOXLUSH_POOL_ORIGINAL_DIR"])
TERMINAL = b'data: {"id":"model-fixture","choices":[{"index":0,"delta":{"content":"x=1"},"finish_reason":"stop"}],"usage":{"prompt_tokens":2,"completion_tokens":3}}\n\ndata: [DONE]\n\n'
PARTIAL = b'data: {"choices":[{"delta":{"reasoning_content":"thinking"}}]}\n\n'


def load_worker(patched=True):
    path = BASE / "api_pool.py" if patched else ORIGINAL / "api_pool.py"
    names = {
        "Handler",
        "response_chunks",
        "close_upstream",
        "upstream_request_with_tls_retry",
        "ssl_error_reason",
        "UsageAccumulator",
        "number",
        "request_budget",
        "upstream_quota_error",
    }
    tree = ast.parse(path.read_text())
    nodes = [n for n in tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef)) and n.name in names]
    ns = dict(globals())
    ns.update(
        {
            "log": logging.getLogger("test"),
            "MAX_INFLIGHT_WAIT_SECONDS": 1,
            "REQUEST_TIMEOUT_SECONDS": 3,
            "UPSTREAM_READ_TIMEOUT_SECONDS": 3,
            "UPSTREAM_SLOTS": threading.BoundedSemaphore(3),
            "MAX_ROUTE_ATTEMPTS": 3,
            "RETRYABLE_UPSTREAM_STATUSES": {502, 503, 504},
            "ALLOWED_PATHS": {"/v1/chat/completions"},
            "PROXY_KEY": "fixture",
            "HOP_HEADERS": {"content-length", "transfer-encoding", "connection"},
            "CHAT_MODEL_DEFAULTS": {},
            "IMAGE_PATHS": set(),
            "THREAD_LOCAL": threading.local(),
            "http_session": lambda _: requests.Session(),
            "proxies_for": lambda _: {},
            "request_model": lambda body: json.loads(body)["model"],
            "rewrite_model": lambda body, _: body,
            "sticky_key": lambda body: "fixture",
            "hmac": __import__("hmac"),
            "defaultdict": __import__("collections").defaultdict,
        }
    )
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), ns)
    return ns


@contextmanager
def upstream(body=TERMINAL, status=200, slow=False):
    calls = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            calls.append(self.rfile.read(int(self.headers["Content-Length"])))
            self.send_response(status)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("NVCF-REQID", "upstream-fixture")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if slow:
                time.sleep(0.1)
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), H)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@contextmanager
def worker(url, patched=True):
    ns = load_worker(patched)
    sources = [{"id": str(i), "api_key": "fixture", "base_url": url} for i in range(3)]
    def noop(*args, **kwargs):
        pass
    ns["SOURCES"] = sources
    ns["STATE"] = SimpleNamespace(
        lock=threading.RLock(),
        resolve_model=lambda m, s: m,
        has_catalog=lambda _: False,
        begin=noop,
        candidates=lambda *a: sources,
        routable_locked=lambda s: True,
        claim_candidate=lambda s: True,
        record_route=noop,
        record_attempt_failure=noop,
        mark_error=noop,
        release_candidate=noop,
        abandon=noop,
        finish=lambda *a: 0,
        estimate_cost=lambda *a: (0, False),
    )
    ns["EGRESS"] = SimpleNamespace(assign=lambda _: None, release=noop, mark_unavailable=noop)
    server = ThreadingHTTPServer(("127.0.0.1", 0), ns["Handler"])
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.fixture(autouse=True)
def receipt_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("API_POOL_RECEIPT_DIR", str(tmp_path / "receipts"))


def post(url, rid=None):
    headers = {"Authorization": "Bearer fixture"}
    if rid:
        headers["X-Pool-Request-Id"] = rid
    return requests.post(
        url + "/v1/chat/completions",
        headers=headers,
        json={"model": "fixture", "stream": True, "messages": []},
        timeout=5,
    )


@pytest.mark.parametrize("patched,expected", [(False, 3), (True, 1)])
def test_retry_multiplication_reproduced_and_disabled(patched, expected):
    with upstream(body=b"{}", status=503) as (url, calls), worker(url, patched) as entry:
        response = post(entry, "a" * 32)
    assert response.status_code == 503
    assert len(calls) == expected
    if patched:
        assert pool_receipts.read("a" * 32)["execution_state"] == "execution_unknown"


def test_tls_eof_before_headers_never_retries_tracked_post():
    for strict, expected in [(False, 2), (True, 1)]:
        ns = load_worker()
        calls = []

        def fail(*a, **k):
            calls.append(1)
            raise requests.exceptions.SSLError("unexpected eof")

        ns["http_session"] = lambda _: SimpleNamespace(request=fail)
        with pytest.raises(requests.exceptions.SSLError):
            ns["upstream_request_with_tls_retry"](
                "POST", "http://fixture", None, time.monotonic() + 3, "test", single_attempt=strict
            )
        assert len(calls) == expected


def test_complete_receipt_authenticated_retrievable_duplicate_post_rejected():
    rid = "b" * 32
    with upstream() as (url, calls), worker(url) as entry:
        response = post(entry, rid)
        assert response.status_code == 200 and response.content == TERMINAL
        headers = {"Authorization": "Bearer fixture"}
        meta = requests.get(entry + "/v1/pool/requests/" + rid, headers=headers).json()
        body = requests.get(entry + "/v1/pool/requests/" + rid + "/body", headers=headers).content
        assert hashlib.sha256(body).hexdigest() == meta["body_sha256"]
        assert meta["response_complete"] and meta["execution_state"] == "terminated"
        assert meta["upstream_headers"]["nvcf-reqid"] == "upstream-fixture"
        assert meta["upstream_posts"] == 1 and meta["cost"] is None
        assert meta['source_sha256'] == hashlib.sha256(b'0').hexdigest()
        assert post(entry, rid).status_code == 409
        assert requests.get(entry + "/v1/pool/requests/" + rid).status_code == 401
        assert len(calls) == 1
    # A new owner still sees the durable identity and cannot send it again.
    with pytest.raises(FileExistsError):
        pool_receipts.Receipt(rid, b"anything")


def test_client_disconnect_continues_collecting_terminal_response():
    rid = "c" * 32
    with upstream(slow=True) as (url, calls), worker(url) as entry:
        payload = json.dumps({"model": "fixture", "stream": True, "messages": []}).encode()
        connection = socket.create_connection(("127.0.0.1", int(entry.rsplit(":", 1)[1])))
        connection.sendall(
            b"POST /v1/chat/completions HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer fixture\r\nX-Pool-Request-Id: "
            + rid.encode()
            + b"\r\nContent-Length: "
            + str(len(payload)).encode()
            + b"\r\n\r\n"
            + payload
        )
        connection.shutdown(socket.SHUT_RDWR)
        connection.close()
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            try:
                meta = pool_receipts.read(rid)
                if meta["state"] == "settled":
                    break
            except FileNotFoundError:
                pass
            time.sleep(0.01)
        assert meta["execution_state"] == "terminated" and meta["response_complete"]
        assert meta["downstream_disconnected"] and len(calls) == 1
        assert pool_receipts.raw_path(rid).read_bytes() == TERMINAL


def test_eof_retains_unknown_and_complete_usage_is_not_required_for_termination():
    rid = "d" * 32
    with upstream(body=PARTIAL) as (url, calls), worker(url) as entry:
        post(entry, rid)
    meta = pool_receipts.read(rid)
    assert meta["execution_state"] == "execution_unknown" and not meta["response_complete"]
    assert meta["cost"] is None and "usage" not in meta


def test_worker_crash_or_local_deadline_does_not_certify_upstream_stop():
    receipt = pool_receipts.Receipt("e" * 32, b"{}")
    receipt.dispatch()
    assert pool_receipts.read("e" * 32)["execution_state"] == "execution_unknown"
    receipt.end("Timeout")
    assert pool_receipts.read("e" * 32)["execution_state"] == "execution_unknown"


def test_gateway_pins_ids_and_queries_do_not_compete_with_generation_slots():
    import asyncio
    import aiohttp
    from aiohttp import web

    async def run():
        async def report(request):
            if request.path.endswith("/body"):
                response = web.StreamResponse()
                await response.prepare(request)
                for _ in range(4):
                    await response.write(b"x" * 65536)
                await response.write_eof()
                return response
            return web.json_response({"worker": request.app["number"]})

        runners = []
        nodes = []
        for i in range(2):
            app = web.Application()
            app["number"] = i
            app.router.add_get("/v1/pool/requests/{rid}", report)
            app.router.add_get("/v1/pool/requests/{rid}/body", report)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            runners.append(runner)
            nodes.append({"url": f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"})
        ns = {
            "NODES": nodes,
            "CONFIG": {},
            "authorized": lambda req: req.headers.get("Authorization") == "Bearer fixture",
            "error": lambda message, status=503: web.json_response({"error": message}, status=status),
            "web": web,
            "ClientTimeout": aiohttp.ClientTimeout,
        }
        tree = ast.parse((BASE / "cluster_gateway.py").read_text())
        exec(
            compile(
                ast.Module(
                    body=[
                        n
                        for n in tree.body
                        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name in {"receipt_query", "routing"}
                    ],
                    type_ignores=[],
                ),
                "gateway",
                "exec",
            ),
            ns,
        )
        gateway = web.Application()
        gateway["session"] = aiohttp.ClientSession()
        gateway.router.add_get("/v1/pool/requests/{request_id}", ns["receipt_query"])
        gateway.router.add_get("/v1/pool/requests/{request_id}/body", ns["receipt_query"])
        runner = web.AppRunner(gateway)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        runners.append(runner)
        address = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
        try:
            async with aiohttp.ClientSession(headers={"Authorization": "Bearer fixture"}) as session:
                for suffix in ["0", "1"]:
                    async with session.get(address + "/v1/pool/requests/" + "a" * 31 + suffix) as response:
                        assert (await response.json())["worker"] == int(suffix)
                async with session.get(address + "/v1/pool/requests/" + "a" * 32 + "/body") as response:
                    assert len(await response.read()) == 4 * 65536
                async with session.get(address + "/v1/pool/requests/not-a-valid-id") as response:
                    assert response.status == 400
        finally:
            await gateway["session"].close()
            for runner in runners:
                await runner.cleanup()

    asyncio.run(run())


def test_worker_predispatch_rejection_is_explicit_not_sent():
    ns = load_worker()

    class Full:
        def acquire(self, timeout):
            return False

    ns["UPSTREAM_SLOTS"] = Full()
    server = ThreadingHTTPServer(("127.0.0.1", 0), ns["Handler"])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        response = post(f"http://127.0.0.1:{server.server_port}", "f" * 32)
        assert response.status_code == 503
        assert response.headers["X-Pool-Execution-State"] == "not_sent"
        assert response.headers["X-Pool-Receipt-Version"] == "pool.receipt.v1"
        assert not pool_receipts.root().exists()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_gateway_forward_uses_same_worker_and_never_fails_over():
    import asyncio
    import aiohttp
    from aiohttp import web

    async def run():
        calls = []
        runners = []
        nodes = []

        async def handle(request):
            calls.append((request.app["number"], request.headers.get("X-Pool-Request-Id")))
            return web.json_response({"worker": request.app["number"]})

        for i in range(2):
            app = web.Application()
            app["number"] = i
            app.router.add_post("/v1/chat/completions", handle)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            runners.append(runner)
            nodes.append(
                dict(
                    id=str(i),
                    url=f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}",
                    reachable=True,
                    active=0,
                    peak=0,
                    capacity=1,
                    models={"fixture": {}},
                )
            )
        ns = dict(
            NODES=nodes,
            CONFIG={},
            ACTIVE=0,
            PEAK=0,
            CURSOR=0,
            LIMIT=2,
            HOP={"host", "content-length", "transfer-encoding"},
            os=os,
            json=json,
            web=web,
            ClientTimeout=aiohttp.ClientTimeout,
            authorized=lambda req: True,
            error=lambda message, status=503: web.json_response({"error": message}, status=status),
            request_budget=lambda *a: 3,
        )
        tree = ast.parse((BASE / "cluster_gateway.py").read_text())
        exec(
            compile(
                ast.Module(
                    body=[
                        n for n in tree.body if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name in {"forward", "routing"}
                    ],
                    type_ignores=[],
                ),
                "gateway",
                "exec",
            ),
            ns,
        )
        app = web.Application()
        app["session"] = aiohttp.ClientSession()
        app.router.add_post("/v1/chat/completions", ns["forward"])
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        runners.append(runner)
        address = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/v1/chat/completions"
        try:
            async with aiohttp.ClientSession() as session:
                for suffix in ("0", "1", "0"):
                    async with session.post(
                        address, json={"model": "fixture"}, headers={"X-Pool-Request-Id": "a" * 31 + suffix}
                    ) as response:
                        assert (await response.json())["worker"] == int(suffix)
                nodes[0]["reachable"] = False
                async with session.post(
                    address, json={"model": "fixture"}, headers={"X-Pool-Request-Id": "a" * 32}
                ) as response:
                    assert response.status == 503 and response.headers["X-Pool-Execution-State"] == "not_sent"
                    assert response.headers["X-Pool-Request-Id"] == "a" * 32
                assert [c[0] for c in calls] == [0, 1, 0] and ns["ACTIVE"] == 0
        finally:
            await app["session"].close()
            for r in runners:
                await r.cleanup()

    asyncio.run(run())


def test_named_model_pool_routes_post_and_receipt_without_legacy_remap():
    import asyncio
    import aiohttp
    from aiohttp import web

    async def run():
        calls, runners, nodes = [], [], []

        async def handle(request):
            calls.append((request.app['number'], request.method, request.path))
            if request.path.endswith('/body') and ('f'*32) in request.path:
                return web.Response(body=b'x'*(17*1024*1024))
            return web.json_response({'worker':request.app['number'], 'path':request.path})

        for i in range(2):
            worker = web.Application()
            worker['number'] = i
            worker.router.add_route('*', '/v1/{path:.*}', handle)
            runner = web.AppRunner(worker)
            await runner.setup()
            site = web.TCPSite(runner, '127.0.0.1', 0)
            await site.start()
            runners.append(runner)
            nodes.append(dict(id=str(i), url=f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}',
                              reachable=True, active=0, peak=0, capacity=1,
                              models={'legacy':{}}))  # Special aliases are hidden in shared catalog.
        ns = dict(NODES=nodes, CONFIG={'model_pools':{'independent':{'nodes':['0'], 'models':['special']}}},
                  ACTIVE=0, PEAK=0, CURSOR=0, LIMIT=2,
                  HOP={'host','content-length','transfer-encoding'}, os=os, json=json, web=web,
                  ClientTimeout=aiohttp.ClientTimeout,
                  authorized=lambda req: req.headers.get('Authorization') == 'Bearer fixture',
                  error=lambda message,status=503:web.json_response({'error':message},status=status),
                  request_budget=lambda *a:3)
        tree = ast.parse((BASE/'cluster_gateway.py').read_text())
        functions = [n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))
                     and n.name in {'routing','forward','receipt_query','models'}]
        exec(compile(ast.Module(body=functions,type_ignores=[]),'gateway','exec'),ns)
        app = web.Application()
        app['session'] = aiohttp.ClientSession()
        for prefix in ('/v1', '/v1/pools/{pool_name}'):
            app.router.add_get(prefix+'/models',ns['models'])
            app.router.add_post(prefix+'/chat/completions',ns['forward'])
            app.router.add_get(prefix+'/pool/requests/{request_id}',ns['receipt_query'])
            app.router.add_get(prefix+'/pool/requests/{request_id}/body',ns['receipt_query'])
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner,'127.0.0.1',0)
        await site.start()
        runners.append(runner)
        url = f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}'
        rid = 'a'*31+'1'  # Legacy hashes to worker 1, which lacks the special model.
        try:
            async with aiohttp.ClientSession(headers={'Authorization':'Bearer fixture'}) as client:
                for prefix, model, expected in [('/v1','legacy',1),('/v1/pools/independent','special',0)]:
                    async with client.post(url+prefix+'/chat/completions',json={'model':model},
                                           headers={'X-Pool-Request-Id':rid}) as response:
                        assert (await response.json())['worker'] == expected
                    for suffix in ('','/body'):
                        async with client.get(url+prefix+'/pool/requests/'+rid+suffix) as response:
                            result = await response.json()
                            assert result == {'worker':expected,'path':'/v1/pool/requests/'+rid+suffix}
                async with client.get(url+'/v1/pools/independent/pool/requests/'+('f'*32)+'/body') as response:
                    assert response.status == 200 and len(await response.read()) == 17*1024*1024
                before = len(calls)
                async with client.post(url+'/v1/pools/independent/chat/completions',json={'model':'legacy'},
                                       headers={'X-Pool-Request-Id':rid}) as response:
                    assert response.status == 400 and response.headers['X-Pool-Execution-State'] == 'not_sent'
                async with client.get(url+'/v1/pools/absent/pool/requests/'+rid) as response:
                    assert response.status == 404  # Does not imply termination or query another pool.
                async with client.get(url+'/v1/pools/independent/models') as response:
                    assert len((await response.json())['data']) == 1
                nodes[0]['reachable'] = False
                async with client.post(url+'/v1/pools/independent/chat/completions',json={'model':'special'},
                                       headers={'X-Pool-Request-Id':rid}) as response:
                    assert response.status == 503
                assert len(calls) == before and ns['ACTIVE'] == 0
                async with client.get(url+'/v1/pools/independent/pool/requests/'+rid,
                                      headers={'Authorization':'Bearer wrong'}) as response:
                    assert response.status == 401
        finally:
            await app['session'].close()
            for runner in runners:
                await runner.cleanup()
    asyncio.run(run())


def test_long_reasoning_receipt_survives_old_16_mib_boundary():
    chunk = b'data: '+json.dumps({'choices':[{'delta':{'reasoning_content':'x'*4096}}]}).encode()+b'\n\n'
    body = chunk * 4200 + TERMINAL
    assert len(body) > 16 * 1024 * 1024
    with upstream(body) as (url, calls), worker(url) as entry:
        rid='f'*32
        response=post(entry, rid)
        assert response.status_code == 200
        meta=requests.get(entry+'/v1/pool/requests/'+rid,headers={'Authorization':'Bearer fixture'}).json()
        saved=requests.get(entry+'/v1/pool/requests/'+rid+'/body',headers={'Authorization':'Bearer fixture'})
        assert meta['response_complete'] and meta['execution_state']=='terminated'
        assert saved.content == body and meta['body_sha256']==hashlib.sha256(body).hexdigest()
        assert len(calls)==1
