"""BB-11: independently implemented pitch/time processing, float64 audio.

API (audio is frames x channels, zero initial history):
``fast_shift(x, sr, ratio, grain_ms=40, delay_ms=0, feedback=0,
highcut_hz=0)``: two Hann-crossfaded rotating delay taps. ratio is a positive
scalar or one value per sample. Constant feed-forward shifts choose tap spacing
from past input periods; no correlation or waveform phase alignment is used.
``wsola(x, sr, stretch, window_ms=40, stereo_link=True,
source_positions=None)``: output/input duration ratio; waveform-similarity
overlap-add, exact rounded output length. Optional strictly increasing source
positions supply one source sample position per output sample for time warps.
``phase_vocoder(x, sr, stretch, window=4096, transients=.7,
stereo_link=True)``: identity phase locking and spectral-flux phase resets.
window is in samples at 48 kHz. The local centred STFT is deliberately private
until BB-06 synthesis is available. Both time stretchers return compensated
audio, and ratio 1 is an exact bypass.
``shift(x, sr, semitones=0, cents=0, quality='high', formant=False,
formant_cents=0, transients=.7, window=4096, stereo_link=True, grain_ms=40)``:
same-length pitch shift. Standard/high stretch then use the existing reference
polyphase resampler, with a rational ratio of denominator at most 4096.
``latency_samples(sr, quality, window=4096, window_ms=40)``: uncompensated
processing lookahead; fast intentionally does not compensate the dry path.
``bend_values(points, frames, sr, interp='linear', glide_ms=0)`` samples an
absolute-time semitone curve. ``bend(...)`` applies it with neutral-region
crossfades. Full input context is required for random-access excerpts.

Equations derived from Driedger & Mueller (2016), doi:10.3390/app6020057,
Laroche & Dolson (1999), doi:10.1109/89.759041, and the low-quefrency envelope
construction discussed by Roebel & Rodet (DAFx 2005). No source code copied.
Only existing NumPy/SciPy public APIs and repository DSP primitives are used.
"""
from __future__ import annotations

from fractions import Fraction
import numpy as np
from scipy import fft, signal

from mankomix.dsp.errors import ParamError


def _audio(x):
    x = np.asarray(x, dtype=np.float64)
    if x.ndim != 2 or x.shape[1] < 1 or not np.isfinite(x).all():
        raise ValueError('finite frames x channels audio required')
    return x


def _positive(value, name):
    if not np.isscalar(value) or not np.isfinite(value) or value <= 0:
        raise ValueError(name + ' must be positive and finite')
    return float(value)


def latency_samples(sr, quality, window=4096, window_ms=40):
    _positive(sr, 'sr')
    if quality == 'fast':
        return 0
    if quality == 'standard':
        return max(32, round(_positive(window_ms, 'window_ms') * sr / 1000))
    if quality == 'high':
        return max(32, round(_positive(window, 'window') * sr / 48000))
    raise ValueError('unknown quality')


def _read(x, positions, method='sinc8'):
    from mankomix.dspx.bb.delayline import read_samples
    out = np.empty((len(positions), x.shape[1]), dtype=np.float64)
    for a in range(0, len(out), 2048):
        out[a:a+2048] = read_samples(x, positions[a:a+2048], method)
    return out


def _period_spacing(x, end, sr, half):
    """Choose a bounded integer-period spacing using only available history.

    Regular positive crossings supply the period, rather than a correlation
    search for a splice. A sinusoidal recurrence refines single-tone estimates
    without the frequency bias of linearly interpolated high-frequency zeros.
    Irregular crossings and periods longer than half the grain use the nominal
    spacing. Channel selection uses only the same causal analysis window.
    """
    block = x[max(0, end-round(sr*.05)):end]
    if len(block) < 8:
        return half
    ref = block[:, int(np.argmax(np.sum(block*block, axis=0)))]
    crossings = np.flatnonzero((ref[:-1] <= 0) & (ref[1:] > 0))[-17:]
    if len(crossings) < 3:
        return half
    times = crossings-ref[crossings]/(ref[crossings+1]-ref[crossings])
    periods = np.diff(times)
    period = float(np.mean(periods))
    if np.max(np.abs(periods-period)) > .02*period:
        return half
    middle = ref[1:-1]
    power = float(np.dot(middle, middle))
    if power > 1e-30:
        neighbours = .5*(ref[:-2]+ref[2:])
        cosine = float(np.dot(middle, neighbours)/power)
        residual = neighbours-cosine*middle
        if -1 < cosine < 1 and np.dot(residual, residual) < 1e-10*power:
            period = 2*np.pi/np.arccos(cosine)
    # A tiny tolerance avoids dropping a whole period due to roundoff at an
    # exactly commensurate nominal grain. The delay bound still holds exactly.
    count = int(np.floor(half/period+1e-7))
    return min(half, count*period) if count else half


def _periodic_fast(x, sr, ratio, grain, delay=0):
    """Causal two-tap crossfades, adapting spacing only at zero tap gain.

    Each tap moves at exactly 1-ratio between resets. The dominant tap reaches
    the fixed midpoint at every handover; only the silent tap is repositioned.
    Complementary Hann gains sum to one for coherent periodic taps. A short
    single-tap startup supplies history even when tiny detuning makes the first
    complete crossfade last several seconds. All delays stay within grain+4.
    """
    delta = 1-ratio
    half = grain/2
    start = min(sr*.04, half/(2*abs(delta)))
    n = np.arange(len(x), dtype=float)-delay
    d1 = np.empty(len(x))
    d2 = np.empty(len(x))
    weight = np.zeros(len(x))
    a = min(len(x), int(np.ceil(start+delay)))
    d1[:a] = 4+half+delta*(n[:a]-start)
    d2[:a] = d1[:a]
    while a < len(x):
        spacing = _period_spacing(x, max(0, int(np.floor(start))-4), sr, half)
        finish = start+spacing/abs(delta)
        b = min(len(x), int(np.ceil(finish+delay)))
        travel = delta*(n[a:b]-start)
        d1[a:b] = 4+half+travel
        d2[a:b] = d1[a:b]-np.copysign(spacing, delta)
        weight[a:b] = .5-.5*np.cos(np.pi*(n[a:b]-start)/(finish-start))
        a, start = b, finish
    return (_read(x, n-d1)*(1-weight[:, None])
            +_read(x, n-d2)*weight[:, None])


def fast_shift(x, sr, ratio, grain_ms=40, delay_ms=0, feedback=0, highcut_hz=0):
    """Causal dual tap shift; musical tap delays are not declared as lookahead.

    Feedback reads the same two taps from shared stored input+feedback history.
    A one-sample minimum loop delay resolves the zero-delay feedback singularity.
    Noninteger reads use the causal four-point Lagrange kernel for feedback;
    the feed-forward path uses the existing centred eight-point sinc kernel.
    """
    from mankomix.dspx.bb.delayline import fractional_delay, LoopFilter, _kernel
    x = _audio(x)
    _positive(sr, 'sr')
    grain = _positive(grain_ms, 'grain_ms') * sr / 1000
    if not np.isfinite(delay_ms) or delay_ms < 0 or not 0 <= feedback < 1:
        raise ValueError('nonnegative delay and feedback in [0,1) required')
    r = np.broadcast_to(np.asarray(ratio, dtype=float), (len(x),))
    if not np.isfinite(r).all() or np.any(r <= 0):
        raise ValueError('positive finite pitch ratios required')
    delay = delay_ms * sr / 1000
    if not len(x):
        return x.copy()
    if np.all(r == 1):
        if not feedback:
            return LoopFilter(sr, x.shape[1], highcut=highcut_hz)(fractional_delay(x, delay))
        # The unity-ratio feedback path has the same causal recurrence.
        from mankomix.dspx.bb.delayline import DelayLine
        d = max(1., delay)
        if d != round(d):
            d = max(3., d)
        filt = LoopFilter(sr, x.shape[1], highcut=highcut_hz)
        wet = DelayLine(d, x.shape[1], 'lagrange3').process(x, d, feedback, loop=filt)
        return LoopFilter(sr, x.shape[1], highcut=highcut_hz)(wet)
    if not feedback and np.all(r == r[0]):
        # Offset the tap clock as well as the reads by the musical delay.
        # Evaluating fractional clocks directly avoids a second centred kernel
        # that would otherwise truncate the intermediate voice at render end.
        wet = _periodic_fast(x, sr, float(r[0]), grain, delay)
        return LoopFilter(sr, x.shape[1], highcut=highcut_hz)(wet)
    # Integrated speed deviation is evaluated from the beginning of context.
    # Scalars use multiplication, avoiding accumulation error on long renders.
    if np.ndim(ratio) == 0:
        deviation = np.arange(len(x), dtype=float) * (1 - float(ratio))
    else:
        deviation = np.r_[0., np.cumsum(1-r[:-1])]
    u = np.remainder(deviation / grain, 1.)
    v = np.remainder(u + .5, 1.)
    w = .5 - .5*np.cos(2*np.pi*u)
    # Four guard samples keep the centred sinc support in available history.
    # They are wet-path musical delay; the zero-ratio fixed-delay bypass above
    # retains the exact requested delay without an interpolation guard.
    d1, d2 = delay + 4 + grain*u, delay + 4 + grain*v
    if not feedback:
        n = np.arange(len(x), dtype=float)
        y = _read(x, n-d1)*w[:, None] + _read(x, n-d2)*(1-w[:, None])
        return LoopFilter(sr, x.shape[1], highcut=highcut_hz)(y)
    # Partition only causally independent samples, retaining the filter state.
    d1, d2 = np.maximum(d1, 3.), np.maximum(d2, 3.)
    stored = np.zeros_like(x)
    y = np.zeros_like(x)
    filt = LoopFilter(sr, x.shape[1], highcut=highcut_hz)
    a = 0
    while a < len(x):
        b = min(len(x), a+1024)
        safe = max(1, int(np.floor(min(d1[a:b].min(), d2[a:b].min()))) - 2)
        b = min(b, a+safe)
        n = np.arange(a, b, dtype=float)
        wet = np.zeros((b-a, x.shape[1]))
        for delays, gains in ((d1[a:b], w[a:b]), (d2[a:b], 1-w[a:b])):
            ix, weights = _kernel(n-delays, 'lagrange3')
            for j in range(4):
                values = stored[np.clip(ix[:, j], 0, len(x)-1)]
                wet += np.where((ix[:, j] >= 0)[:, None], values, 0) * (weights[:, j]*gains)[:, None]
        wet = filt(wet)
        y[a:b] = wet
        stored[a:b] = x[a:b] + feedback*wet
        a = b
    return y


def _reference(x):
    """Mid reference, with deterministic energy fallback for cancelled mid."""
    ref = x.mean(axis=1)
    energy = np.sum(x*x, axis=0)
    if np.sum(ref*ref) < .01*max(float(energy.max(initial=0)), 1e-30):
        ref = x[:, int(np.argmax(energy))]
    return ref


def _separate_transients(x, sr):
    """Split isolated high-crest broadband attacks for anchored relocation.

    Tonal samples are excluded by spectral flatness. A compact 10 ms support
    and a cosine edge separate the attack from the sustained stretch path.
    This is a conservative time-domain transient treatment, not HPSS.
    """
    from scipy.ndimage import uniform_filter1d
    ref = _reference(x)
    if not len(x) or not np.any(ref):
        return x, []
    power = uniform_filter1d(ref*ref, max(3, round(sr*.05)), mode='constant')
    candidates = signal.find_peaks(np.abs(ref), distance=max(1, round(sr*.015)))[0]
    candidates = candidates[ref[candidates]**2 > 64*np.maximum(power[candidates], 1e-30)]
    residual = x.copy()
    events = []
    radius = max(2, round(sr*.005))
    for peak in candidates:
        a, b = max(0, peak-radius), min(len(x), peak+radius+1)
        mag = np.abs(fft.rfft(ref[a:b], workers=1))
        flatness = np.exp(np.mean(np.log(mag+1e-20)))/max(float(np.mean(mag)), 1e-20)
        if flatness < .25:
            continue
        taper = signal.windows.tukey(b-a, .5)
        event = residual[a:b]*taper[:, None]
        residual[a:b] -= event
        events.append((peak, peak-a, event))
    return residual, events


def _restore_transients(y, events, stretch, source_positions=None):
    for peak, offset, event in events:
        center = peak*stretch if source_positions is None else np.interp(
            peak, source_positions, np.arange(len(source_positions)))
        a = round(center)-offset
        lo, hi = max(0, a), min(len(y), a+len(event))
        if hi > lo:
            y[lo:hi] += event[lo-a:hi-a]
    return y


def wsola(x, sr, stretch, window_ms=40, stereo_link=True, *, source_positions=None):
    """Windowed waveform-similarity alignment, output/input duration ratio."""
    x = _audio(x)
    stretch = _positive(stretch, 'stretch')
    _positive(sr, 'sr')
    mapping = None if source_positions is None else np.asarray(source_positions, dtype=float)
    if mapping is not None and (mapping.ndim != 1 or not np.isfinite(mapping).all()
                                or np.any(np.diff(mapping) <= 0)):
        raise ValueError('source_positions must be finite and strictly increasing')
    nout = round(len(x)*stretch) if mapping is None else len(mapping)
    if not len(x) or nout == 0:
        return np.zeros((nout, x.shape[1]), dtype=np.float64)
    if stretch == 1 and mapping is None:
        return x.copy()
    if not stereo_link and x.shape[1] > 1:
        return np.column_stack([wsola(x[:, c:c+1], sr, stretch, window_ms,
                                     source_positions=mapping)[:, 0]
                                for c in range(x.shape[1])])
    x, events = _separate_transients(x, sr)
    size = max(32, round(_positive(window_ms, 'window_ms')*sr/1000))
    hop = max(1, size//4)
    search = size//2
    padded = np.pad(x, ((size*2, size*2), (0, 0)))
    ref = _reference(padded)
    win = signal.windows.hann(size, sym=False)
    out = np.zeros((nout+size*2, x.shape[1]))
    weight = np.zeros(len(out))
    prev = None
    # Include negative centres to cover the left edge with fully normalised OLA.
    for center in range(-size//2, nout+size//2, hop):
        source = center/stretch if mapping is None else mapping[min(max(center, 0), nout-1)]
        if mapping is not None and nout > 1:
            if center < 0:
                source = mapping[0]+center*(mapping[1]-mapping[0])
            elif center >= nout:
                source = mapping[-1]+(center-nout+1)*(mapping[-1]-mapping[-2])
        expected = round(source) + size*2-size//2
        expected = int(np.clip(expected, 0, len(padded)-size))
        pos = expected
        if prev is not None:
            natural = min(prev+hop, len(padded)-size)
            target = ref[natural:natural+size-hop]
            lo = max(0, expected-search)
            hi = min(len(padded)-size, expected+search)
            candidates = ref[lo:hi+size-hop]
            corr = signal.correlate(candidates, target, mode='valid', method='fft')
            sums = np.r_[0., np.cumsum(candidates*candidates)]
            powers = sums[len(target):]-sums[:-len(target)]
            corr /= np.sqrt(np.maximum(powers*np.sum(target*target), 1e-30))
            # Resolve equal periodic maxima by closeness to the nominal map.
            best = np.flatnonzero(corr >= corr.max()-1e-8)
            pos = lo+int(best[np.argmin(np.abs(lo+best-expected))])
        start = center-size//2+size
        out[start:start+size] += padded[pos:pos+size]*win[:, None]
        weight[start:start+size] += win
        prev = pos
    out /= np.maximum(weight, 1e-15)[:, None]
    return _restore_transients(out[size:size+nout], events, stretch, mapping)


def _stft(x, size, hop):
    padded = np.pad(x, ((size//2, size+size//2), (0, 0)))
    win = signal.windows.hann(size, sym=False)
    frames = np.lib.stride_tricks.sliding_window_view(padded, size, axis=0)[::hop]
    return fft.rfft(frames*win, axis=-1, workers=1).transpose(0, 2, 1), win


def _envelope(magnitude, sr, size):
    """Low-quefrency log spectral envelope (local BB-19 integration seam)."""
    logmag = np.log(np.maximum(magnitude, np.max(magnitude, axis=0, keepdims=True)*1e-10+1e-30))
    cep = fft.irfft(logmag, n=size, axis=0, workers=1)
    cutoff = max(2, min(size//4, round(sr*.005)))
    lifter = np.zeros(size)
    lifter[:cutoff+1] = 1
    lifter[-cutoff:] = 1
    return np.exp(fft.rfft(cep*lifter[:, None], axis=0, workers=1).real)


def _formant_correct(x, sr, ratio, formant_ratio, size):
    """Correct a stretched spectrum before the final pitch-changing resample."""
    hop = max(1, size//8)
    spec, win = _stft(x, size, hop)
    out = np.zeros((len(x)+size*2, x.shape[1]))
    norm = np.zeros(len(out))
    bins = np.arange(size//2+1)
    for i, frame in enumerate(spec):
        local_ratio = float(ratio) if np.ndim(ratio) == 0 else ratio[min(i*hop, len(ratio)-1)]
        env = _envelope(np.abs(frame), sr, size)
        target = np.column_stack([np.interp(bins*local_ratio/formant_ratio, bins, env[:, c], right=0)
                                  for c in range(x.shape[1])])
        correction = np.minimum(100., target/np.maximum(env, 1e-20))
        block = fft.irfft(frame*correction, n=size, axis=0, workers=1)*win[:, None]
        a = i*hop
        if a+size > len(out):
            break
        out[a:a+size] += block
        norm[a:a+size] += win*win
    out /= np.maximum(norm, 1e-15)[:, None]
    return out[size//2:size//2+len(x)]


def phase_vocoder(x, sr, stretch, window=4096, transients=.7, stereo_link=True):
    """Phase propagation with nearest-peak identity locking and onset resets."""
    x = _audio(x)
    stretch = _positive(stretch, 'stretch')
    if not 0 <= transients <= 1:
        raise ValueError('transients must be in [0,1]')
    size = latency_samples(sr, 'high', window)
    nout = round(len(x)*stretch)
    if stretch == 1 or not len(x):
        return x.copy()
    if not stereo_link and x.shape[1] > 1:
        return np.column_stack([phase_vocoder(x[:, c:c+1], sr, stretch, window, transients)[:, 0]
                                for c in range(x.shape[1])])
    x, events = _separate_transients(x, sr) if transients > 0 else (x, [])
    hop = max(1, size//8)
    spec, win = _stft(x, size, hop)
    ref, _ = _stft(_reference(x)[:, None], size, hop)
    ref = ref[:, :, 0]
    omega = 2*np.pi*np.arange(size//2+1)/size
    delta = np.angle(ref[1:]*np.conj(ref[:-1]))-omega[None, :]*hop
    delta = (delta+np.pi) % (2*np.pi)-np.pi
    freqs = omega[None, :]+delta/hop
    phase = np.angle(ref[0])
    out = np.zeros((nout+size*2, x.shape[1]))
    norm = np.zeros(len(out))
    previous_mag = np.abs(ref[0])
    bins = np.arange(size//2+1)
    previous_peaks = np.empty(0, dtype=int)
    previous_freq = omega.copy()
    for a in range(0, nout+size//2, hop):
        time = a/(stretch*hop)
        i = min(int(time), len(spec)-2)
        u = min(1., time-i)
        mag = (1-u)*np.abs(spec[i])+u*np.abs(spec[i+1])
        inphase = np.angle(ref[i])+u*hop*freqs[i]
        freqtime = max(0., min(time-.5, len(freqs)-1.))
        fi = min(int(freqtime), len(freqs)-2)
        fu = freqtime-fi
        current_freq = (1-fu)*freqs[fi]+fu*freqs[fi+1]
        refmag = (1-u)*np.abs(ref[i])+u*np.abs(ref[i+1])
        flux = np.sum(np.maximum(refmag-previous_mag, 0))/max(np.sum(previous_mag), 1e-20)
        broadband = np.mean(refmag > refmag.max(initial=0)*.1) > .2
        reset = a == 0 or (transients > 0 and broadband and flux > 1.05-transients)
        peaks = signal.find_peaks(refmag)[0]
        if len(peaks):
            peaks = peaks[refmag[peaks] > refmag.max()*1e-4]
        if len(peaks):
            if reset or not len(previous_peaks):
                peakphase = inphase[peaks]
            else:
                old_boundaries = (previous_peaks[:-1]+previous_peaks[1:])/2
                old = previous_peaks[np.searchsorted(old_boundaries, peaks)]
                # Follow moving peaks, including the centred FFT's pi phase
                # change for each bin crossed. Trapezoidal frequency advance
                # avoids a systematic half-hop bias on frequency glides.
                peakphase = (phase[old]+hop*.5*(previous_freq[old]+current_freq[peaks])
                             +np.pi*(peaks-old))
            boundaries = (peaks[:-1]+peaks[1:])/2
            owners = np.searchsorted(boundaries, bins)
            nearest = peaks[owners]
            locked = peakphase[owners]+inphase-inphase[nearest]
        else:
            locked = inphase.copy() if reset else phase+hop*current_freq
        phase = locked.copy()
        previous_peaks = peaks
        previous_freq = current_freq.copy()
        # Preserve each channel's inter-channel phase relative to shared mid.
        channelphase = np.angle(spec[i])+u*hop*(omega[:, None]+
            ((np.angle(spec[i+1]*np.conj(spec[i]))-hop*omega[:, None]+np.pi) % (2*np.pi)-np.pi)/hop)
        result = mag*np.exp(1j*(locked[:, None]+channelphase-inphase[:, None]))
        block = fft.irfft(result, n=size, axis=0, workers=1)*win[:, None]
        out[a:a+size] += block
        norm[a:a+size] += win*win
        previous_mag = refmag
    out /= np.maximum(norm, 1e-15)[:, None]
    return _restore_transients(out[size//2:size//2+nout], events, stretch)


def shift(x, sr, semitones=0, cents=0, quality='high', formant=False,
          formant_cents=0, transients=.7, window=4096, stereo_link=True, grain_ms=40):
    """Same-length pitch shift; zero offset is an unconditional exact bypass."""
    x = _audio(x)
    ratio = 2.**((float(semitones)+float(cents)/100)/12)
    if quality not in ('fast', 'standard', 'high'):
        raise ValueError('unknown quality')
    _positive(ratio, 'ratio')
    if ratio == 1 or not len(x):
        return x.copy()
    if quality == 'fast':
        if ratio > 1:
            # Causal anti-alias prefilter; its frequency-dependent phase is
            # intentionally not compensated on the fast wet path.
            sos = signal.ellip(12, .01, 100, min(.99, .94/ratio), output='sos')
            x = signal.sosfilt(sos, x, axis=0)
        return fast_shift(x, sr, ratio, grain_ms)
    # Stretch by r, then play r times faster. The inverse is a rate, not a
    # duration factor: this explicit convention avoids ambiguous ratio APIs.
    rational = Fraction(float(ratio)).limit_denominator(4096)
    rate = rational.numerator/rational.denominator
    if quality == 'standard':
        y = wsola(x, sr, rate, stereo_link=stereo_link)
    else:
        y = phase_vocoder(x, sr, rate, window, transients, stereo_link)
    if formant:
        y = _formant_correct(y, sr, rate, 2.**(formant_cents/1200),
                            latency_samples(sr, 'high', window))
    from mankomix.dsp.reference.export import resample_poly_hq
    y = resample_poly_hq(y, rational.numerator, rational.denominator)
    return np.pad(y, ((0, max(0, len(x)-len(y))), (0, 0)))[:len(x)]


def bend_values(points, frames, sr, interp='linear', glide_ms=0):
    """Absolute curve; step glide is a finite causal raised-cosine transition."""
    if not points:
        return np.zeros(frames)
    from mankomix.dspx.bb.curves import sample_curve
    if interp == 'step':
        knots = {}
        for t, v in points:
            knots[round(t*sr)] = v
        times, values = np.array(list(knots.items()), dtype=np.float64).T
        values = values[np.maximum(0, np.searchsorted(times, np.arange(frames), side='right')-1)]
        if glide_ms:
            # Finite support is essential: a one-pole would never return to
            # exact zero, violating the neutral-region bit-identity contract.
            length = max(1, round(glide_ms*sr/1000))
            result = values.copy()
            changes = np.flatnonzero(np.diff(np.r_[0., values]))
            for a in changes:
                b = min(frames, a+length)
                delta = values[a]-(values[a-1] if a else 0)
                ramp = .5-.5*np.cos(np.pi*np.arange(1, b-a+1)/length)
                result[a:b] += delta*(ramp-1)
            values = result
        return values
    return sample_curve(points, frames, sr, interp=interp)


def bend(x, sr, points, interp='linear', glide_ms=0, quality='fast',
         formant=False, grain_ms=40):
    """Curve shift with exact neutral interiors; requires complete context."""
    x = _audio(x)
    if quality not in ('fast', 'standard'):
        raise ValueError('bend quality must be fast or standard')
    values = bend_values(points, len(x), sr, interp, glide_ms)
    if not np.any(values):
        return x.copy()
    if quality == 'fast':
        wet = fast_shift(x, sr, 2.**(values/12), grain_ms)
    else:
        # Invert the integrated speed map, stretch along it, then continuously
        # resample it. Ratios are never restarted in independently shifted
        # blocks, so there are no phase resets at control-frame boundaries.
        ratios = 2.**(values/12)
        clock = np.r_[0., np.cumsum(.5*(ratios[:-1]+ratios[1:]))]
        grid = np.arange(int(np.ceil(clock[-1]))+1, dtype=float)
        mapping = np.interp(grid, clock, np.arange(len(x)))
        tail = grid > clock[-1]
        mapping[tail] = len(x)-1+(grid[tail]-clock[-1])/ratios[-1]
        stretched = wsola(x, sr, len(grid)/len(x), stereo_link=True, source_positions=mapping)
        if formant:
            # Correct each overlapping STFT frame with its local ratio.
            local_ratios = np.interp(np.arange(len(stretched)), clock, ratios)
            stretched = _formant_correct(stretched, sr, local_ratios, 1,
                                        latency_samples(sr, 'high', 4096))
        maximum = float(ratios.max())
        if maximum > 1:
            taps, beta = signal.kaiserord(120, .06/maximum)
            kernel = signal.firwin(taps | 1, .97/maximum, window=('kaiser', beta))
            stretched = signal.fftconvolve(stretched, kernel[:, None], mode='same', axes=0)
        wet = _read(stretched, clock, 'sinc256')
    # Distance to an active sample gives a two-sided, compact crossfade into
    # exact dry interiors; no infinitely decaying smoother leaks into them.
    from scipy.ndimage import distance_transform_edt
    active = values != 0
    distance = distance_transform_edt(~active)
    fade = max(1, round(grain_ms*sr/1000))
    amount = np.maximum(0., 1-distance/fade)
    y = x.copy()
    change = amount > 0
    y[change] += (wet[change]-x[change])*amount[change, None]
    return y
