import asyncio
import json

import pytest_asyncio


@pytest_asyncio.fixture
async def fake_http():
    """Actual loopback HTTP/SSE transport; it never contacts a model provider."""
    servers, writers, handlers = [], set(), set()

    async def start(body, *, status=200, headers=None, hold_open=False):
        requests = []

        async def handle(reader, writer):
            task = asyncio.current_task()
            handlers.add(task)
            writers.add(writer)
            try:
                head = await reader.readuntil(b"\r\n\r\n")
                fields = dict(line.split(b":", 1) for line in head.split(b"\r\n")[1:] if b":" in line)
                length = int(next((v for k, v in fields.items() if k.lower() == b"content-length"), b"0"))
                requests.append(json.loads(await reader.readexactly(length)))
                if body is None:
                    return  # Disconnect after receiving the POST, before a response.
                response_headers = {"Content-Type": "text/event-stream", **(headers or {})}
                chunks = body if isinstance(body,list) else [body]
                if hold_open or isinstance(body,list):
                    response_headers["Transfer-Encoding"] = "chunked"
                    payload = b"".join(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n" for chunk in chunks)
                    if not hold_open:
                        payload += b"0\r\n\r\n"
                else:
                    response_headers.update({"Content-Length": str(len(body)), "Connection": "close"})
                    payload = body
                head = f"HTTP/1.1 {status} Fixture\r\n".encode()
                head += b"".join(f"{key}: {value}\r\n".encode() for key, value in response_headers.items())
                writer.write(head + b"\r\n" + payload)
                await writer.drain()
                if hold_open:
                    await reader.read()
            except (ConnectionError, asyncio.IncompleteReadError):
                pass
            finally:
                writer.close()
                await writer.wait_closed()
                writers.discard(writer)
                handlers.discard(task)

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        servers.append(server)
        return f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1", requests

    yield start
    for server in servers:
        server.close()
        await server.wait_closed()
    for writer in list(writers):
        writer.close()
    for task in list(handlers):
        task.cancel()
    await asyncio.gather(*handlers, return_exceptions=True)
