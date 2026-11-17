"""Offline scale-degree voices using BB-12 tracking and BB-19 PSOLA."""
import numpy as np
from mankomix.dspx.params import _f, _i, _a, _e, _b


def validate(p):
    from mankomix.dsp.errors import ParamError
    from mankomix.dspx.bb.psola import scale_notes
    scale_notes(p['key'], p['scale'], p['scale_mask'])
    if p['scale'] == 'chromatic':
        raise ParamError('harmony degrees require a nonchromatic scale')
    if any(v != int(v) for v in p['degrees']):
        raise ParamError('degrees must be integers')
    for name in ('level_db', 'pan', 'delay_ms'):
        if p[name] and len(p[name]) != len(p['degrees']):
            raise ParamError(name+' must be empty or match degrees')


def voices(p):
    """Expand empty parallel arrays; -60 dB is the specified mute sentinel."""
    validate(p)
    return [dict(degree=int(d), **{key: p[key][i] if p[key] else default
                for key, default in (('level_db', -6), ('pan', 0), ('delay_ms', 10))})
            for i, d in enumerate(p['degrees'])]


def harmony_voices(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.psola import track_notes, scale_notes, td_psola
    from mankomix.dspx.bb.delayline import read_samples
    resolved = voices(p)
    active = [v for v in resolved if v['level_db'] > -60]
    y = x.copy() if p['dry_db'] == 0 else x*10**(p['dry_db']/20)
    if not active or not len(x) or not np.any(x):
        return y, sr, dict(voices=resolved, notes=[])
    tr, notes = track_notes(x, sr, a4_hz=p['a4_hz'])
    allowed = scale_notes(p['key'], p['scale'], p['scale_mask'])
    rng = np.random.Generator(np.random.PCG64(np.random.SeedSequence([int(seed), p['seed'], 319])))
    if x.shape[1] == 1 and any(v['pan'] != 0 for v in active):
        y = np.repeat(y, 2, axis=1)
    logs = []
    for voice in active:
        cents, delays = np.zeros(len(x)), np.full(len(x), voice['delay_ms'])
        note_mask = np.zeros(len(x), bool)
        record = []
        for note in notes:
            index = int(np.argmin(abs(allowed-note['pitch_midi'])))
            target = float(allowed[index+voice['degree']])
            jitter_cents = rng.uniform(-p['humanize_cents'], p['humanize_cents'])
            jitter_ms = rng.uniform(-p['humanize_ms'], p['humanize_ms'])
            lo, hi = note['start_sample'], note['end_sample']
            note_mask[lo:hi] = True
            cents[lo:hi] = 100*(target-note['pitch_midi'])+jitter_cents
            delays[lo:hi] = max(0., voice['delay_ms']+jitter_ms)
            record.append({**note, 'target_midi': target, 'humanize_cents': float(jitter_cents),
                           'delay_ms': float(max(0., voice['delay_ms']+jitter_ms))})
        if p['formant']:
            wet = td_psola(x, sr, 2**(cents/1200), tr)
        else:
            from mankomix.dspx.procs.pitch_correct import apply_correction
            wet = apply_correction(x, sr, cents, tr, False)
        wet[~note_mask] = 0
        wet = read_samples(wet, np.arange(len(x))-delays*sr/1000, method='sinc8')
        if y.shape[1] == 2:
            if wet.shape[1] == 1:
                wet = np.repeat(wet, 2, axis=1)
            wet *= [1-max(0., voice['pan']), 1+min(0., voice['pan'])]
        y += wet*10**(voice['level_db']/20)
        logs.append(dict(**voice, notes=record))
    return y, sr, dict(voices=logs, notes=notes, latency_samples=0, full_context=True)


# Keep registration independent of another processor's import side effects.
SPECS = [dict(type='harmony_voices', description='Offline scale-degree harmony voices.',
    stages=['track'], master_slot=None, offline_only=True, backends=['reference'], implemented=True,
    realtime=dict(block_ok=False, latency_samples=0, allocates=True), params=[
        _e('key', ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'], 'C', 'Scale root.'),
        _e('scale', ['major', 'minor', 'custom'], 'major', 'Scale defining degrees.'),
        _a('scale_mask', None, 0, 1, 12, [], 'Custom binary intervals from key.'),
        _f('a4_hz', 'Hz', 400, 480, 440, 'Reference tuning.'),
        _a('degrees', 'degrees', -14, 14, 4, [2], 'Integer scale-degree offsets.'),
        _a('level_db', 'dB', -60, 6, 4, [], 'Voice gains; empty: -6; -60: mute.'),
        _a('pan', None, -1, 1, 4, [], 'Voice balance; empty: center.'),
        _a('delay_ms', 'ms', 0, 60, 4, [], 'Voice delays; empty: 10 ms.'),
        _f('humanize_cents', 'cents', 0, 30, 6, 'Per-note seeded pitch jitter.'),
        _f('humanize_ms', 'ms', 0, 40, 8, 'Per-note seeded delay jitter.'),
        _b('formant', True, 'Pitch-synchronous formant preservation.'),
        _f('dry_db', 'dB', -90, 6, 0, 'Dry gain.'),
        _i('seed', None, 0, 65535, 0, 'Voice jitter seed.')])]
IMPLS = {'harmony_voices': harmony_voices}
TIME_VARYING = {'harmony_voices'}
CROSS_VALIDATE = {'harmony_voices': validate}
