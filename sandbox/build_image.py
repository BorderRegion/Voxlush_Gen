"""Prepare the version-bound isolated renderer/executor without copying local datasets."""

from pathlib import Path
import hashlib
import subprocess

root = Path(__file__).resolve().parents[1]
resources = root / "backend/src/voxlush/voxel/resources"
h = hashlib.sha256()
for name in ("sandbox_worker.py", "legacy_render.py"):
    h.update(name.encode() + b"\0" + (resources / name).read_bytes())
subprocess.run(
    [
        "docker",
        "build",
        "-t",
        "voxlush-sandbox:v1",
        "--build-arg",
        "runtime_hash=" + h.hexdigest(),
        "-f",
        "sandbox/Dockerfile",
        ".",
    ],
    cwd=root,
    check=True,
)
