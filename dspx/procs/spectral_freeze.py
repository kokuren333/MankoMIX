"""T09-03 held spectrum with absolute-frame phase streams and exact regions.

Advance mode uses the specified bin-center phase advance. Its detuning on
off-grid tones is explicitly measured in the acceptance test, not hidden by
an unrequested sinusoidal-model replacement. Random mode is not a loop.
"""
import numpy as np
from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _a, _f, _i, _e


def validate(p):
    starts, ends = p['freeze_start_s'], p['freeze_end_s']
    if len(starts) != len(ends):
        raise ParamError('spectral_freeze: freeze array lengths must agree')
    if any(b <= a for a, b in zip(starts, ends)) or any(b >= a for b, a in zip(ends, starts[1:])):
        raise ParamError('spectral_freeze: ordered, separated, nonempty intervals required')


def latency_samples(sr, p):
    from mankomix.dspx.bb.stft import window_samples
    return window_samples(p['window'], sr)


def interval_envelope(length, sr, start, end, fade_in_ms, fade_out_ms):
    """Linear fades inside [start,end), exact zero outside, safe when short."""
    u = np.arange(length)
    env = ((u >= start) & (u < end)).astype(float)
    if fade_in_ms:
        env *= np.clip((u-start)/max(1, round(fade_in_ms*sr/1000)), 0, 1)
    if fade_out_ms:
        env *= np.clip((end-1-u)/max(1, round(fade_out_ms*sr/1000)), 0, 1)
    return env


def spectral_freeze(x, sr, p, *, seed=0, compensate=True):
    from mankomix.dspx.bb import stft
    from mankomix.dspx.procs.spectral_fx import event_rng
    validate(p)
    n = latency_samples(sr, p)
    y = x.copy()
    captures = []
    if p['freeze_start_s'] and len(x):
        a = stft.analyze(x, sr, window=n)
        z = a.spectra
        for event, (start_s, end_s) in enumerate(zip(p['freeze_start_s'], p['freeze_end_s'])):
            start, end = round(start_s*sr), round(end_s*sr)
            if end <= start:
                raise ParamError('spectral_freeze: interval collapses on sample grid')
            if start >= len(x):
                continue
            capture = min(len(z)-1, int(np.argmin(abs(a.samples-start))))
            count = max(1, round(p['capture_ms']*.001*sr/a.hop_samples))
            stop = min(len(z), capture+count)
            magnitude = np.mean(abs(z[capture:stop]), axis=0)
            initial_phase = np.angle(z[capture])
            frozen = np.zeros_like(z)
            # Frames with support in the interval, including its boundaries.
            frames = np.flatnonzero((a.samples+n//2 >= start) & (a.samples-n//2 < end))
            for t in frames:
                rng = event_rng(seed, p['seed'], int(t)*33+event)
                random_phase = rng.uniform(-np.pi, np.pi, magnitude.shape)
                drift_draw = rng.uniform(-1, 1, magnitude.shape)
                phase = (initial_phase+2*np.pi*a.frequencies_hz[:, None]
                         *(a.samples[t]-a.samples[capture])/sr) if p['phase_mode'] == 'advance' else random_phase
                frozen[t] = magnitude*10**((p['freeze_db']+3*p['drift']*drift_draw)/20)*np.exp(1j*phase)
                if p['phase_mode'] == 'random':
                    # Independent phases remove cross-frame covariance. With
                    # sqrt-Hann/4x WOLA the noise power drops by four; restore
                    # its expected level analytically, not by peak limiting.
                    frozen[t] *= 2
            frozen[:, 0] = frozen[:, 0].real
            frozen[:, -1] = frozen[:, -1].real
            wet = stft.synthesize(a, frozen)
            envelope = interval_envelope(len(x), sr, start, end, p['fade_in_ms'], p['fade_out_ms'])
            if p['input_during'] == 'mute':
                correction = wet-x
            else:
                correction = wet
            active = envelope > 0
            y[active] += envelope[active, None]*correction[active]
            captures.append(dict(start_s=start/sr, end_s=end/sr,
                                 capture_sample=int(a.samples[capture]), capture_frames=stop-capture))
    if not compensate:
        y = stft.delay_output(y, n)
    return y, sr, dict(latency_samples=n, latency_compensated=compensate, captures=captures)


SPECS = [dict(type='spectral_freeze', implemented=False,
    description='Offline-context held spectral amplitudes with evolving phase.',
    stages=['track', 'bus'], master_slot=None, offline_only=False, backends=['reference'],
    realtime=dict(block_ok=False, latency_samples='window_scaled', allocates=True),
    params=[
        _a('freeze_start_s', 's', 0, 36000, 32, [], 'Ordered freeze starts.'),
        _a('freeze_end_s', 's', 0, 36000, 32, [], 'Matching ends before the next start.'),
        _f('capture_ms', 'ms', 0, 500, 0, 'Capture magnitude averaging duration.'),
        _f('fade_in_ms', 'ms', 0, 5000, 30, 'Freeze entry fade.'),
        _f('fade_out_ms', 'ms', 0, 5000, 500, 'Freeze exit fade.'),
        _e('phase_mode', ['advance', 'random'], 'random', 'Phase update mode.'),
        _f('drift', None, 0, 1, 0, 'Random per-frame magnitude drift up to +/-3 dB.'),
        _e('window', [2048, 4096, 8192, 16384], 4096, '48 kHz analysis size.'),
        _e('input_during', ['mute', 'pass'], 'pass', 'Live input during freeze.'),
        _f('freeze_db', 'dB', -24, 12, 0, 'Held spectrum gain.'),
        _i('seed', None, 0, 65535, 0, 'Parameter seed.')])]
IMPLS = {'spectral_freeze': spectral_freeze}
TIME_VARYING = {'spectral_freeze'}
CROSS_VALIDATE = {'spectral_freeze': validate}
