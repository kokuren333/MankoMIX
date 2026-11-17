"""T10-03: isolate vocals/background through the existing separation layer."""
from __future__ import annotations

import copy
import hashlib
import json
import math

import numpy as np

from mankomix.core import registry
from mankomix.core.errors import InputError
from . import ClipPlan, DerivedPlan, OpSpec
from . import _isolate
from . import _w4g as W

VERSION = 'w5c-isolate-1'
NUMERIC = {'strength': (0, 1, 1., False), 'residual_db': (-90, 0, -90., False)}
ENUMS = {'keep': (('voice', 'background'), 'voice')}


def model_id(params):
    value = params.get('model', registry.default_model('full'))
    if not isinstance(value, str) or not value:
        raise InputError('edit_isolate requires a registered separation model')
    return value


def check_entry(entry):
    if entry.get('task') != 'separation' or 'vocals' not in (entry.get('stems') or []):
        raise InputError('edit_isolate requires a separation model with a vocals output')
    if not (entry.get('runtime') or {}).get('backend'):
        raise InputError('edit_isolate model has no runtime backend')


def validate(move, ctx):
    p = W.validate(move, ctx, NUMERIC, ENUMS, extra=('model', 'section'))
    if 'section' in p and 'section' in move:
        ctx.err('bad_value', 'write section on the move or in params, not both')
    try:
        check_entry(registry.model_show(model_id(p))['entry'])
    except (InputError, ValueError) as exc:
        ctx.err('bad_value', str(exc))
    section = move.get('section', p.get('section'))
    if ctx.project is not None and isinstance(section, dict):
        end = section.get('t1_s')
        duration = (ctx.project.data.get('timebase') or {}).get('length_samples', 0) / ctx.project.rate
        if W.number(end) and end > duration:
            ctx.err('bad_value', 'section extends past the project timeline')


def _hash(x):
    return hashlib.sha256(np.ascontiguousarray(x, dtype='<f8').tobytes()).hexdigest()


def _recipe(resolved):
    entry = resolved['entry']
    return {'model_sha256': resolved['model_sha256'], 'architecture': entry.get('architecture'),
            'runtime': copy.deepcopy(entry['runtime']), 'stems': list(entry['stems']),
            'roles': copy.deepcopy(resolved['roles']), 'device': 'cpu',
            'threads': {'intra_op': 1, 'inter_op': 1}, 'seed': 0,
            'deterministic_algorithms': True}


def _resolve(p):
    resolved = registry.resolve_for_run(p['model'])
    check_entry(resolved['entry'])
    if 'model_recipe' in p and p['model_recipe'] != _recipe(resolved):
        raise InputError('edit_isolate model or inference settings changed since the recipe was recorded')
    return resolved


def _energy(x):
    return float(np.sum(np.square(x), dtype=np.float64))


def _relative_db(error, reference):
    e, r = _energy(error), _energy(reference)
    return 10 * math.log10(e / r) if e > 0 and r > 0 else None


def process(x, sr, p, resolved=None):
    """Calculate one fixed segment and record the actual stem-sum error."""
    resolved = _resolve(p) if resolved is None else resolved
    outs, run = _isolate.separate_segment(x, sr, resolved)
    voice = outs.pop('vocals')
    # A vocals-only model has a well-defined complementary residual. Otherwise
    # use the model's actual background stems and report their reconstruction.
    model_background = sum(outs.values()) if outs else x - voice
    residual_model = bool((resolved['entry']['runtime'].get('config') or {}).get('residual'))
    # Preserve the complementary model's residual after the rate conversion as
    # well. Record the uncorrected model sum separately instead of hiding it.
    background = x - voice if residual_model or not outs else model_background
    kept, discarded = (voice, background) if p['keep'] == 'voice' else (background, voice)
    wet = kept + 10 ** (p['residual_db'] / 20) * discarded
    y = (1 - p['strength']) * x + p['strength'] * wet
    error = voice + background - x
    from mankomix.core.measure import loudness
    entry = resolved['entry']
    record = {**run, 'model_id': p['model'], 'model_sha256': resolved['model_sha256'],
              'license': registry.license_record(entry), 'attribution': entry.get('attribution') or '',
              'warnings': list(resolved['warnings']), 'fallback': 'error', 'fallback_used': False,
              'keep': p['keep'], 'strength': p['strength'], 'residual_db': p['residual_db'],
              'kept_energy': _energy(kept), 'discarded_energy': _energy(discarded),
              'reconstruction_error_energy': _energy(error),
              'reconstruction_error_rel_db': _relative_db(error, x),
              'model_reconstruction_error_rel_db': _relative_db(voice+model_background-x, x),
              'background_mode': 'input_minus_vocals' if residual_model or not outs else 'model_stems',
              'removed_energy_rel_db': _relative_db(x-y, x),
              'before_lufs': float(loudness.integrated(x, sr)),
              'after_lufs': float(loudness.integrated(y, sr)),
              'before_peak_dbfs': float(loudness.sample_peak_dbfs(x)),
              'after_peak_dbfs': float(loudness.sample_peak_dbfs(y)),
              'caveats': ['Separated audio can contain bleed and artifacts; these measurements do not establish restoration.']}
    return y, W.clean(record)


def calculate(x, sr, p):
    """Versioned BB-18 regeneration callback, using only verified local weights."""
    if sr != p['sample_rate'] or _hash(x) != p['segment_sha256']:
        raise InputError('edit_isolate source segment changed')
    return process(x, sr, p)[0]


def derive(root, move):
    from mankomix.director import edit
    from mankomix.director.direction import _Project
    p = W.params(move, NUMERIC, ENUMS)
    p['model'] = model_id(p)
    check_entry(registry.model_show(p['model'])['entry'])
    x, sr, data = edit.raw_track(root, move['target'])
    section = move.get('section', p.get('section'))
    if section in (None, 'all'):
        track = next(t for t in data['tracks'] if t['id'] == move['target'])
        clips = [c for c in track.get('clips', []) if not c.get('muted') and c.get('length', 0) > 0]
        if not clips:
            raise InputError('edit_isolate target has no active clips')
        a = min(c['timeline_start'] for c in clips)
        b = max(c['timeline_start'] + c['length'] for c in clips)
    else:
        a, b = W.scope(_Project(root), move, x, sr)
    if not 0 <= a < b <= len(x):
        raise InputError('edit_isolate section is outside the target timeline')
    p.update(sample_rate=sr, start=a, end=b)
    if p['strength'] == 0:
        return ClipPlan({}, p, record={'bypassed': True, 'reason': 'strength=0',
                                      'model_id': p['model'], 'fallback_used': False,
                                      'section_samples': [a, b]})
    resolved = _resolve(p)
    p.update(model_recipe=_recipe(resolved), segment_sha256=_hash(x[a:b]))
    y, record = process(x[a:b], sr, p, resolved)
    record['section_samples'] = [a, b]
    # Derive must measure before returning its plan. Avoid a second inference at
    # apply; BB-18 still owns registration/cache and verifies the frozen input.
    frozen = json.dumps(p, sort_keys=True)

    def prepared(segment, rate, params):
        if rate != sr or _hash(segment) != p['segment_sha256'] or json.dumps(params, sort_keys=True) != frozen:
            raise InputError('edit_isolate planned input or recipe changed')
        return y.copy()

    return DerivedPlan(a, b, p, prepared, fit='keep_length', record=record)


OPS = {'edit_isolate': OpSpec('edit', ('target',), validate,
                              derive=derive, code_version=VERSION)}
