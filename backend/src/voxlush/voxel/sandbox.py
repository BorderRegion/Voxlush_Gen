"""Disposable Docker execution. There is deliberately no host execution fallback."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import threading
import time
import uuid

RESOURCES = Path(__file__).parent / "resources"
DEFAULT_IMAGE = "voxlush-sandbox:v1"
ALLOWED = {
    "sample.json",
    "spec.json",
    "preservation_reference.json",
    "probe.json",
    "previews/view_a.webp",
    "previews/view_b.webp",
    "previews/contact.webp",
}


class SandboxError(RuntimeError):
    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(reason + (": " + detail if detail else ""))


def runtime_hash() -> str:
    h = hashlib.sha256()
    for name in ("sandbox_worker.py", "legacy_render.py"):
        h.update(name.encode() + b"\0" + (RESOURCES / name).read_bytes())
    return h.hexdigest()


def image_info(image: str = DEFAULT_IMAGE) -> dict:
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image], capture_output=True, timeout=10, check=True
        )
        info = json.loads(result.stdout)[0]
    except (OSError, subprocess.SubprocessError, ValueError, IndexError) as exc:
        raise SandboxError("sandbox_unavailable", str(exc)) from exc
    if info.get("Config", {}).get("Labels", {}).get("voxlush.runtime") != runtime_hash():
        raise SandboxError("sandbox_image_version_mismatch", "Rebuild with python sandbox/build_image.py")
    return {"image_id": info["Id"], "runtime_hash": runtime_hash()}


def run(
    payload: bytes, *, mode: str = "build", config: dict | None = None, seed: int = 0
) -> tuple[dict[str, bytes], dict]:
    config = config or {}
    info = image_info(config.get("sandbox_image", DEFAULT_IMAGE))
    timeout = min(300, max(0.1, float(config.get("build_timeout_seconds", 60))))
    memory = min(2048, max(64, int(config.get("sandbox_memory_mb", 512))))
    max_output = min(256 * 1024**2, int(config.get("max_output_bytes", 128 * 1024**2)))
    name = "voxlush-" + uuid.uuid4().hex
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="voxlush-isolated-input-") as directory:
        root = Path(directory)
        root.chmod(0o755)
        path = root / ("sample.json" if mode == "render" else "build.py")
        path.write_bytes(payload)
        path.chmod(0o444)
        command = [
            "docker",
            "run",
            "--rm",
            "--name",
            name,
            "--network",
            "none",
            "--read-only",
            "--user",
            "10001:10001",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "32",
            "--memory",
            f"{memory}m",
            "--memory-swap",
            f"{memory}m",
            "--cpus",
            "1",
            "--ulimit",
            "nofile=64:64",
            "--ulimit",
            "fsize=100663296:100663296",
            "--ulimit",
            "core=0:0",
            "--tmpfs",
            "/output:rw,noexec,nosuid,nodev,size=256m,uid=10001,gid=10001",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=32m,uid=10001,gid=10001",
            "--mount",
            f"type=bind,src={root},dst=/input,readonly",
            "--env",
            f"PYTHONHASHSEED={int(seed) % (2**32)}",
            info["image_id"],
            mode,
        ]
        try:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as exc:
            raise SandboxError("sandbox_unavailable", str(exc)) from exc
        chunks: list[bytes] = []
        errors: list[bytes] = []
        overflow = threading.Event()

        def read_bounded(pipe, target: list[bytes], limit: int):
            size = 0
            while True:
                data = pipe.read(65536)
                if not data:
                    return
                if size + len(data) > limit:
                    overflow.set()
                    return
                target.append(data)
                size += len(data)

        readers = [
            threading.Thread(target=read_bounded, args=(process.stdout, chunks, max_output), daemon=True),
            threading.Thread(target=read_bounded, args=(process.stderr, errors, 1024**2), daemon=True),
        ]
        for reader in readers:
            reader.start()
        reason = None
        try:
            while process.poll() is None:
                if overflow.is_set():
                    reason = "sandbox_output_limit"
                    break
                if time.monotonic() - started > timeout:
                    reason = "sandbox_timeout"
                    break
                time.sleep(0.02)
            if reason:
                subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=10)
                process.kill()
            process.wait(timeout=10)
        finally:
            if process.poll() is None:
                process.kill()
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=10)
            for reader in readers:
                reader.join(timeout=2)
            process.stdout.close()
            process.stderr.close()
        stderr = b"".join(errors).decode("utf-8", errors="replace")[-12000:]
        if reason or overflow.is_set():
            raise SandboxError(reason or "sandbox_output_limit", stderr)
        if process.returncode != 0:
            raise SandboxError("sandbox_execution_failed", stderr)
        artifacts = unpack(b"".join(chunks), max_output)
    return artifacts, {
        **info,
        "isolation": "docker_nonroot_readonly_network_none",
        "duration_seconds": round(time.monotonic() - started, 3),
        "memory_limit_mb": memory,
        "timeout_seconds": timeout,
        "network": "none",
        "uid": 10001,
    }


def unpack(data: bytes, max_bytes: int) -> dict[str, bytes]:
    result = {}
    total = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
            for member in archive:
                if member.name not in ALLOWED or member.name in result or not member.isfile():
                    raise SandboxError("sandbox_invalid_artifact", member.name)
                total += member.size
                if member.size < 0 or total > max_bytes:
                    raise SandboxError("sandbox_output_limit")
                handle = archive.extractfile(member)
                result[member.name] = handle.read(member.size)
                if len(result[member.name]) != member.size:
                    raise SandboxError("sandbox_truncated_artifact")
    except (tarfile.TarError, OSError) as exc:
        raise SandboxError("sandbox_invalid_archive", str(exc)) from exc
    return result
