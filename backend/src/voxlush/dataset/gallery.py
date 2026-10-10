"""Stratified, anonymous review export. Never writes scores or promotes assets."""
from __future__ import annotations

import hashlib
import html
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image

from .archive import verify_asset
from .files import json_bytes, safe_path, write_atomic
from .sample_io import read_sample
from voxlush.themes.composition import INSTRUCTIONS


# This exact renderer places all geometry in y=[90,850], with captions
# above y=64 and below y=864. Reject unknown layouts rather than hide geometry.
BLIND_RENDERER = 'legacy-orthographic-webp-v1@sha256:6692402cbabcbdbbc3c2fc7a6331c4fb382e1d8262db041a73932d3ca0214781'
BLIND_RENDERERS = {BLIND_RENDERER,
    # Same two lossless views and caption layout; no extra contact-sheet derivative.
    'legacy-orthographic-webp-v1@sha256:243e43dbbb5ba2eb3ee663d84ae2c90b599163853577faa5ee20d3e0968ed383'}
BLIND_CROP = (0, 64, 1200, 864)


def blind_preview(source, target, renderer):
    if renderer not in BLIND_RENDERERS:
        raise ValueError('unsupported blind preview renderer; caption layout must be verified')
    with Image.open(source) as original:
        if original.size != (1200, 900):
            raise ValueError('unsupported blind preview dimensions')
        # Lossless derivative: no rescaling, retouching or geometry rerendering.
        original.convert('RGB').crop(BLIND_CROP).save(target, 'WEBP', lossless=True, method=4)
    return {'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
            'derived_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
            'crop_xyxy':list(BLIND_CROP), 'geometry_pixels_unchanged':True}


def blind_gallery(store, data_root: Path, campaign_id: str, output: Path, *, count=100, seed=0):
    if not 1 <= count <= 1000:
        raise ValueError('gallery count must be between 1 and 1000')
    if output.exists() or output.is_symlink():
        raise ValueError('gallery output must be new')
    groups = defaultdict(list)
    available = Counter()
    for raw in store.iter_assets(campaign_id, True):
        row = dict(raw)
        manifest = row['manifest_json']
        if isinstance(manifest, str):
            manifest = json.loads(manifest)
        if (manifest['record_kind'] != 'calibration' or manifest['lifecycle'] != 'candidate'
                or manifest['quality']['visual']['status'] != 'pass'):
            continue
        asset = safe_path(data_root, row['path'])
        brief = json.loads((asset/'brief.json').read_text())
        group = (manifest['scene_type'], brief.get('bounds', {}).get('scale_class', 'unknown'),
                 manifest['provenance']['generation_mode'], brief.get('composition_mode') or 'unspecified')
        rank = hashlib.sha256(f"{seed}:{manifest['sample_id']}:{manifest['revision']}".encode()).hexdigest()
        available[group] += 1
        groups[group].append((rank, row, brief))
        # Keep a bounded random subset within each scene/scale/route/context stratum.
        groups[group].sort(key=lambda item: item[0])
        del groups[group][count:]
    rng = random.Random(seed)
    strata = sorted(groups)
    rng.shuffle(strata)
    selected = []
    while len(selected) < count and any(groups.values()):
        for group in strata:
            if groups[group] and len(selected) < count:
                _, row, brief = groups[group].pop(0)
                selected.append((group, row, brief))
    rng.shuffle(selected)
    output.mkdir(parents=True)
    reviewer = output/'reviewer'
    reviewer.mkdir()
    curator = output/'curator'
    curator.mkdir(mode=0o700)
    cards, mapping, scores = [], [], []
    for index, (group, row, brief) in enumerate(selected, 1):
        asset = safe_path(data_root, row['path'])
        manifest = verify_asset(asset)
        stored = row['manifest_json']
        if manifest != (json.loads(stored) if isinstance(stored, str) else stored):
            raise ValueError('Store/asset manifest mismatch')
        review = json.loads((asset/'review.json').read_text())
        if review.get('evidence_kind') != 'live_model':
            raise ValueError('blind candidates require an actual model review')
        sample = read_sample(asset)
        caption = sample['sample_id'] + sample['building']['name'][:62]
        if '\n' in caption or '\r' in caption:
            raise ValueError('unsupported multiline preview caption; anonymous rerender required')
        del sample
        blind_id = f'B{index:04d}'
        images, derivatives = [], {}
        for view in ('a', 'b'):
            name = f'{blind_id}_{view}.webp'
            derivatives[view] = blind_preview(safe_path(asset, f'previews/view_{view}.webp'),
                                              reviewer/name, manifest['versions']['renderer'])
            images.append(f'<img loading="lazy" src="{name}" alt="{blind_id} 视图 {view}">')
        task = brief.get('brief', {})
        instruction = '；'.join(str(task[k]) for k in ('instruction', 'design_focus') if task.get(k))
        mode = brief.get('composition_mode')
        if mode:
            instruction += f' | Requested composition: {mode}. {INSTRUCTIONS[mode]}'
        cards.append(f'<article id="{blind_id}"><h2>{blind_id}</h2><p>{html.escape(instruction)}</p><div>{"".join(images)}</div></article>')
        mapping.append({'blind_id':blind_id,'sample_id':manifest['sample_id'], 'revision':manifest['revision'],
                        'stratum':group,'manifest_sha256':hashlib.sha256((asset/'manifest.json').read_bytes()).hexdigest(),
                        'versions':manifest['versions'],'image_sha256':manifest['quality']['visual']['image_sha256'],
                        'blind_previews':derivatives})
        scores.append({'blind_id':blind_id,'reviewer':None,'verdict':None,'defects':None,'notes':None,
                       'observed_composition_mode':None,'composition_meets_requested':None,
                       'scores':{key:None for key in ('silhouette_proportion','spatial_hierarchy','structural_detail',
                                                     'materials_style','landscape_composition','theme','repetition','completeness')}})
    document = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Voxlush 候选盲评</title><style>body{max-width:1200px;margin:auto;padding:24px;font:17px/1.6 system-ui;background:#eef1f0;color:#182720}article{background:white;padding:20px;margin:24px 0;border-radius:12px}article div{display:flex;flex-wrap:wrap}img{width:50%;min-width:260px;object-fit:contain}a{color:#126b50}</style>
<h1>候选资产盲评</h1><p>按任务主题评估轮廓比例、空间层次、结构细节、材料风格、景观构成、主题辨识、重复装饰及完成度。自然场景不要求建筑室内。图像不足以判断时请记为 gray，不能猜测隐藏结构。</p>
<p>在评分文件记录 pass / fail / gray、具体缺陷与适用维度的 1–5 分；不适用或无法判断的维度留空。不要用平均分掩盖严重缺陷。当前文件没有预填评分。</p><p><a href="scores.json" download>下载空白评分文件</a></p>'''
    write_atomic(reviewer/'index.html', (document+''.join(cards)+'</html>').encode())
    write_atomic(reviewer/'scores.json', json_bytes({'schema_version':'voxlush.blind_scores.v1','items':scores}))
    result = {'schema_version':'voxlush.blind_gallery.v1','requested':count,'selected':len(selected),
              'available':sum(available.values()),'seed':seed,'human_reviewed':0,'qualified':False,
              'preview_transform':'lossless caption-margin crop; full geometry pixels retained',
              'strata':[{'scene_type':g[0],'scale':g[1],'generation_mode':g[2],'available':available[g],
                         'composition_mode':None if g[3]=='unspecified' else g[3],
                         'selected':sum(item[0] == g for item in selected)} for g in sorted(available)],
              'instructions':'Send only reviewer/ to reviewers. curator/ reveals identities. Missing scores stay missing; this export never qualifies or promotes assets.'}
    write_atomic(curator/'mapping.json', json_bytes(mapping))
    write_atomic(output/'manifest.json', json_bytes(result))
    return result
