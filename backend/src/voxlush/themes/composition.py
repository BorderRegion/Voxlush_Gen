"""Small shared composition contract; controls context, never architectural design."""
from typing import Literal
import math

CompositionMode = Literal['pure_target', 'light_context', 'contextual', 'environment_rich']
MODES = ('pure_target', 'light_context', 'contextual', 'environment_rich')
DEFAULT_WEIGHTS = dict(zip(MODES, (40, 30, 20, 10), strict=True))
VERSION = 'voxlush.composition.v1'
LIMITS = {
    'pure_target': {'max_context_fraction': .10, 'min_subject_footprint_fraction': .80},
    'light_context': {'max_context_fraction': .25, 'min_subject_footprint_fraction': .60},
}
INSTRUCTIONS = {
    'pure_target': 'Focus on the building itself; avoid extraneous surroundings; minimal non-building content; '
        'no large decorative environment unless functionally necessary. The single building must dominate '
        'voxels and both views. Preserve architectural detail, material richness, necessary foundations and '
        'functional attachments. No broad yards, forests, roads, water or mountains.',
    'light_context': 'The building must strongly dominate voxels and both views. Allow only small supporting '
        'ground/contact treatment, a short path, a few plants or a small fence; avoid distracting scenery.',
    'contextual': 'Compose a coherent building-and-surroundings scene. Moderate terrain, courtyard, paths, '
        'water and planting are allowed; keep the building one of the main visual subjects.',
    'environment_rich': 'Rich environmental storytelling, estate grounds, settlement slices and building-nature '
        'compositions are allowed. Keep the architectural subject recognizable and object boundaries/use clear.',
}


def validate_weights(weights: dict) -> dict:
    if (not isinstance(weights, dict) or not weights or set(weights) - set(MODES)
            or any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in weights.values())
            or not math.isfinite(sum(weights.values())) or sum(weights.values()) <= 0):
        raise ValueError('composition weights require known modes and finite nonnegative positive mass')
    return {mode: weights.get(mode, 0) for mode in MODES}


def requested_mode(task: dict) -> str | None:
    mode = task.get('composition_mode')
    if mode is not None and (mode not in MODES or task.get('scene_type') == 'natural'
                            or task.get('scene_type') == 'hybrid' and mode not in MODES[2:]):
        raise ValueError('invalid composition_mode for scene type')
    return mode


def scene_weights(weights: dict, scene_type: str) -> dict:
    """Composite briefs retain their multi-building/landscape requirements."""
    if scene_type == 'natural':
        return {}
    allowed = MODES[2:] if scene_type == 'hybrid' else MODES
    selected = {mode: weights.get(mode, 0) for mode in allowed}
    if not any(selected.values()):
        raise ValueError('hybrid themes require positive contextual or environment_rich weight; use architecture for pure/light datasets')
    return selected


def instruction(task: dict) -> str | None:
    mode = requested_mode(task)
    if mode is None:
        return None
    text = INSTRUCTIONS[mode]
    if mode in LIMITS:
        limits = LIMITS[mode]
        text += (f" Measured non-subject voxels must be <= {limits['max_context_fraction']:.0%}; "
                 f"subject occupied XZ columns >= {limits['min_subject_footprint_fraction']:.0%} of scene columns. "
                 'Use truthful component categories; do not relabel scenery as structure.')
    return text + ' Design the building freely; context limits never justify reducing architectural quality.'


def visual_compliance(mode: str, observation: dict) -> bool | None:
    """Upper bounds on environment, not a requirement to fill every allowed voxel."""
    focus = observation['building_focus']
    observed = observation['observed_mode']
    if focus == 'unclear' or observed is None:
        return None
    if focus in ('absent', 'incidental'):
        return False
    if mode in LIMITS:
        allowed = ('pure_target',) if mode == 'pure_target' else ('pure_target', 'light_context')
        return focus == 'dominant' and observed in allowed and not observation['extraneous_environment']
    return True


def validate_observation(mode: str, observation: dict) -> dict:
    if (not isinstance(observation,dict) or 'observed_mode' not in observation
            or observation['observed_mode'] not in (*MODES, None)
            or observation.get('building_focus') not in ('dominant','co_primary','incidental','absent','unclear')
            or type(observation.get('extraneous_environment')) is not bool
            or not isinstance(observation.get('evidence'),str) or not observation['evidence'].strip()
            or type(observation.get('confidence')) not in (float,int) or not 0 <= observation['confidence'] <= 1):
        raise ValueError('composition review requires actual image context evidence')
    return {**observation,'requested_mode':mode,'meets_requested':visual_compliance(mode,observation),
            'source':'visual_review','evidence_ref':'review.json'}


def export_selection(modes=None, weights=None, count=None) -> dict:
    if modes is not None:
        if not modes or len(set(modes)) != len(modes) or set(modes) - set(MODES):
            raise ValueError('export composition_modes must be a nonempty set of known modes')
        modes = sorted(modes)
    if weights is not None:
        weights = validate_weights(weights)
        if modes is not None or type(count) is not int or not 1 <= count <= 1000000:
            raise ValueError('mixed export requires composition_weights and composition_count, without modes')
    elif count is not None:
        raise ValueError('composition_count requires composition_weights')
    return {'composition_modes': modes, 'composition_weights': weights, 'composition_count': count}
