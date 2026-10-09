"""Prepare a hash-pinned pool release locally; never restarts or contacts services."""

import argparse
import hashlib
import shutil
import subprocess
from pathlib import Path

HASHES = {
    "api_pool.py": "2fc2e8c14f5e5f2a81de58c460ff8f8bd2b94de3edc08b708aaccf1bd0616bb9",
    "cluster_gateway.py": "a0b13756bb83671c5ee190549f807b088bda0adb1f8e31100d9193bbcde35359",
    "proxy_allocator.py": "03e83bd8ddcaab5d0206160ac215a7fc2742b939ccd7f4bf5065eefd53355ffa",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    for name, expected in HASHES.items():
        if hashlib.sha256((args.source_dir / name).read_bytes()).hexdigest() != expected:
            raise ValueError("source version mismatch: " + name)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    package = Path(__file__).resolve().parent
    for name in HASHES:
        # The pinned gateway has CRLF; patches were generated from parsed text.
        (args.output_dir / name).write_text((args.source_dir / name).read_text())
        if name.endswith("_pool.py") or name == "cluster_gateway.py":
            subprocess.run(
                ["patch", "--batch", "--forward", "-p1", "-i", str(package / (name + ".patch"))],
                cwd=args.output_dir,
                check=True,
            )
    shutil.copyfile(package / "pool_receipts.py", args.output_dir / "pool_receipts.py")
    for name in [*HASHES, "pool_receipts.py"]:
        compile((args.output_dir / name).read_bytes(), name, "exec")
    print("Prepared pinned release, including local proxy allocator; no service changes.")


if __name__ == "__main__":
    main()
