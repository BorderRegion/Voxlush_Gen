"""Linear-time context measurements over final occupied voxels, not declared volumes."""
from collections import Counter

from voxlush.themes.composition import LIMITS, VERSION, requested_mode

ENVIRONMENT = {'environment', 'terrain', 'rock', 'cave', 'vegetation', 'water', 'path'}
STRUCTURE = {'exterior_wall', 'interior_wall', 'roof', 'door', 'window', 'column', 'beam', 'stair', 'ruin'}
ATTACHED = {'foundation', 'slab', 'decoration', 'furniture', 'object'}


def measure(sample: dict, task: dict) -> tuple[dict, list]:
    mode = requested_mode(task)
    if mode is None:
        return {'version': VERSION, 'requested_mode': None, 'applicable': False,
                'reason': 'natural_contract' if task.get('scene_type') == 'natural' else 'legacy_unspecified',
                'meets_requested': None}, []
    categories = {c['id']: c.get('category') for c in sample['components']}
    blocks = sample['blocks']
    core = [b for b in blocks if categories.get(b['component_id']) in STRUCTURE]
    bbox = ({'min': [min(b[a] for b in core) for a in ('x', 'y', 'z')],
             'max': [max(b[a] for b in core) for a in ('x', 'y', 'z')]} if core else None)
    # Ground/furnishing/detail outside the real structural envelope is not
    # automatically a building. Two blocks allow necessary contact/attachments.
    counts = Counter(subject=0, environment=0, unclassified=0)
    category_voxels = Counter()
    subject_columns, scene_columns = set(), set()
    for block in blocks:
        category = categories.get(block['component_id'], 'unknown')
        category_voxels[category] += 1
        near = bbox and all(bbox['min'][i] - 2 <= block[a] <= bbox['max'][i] + 2
                            for i, a in ((0, 'x'), (2, 'z')))
        kind = ('environment' if category in ENVIRONMENT else 'subject'
                if category in STRUCTURE or (category in ATTACHED and near) else 'unclassified')
        counts[kind] += 1
        column = (block['x'], block['z'])
        scene_columns.add(column)
        if kind == 'subject':
            subject_columns.add(column)
    total = len(blocks)
    context_fraction = (counts['environment'] + counts['unclassified']) / max(1, total)
    footprint_fraction = len(subject_columns) / max(1, len(scene_columns))
    limits = LIMITS.get(mode, {})
    violations = []
    if not core:
        violations.append({'rule': 'composition_subject_missing', 'detail': 'No occupied architectural structure; keep a recognizable building.'})
    if context_fraction > limits.get('max_context_fraction', 1):
        violations.append({'rule': 'composition_context_voxels', 'actual': context_fraction,
                           'maximum': limits['max_context_fraction'], 'detail': 'Reduce unrelated environment, not building detail. Ground outside the structural footprint is context.'})
    if footprint_fraction < limits.get('min_subject_footprint_fraction', 0):
        violations.append({'rule': 'composition_context_extent', 'actual': footprint_fraction,
                           'minimum': limits['min_subject_footprint_fraction'], 'detail': 'Broad surroundings occupy too much of the scene footprint; retain necessary foundations and architecture.'})
    evidence = {'version': VERSION, 'requested_mode': mode, 'applicable': True,
                'measurement_source': 'final_occupied_voxels', 'semantic_source': 'generator_declared_categories',
                'independent_semantics_verified': False, 'requires_visual_confirmation': True,
                'voxel_counts': dict(counts), 'category_voxels': dict(sorted(category_voxels.items())),
                'context_fraction': context_fraction, 'subject_footprint_fraction': footprint_fraction,
                'subject_bbox': bbox, 'limits': limits, 'meets_requested': not violations}
    return evidence, violations
