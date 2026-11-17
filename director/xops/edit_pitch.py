"""T08-02 note-local pitch, formant, gain and time editing through BB-18."""
import numpy as np
from . import OpSpec, DerivedPlan, ClipPlan
from ._pitch_notes import number, clean, vibrato, accounting

DEFAULTS = {'shift_cents': 0, 'flatten': 0, 'vibrato': 1, 'formant_cents': 0,
            'move_ms': 0, 'gain_db': 0}
RANGES = {'shift_cents': (-1200, 1200), 'flatten': (0, 1), 'vibrato': (0, 2),
          'formant_cents': (-600, 600), 'move_ms': (-200, 200), 'gain_db': (-12, 12)}
VERSION = 'w4e-edit-pitch-1'


def resolve(p):
    return {'transition_ms': p.get('transition_ms', 30), 'formant': p.get('formant', True),
            'notes': [{**DEFAULTS, **n} for n in sorted(p['notes'], key=lambda n: (n['t0'], n['t1']))],
            'lo_hz': 70, 'hi_hz': 1000, 'a4_hz': 440, 'min_confidence': .6, 'seed': 0}


def clip_scope(root, target):
    from mankomix.core.project import Project
    from mankomix.core import mixrender as mr
    project = Project.open(root)
    track = next(t for t in project.data['tracks'] if t['id'] == target)
    clips = [c for c in track.get('clips', []) if not c.get('muted')]
    if len(clips) != 1:
        raise ValueError('edit_pitch needs one unmuted clip to resolve clip-local note times')
    c = clips[0]
    a = c['timeline_start']
    b = a+mr.clip_length(project.data, c, project.data['timebase']['sample_rate'])
    if b > project.data['timebase']['length_samples']:
        raise ValueError('pitch clip extends beyond project end')
    return a, b


def time_map(notes, frames, sr):
    anchors = {0: 0, frames: frames}
    starts = {round(n['t0']*sr) for n in notes}
    for n in notes:
        a, b = round(n['t0']*sr), round(n['t1']*sr)
        shifted = a+round(n['move_ms']*.001*sr)
        if a == 0 and shifted != 0:
            # A delayed first head is filled with silence, not extrapolated audio.
            anchors[0] = shifted
        else:
            anchors[a] = shifted
        if b not in starts:
            anchors[b] = b
    pairs = sorted(anchors.items())
    source, dest = np.asarray(pairs).T
    if np.any(np.diff(dest) <= 0) or np.any(dest < 0) or np.any(dest > frames):
        raise ValueError('moved note heads must retain a strictly increasing time map inside the clip')
    return [[int(a), int(b)] for a, b in pairs]


def validate(move, ctx):
    p = move.get('params')
    if not isinstance(p, dict):
        ctx.err('bad_value', 'params must be an object')
        return
    valid = True
    def error(message):
        nonlocal valid
        valid = False
        ctx.err('bad_value', message)
    if set(p)-{'notes', 'transition_ms', 'formant'}:
        error('unknown edit_pitch parameter')
    if not number(p.get('transition_ms', 30)) or not 0 <= p.get('transition_ms', 30) <= 200:
        error('transition_ms must be in [0, 200]')
    if type(p.get('formant', True)) is not bool:
        error('formant must be boolean')
    rows = p.get('notes')
    if not isinstance(rows, list) or len(rows) > 256:
        error('notes must be an array with at most 256 entries')
        return
    intervals = []
    for n in rows:
        if not isinstance(n, dict):
            error('each note must be an object')
            continue
        if set(n)-set(DEFAULTS)-{'t0', 't1'}:
            error('unknown note field')
        a, b = n.get('t0'), n.get('t1')
        if not number(a) or not number(b) or not 0 <= a < b:
            error('notes must have finite, nonoverlapping 0 <= t0 < t1')
        else:
            intervals.append((a, b))
        for k, (lo, hi) in RANGES.items():
            v = n.get(k, DEFAULTS[k])
            if not number(v) or not lo <= v <= hi:
                error(f'{k} must be in [{lo}, {hi}]')
    intervals.sort()
    if any(a < previous_b for (_, previous_b), (a, _) in zip(intervals[:-1], intervals[1:])):
        error('note intervals must not overlap')
    target = move.get('target')
    if not isinstance(target, str) or not target.startswith('trk_'):
        error('target must be a track ID')
    elif ctx.project is not None:
        if target not in ctx.project.tracks():
            error('unknown target track')
        elif valid:
            try:
                a, b = clip_scope(ctx.project.root, target)
                sr = ctx.project.rate
                if any(round(n['t1']*sr) > b-a or round(n['t0']*sr) >= round(n['t1']*sr) for n in rows):
                    raise ValueError('notes must fit inside the clip and span at least one sample')
                time_map(resolve(p)['notes'], b-a, sr)
            except ValueError as exc:
                error(str(exc))
    if 'section' in move:
        error('edit_pitch uses clip-local note intervals rather than sections')


def weight(a, b, sr, transition_ms):
    if transition_ms == 0:
        return np.ones(b-a)
    distance = np.minimum(np.arange(b-a), np.arange(b-a)[::-1])
    return .5-.5*np.cos(np.pi*np.clip(distance/max(1, sr*transition_ms*.0005), 0, 1))


def process(x, sr, p):
    from mankomix.dspx.bb import psola
    from mankomix.dspx.procs.pitch_correct import apply_correction
    notes = p['notes']
    cents = np.zeros(len(x))
    track = None
    if any(n['shift_cents'] or n['flatten'] or n['vibrato'] != 1 for n in notes):
        track = psola.voice_track(x, sr, fmin=p['lo_hz'], fmax=p['hi_hz'])
        refined = track.f0_hz.copy()
        if any(n['flatten'] or n['vibrato'] != 1 for n in notes):
            # Use the same mark-spacing refinement as the BB-19 synthesizer.
            # Otherwise its refined source F0 retains the pYIN quantization error.
            from scipy.ndimage import median_filter, gaussian_filter1d
            marks = psola.pitch_marks(x, sr, track)
            if len(marks) >= 3:
                periods = np.diff(marks)
                stable = gaussian_filter1d(median_filter(periods, size=5, mode='nearest'), 1, mode='nearest')
                hz = np.interp(track.samples, (marks[:-1]+marks[1:])/2,
                               np.where(periods < 1.5*sr/p['lo_hz'], sr/stable, np.nan))
                refined = np.where(np.isfinite(hz), hz, refined)
        for n in notes:
            a, b = round(n['t0']*sr), round(n['t1']*sr)
            ix = (track.samples >= a) & (track.samples < b) & track.voiced
            if not np.any(ix):
                continue
            actual = 1200*np.log2(refined[ix]/p['a4_hz'])+6900
            fast = vibrato(actual, sr/track.hop_samples)
            control = (n['shift_cents']+n['flatten']*(np.median(actual)-actual)
                       +(n['vibrato']-1)*fast)
            cents[a:b] = np.interp(np.arange(a, b), track.samples[ix], control)*weight(a, b, sr, p['transition_ms'])
    y = apply_correction(x, sr, cents, track, p['formant'], p['min_confidence']) if np.any(cents) else x.copy()
    for n in notes:
        a, b = round(n['t0']*sr), round(n['t1']*sr)
        blend = weight(a, b, sr, p['transition_ms'])[:, None]
        if n['formant_cents']:
            # Context comes from the full clip; only the requested note is replaced.
            shifted, _ = psola.shift_envelope(y, sr, n['formant_cents'])
            y[a:b] += blend*(shifted[a:b]-y[a:b])
        if n['gain_db']:
            y[a:b] *= 10**(blend*n['gain_db']/20)
    mapping = p['time_map']
    if any(a != b for a, b in mapping):
        from mankomix.dspx.bb.pitchtime import wsola
        warped = np.zeros_like(y)
        for (a, c), (b, d) in zip(mapping[:-1], mapping[1:]):
            if b-a == d-c:
                warped[c:d] = y[a:b]
            else:
                warped[c:d] = wsola(y[a:b], sr, (d-c)/(b-a))
        y = warped
    return y


def derive(root, move):
    from mankomix.director.edit import raw_track
    p = resolve(move['params'])
    a, b = clip_scope(root, move['target'])
    x, sr, _ = raw_track(root, move['target'])
    x = x[a:b]
    if any(round(n['t1']*sr) > len(x) for n in p['notes']):
        raise ValueError('note lies outside clip')
    p['time_map'] = time_map(p['notes'], len(x), sr)
    neutral = all(all(n[k] == v for k, v in DEFAULTS.items()) for n in p['notes'])
    y = x.copy() if neutral else process(x, sr, p)
    identical = np.array_equal(x, y)
    record = clean({'identical': identical, 'notes': p['notes'], 'time_map': p['time_map'],
                    'clip_samples': [a, b], 'measurements': accounting(x, y, sr),
                    'confidence': 'monophonic_estimate',
                    'caveats': ['Note times are relative to the sole unmuted clip.',
                                'Low-confidence and unvoiced pitch is preserved.',
                                'Time-map endpoints retain the clip and project duration.']})
    if identical:
        return ClipPlan({}, p, record)
    return DerivedPlan(a, b, p, process, fit='keep_length', record=record)


OPS = {'edit_pitch': OpSpec('edit', ('target', 'params'), validate, derive=derive,
                            code_version=VERSION, time_varying=True)}
