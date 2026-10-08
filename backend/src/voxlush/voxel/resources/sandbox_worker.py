"""Trusted container entrypoint. Only allowlisted regular artifacts cross the boundary."""

import contextlib
from pathlib import Path
import runpy
import shutil
import sys
import tarfile

OUTPUT = Path("/output")
MODE = sys.argv[1]
if MODE in ("build", "probe"):
    shutil.copyfile("/input/build.py", OUTPUT / "build.py")
    with contextlib.redirect_stdout(sys.stderr):
        runpy.run_path(str(OUTPUT / "build.py"), run_name="__main__")
    names = ("sample.json", "spec.json", "preservation_reference.json", "probe.json")
elif MODE == "render":
    shutil.copyfile("/input/sample.json", OUTPUT / "sample.json")
    sys.path.insert(0, "/runtime")
    from legacy_render import render
    from PIL import Image

    with contextlib.redirect_stdout(sys.stderr):
        render(OUTPUT)
    OUTPUT.joinpath("previews").mkdir()
    views = []
    for label, source in [("view_a", "southwest"), ("view_b", "northeast")]:
        with Image.open(OUTPUT / ("preview_" + source + ".png")) as original:
            original.save(OUTPUT / "previews" / (label + ".webp"), "WEBP", lossless=True, method=4)
            views.append(original.resize((600, 450)))
    contact = Image.new("RGB", (1200, 450))
    contact.paste(views[0], (0, 0))
    contact.paste(views[1], (600, 0))
    contact.save(OUTPUT / "previews" / "contact.webp", "WEBP", lossless=True, method=4)
    names = ("previews/view_a.webp", "previews/view_b.webp", "previews/contact.webp")
else:
    raise ValueError("Unsupported isolated operation")
with tarfile.open(fileobj=sys.stdout.buffer, mode="w|") as archive:
    for name in names:
        path = OUTPUT / name
        if path.exists():
            if path.is_symlink() or not path.is_file():
                raise ValueError("Non-regular artifact")
            info = archive.gettarinfo(str(path), arcname=name)
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = 0
            with path.open("rb") as handle:
                archive.addfile(info, handle)
