"""Shared read-only planning, validation and frozen-map playback for W4f."""
import copy
import hashlib
import numpy as np
from . import DerivedPlan, DerivedBundle, ClipPlan, ClipBundle
from ._pitch_notes import number, clean, accounting, vibrato

TIME_NUMERIC = {'max_shift_ms': (10, 500, 120), 'tightness': (0, 1, .7),
                'stretch_min': (.25, 1, .5), 'stretch_max': (1, 4, 2),
                'smooth_ms': (0, 500, 80), 'protect_sustain': (0, 1, .5)}
TIME_ENUMS = {'feature': (['onset_env', 'spectral', 'both'], 'both'),
              'quality': (['standard', 'high'], 'standard')}
PITCH_NUMERIC = {'pitch_tightness': (0, 1, .6), 'keep_vibrato': (0, 1, .7),
                 'max_cents': (0, 300, 100)}


def validate(move, ctx, pitch=False, quantize=False):
    from mankomix.dsp.processors import NOTE_VALUES
    from .edit_quantize import NUMERIC, ENUMS
    p = move.get('params')
    if not isinstance(p, dict):
        ctx.err('bad_value', 'params must be an object')
        return
    nums = NUMERIC if quantize else TIME_NUMERIC | (PITCH_NUMERIC if pitch else {})
    enums = ENUMS if quantize else TIME_ENUMS
    extra = {'group', 'section'} | ({'grid_note', 'only', 'skip', 'detect_from'} if quantize else {'guide', 'anchors'})
    if pitch:
        extra |= {'time', 'interval', 'formant'}
    if set(p)-set(nums)-set(enums)-extra:
        ctx.err('bad_value', 'unknown alignment parameter: '+', '.join(sorted(set(p)-set(nums)-set(enums)-extra)))
    for k, (lo, hi, default) in nums.items():
        v = p.get(k, default)
        values = v if k == 'strength' and isinstance(v, list) and len(v) == 2 else [v]
        if not all(number(n) and lo <= n <= hi for n in values) or (len(values) == 2 and values[0] > values[1]):
            ctx.err('bad_value', f'{k} needs a finite value in [{lo}, {hi}]')
    for k, (choices, default) in enums.items():
        if p.get(k, default) not in choices:
            ctx.err('bad_value', f'invalid {k}')
    target = move.get('target')
    tracks = ctx.project.tracks() if ctx.project is not None else None
    def track(t):
        return isinstance(t, str) and t.startswith('trk_') and (tracks is None or t in tracks)
    if not track(target):
        ctx.err('bad_target', 'target must name an existing track')
    peers = p.get('group', [])
    limit = 16 if quantize else 8
    if not isinstance(peers, list) or len(peers) > limit or any(not track(t) for t in peers):
        ctx.err('bad_value', f'group needs at most {limit} existing track IDs')
    elif len(set(peers)) != len(peers) or target in peers:
        ctx.err('bad_value', 'group tracks must be unique and exclude target')
    if quantize:
        if 'bpm' not in p:
            ctx.err('missing', 'bpm is required; only constant tempo is supported')
        if p.get('grid_note', '1/16') not in NOTE_VALUES[1:]:
            ctx.err('bad_value', 'grid_note must be a NOTE_VALUES value other than none')
        if 'detect_from' in p and not track(p['detect_from']):
            ctx.err('bad_target', 'detect_from must name an existing track')
        if number(p.get('detect_lo_hz', 20)) and number(p.get('detect_hi_hz', 20000)) and p.get('detect_lo_hz', 20) >= p.get('detect_hi_hz', 20000):
            ctx.err('bad_value', 'detect_lo_hz must be below detect_hi_hz')
        for k in ('only', 'skip'):
            ids = p.get(k, [])
            if not isinstance(ids, list) or len(ids) > 1024 or any(not isinstance(i, str) or not i.startswith('o_') or not i[2:].isdigit() for i in ids):
                ctx.err('bad_value', k+' must contain at most 1024 onset IDs')
            if ids and not all(k in p for k in ('threshold_db', 'detect_lo_hz', 'detect_hi_hz', 'min_interval_ms')):
                ctx.err('bad_value', 'only/skip require all explicit detector parameters')
    else:
        if not track(p.get('guide')) or p.get('guide') == target:
            ctx.err('bad_target', 'guide must name a different existing track')
        anchors = p.get('anchors', [])
        valid = isinstance(anchors, list) and len(anchors) <= 64
        valid = valid and all(isinstance(row, list) and len(row) == 2 and all(number(v) and v >= 0 for v in row) for row in anchors)
        if not valid:
            ctx.err('bad_value', 'anchors need at most 64 finite nonnegative [target_s, guide_s] pairs')
        elif any(a[0] >= b[0] or a[1] >= b[1] for a, b in zip(anchors[:-1], anchors[1:])):
            ctx.err('bad_value', 'anchor times must increase strictly in both tracks')
        elif number(p.get('max_shift_ms', 120)) and any(abs(a-b)*1000 > p.get('max_shift_ms', 120) for a, b in anchors):
            ctx.err('bad_value', 'anchors exceed max_shift_ms')
    if pitch:
        for k in ('time', 'formant'):
            if type(p.get(k, True)) is not bool:
                ctx.err('bad_value', k+' must be boolean')
        interval = p.get('interval', 'auto')
        if not (isinstance(interval, str) and interval in ('auto', 'unison')) and not (number(interval) and -24 <= interval <= 24):
            ctx.err('bad_value', 'interval must be auto, unison or -24..24 semitones')
    section = move.get('section', p.get('section'))
    if 'section' in move and 'section' in p:
        ctx.err('bad_value', 'write section only once')
    if section is not None:
        if isinstance(section, dict):
            a, b = section.get('t0_s'), section.get('t1_s')
            if set(section) != {'t0_s', 't1_s'} or not number(a) or not number(b) or not 0 <= a < b or b-a < .4:
                ctx.err('bad_value', 'section needs 0 <= t0_s < t1_s, duration >= .4 s')
            elif ctx.project is not None and b > ctx.project.data['timebase']['length_samples']/ctx.project.rate:
                ctx.err('bad_value', 'section exceeds project duration')
        elif not isinstance(section, str) or (ctx.project is not None and section != 'all' and section not in {s['id'] for s in ctx.project.sections()}):
            ctx.err('bad_value', 'unknown section')


def resolve(move, pitch=False):
    p = {k: d for k, (_, _, d) in TIME_NUMERIC.items()}
    p.update({k: d for k, (_, d) in TIME_ENUMS.items()})
    p.update(anchors=[], group=[], seed=0)
    if pitch:
        p.update({k: d for k, (_, _, d) in PITCH_NUMERIC.items()})
        p.update(time=True, interval='auto', formant=True)
    p.update(copy.deepcopy(move['params']))
    return p


def source(root, move):
    from mankomix.director.edit import raw_track
    from mankomix.director.query import section_range
    from mankomix.core import mixrender as mr
    x, sr, data = raw_track(root, move['target'])
    section = move.get('section', move['params'].get('section'))
    if section is None:
        t = next(t for t in data['tracks'] if t['id'] == move['target'])
        clips = [c for c in t['clips'] if not c.get('muted')]
        if not clips:
            raise ValueError('target has no audible source clips')
        a = min(c['timeline_start'] for c in clips)
        b = max(c['timeline_start']+mr.clip_length(data, c, sr) for c in clips)
    else:
        if isinstance(section, dict) and section['t1_s'] > len(x)/sr:
            raise ValueError('section exceeds project duration')
        lo, hi = section_range(section, data.get('sections', []), len(x)/sr)
        a, b = round(lo*sr), round(hi*sr)
    if not 0 <= a < b <= len(x):
        raise ValueError('selected interval lies outside the project timeline')
    return x, sr, data, a, b


def dependency(root, tid):
    from mankomix.director.edit import raw_track
    x, sr, data = raw_track(root, tid)
    track = next(t for t in data['tracks'] if t['id'] == tid)
    assets = {c['asset'] for c in track['clips']}
    return x, {'track': tid, 'raw_sha256': hashlib.sha256(np.ascontiguousarray(x, dtype='<f8').tobytes()).hexdigest(),
               'clips': copy.deepcopy(track['clips']), 'assets': [{'id': a['id'], 'sha256': a['sha256']} for a in data['assets'] if a['id'] in assets]}


def onset_distribution(x, guide, sr):
    from mankomix.dspx.bb.onsets import detect_onsets
    from mankomix.director._observations_w4b import distribution
    target = detect_onsets(x, sr, kind='soft')
    other = detect_onsets(guide, sr, kind='soft')
    values = []
    if other:
        positions = np.array([e['sample'] for e in other])
        values = [(e['sample']-positions[np.argmin(abs(positions-e['sample']))])*1000/sr for e in target]
    return distribution(values)


def calculate(x, sr, p):
    from mankomix.dspx.bb.alignment_warp import warp, synthesize_pitch
    mapping = p.get('group_mapping', p['mapping'])
    time_identity = mapping.get('time_identity', False)
    dry = x.copy() if time_identity else warp(x, sr, mapping['synthesis'])
    if p.get('pitch_synthesis'):
        return synthesize_pitch(x, sr, p['pitch_synthesis'], dry)
    return dry


def bundle(move, a, b, params, mapping, record, neutral=False):
    targets = [move['target']]+move['params'].get('group', [])
    if neutral:
        plans = {t: ClipPlan({}, params[t], record) for t in targets}
        return ClipBundle(plans, mapping, record) if len(targets) > 1 else plans[targets[0]]
    plans = {t: DerivedPlan(a, b, params[t], calculate, record=record) for t in targets}
    return DerivedBundle(plans, mapping, record) if len(targets) > 1 else plans[targets[0]]


def pitch_plan(x, guide, sr, p, mapping, synthesis_mapping=None):
    from mankomix.dspx.bb.psola import track_notes, pitch_marks
    from mankomix.dspx.bb.pitch import sample_pitch
    from mankomix.dspx.bb.alignment_warp import pitch_schedule
    from scipy.ndimage import median_filter, gaussian_filter1d
    tr, notes = track_notes(x, sr)
    gr, _ = track_notes(guide, sr)
    # Match the mark-spacing refinement used by pitch_correct's PSOLA kernel.
    def refined(signal, track):
        hz = track.f0_hz.copy()
        marks = pitch_marks(signal, sr, track)
        if len(marks) >= 3:
            periods = np.diff(marks)
            stable = gaussian_filter1d(median_filter(periods, size=5, mode='nearest'), 1, mode='nearest')
            hz0 = np.interp(track.samples, (marks[:-1]+marks[1:])/2, np.where(periods < 1.5*sr/70, sr/stable, np.nan))
            hz = np.where(np.isfinite(hz0), hz0, hz)
        return hz
    hz, ghz = refined(x, tr), refined(guide, gr)
    curve = np.zeros(len(tr.samples))
    rows = []
    knots = np.asarray(mapping)
    correspondence = np.interp(tr.samples, knots[:, 0], knots[:, 1])
    _, gv, gc = sample_pitch(gr, correspondence)
    guide_pitch = np.interp(correspondence, gr.samples, np.nan_to_num(ghz, nan=70))
    for note in notes:
        ix = np.flatnonzero((tr.samples >= note['start_sample']) & (tr.samples < note['end_sample']) & tr.voiced & (tr.probability >= .6) & gv & (gc >= .6))
        if not len(ix):
            rows.append({**note, 'reason': 'low_confidence', 'max_correction_cents': 0.})
            continue
        actual = 69+12*np.log2(hz[ix]/440)
        reference = 69+12*np.log2(guide_pitch[ix]/440)
        interval = p['interval']
        interval = float(np.floor(np.median(actual-reference)+.5)) if interval == 'auto' else 0. if interval == 'unison' else float(interval)
        error = 100*(float(np.median(reference))+interval-float(np.median(actual)))
        if abs(error) > p['max_cents']+1e-8:
            rows.append({**note, 'reason': 'max_cents', 'interval': interval, 'required_cents': error, 'max_correction_cents': 0.})
            continue
        # Blend guide trajectory with the target's vibrato; center follows guide median.
        # Closure estimates at note boundaries can contain the neighboring
        # pitch. Do not turn that boundary error into a ringing vibrato band.
        def stable(values):
            guard = max(1, len(values)//5)
            core = values[guard:-guard] if len(values) > 2*guard else values
            low, high = np.percentile(core, [5, 95])
            return np.clip(values, low, high)
        actual_line = stable(actual)
        target_fast = vibrato(actual_line, sr/tr.hop_samples)
        reference_line = stable(reference)
        guide_fast = vibrato(reference_line, sr/tr.hop_samples)
        desired = reference_line+interval+p['keep_vibrato']*(target_fast-guide_fast)
        control = p['pitch_tightness']*100*(desired-actual_line)
        if np.max(abs(control)) > p['max_cents']+1e-8:
            rows.append({**note, 'reason': 'max_cents', 'interval': interval,
                         'required_cents': float(np.max(abs(control))), 'max_correction_cents': 0.})
            continue
        curve[ix] = control
        rows.append({**note, 'reason': 'aligned', 'interval': interval, 'target_midi': float(np.median(reference))+interval,
                     'required_cents': error, 'max_correction_cents': float(np.max(abs(control)))})
    synthesis_mapping = mapping if synthesis_mapping is None else synthesis_mapping
    plan = pitch_schedule(x, sr, tr, curve, synthesis_mapping, p['formant']) if np.any(curve) or any(a != b for a, b in synthesis_mapping) else None
    return plan, rows


def derive(root, move, pitch=False):
    from mankomix.dspx.bb.dtw import alignment
    from mankomix.dspx.bb.alignment_warp import schedule
    x, sr, data, a, b = source(root, move)
    p = resolve(move, pitch)
    guide, dep = dependency(root, p['guide'])
    p['guide_source'] = dep
    x, guide = x[a:b], guide[a:b]
    measured = alignment(x, guide, sr, p)
    time_identity = measured['identity'] or (pitch and not p['time'])
    mapping = {'map': [[0, 0], [len(x), len(x)]] if time_identity else measured['map'],
               'time_identity': time_identity, 'synthesis': None}
    if not time_identity:
        mapping['synthesis'] = schedule(x, sr, mapping['map'], p['quality'])
    params, note_rows = {}, {}
    for tid in [move['target']]+p['group']:
        local = copy.deepcopy(p)
        local['mapping'] = mapping
        if pitch:
            peer, _ = dependency(root, tid)
            plan, rows = pitch_plan(peer[a:b], guide, sr, p, measured['map'], mapping['map'])
            local['pitch_synthesis'] = plan
            note_rows[tid] = rows
        params[tid] = local
    y = calculate(x, sr, params[move['target']])
    record = clean({'mapping': {k: v for k, v in mapping.items() if k != 'synthesis'}, 'alignment': measured, 'notes': note_rows,
                    'confidence': measured['confidence'], 'measurements': accounting(x, y, sr),
                    'onset_delta_ms': {'before': onset_distribution(x, guide, sr), 'after': onset_distribution(y, guide, sr)},
                    'reason': 'measured_identity' if time_identity else 'measured_time_map',
                    'sample_rate': sr, 'section_samples': [a, b], 'anchor_clock': 'seconds relative to selected interval',
                    'caveats': ['Constant project sample rate; pitch alignment assumes monophonic voices.']})
    neutral = time_identity and all(not p0.get('pitch_synthesis') or not p0['pitch_synthesis']['grains'] for p0 in params.values())
    return bundle(move, a, b, params, mapping, record, neutral)
