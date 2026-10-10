"""Build a minimal scratch image from an installed, pinned local Python runtime.

Run with .venv/bin/python. No source, environment, credentials or datasets are copied.
The resulting image identity and runtime manifest are recorded by each build.
"""

import hashlib
import argparse
import importlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('--tag', default='voxlush-sandbox:v2')
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
resources = root / "backend/src/voxlush/voxel/resources"
h = hashlib.sha256()
for name in ("sandbox_worker.py", "legacy_render.py"):
    h.update(name.encode() + b"\0" + (resources / name).read_bytes())
if sys.version_info[:2] != (3, 12):
    raise RuntimeError("Python 3.12 runtime is required")
modules = [importlib.import_module(name) for name in ("numpy", "PIL")]
if [module.__version__ for module in modules] != ["2.2.5", "11.2.1"]:
    raise RuntimeError("Install the project pinned NumPy/Pillow versions first")
with tempfile.TemporaryDirectory(prefix="voxlush-runtime-image-") as directory:
    context = Path(directory)
    filesystem = context / "rootfs"
    filesystem.mkdir()
    interpreter = Path(sys.executable).resolve()
    target_python = Path("/usr/bin/python3.12")

    def copy_file(source, target):
        target = filesystem / str(target).lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target, follow_symlinks=True)

    copy_file(interpreter, target_python)
    stdlib = Path(sysconfig.get_path("stdlib"))
    shutil.copytree(
        stdlib,
        filesystem / "usr/lib/python3.12",
        ignore=shutil.ignore_patterns("__pycache__", "test", "tests", "site-packages", "dist-packages"),
    )
    for module in modules:
        package = Path(module.__file__).parent
        target = filesystem / "usr/local/lib/python3.12/dist-packages" / package.name
        shutil.copytree(package, target, ignore=shutil.ignore_patterns("__pycache__", "tests"))
        libraries = package.parent / (("pillow" if package.name == "PIL" else package.name.lower()) + ".libs")
        if libraries.exists():
            shutil.copytree(libraries, target.parent / libraries.name)
    libraries = set()
    binaries = [interpreter, *filesystem.rglob("*.so"), *filesystem.rglob("*.so.*")]
    for binary in binaries:
        result = subprocess.run(["ldd", str(binary)], capture_output=True, text=True)
        for line in result.stdout.splitlines():
            match = re.search(r"(?:=>\s+)?(/[^\s]+)", line)
            if match and Path(match[1]).is_file() and not Path(match[1]).is_relative_to(filesystem):
                libraries.add(Path(match[1]))
    for library in libraries:
        copy_file(library, library)
    for name in ("sandbox_worker.py", "legacy_render.py"):
        copy_file(resources / name, Path("/runtime") / name)
    for name in ("tmp", "output", "input"):
        (filesystem / name).mkdir()
    manifest = {
        "python": sys.version,
        "numpy": modules[0].__version__,
        "Pillow": modules[1].__version__,
        "stdlib": str(stdlib),
        "origin": "local_runtime_allowlist",
        "libraries": {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(libraries)},
    }
    copy_path = filesystem / "runtime/runtime_manifest.json"
    copy_path.write_text(json.dumps(manifest, sort_keys=True))
    (context / "Dockerfile").write_text(
        "FROM scratch\nCOPY rootfs /\n"
        + 'LABEL voxlush.runtime="'
        + h.hexdigest()
        + '"\n'
        + "ENV PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1\n"
        + 'USER 10001:10001\nENTRYPOINT ["/usr/bin/python3.12", "-I", "/runtime/sandbox_worker.py"]\n'
    )
    subprocess.run(["docker", "build", "-t", args.tag, str(context)], check=True)
