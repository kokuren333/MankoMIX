"""BB-19: pitch-synchronous synthesis and spectral/LPC envelopes.

Independent implementations of pitch-synchronous OLA (Moulines & Charpentier,
Speech Communication 1990), autocorrelation LPC/Schur recursion (Makhoul,
Proc. IEEE 1975, doi:10.1109/PROC.1975.9792), and iterative cepstral upper
envelopes (Roebel & Rodet, DAFx-05). No external implementation is copied.

Audio is float64 (frames, channels). Public API:
 lpc(frame, order) -> (monic denominator, reflection coefficients, error power)
 reflection_to_lpc(k), lpc_to_reflection(a): step-up/down, |k| < 1
 interpolate_lpc(k0, k1, fraction): stable interpolation in reflection space
 spectral_envelope(magnitude, sr, method, order): frequency axis is axis 0
 envelope_transfer(source, target, limit_db=24): bounded target/source gain
 shift_envelope(x, sr, cents, ...): (centered audio, analysis window samples)
 pitch_marks(x, sr, track): approximate closures at fractional sample positions
 td_psola(x, sr, ratio, track=None, ...): same-length voiced shift; unvoiced dry
 voice_track(x, sr, ...): BB-12 pYIN with a conservative low-pass second pass
 track_notes(x, sr, ...): (BB-12 PitchTrack, note dictionaries), 60 ms hysteresis
 scale_notes(key, scale, mask), nearest_note(midi, allowed): scale arithmetic
 lpc_frames(x, sr, order, frame_ms, emphasis=0): centers, reflections, RMS gain
 lattice_synthesis(excitation, centers, reflections, gains): continuous state,
 samplewise linear interpolation of stable reflection coefficients.
Whole-context offline calls have no persistent streaming state.
"""
from __future__ import annotations

import numpy as np
from scipy import fft, signal, ndimage
from mankomix.dsp.errors import ParamError


def _audio(x, sr):
    a = np.asarray(x, dtype=np.float64)
    if (a.ndim != 2 or a.shape[1] < 1 or not np.isfinite(a).all()
            or isinstance(sr, bool) or not np.isfinite(sr) or sr <= 0 or int(sr) != sr):
        raise ParamError('finite frames/channels audio and positive integer sr required')
    return a


def reflection_to_lpc(k):
    """Step-up recursion; denominator convention y[n]+sum(a[j]*y[n-j])."""
    k = np.asarray(k, dtype=np.float64)
    if k.ndim != 1 or not np.isfinite(k).all() or np.any(abs(k) >= 1):
        raise ParamError('reflection coefficients must be finite with magnitude < 1')
    a = np.ones(1)
    for value in k:
        a = np.r_[a, 0.] + value*np.r_[0., a[::-1]]
    return a


def lpc_to_reflection(a):
    """Step-down recursion; reject unstable rather than silently repair models."""
    a = np.asarray(a, dtype=np.float64).copy()
    if a.ndim != 1 or not len(a) or a[0] != 1 or not np.isfinite(a).all():
        raise ParamError('finite monic LPC polynomial required')
    out = np.empty(len(a)-1)
    for m in range(len(a)-1, 0, -1):
        k = a[m]
        if abs(k) >= 1:
            raise ParamError('unstable LPC model')
        out[m-1] = k
        a = (a[:m]-k*a[m:0:-1])/(1-k*k)
    return out


def interpolate_lpc(k0, k1, fraction):
    """Return a denominator at fraction 0..1 in reflection space."""
    if not np.isfinite(fraction) or not 0 <= fraction <= 1:
        raise ParamError('interpolation fraction must be in [0,1]')
    reflection_to_lpc(k0)
    reflection_to_lpc(k1)
    if np.shape(k0) != np.shape(k1):
        raise ParamError('reflection orders differ')
    return reflection_to_lpc((1-fraction)*np.asarray(k0)+fraction*np.asarray(k1))


def lpc(frame, order):
    """Autocorrelation/Levinson LPC with relative 1e-7 diagonal loading."""
    v = np.asarray(frame, dtype=np.float64)
    if (v.ndim != 1 or not np.isfinite(v).all() or isinstance(order, bool)
            or not isinstance(order, (int, np.integer)) or order < 1):
        raise ParamError('LPC requires a finite vector and positive integer order')
    if not len(v) or not np.any(v):
        return np.r_[1., np.zeros(order)], np.zeros(order), 0.
    size = fft.next_fast_len(2*len(v)-1)
    power = abs(fft.rfft(v, size, workers=1))**2
    r = fft.irfft(power, size, workers=1)[:order+1]
    r = np.pad(r, (0, max(0, order+1-len(r))))
    a, k, error = _levinson(r, order)
    return a, k, error/len(v)


def _levinson(correlation, order):
    """Shared autocorrelation recursion; error has the units of lag zero."""
    r = np.asarray(correlation, dtype=np.float64).copy()
    r[0] *= 1+1e-7
    error, a, ks = float(r[0]), np.ones(1), []
    for m in range(1, order+1):
        k = float(np.clip(-(r[m]+a[1:] @ r[m-1:0:-1])/max(error, 1e-30), -.9999, .9999))
        ks.append(k)
        a = np.r_[a, 0.] + k*np.r_[0., a[::-1]]
        error = max(error*(1-k*k), 1e-30)
    return a, np.asarray(ks), error


def spectral_envelope(magnitude, sr, method='true_env', order=40):
    """Estimate positive amplitude envelope; order is specified at 48 kHz."""
    m = np.asarray(magnitude, dtype=np.float64)
    if (m.ndim not in (1, 2) or len(m) < 3 or not np.isfinite(m).all()
            or np.any(m < 0) or sr <= 0 or order < 1
            or method not in ('cepstrum', 'lpc', 'true_env')):
        raise ParamError('invalid spectral envelope input')
    mono = m.ndim == 1
    m = m[:, None] if mono else m
    size = 2*(len(m)-1)
    count = max(1, min(size//2-1, round(order*sr/48000)))
    floor = np.max(m, axis=0, keepdims=True)*1e-8+1e-30
    logs = np.log(np.maximum(m, floor))
    if method == 'lpc':
        env = np.empty_like(m)
        for c in range(m.shape[1]):
            # Autocorrelation comes directly from the power spectrum. A
            # zero-phase inverse waveform wraps across its edges: treating
            # that waveform as zero-extended would change its correlation.
            correlation = fft.irfft(m[:, c]**2, size, workers=1)
            a, _, error = _levinson(correlation[:count+1], count)
            response = abs(fft.rfft(a, size, workers=1))
            env[:, c] = np.sqrt(error)/np.maximum(response, 1e-15)
    else:
        def smooth(v):
            cep = fft.irfft(v, size, axis=0, workers=1)
            cep[count+1:-count] = 0
            return fft.rfft(cep, size, axis=0, workers=1).real
        estimate = smooth(logs)
        if method == 'true_env':
            for _ in range(100):
                if np.max(logs-estimate) <= .005:
                    break
                estimate = smooth(np.maximum(logs, estimate))
        env = np.exp(np.clip(estimate, -700, 700))
    return env[:, 0] if mono else env


def envelope_transfer(source, target, limit_db=24):
    """Real positive gain; the phase of the spectrum is preserved."""
    s, t = np.asarray(source), np.asarray(target)
    if not np.isfinite(s).all() or not np.isfinite(t).all() or np.any(s < 0) or np.any(t < 0) or limit_db < 0:
        raise ParamError('invalid envelope transfer')
    bound = 10**(limit_db/20)
    return np.clip(t/np.maximum(s, 1e-30), 1/bound, bound)


def resolved_spectral_envelope(magnitude, sr, method='true_env', order=40, *, window=2048):
    """Precondition the requested estimator with a window-debiased AR envelope.

    Short-window cepstral smoothing alone broadens narrow resonances. An
    eight-pole seed removes that curvature before estimating the residual
    with the selected method/order, then restores it. Its correlation is
    divided by the Hann autocorrelation, undoing analysis-window broadening.
    A grid capped at 16 kHz keeps the low-frequency pole fit conditioned at
    high sample rates; above that grid the residual models the spectrum.
    This is opt-in: spectral_envelope retains its original behavior.
    """
    m = np.asarray(magnitude, dtype=np.float64)
    if (m.ndim not in (1, 2) or len(m) < 3 or not np.isfinite(m).all()
            or np.any(m < 0) or sr <= 0 or order < 1
            or method not in ('cepstrum', 'lpc', 'true_env')):
        raise ParamError('invalid spectral envelope input')
    mono = m.ndim == 1
    m = m[:, None] if mono else m
    n = 2*(len(m)-1)
    if n != window:
        raise ParamError('envelope spectrum must match the Hann window')
    from .stft import sqrt_hann
    ref_sr = min(sr, 16000)
    ref_n = max(4, 4*round(n*ref_sr/sr/4))
    ref_f = fft.rfftfreq(ref_n, 1/ref_sr)
    f = fft.rfftfreq(n, 1/sr)
    w = sqrt_hann(ref_n)**2
    count = min(8, ref_n//2-1)
    wc = np.correlate(w, w, mode='full')[ref_n-1:ref_n+count]
    wc /= wc[0]
    seed = np.empty_like(m)
    low_env = np.empty((len(ref_f), m.shape[1])) if method == 'lpc' and ref_sr < sr else None
    for c in range(m.shape[1]):
        ref_m = np.interp(ref_f, f, m[:, c])
        r = fft.irfft(ref_m**2, ref_n, workers=1)[:count+1]/wc
        a, _, error = _levinson(r, count)
        response = np.maximum(abs(fft.rfft(a, ref_n, workers=1)), 1e-15)
        ref_seed = np.maximum(np.sqrt(error)/response, 1e-30)
        seed[:, c] = np.interp(f, ref_f, ref_seed)
        if low_env is not None:
            low_env[:, c] = ref_seed*spectral_envelope(ref_m/ref_seed, ref_sr, method, order)
    seed = np.maximum(seed, 1e-30)
    env = seed*spectral_envelope(m/seed, sr, method, order)
    if low_env is not None:
        # The residual all-pole fit needs the same conditioning as its seed.
        # Crossfade back to the full-band model over the grid's last octave.
        blend = np.clip((f-ref_sr/4)/(ref_sr/4), 0, 1)
        for c in range(m.shape[1]):
            low = np.interp(f, ref_f, low_env[:, c])
            env[:, c] = np.exp((1-blend)*np.log(np.maximum(low, 1e-30))
                               +blend*np.log(np.maximum(env[:, c], 1e-30)))
    return env[:, 0] if mono else env


def _resolved_envelope_shift(x, sr, cents, method, order, n, lo_hz, hi_hz, target):
    """Hann WOLA and component-coherent, bounded real envelope gains."""
    from dataclasses import replace
    from . import stft as S

    def analyze(v):
        a = S.analyze(v, sr, window=n)
        # BB-06's default sqrt-Hann path remains unchanged. Multiplying once
        # more yields a Hann analysis/synthesis pair with lower sidelobes.
        blocks = fft.irfft(a.spectra, n, axis=1, workers=1)*a.window[None, :, None]
        return replace(a, window=a.window**2,
                       spectra=fft.rfft(blocks, axis=1, workers=1))

    a = analyze(x)
    other = analyze(target) if target is not None else a
    if other.spectra.shape != a.spectra.shape:
        raise ParamError('envelope donor must match audio shape')
    f = a.frequencies_hz
    weights = ((f >= lo_hz) & (f <= hi_hz)).astype(float)
    if lo_hz:
        weights *= .5-.5*np.cos(np.pi*np.clip(3*np.log2(np.maximum(f, 1e-30)/lo_hz), 0, 1))
    weights *= .5-.5*np.cos(np.pi*np.clip(3*np.log2(hi_hz/np.maximum(f, 1e-30)), 0, 1))
    # Five centers cover +/- half a window. Together with centered analysis,
    # the latest required input stays within the declared one-window buffer.
    mags = np.sqrt(np.maximum(0, ndimage.uniform_filter1d(abs(a.spectra)**2, 5, axis=0, mode='nearest')))
    donors = (np.sqrt(np.maximum(0, ndimage.uniform_filter1d(abs(other.spectra)**2, 5, axis=0, mode='nearest')))
              if target is not None else mags)
    gains = np.ones_like(mags)
    for i, m in enumerate(mags):
        env = resolved_spectral_envelope(m, sr, method, order, window=n)
        donor = resolved_spectral_envelope(donors[i], sr, method, order, window=n) if target is not None else env
        shifted = np.column_stack([np.interp(f/2**(cents/1200), f, e) for e in donor.T])
        logs = np.log(envelope_transfer(env, shifted))
        for c in range(x.shape[1]):
            peaks = signal.find_peaks(m[:, c], prominence=np.max(m[:, c])*1e-6, distance=3)[0]
            if len(peaks):
                # A sinusoid occupies several window bins. Give its whole
                # region one gain evaluated at its spectral peak bin,
                # preserving its phase and avoiding hop-synchronous beating.
                bounds = np.r_[0, (peaks[1:]+peaks[:-1])//2, len(f)]
                values = logs[peaks, c].copy()
                for j, value in enumerate(values):
                    logs[bounds[j]:bounds[j+1], c] = value
        gains[i] = np.exp(logs*weights[:, None])
    gains = S.smooth_gains(gains, sr, a.hop_samples, f, time_ms=20)
    return S.synthesize(a, a.spectra*gains), n


def shift_envelope(x, sr, cents, *, method='true_env', order=40, window=2048,
                   lo_hz=100, hi_hz=10000, target=None, resolved=False):
    """Move E(f) to E(f/ratio), or transfer target audio's centered envelope.

    resolved=True opts into window-debiased estimation and component gains;
    the default preserves the original shared pitch/harmony processing.
    """
    from . import stft as S
    x = _audio(x, sr)
    if not np.isfinite(cents) or not 0 <= lo_hz < hi_hz:
        raise ParamError('invalid envelope shift or band')
    if (cents == 0 and target is None) or not len(x) or not np.any(x):
        return x.copy(), 0
    n = S.window_samples(window, sr)
    if resolved:
        return _resolved_envelope_shift(x, sr, cents, method, order, n, lo_hz, hi_hz, target)
    a = S.analyze(x, sr, window=n)
    other = S.analyze(target, sr, window=n) if target is not None else a
    if other.spectra.shape != a.spectra.shape:
        raise ParamError('envelope donor must match audio shape')
    gains = np.ones_like(a.spectra.real)
    f = a.frequencies_hz
    weights = ((f >= lo_hz) & (f <= hi_hz)).astype(float)
    # Raised-cosine edges, including the legal DC=0 band endpoint.
    if lo_hz:
        weights *= .5-.5*np.cos(np.pi*np.clip(3*np.log2(np.maximum(f, 1e-30)/lo_hz), 0, 1))
    weights *= .5-.5*np.cos(np.pi*np.clip(3*np.log2(hi_hz/np.maximum(f, 1e-30)), 0, 1))
    for i, z in enumerate(a.spectra):
        env = spectral_envelope(abs(z), sr, method, order)
        donor = spectral_envelope(abs(other.spectra[i]), sr, method, order) if target is not None else env
        shifted = np.column_stack([np.interp(f/2**(cents/1200), f, donor[:, c]) for c in range(x.shape[1])])
        gains[i] = np.exp(np.log(envelope_transfer(env, shifted))*weights[:, None])
    # Envelope estimates fluctuate with the position of the harmonic cycles
    # inside the window. Smooth the *real gains*, retaining the input phase.
    gains = S.smooth_gains(gains, sr, a.hop_samples, f, time_ms=80)
    return S.synthesize(a, a.spectra*gains), n


def pitch_marks(x, sr, track):
    """Predict periods from BB-12; snap closures using same-polarity slope peaks."""
    from .pitch import sample_pitch
    a = _audio(x, sr)
    if not len(a) or not np.any(track.voiced):
        return np.empty(0)
    mono = a[:, int(np.argmax(np.sum(a*a, axis=0)))]
    slope = np.r_[0., np.diff(mono)]
    # A fixed polarity avoids alternating positive/negative closure choices.
    polarity = 1 if np.max(slope) >= -np.min(slope) else -1
    strength = slope*polarity
    out, pos = [], 0.
    while pos < len(a):
        hz, voiced, _ = sample_pitch(track, np.array([pos]))
        if not voiced[0]:
            pos += track.hop_samples
            continue
        period = sr/hz[0]
        radius = .28*period if not out else .12*period
        left, right = max(1, round(pos-radius)), min(len(a)-1, round(pos+radius)+1)
        if right <= left:
            break
        peak = left+int(np.argmax(strength[left:right]))
        den = strength[peak-1]-2*strength[peak]+strength[peak+1]
        delta = .5*(strength[peak-1]-strength[peak+1])/den if den < 0 else 0.
        mark = peak+np.clip(delta, -.5, .5)
        if not out or mark-out[-1] > .45*period:
            out.append(float(mark))
        pos = mark+period
    return np.asarray(out)


def td_psola(x, sr, ratio, track=None, *, fmin=70, fmax=1000, min_confidence=.6):
    """Pitch-synchronous two-period Hann grains; shared marks across channels.

    ratio is scalar or frames values. Unvoiced/low-confidence intervals retain
    dry samples, with an inward 10 ms raised-cosine crossfade. Unity is exact.
    """
    from .pitch import sample_pitch
    from .delayline import read_samples
    a = _audio(x, sr)
    r = np.broadcast_to(np.asarray(ratio, dtype=np.float64), (len(a),))
    if not np.isfinite(r).all() or np.any(r <= 0):
        raise ParamError('PSOLA ratios must be finite and positive')
    if not len(a) or np.all(r == 1) or not np.any(a):
        return a.copy()
    if track is None:
        track = voice_track(a, sr, fmin=fmin, fmax=fmax)
    marks = pitch_marks(a, sr, track)
    if len(marks) < 3:
        return a.copy()
    samples = np.arange(len(a))
    hz, voiced, confidence = sample_pitch(track, samples)
    voiced &= confidence >= min_confidence
    # Actual mark spacing refines the quantized pYIN grid without replacing its
    # voicing decisions. Long gaps are never interpreted as a pitch period.
    periods = np.diff(marks)
    valid = periods < 1.5*sr/fmin
    # Smooth periods before inversion: averaging instantaneous 1/T would
    # bias F0 upwards when closure snapping alternates between nearby peaks.
    stable_periods = ndimage.median_filter(periods, size=5, mode='nearest')
    stable_periods = ndimage.gaussian_filter1d(stable_periods, 1, mode='nearest')
    refined = np.interp(samples, (marks[:-1]+marks[1:])/2,
                        np.where(valid, sr/stable_periods, np.nan))
    hz = np.where(np.isfinite(refined), refined, hz)
    target_hz = np.nan_to_num(hz, nan=fmin)*r
    if np.any(voiced & (target_hz >= sr/2)):
        raise ParamError('requested voiced pitch must be below Nyquist at the processing sample rate')
    target_hz = np.where(voiced, target_hz, fmin)
    phase = np.r_[0., np.cumsum(target_hz[:-1]/sr)]
    cycles = np.arange(np.ceil(phase[0]), np.floor(phase[-1])+1)
    synth = np.interp(cycles, phase, samples)
    y, norm = np.zeros_like(a), np.zeros(len(a))
    for center in synth:
        if not voiced[min(round(center), len(a)-1)]:
            continue
        j = int(np.argmin(abs(marks-center)))
        period = sr/max(1, float(np.nan_to_num(hz[min(round(center), len(a)-1)], nan=fmin)))
        left, right = max(0, int(np.ceil(center-period))), min(len(a), int(np.floor(center+period))+1)
        offsets = np.arange(left, right)-center
        w = .5+.5*np.cos(np.pi*offsets/period)
        grain = read_samples(a, marks[j]+offsets, method='sinc8')
        y[left:right] += grain*w[:, None]
        norm[left:right] += w
    covered = norm > 1e-12
    y[covered] /= norm[covered, None]
    # Low synthesis pitches can leave a gap between two-period grains. That
    # gap is silence in the voiced synthesis, not an unshifted dry oscillator.
    y[~covered] = 0
    distance = ndimage.distance_transform_edt(np.pad(voiced, (1, 1)))[1:-1]
    blend = .5-.5*np.cos(np.pi*np.clip((distance-1)/max(1, .010*sr), 0, 1))
    blend[r == 1] = 0
    return a+blend[:, None]*(y-a)


KEYS = ('C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B')


def scale_notes(key='C', scale='chromatic', mask=()):
    """Ascending allowed MIDI notes over an extended range, with key rotation."""
    if key not in KEYS or scale not in ('chromatic', 'major', 'minor', 'custom'):
        raise ParamError('invalid key or scale')
    degrees = {'chromatic': range(12), 'major': (0, 2, 4, 5, 7, 9, 11),
               'minor': (0, 2, 3, 5, 7, 8, 10)}
    if scale == 'custom':
        if len(mask) != 12 or any(v not in (0, 1) for v in mask) or not any(mask):
            raise ParamError('custom scale needs a nonempty binary mask of length 12')
        offsets = np.flatnonzero(mask)
    else:
        if len(mask) and (len(mask) != 12 or any(v not in (0, 1) for v in mask)):
            raise ParamError('scale_mask must be empty or binary length 12')
        offsets = degrees[scale]
    return np.asarray(sorted(KEYS.index(key)+12*octave+int(d) for octave in range(-12, 24) for d in offsets))


def nearest_note(midi, allowed):
    """Nearest scale pitch; sorted search/argmin resolves ties downwards."""
    return float(allowed[int(np.argmin(abs(np.asarray(allowed)-midi)))])


def voice_track(x, sr, *, fmin=70, fmax=1000):
    """Reuse BB-12 twice; formant ringing is reduced in an agreeing second pass.

    The global median determines a 1.8*F0 low-pass, not a replacement pitch
    detector. Keep the original decision unless the second pYIN is voiced,
    agrees within one semitone and has a larger voiced probability. This also
    retains high notes outside the low-pass passband and raw unvoiced noise.
    """
    from .pitch import detect_pitch, PitchTrack
    kwargs = dict(fmin=fmin, fmax=min(fmax, .45*sr), hop_ms=1000*256/48000)
    tr = detect_pitch(x, sr, **kwargs)
    if not np.any(tr.voiced) or len(x) < 32:
        return tr
    cutoff = min(.4*sr, max(fmin*1.5, 1.8*float(np.nanmedian(tr.f0_hz))))
    filtered = signal.sosfiltfilt(signal.butter(4, cutoff, fs=sr, output='sos'), x, axis=0)
    other = detect_pitch(filtered, sr, **kwargs)
    agree = tr.voiced & other.voiced & (abs(12*np.log2(other.f0_hz/tr.f0_hz)) <= 1)
    take = agree & (other.probability > tr.probability)
    return PitchTrack(tr.samples, tr.times_s, np.where(take, other.f0_hz, tr.f0_hz),
                      tr.voiced, np.where(take, other.probability, tr.probability),
                      tr.sr, tr.hop_samples, tr.frame_length, 'pyin')


def track_notes(x, sr, *, fmin=70, fmax=1000, min_confidence=.6, a4_hz=440):
    """BB-12 fixed 256@48k pYIN grid; semi-tone labels require 60 ms dwell."""
    tr = voice_track(x, sr, fmin=fmin, fmax=fmax)
    good = tr.voiced.copy()
    midi = np.full(len(good), np.nan)
    midi[good] = 69+12*np.log2(tr.f0_hz[good]/a4_hz)
    # Note identity follows the center, rather than splitting a 5 Hz vibrato
    # whenever its extreme spends 60 ms over a semitone boundary. Filtering
    # each voiced run separately never bridges silence/unvoiced intervals.
    baseline = midi.copy()
    edges = np.diff(np.r_[False, good, False].astype(int))
    for left, right in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
        if right-left > 8:
            sos = signal.butter(2, 3, fs=sr/tr.hop_samples, output='sos')
            baseline[left:right] = signal.sosfiltfilt(sos, midi[left:right], padlen=min(12, right-left-1))
    labels = np.where(good, np.floor(np.nan_to_num(baseline)+.5), -999).astype(int)
    dwell = max(1, int(np.ceil(.060*sr/tr.hop_samples)))
    stable = labels.copy()
    i = 0
    while i < len(labels):
        if labels[i] == -999:
            i += 1
            continue
        end = i+1
        while end < len(labels) and labels[end] != -999:
            end += 1
        current, j = labels[i], i
        while j < end:
            if labels[j] == current:
                stable[j] = current
                j += 1
                continue
            stop = j+1
            while stop < end and labels[stop] == labels[j]:
                stop += 1
            if stop-j >= dwell:
                current = labels[j]
            stable[j:stop] = current
            j = stop
        i = end
    changes = np.r_[0, np.flatnonzero(np.diff(stable))+1, len(stable)]
    notes = []
    for left, right in zip(changes[:-1], changes[1:]):
        if right == left or stable[left] == -999:
            continue
        if not np.any(tr.probability[left:right] >= min_confidence):
            continue
        start, stop = int(tr.samples[left]), min(len(x), int(tr.samples[right]) if right < len(tr.samples) else len(x))
        if stop-start < round(.060*sr):
            continue
        notes.append(dict(start_sample=start, end_sample=stop, t0=start/sr, t1=stop/sr,
                          pitch_midi=float(np.median(midi[left:right])),
                          confidence=float(np.mean(tr.probability[left:right]))))
    return tr, notes


def lpc_frames(x, sr, order=24, frame_ms=20, emphasis=0):
    """Centered Hann autocorrelation LPC with 75% overlap and preemphasis."""
    a = _audio(x, sr)
    if (isinstance(order, bool) or not isinstance(order, (int, np.integer)) or order < 1
            or not np.isfinite(frame_ms) or frame_ms <= 0 or not 0 <= emphasis <= 1):
        raise ParamError('invalid LPC frame length, order or emphasis')
    length = max(8, round(sr*frame_ms/1000))
    p = max(2, min(length-2, round(order*sr/48000)))
    hop = max(1, round(length/4))
    centers = np.arange(0, len(a), hop)
    pre = signal.lfilter([1, -np.exp(-2*np.pi*1000/sr)], [1], a, axis=0)
    padded = np.pad(pre, ((length//2, length), (0, 0)))
    window = np.hanning(length)
    ks = np.zeros((len(centers), p, a.shape[1]))
    gains = np.zeros((len(centers), a.shape[1]))
    for i, center in enumerate(centers):
        frame = padded[center:center+length]*window[:, None]
        for c in range(a.shape[1]):
            coeff, k, error = lpc(frame[:, c], p)
            # Bandwidth expansion gives a strict stability margin. Emphasis
            # reduces that expansion, narrowing the poles towards the unit circle.
            gamma = np.exp(-2*np.pi*(25*(1-emphasis)+2)/sr)
            coeff *= gamma**np.arange(len(coeff))
            ks[i, :, c] = lpc_to_reflection(coeff)
            gains[i, c] = np.sqrt(error)
    if len(centers) > 1:
        # Smooth in reflection space before samplewise interpolation. The
        # convex averages retain |k|<1 and suppress pitch/frame beating even
        # when a short frame contains fewer than two voiced periods.
        ks = ndimage.gaussian_filter1d(ks, 2, axis=0, mode='nearest')
        gains = ndimage.gaussian_filter1d(gains, 2, axis=0, mode='nearest')
    return centers, ks, gains


def lattice_synthesis(excitation, centers, reflections, gains):
    """All-pole synthesis lattice; linear interpolation of |k|<1 is stable.

    Backward errors are retained across frames; no filter-state reset or
    denominator-coefficient interpolation occurs. Initial state is zero.
    """
    x = np.asarray(excitation, dtype=np.float64)
    k = np.asarray(reflections, dtype=np.float64)
    g = np.asarray(gains, dtype=np.float64)
    if (x.ndim != 2 or not np.isfinite(x).all() or k.ndim != 3 or k.shape[0] != len(centers) or k.shape[2] != x.shape[1]
            or g.shape != (len(centers), x.shape[1]) or not np.isfinite(k).all()
            or np.any(abs(k) >= 1) or not np.isfinite(g).all() or np.any(g < 0)
            or not np.isfinite(centers).all() or np.any(np.asarray(centers) < 0)
            or np.any(np.diff(centers) <= 0)):
        raise ParamError('invalid synthesis lattice frames')
    y = np.zeros_like(x)
    if not len(centers):
        return y
    state = np.zeros((k.shape[1]+1, x.shape[1]))
    j = 0
    for n in range(len(x)):
        while j+1 < len(centers) and centers[j+1] <= n:
            j += 1
        end = min(j+1, len(centers)-1)
        u = (n-centers[j])/(centers[end]-centers[j]) if end != j else 0.
        reflection = (1-u)*k[j]+u*k[end]
        value = x[n]*((1-u)*g[j]+u*g[end])
        for m in range(k.shape[1], 0, -1):
            value = value-reflection[m-1]*state[m-1]
            state[m] = reflection[m-1]*value+state[m-1]
        state[0] = value
        y[n] = value
    return y
