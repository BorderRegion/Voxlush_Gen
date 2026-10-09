import json
import hashlib

import pytest
from PIL import Image, ImageChops

from voxlush.dataset.archive import Archive
from voxlush.dataset.gallery import BLIND_CROP, BLIND_RENDERER, blind_gallery, blind_preview
from voxlush.pipeline.prompts import parse_review
from voxlush.voxel.adapter import versions
from voxlush.voxel.resources.legacy_render import render
from test_dataset import AssetStore, artifact_fixture


def test_blind_gallery_verifies_images_hides_identity_and_keeps_scores_missing(tmp_path):
    record, fixture = artifact_fixture(tmp_path / "build")
    record["record_kind"] = "calibration"
    record["task"]["brief"] = {"instruction": "<script>unsafe</script> 独立景观"}
    build = tmp_path / 'build'
    sample = json.loads((build / 'sample.json').read_text())
    sample['building'] = {'name': 'Identity visible in original caption'}
    (build / 'sample.json').write_text(json.dumps(sample))
    render(build)  # Trusted tiny saved-voxel fixture; actual production caption layout.
    image_hashes = []
    for view, direction in (('a', 'southwest'), ('b', 'northeast')):
        path = build / f'previews/view_{view}.webp'
        with Image.open(build / f'preview_{direction}.png') as image:
            image.save(path, 'WEBP', lossless=True)
        image_hashes.append(hashlib.sha256(path.read_bytes()).hexdigest())
    (build / 'render.json').write_text(json.dumps({
        'passed': True, 'canonical_voxel_hash': fixture['input_voxel_sha256'], **versions()}))
    review = parse_review(
        json.dumps({"verdict": "pass", "issues": [], "observed_tags": []}),
        fixture["input_voxel_sha256"],
        image_hashes,
    )
    root = tmp_path / "data"
    asset = Archive(root).prepare(record, tmp_path / "build", review)
    store = AssetStore([asset])
    output = tmp_path / "gallery"
    report = blind_gallery(store, root, "dataset-fixture", output, count=100, seed=91)
    assert report["selected"] == 1 and report["human_reviewed"] == 0 and not report["qualified"]
    document = (output / "reviewer/index.html").read_text()
    assert record["sample_id"] not in document and "live_model" not in document
    assert "<script>" not in document and "&lt;script&gt;" in document
    scores = json.loads((output / "reviewer/scores.json").read_text())["items"]
    assert scores[0]["verdict"] is None and set(scores[0]["scores"].values()) == {None}
    with Image.open(build / 'previews/view_a.webp') as original, Image.open(output / 'reviewer/B0001_a.webp') as anonymous:
        assert anonymous.size == (1200, 800)
        assert ImageChops.difference(original.crop(BLIND_CROP), anonymous).getbbox() is None
        # Rendered geometry fits wholly in the retained area; captions do not.
        for strip in (original.crop((0, 64, 1200, 90)), original.crop((0, 851, 1200, 864))):
            assert len(strip.getcolors()) == 1
        assert len(original.crop((0, 0, 1200, 64)).getcolors()) > 1
        assert len(original.crop((0, 864, 1200, 900)).getcolors()) > 1
    mapping = json.loads((output / "curator/mapping.json").read_text())[0]
    assert mapping['sample_id'] == record['sample_id']
    derivative = mapping['blind_previews']['a']
    assert derivative['source_sha256'] == image_hashes[0]
    assert derivative['derived_sha256'] == hashlib.sha256((output / 'reviewer/B0001_a.webp').read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="must be new"):
        blind_gallery(store, root, "dataset-fixture", output)
    # Immutable verification catches later corruption; no silently broken gallery.
    image = root / asset["path"] / "previews/view_a.webp"
    image.chmod(0o644)
    image.write_bytes(b"corrupt")
    with pytest.raises(ValueError):
        blind_gallery(store, root, "dataset-fixture", tmp_path / "broken")


def test_fixture_is_not_a_blind_model_candidate(tmp_path):
    record, review = artifact_fixture(tmp_path / "build")
    root = tmp_path / "data"
    asset = Archive(root).prepare(record, tmp_path / "build", review)
    result = blind_gallery(AssetStore([asset]), root, "dataset-fixture", tmp_path / "gallery")
    assert result["selected"] == 0 and result["available"] == 0


def test_unknown_preview_layout_is_never_blindly_cropped(tmp_path):
    source = tmp_path / 'small.webp'
    target = tmp_path / 'anonymous.webp'
    Image.new('RGB', (8, 8)).save(source, 'WEBP')
    with pytest.raises(ValueError, match='renderer'):
        blind_preview(source, target, 'unknown')
    with pytest.raises(ValueError, match='dimensions'):
        blind_preview(source, target, BLIND_RENDERER)
    assert not target.exists()
