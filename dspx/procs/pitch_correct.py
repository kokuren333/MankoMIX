"""Offline pYIN note tracking and deterministic monophonic pitch correction."""
import numpy as np
from mankomix.dspx.params import _f, _a, _e, _b
from mankomix.dspx.bb.time_creative import curve_param


def scale_params(harmony=False):
    from mankomix.dspx.bb.psola import KEYS
    return [_e('key', KEYS, 'C', 'Scale root.'),
        _e('scale', ['major', 'minor', 'custom'] if harmony else ['chromatic', 'major', 'minor', 'custom'],
           'major' if harmony else 'chromatic', 'Allowed pitch classes.'),
        _a('scale_mask', None, 0, 1, 12, [], 'Custom binary intervals from key.'),
        _f('a4_hz', 'Hz', 400, 480, 440, 'Reference tuning.')]


def validate(p):
    from mankomix.dspx.bb.psola import scale_notes
    from mankomix.dsp.errors import ParamError
    scale_notes(p['key'], p['scale'], p['scale_mask'])
    if p['lo_hz'] >= p['hi_hz']:
        raise ParamError('lo_hz must be below hi_hz')


def correction_curve(track, notes, frames, p):
    """Return samplewise cents and annotated notes; retune smooths note center.

    A 4..8 Hz vibrato component is separated before center smoothing and
    independently retained. This prevents a long retune time from making
    keep_vibrato=0 ineffective. Targets apply only in their explicit interval
    (a single point continues to the clip end), with step interpolation.
    """
    from scipy import signal
    from mankomix.dspx.bb.psola import scale_notes, nearest_note
    allowed = scale_notes(p['key'], p['scale'], p['scale_mask'])
    hz = track.f0_hz
    midi = np.full(len(hz), np.nan)
    good = track.voiced.copy()
    midi[good] = 69+12*np.log2(hz[good]/p['a4_hz'])
    control = np.zeros(len(hz))
    records = []
    for note in notes:
        ix = np.flatnonzero((track.samples >= note['start_sample']) & (track.samples < note['end_sample']) & good)
        if not len(ix):
            continue
        actual = midi[ix]
        target = np.full(len(ix), nearest_note(note['pitch_midi'], allowed))
        points = p['targets']
        if points:
            knots = np.asarray(points, dtype=float)
            times = track.samples[ix]/track.sr
            active = (times >= knots[0, 0]) & ((times <= knots[-1, 0]) if len(knots) > 1 else True)
            index = np.clip(np.searchsorted(knots[:, 0], times, side='right')-1, 0, len(knots)-1)
            target[active] = knots[index[active], 1]
        vibrato = np.zeros(len(ix))
        if len(ix) > 15:
            sos = signal.butter(2, [4, 8], btype='bandpass', fs=track.sr/track.hop_samples, output='sos')
            vibrato = signal.sosfiltfilt(sos, actual-np.median(actual), padlen=min(len(ix)-1, 24))
        center_error = 100*(target-actual+vibrato)
        if p['retune_ms']:
            alpha = np.exp(-track.hop_samples/(track.sr*p['retune_ms']*.001))
            center_error = signal.lfilter([1-alpha], [1, -alpha], center_error)
        correction = center_error-100*(1-p['keep_vibrato'])*vibrato
        correction[abs(100*(target-actual)) <= p['tolerance_cents']] = 0
        if p['transition_ms']:
            t = track.samples[ix]
            distance = np.minimum(t-note['start_sample'], note['end_sample']-t)
            correction *= .5-.5*np.cos(np.pi*np.clip(distance/(track.sr*p['transition_ms']*.0005), 0, 1))
        correction *= p['amount']
        correction[track.probability[ix] < p['min_confidence']] = 0
        control[ix] = correction
        records.append({**note, 'target_midi': float(np.median(target)),
                        'max_correction_cents': float(np.max(abs(correction)))})
    samples = np.arange(frames)
    cents = np.interp(samples, track.samples, control) if len(control) else np.zeros(frames)
    # Never bridge an unvoiced hole by interpolating cents across it.
    from mankomix.dspx.bb.pitch import sample_pitch
    _, voiced, probability = sample_pitch(track, samples)
    cents[~voiced | (probability < p['min_confidence'])] = 0
    return cents, records, float(np.mean(cents == 0)) if frames else 1.


def apply_correction(x, sr, cents, track, formant, min_confidence=.6):
    """Reuse BB-19 PSOLA or the existing BB-11 standard variable shifter."""
    from mankomix.dspx.bb.pitch import sample_pitch
    from mankomix.dsp.errors import ParamError
    hz, voiced, confidence = sample_pitch(track, np.arange(len(x)))
    voiced &= confidence >= min_confidence
    if np.any(voiced & (hz*2**(cents/1200) >= sr/2)):
        raise ParamError('requested voiced pitch must be below Nyquist at the processing sample rate')
    if formant:
        from mankomix.dspx.bb.psola import td_psola
        return td_psola(x, sr, 2**(cents/1200), track, min_confidence=min_confidence)
    from mankomix.dspx.bb.pitchtime import bend
    positions = np.r_[track.samples, len(x)-1]
    positions = np.unique(positions)
    points = [[float(n/sr), float(cents[n]/100)] for n in positions if 0 <= n < len(x)]
    if not points or not np.any(cents):
        return x.copy()
    wet = bend(x, sr, points, quality='standard')
    # BB-11's general bend has a 40 ms crossfade around active controls.
    # This processor's contract instead preserves unvoiced/low-confidence
    # samples exactly, with a 10 ms fade confined to the voiced side.
    from scipy.ndimage import distance_transform_edt
    active = voiced & (cents != 0)
    distance = distance_transform_edt(np.pad(active,(1,1)))[1:-1]
    blend = .5-.5*np.cos(np.pi*np.clip((distance-1)/max(1,.010*sr),0,1))
    return x+blend[:,None]*(wet-x)


def pitch_correct(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.psola import track_notes
    if p['amount'] == 0 or not len(x) or not np.any(x):
        return x.copy(), sr, dict(notes=[], untouched_fraction=1., mean_voiced_probability=0.)
    track, notes = track_notes(x, sr, fmin=p['lo_hz'], fmax=p['hi_hz'],
                              min_confidence=p['min_confidence'], a4_hz=p['a4_hz'])
    cents, records, _ = correction_curve(track, notes, len(x), p)
    y = apply_correction(x, sr, cents, track, p['formant'], p['min_confidence'])
    return y, sr, dict(notes=records, untouched_fraction=float(np.mean(np.all(y == x,axis=1))),
        mean_voiced_probability=float(np.mean(track.probability)) if len(track.probability) else 0.,
        latency_samples=0, full_context=True)


SPECS = [dict(type='pitch_correct', description='Offline monophonic scale correction.',
    stages=['track'], master_slot=None, offline_only=True, backends=['reference'], implemented=True,
    realtime=dict(block_ok=False, latency_samples=0, allocates=True,
                  latency_rule='Whole-clip pYIN analysis; offline centered synthesis.'),
    params=scale_params()+[
        _f('retune_ms', 'ms', 0, 500, 80, 'Center correction time constant.'),
        _f('amount', None, 0, 1, 1, 'Correction amount; zero bypasses.'),
        _f('tolerance_cents', 'cents', 0, 50, 0, 'Leave smaller errors untouched.'),
        _f('keep_vibrato', None, 0, 1, .7, 'Preserve the 4..8 Hz pitch component.'),
        _f('transition_ms', 'ms', 0, 300, 60, 'Weaken correction around note changes.'),
        _b('formant', True, 'Use pitch-synchronous formant preservation.'),
        _f('lo_hz', 'Hz', 40, 400, 70, 'Lowest tracked pitch.'),
        _f('hi_hz', 'Hz', 200, 2000, 1000, 'Highest tracked pitch.'),
        _f('min_confidence', None, 0, 1, .6, 'Minimum pYIN voiced probability.'),
        curve_param('targets', 4096, 0, 36000, 0, 127)])]
IMPLS = {'pitch_correct': pitch_correct}
TIME_VARYING = {'pitch_correct'}
CROSS_VALIDATE = {'pitch_correct': validate}
