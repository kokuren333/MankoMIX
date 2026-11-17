"""T11-04 onset-triggered gate using BB-03's open/hold/release machine."""
import numpy as np
from mankomix.dspx.params import _f

TABLE = [('threshold_db', 'dBFS', -80, 0, -30), ('detect_lo_hz', 'Hz', 20, 20000, 40),
         ('detect_hi_hz', 'Hz', 20, 20000, 200), ('reject_lo_hz', 'Hz', 0, 20000, 0),
         ('reject_hi_hz', 'Hz', 0, 20000, 0), ('reject_ratio_db', 'dB', -12, 24, 6),
         ('range_db', 'dB', -90, 0, -40), ('lookahead_ms', 'ms', 0, 20, 5),
         ('attack_ms', 'ms', .05, 20, .5), ('hold_ms', 'ms', 0, 2000, 60),
         ('release_ms', 'ms', 10, 3000, 200), ('decay_follow', '', 0, 1, .6),
         ('velocity_sense', '', 0, 1, .3), ('min_interval_ms', 'ms', 5, 500, 30),
         ('resonance_cut', '', 0, 1, 0)]
SPECS = [{'type': 'drum_gate', 'name': 'Drum gate', 'description': 'Onset-triggered band-selective gate.',
          'stages': ['track'], 'master_slot': None, 'offline_only': True, 'backends': ['reference'], 'implemented': True,
          'realtime': {'block_ok': False, 'latency_samples': 0, 'allocates': True},
          'params': [_f(k, u, lo, hi, d, k.replace('_', ' ')) for k, u, lo, hi, d in TABLE]}]
TIME_VARYING = {'drum_gate'}


def check(p):
    from mankomix.dspx.bb.drum_events import check_bands
    check_bands(p)


def drum_gate(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.drum_events import drum_events, band_audio
    from mankomix.dspx.bb.dynamics import GateState
    from scipy import ndimage
    rows, detected = drum_events(x, sr, p)
    levels = np.full((len(x), 1), -300.)
    velocity_db = np.zeros(len(x))
    envelope = np.sqrt(np.maximum(0, ndimage.uniform_filter1d(np.mean(detected**2, axis=1),
                                       max(1, round(.005*sr))))) if len(x) else np.zeros(0)
    look, attack = round(p['lookahead_ms']*sr/1000), max(1, round(p['attack_ms']*sr/1000))
    windows = []
    openings = []
    strongest = max((r['detect_peak_dbfs'] for r in rows if r['opened']), default=0.)
    for r in rows:
        if not r['opened']:
            continue
        pos = r['sample']
        start = max(0, pos-look)
        tail = min(len(x), pos+round(3*sr))
        peak_end = min(tail, pos+round(.03*sr))
        peak = pos+int(np.argmax(envelope[pos:peak_end])) if peak_end > pos else pos
        crossed = np.flatnonzero(envelope[peak:tail] < envelope[peak]*.1)
        follow = (peak+int(crossed[0])-pos) if len(crossed) else tail-pos
        stop = min(len(x), pos+max(round(.005*sr), round(p['decay_follow']*follow)))
        levels[start:stop] = 0
        amount = p['velocity_sense']*min(0., r['detect_peak_dbfs']-strongest)
        openings.append((start, amount))
        r.update(open_start_sample=start, trigger_end_sample=stop,
                 close_start_sample=min(len(x), stop+round(p['hold_ms']*sr/1000)), open_gain_db=amount)
        windows.append((start, stop))
    for i, (start, amount) in enumerate(openings):
        stop = openings[i+1][0] if i+1 < len(openings) else len(x)
        velocity_db[start:stop] = amount
    machine = GateState(sr, {'threshold_db': -1, 'ratio': 100, 'range_db': p['range_db'],
                            'knee_db': 0, 'hysteresis_db': 0, 'hold_ms': p['hold_ms'],
                            'attack_ms': p['attack_ms'], 'release_ms': p['release_ms']})
    machine.gain, machine.open, machine.remaining = np.array([p['range_db']]), np.array([False]), np.array([0])
    db, states = machine.process(levels)
    # A finite opening ramp reaches exact unity; this preserves open audio bits.
    for start, stop in windows:
        end = min(stop, start+attack)
        db[start:end, 0] = np.linspace(db[start, 0], 0., end-start, endpoint=False)
        db[end:stop, 0] = 0
    db[states[:, 0] > 0, 0] = np.where(levels[states[:, 0] > 0, 0] < -1, 0,
                                       db[states[:, 0] > 0, 0])
    # Interpolate the opening level back to the exact closed floor during release.
    active = np.clip(1+db/max(abs(p['range_db']), 1e-30), 0, 1)
    db += velocity_db[:, None]*active
    gain = 10**(db/20)
    y = x*gain
    if p['resonance_cut'] and len(x):
        low = band_audio(x, sr, max(1, p['detect_lo_hz']/2), p['detect_lo_hz'])
        closing = (states[:, 0] == 0)[:, None]
        y -= low*gain*closing*p['resonance_cut']*(1-gain)
    return y, sr, {'latency_samples': 0, 'latency_compensated': True,
                    'lookahead_samples': look, 'hits': rows,
                    'opened_count': sum(r['opened'] for r in rows)}


CROSS_VALIDATE = {'drum_gate': check}
IMPLS = {'drum_gate': drum_gate}
