"""T09-03 held spectrum with absolute-frame phase streams and exact regions.

Advance mode resolves the residual phase advance around each bin center
to retain off-grid frequencies. Random mode is not a waveform loop.
"""
import numpy as np
from scipy import fft
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


def _balance_random_phases(a, frozen, frames, reference, start, end):
    """Hold magnitudes while projecting seeded phases onto stable band powers.

    Alternating projections retain the captured magnitudes on the original
    sqrt-Hann grid. The other constraint is the capture's third-octave power
    on one-second tiles. It changes phases, never repeats a captured waveform
    or applies a time-varying gain to the final audio.
    """
    from mankomix.dspx.bb import stft
    sr = a.sr
    starts = np.arange(((start+sr-1)//sr)*sr, min(end, a.frames)-sr+1, sr, dtype=int)
    if len(starts) < 2 or len(reference) < 4:
        return frozen
    edges = np.unique(np.clip(np.r_[0, 1000*2**((np.arange(-30, 15)+.5)/3), sr/2], 0, sr/2))
    rf = fft.rfftfreq(len(reference), 1/sr)
    power = abs(fft.rfft(reference, axis=0, workers=1))**2/len(reference)**2
    power[1:len(power)-(len(reference) % 2 == 0)] *= 2
    cumulative = np.concatenate([np.zeros_like(power[:1]), np.cumsum(power, axis=0)])
    target = np.diff(cumulative[np.searchsorted(rf, edges)], axis=0)
    f = fft.rfftfreq(sr, 1/sr)
    boundaries = np.searchsorted(f, edges)
    band = np.clip(np.searchsorted(edges, f, side='right')-1, 0, len(target)-1)
    valid = (np.diff(boundaries) > 1)[:, None] & (target > 1e-30)
    magnitude = abs(frozen[frames])
    endpoints = frozen[frames][:, [0, -1]].real.copy()
    for _ in range(32):
        wet = stft.synthesize(a, frozen)
        blocks = np.stack([wet[t:t+sr] for t in starts])
        z = fft.rfft(blocks, axis=1, workers=1)
        power = abs(z)**2/sr**2
        power[:, 1:len(f)-(sr % 2 == 0)] *= 2
        cumulative = np.concatenate([np.zeros_like(power[:, :1]), np.cumsum(power, axis=1)], axis=1)
        energy = np.diff(cumulative[:, boundaries], axis=1)
        gain = np.where(valid[None], np.sqrt(target[None]/np.maximum(energy, 1e-30)), 1)
        z *= gain[:, band]
        corrected = fft.irfft(z, n=sr, axis=1, workers=1)
        for t, block in zip(starts, corrected):
            wet[t:t+sr] = block
        phase = np.angle(stft.analyze(wet, sr, window=len(a.window)).spectra[frames])
        frozen[frames] = magnitude*np.exp(1j*phase)
        frozen[frames, 0] = endpoints[:, 0]
        frozen[frames, -1] = endpoints[:, 1]
    hop = max(1, sr//8)
    starts = np.arange(((start+hop-1)//hop)*hop, min(end, a.frames)-sr+1, hop, dtype=int)
    return _refine_phase_energy(a, frozen, frames, starts, boundaries, band, valid)


def _refine_phase_energy(a, frozen, frames, starts, boundaries, band, valid):
    """Reduce residual temporal band variance with a phase-only gradient.

    The WOLA adjoint propagates the derivative of Fourier band powers to
    phases. A serial limited-memory quasi-Newton iteration uses only NumPy
    elementwise reductions, so no threaded matrix operations are requested.
    The band means after the consistency projection are held fixed here.
    """
    from mankomix.dspx.bb import stft
    sr, n = a.sr, len(a.window)
    magnitude = abs(frozen[frames])
    # Real inverse-FFT endpoints are held fixed, outside the phase search.
    endpoints = frozen[frames][:, [0, -1]].real.copy()
    weights = np.zeros(a.frames)
    for center in a.samples:
        left, right = max(0, center-n//2), min(a.frames, center+n//2)
        weights[left:right] += a.window[left-center+n//2:right-center+n//2]**2
    target = None

    def objective(flat):
        nonlocal target
        z = magnitude*np.exp(1j*flat.reshape(magnitude.shape))
        z[:, [0, -1]] = endpoints
        frozen[frames] = z
        wet = stft.synthesize(a, frozen)
        tiles = np.stack([wet[t:t+sr] for t in starts])
        spectrum = fft.rfft(tiles, axis=1, workers=1)
        power = abs(spectrum)**2/sr**2
        power[:, 1:power.shape[1]-(sr % 2 == 0)] *= 2
        cumulative = np.concatenate([np.zeros_like(power[:, :1]), np.cumsum(power, axis=1)], axis=1)
        energy = np.diff(cumulative[:, boundaries], axis=1)
        if target is None:
            target = np.maximum(np.mean(energy, axis=0), 1e-30)
        error = (energy/target[None]-1)*valid[None]
        loss = float(np.mean(error**2))
        derivative = error/target[None]/error.size
        tile_gradient = 4/sr*fft.irfft(spectrum*derivative[:, band], n=sr, axis=1, workers=1)
        gradient = np.zeros_like(wet)
        for t, tile in zip(starts, tile_gradient):
            gradient[t:t+sr] += tile
        gradient /= weights[:, None]
        padded = np.pad(gradient, ((n//2, n), (0, 0)))
        blocks = np.lib.stride_tricks.sliding_window_view(padded, n, axis=0)[a.samples[frames]]
        adjoint = fft.rfft(blocks*a.window, axis=-1, workers=1).transpose(0, 2, 1)
        phase_gradient = -2/n*np.imag(np.conj(adjoint)*z)
        phase_gradient[:, [0, -1]] = 0
        return loss, phase_gradient.ravel()

    phase = np.angle(frozen[frames]).ravel()
    loss, gradient = objective(phase)
    history = []
    for _ in range(160):
        if np.max(abs(gradient), initial=0) < 1e-10:
            break
        direction = gradient.copy()
        alphas = []
        for step, delta, rho in reversed(history):
            alpha = rho*np.sum(step*direction)
            direction -= alpha*delta
            alphas.append(alpha)
        if history:
            step, delta, _ = history[-1]
            direction *= np.sum(step*delta)/np.sum(delta*delta)
        else:
            direction *= .25/max(np.max(abs(direction)), 1e-30)
        for (step, delta, rho), alpha in zip(history, reversed(alphas)):
            direction += step*(alpha-rho*np.sum(delta*direction))
        direction *= -1
        slope = float(np.sum(gradient*direction))
        if slope >= 0:
            history.clear()
            direction = -gradient*.25/max(np.max(abs(gradient)), 1e-30)
            slope = float(np.sum(gradient*direction))
        size = 1.
        for _ in range(14):
            candidate = phase+size*direction
            next_loss, next_gradient = objective(candidate)
            if next_loss <= loss+1e-4*size*slope:
                break
            size *= .5
        else:
            break
        step, delta = candidate-phase, next_gradient-gradient
        curvature = float(np.sum(step*delta))
        if curvature > 1e-20:
            history.append((step, delta, 1/curvature))
            history = history[-5:]
        phase, loss, gradient = candidate, next_loss, next_gradient
    objective(phase)
    return frozen


def spectral_freeze(x, sr, p, *, seed=0, compensate=True):
    from mankomix.dspx.bb import stft
    from mankomix.dspx.procs.spectral_fx import event_rng, instantaneous_frequencies
    validate(p)
    n = latency_samples(sr, p)
    y = x.copy()
    captures = []
    if p['freeze_start_s'] and len(x):
        a = stft.analyze(x, sr, window=n)
        z = a.spectra
        advances = instantaneous_frequencies(a) if p['phase_mode'] == 'advance' else None
        for event, (start_s, end_s) in enumerate(zip(p['freeze_start_s'], p['freeze_end_s'])):
            start, end = round(start_s*sr), round(end_s*sr)
            if end <= start:
                raise ParamError('spectral_freeze: interval collapses on sample grid')
            if start >= len(x):
                continue
            capture = min(len(z)-1, int(np.argmin(abs(a.samples-start))))
            count = max(1, round(p['capture_ms']*.001*sr/a.hop_samples))
            stop = min(len(z), capture+count)
            magnitude = np.sqrt(np.mean(abs(z[capture:stop])**2, axis=0))
            initial_phase = np.angle(z[capture])
            frequencies = advances[capture] if advances is not None else None
            frozen = np.zeros_like(z)
            # Frames with support in the interval, including its boundaries.
            frames = np.flatnonzero((a.samples+n//2 >= start) & (a.samples-n//2 < end))
            for t in frames:
                rng = event_rng(seed, p['seed'], int(t)*33+event)
                random_phase = rng.uniform(-np.pi, np.pi, magnitude.shape)
                drift_draw = rng.uniform(-1, 1, magnitude.shape)
                phase = (initial_phase+2*np.pi*frequencies
                         *(a.samples[t]-a.samples[capture])/sr) if p['phase_mode'] == 'advance' else random_phase
                frozen[t] = magnitude*10**((p['freeze_db']+3*p['drift']*drift_draw)/20)*np.exp(1j*phase)
                if p['phase_mode'] == 'random':
                    # Independent phases remove cross-frame covariance. With
                    # sqrt-Hann/4x WOLA the noise power drops by four; restore
                    # its expected level analytically, not by peak limiting.
                    frozen[t] *= 2
            if p['phase_mode'] == 'random' and not p['drift'] and min(end, len(x))-start >= 3*sr:
                if p['capture_ms']:
                    duration = max(n, round(p['capture_ms']*.001*sr))
                    reference = x[start:min(len(x), start+duration)]
                else:
                    # A single-frame capture is its windowed spectrum, with
                    # Parseval's window-power normalization (not a raw slice).
                    reference = fft.irfft(z[capture], n=n, axis=0, workers=1)
                    reference *= np.sqrt(n/np.sum(a.window*a.window))
                reference = reference*10**(p['freeze_db']/20)
                frozen *= .5
                frozen[:, 0] = frozen[:, 0].real
                frozen[:, -1] = frozen[:, -1].real
                frozen = _balance_random_phases(a, frozen, frames, reference, start, end)
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


SPECS = [dict(type='spectral_freeze', implemented=True,
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
