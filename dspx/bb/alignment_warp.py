"""Frozen BB-11b/BB-19 overlap-add plans shared by every group member.

WSOLA correlation and PSOLA closure selection run once on the reference.
Calculators only replay immutable grain positions, never search peer audio.
Equations: Verhelst & Roelands (1993), Moulines & Charpentier (1990).
Repository primitives supply interpolation, pitch marks and transient handling.
"""
import numpy as np
from scipy import signal, ndimage
from .pitchtime import _reference


def attack_mask(x, events):
    residual = x.copy()
    for a, b, _ in events:
        residual[a:b] *= 1-signal.windows.tukey(b-a, .5)[:, None]
    return residual


def schedule(x, sr, mapping, quality='standard'):
    from .onsets import detect_onsets
    from .pitchtime import _separate_transients
    knots = np.asarray(mapping)
    nout = round(knots[-1, 1])
    events = []
    # BB-11's broadband crest detector also catches single-sample clicks.
    _, bursts = _separate_transients(x, sr)
    peaks = [e['sample'] for e in detect_onsets(x, sr, kind='soft')]
    peaks += [int(e[0]) for e in bursts]
    radius = max(2, round(.015*sr))
    for peak in sorted(set(peaks)):
        a, b = max(0, peak-radius), min(len(x), peak+radius)
        if events and a < events[-1][1]:
            continue
        shift = round(np.interp(peak, knots[:, 0], knots[:, 1])-peak)
        events.append([a, b, shift])
    residual = attack_mask(x, events)
    if quality == 'high':
        return spectral_schedule(residual, sr, knots, events)
    size = max(32, round((.04 if quality == 'standard' else .06)*sr))
    hop = max(1, size//4)
    padded = np.pad(residual, ((size*2, size*2), (0, 0)))
    ref = _reference(padded)
    grains, previous = [], None
    for center in range(-size//2, nout+size//2, hop):
        source = float(np.interp(center, knots[:, 1], knots[:, 0]))
        if center < 0:
            source = center*(knots[1, 0]-knots[0, 0])/(knots[1, 1]-knots[0, 1])
        elif center >= nout:
            source = len(x)+(center-nout)*(knots[-1, 0]-knots[-2, 0])/(knots[-1, 1]-knots[-2, 1])
        expected = int(np.clip(round(source)+size*2-size//2, 0, len(padded)-size))
        pos = expected
        if previous is not None:
            natural = min(previous+hop, len(padded)-size)
            target = ref[natural:natural+size-hop]
            lo, hi = max(0, expected-size//2), min(len(padded)-size, expected+size//2)
            candidates = ref[lo:hi+size-hop]
            corr = signal.correlate(candidates, target, mode='valid', method='fft')
            sums = np.r_[0., np.cumsum(candidates*candidates)]
            powers = sums[len(target):]-sums[:-len(target)]
            corr /= np.sqrt(np.maximum(powers*np.sum(target*target), 1e-30))
            best = np.flatnonzero(corr >= corr.max()-1e-8)
            pos = lo+int(best[np.argmin(abs(lo+best-expected))])
        grains.append([center-size//2, pos-size*2])
        previous = pos
    return {'window': size, 'grains': grains, 'attacks': events, 'frames': nout}


def warp(x, sr, plan):
    if plan.get('method') == 'phase_locked':
        return spectral_warp(x, sr, plan)
    size = plan['window']
    residual = attack_mask(x, plan['attacks'])
    nout = plan.get('frames', len(x))
    out, norm = np.zeros((nout, x.shape[1])), np.zeros(nout)
    window = signal.windows.hann(size, sym=False)
    for dest, source in plan['grains']:
        a, b = max(0, dest, dest-source), min(nout, dest+size, dest+len(x)-source)
        if a >= b:
            continue
        w = window[a-dest:b-dest]
        out[a:b] += residual[source+a-dest:source+b-dest]*w[:, None]
        norm[a:b] += w
    out /= np.maximum(norm[:, None], 1e-20)
    # The same linear mask and integer relocation is applied to all peers.
    remaining = x.copy()
    for a, b, shift in plan['attacks']:
        w = signal.windows.tukey(b-a, .5)[:, None]
        event = remaining[a:b]*w
        remaining[a:b] -= event
        lo, hi = max(0, a+shift), min(nout, b+shift)
        if hi > lo:
            out[lo:hi] += event[lo-a-shift:hi-a-shift]
    return out


def spectral_schedule(x, sr, knots, events):
    """BB-11c identity phase locking; frozen phase rotations preserve group phase."""
    from .pitchtime import _stft
    size = max(32, round(4096*sr/48000))
    hop = max(1, size//8)
    spec, _ = _stft(_reference(x)[:, None], size, hop)
    ref = spec[:, :, 0]
    omega = 2*np.pi*np.arange(size//2+1)/size
    delta = np.angle(ref[1:]*np.conj(ref[:-1]))-omega*hop
    frequencies = omega+(delta+np.pi) % (2*np.pi)/hop-np.pi/hop
    phase = np.angle(ref[0])
    previous_peaks = np.empty(0, int)
    previous_frequency = omega.copy()
    previous_mag = abs(ref[0])
    rotations, times = [], []
    bins = np.arange(len(omega))
    for center in range(0, len(x)+size//2, hop):
        source = np.interp(center, knots[:, 1], knots[:, 0])
        t = min(source/hop, len(ref)-1.0000001)
        i, u = int(t), t-int(t)
        inphase = np.angle(ref[i])+u*hop*frequencies[i]
        frequency = frequencies[min(i, len(frequencies)-1)]
        magnitude = (1-u)*abs(ref[i])+u*abs(ref[i+1])
        flux = np.sum(np.maximum(magnitude-previous_mag, 0))/max(float(previous_mag.sum()), 1e-20)
        broadband = np.mean(magnitude > magnitude.max(initial=0)*.1) > .2
        reset = center == 0 or (broadband and flux > .35)
        peaks = signal.find_peaks(magnitude)[0]
        peaks = peaks[magnitude[peaks] > magnitude.max(initial=0)*1e-4]
        if len(peaks):
            if reset or not len(previous_peaks):
                peak_phase = inphase[peaks]
            else:
                old = previous_peaks[np.searchsorted((previous_peaks[:-1]+previous_peaks[1:])/2, peaks)]
                peak_phase = phase[old]+hop*.5*(previous_frequency[old]+frequency[peaks])+np.pi*(peaks-old)
            nearest = peaks[np.searchsorted((peaks[:-1]+peaks[1:])/2, bins)]
            phase = peak_phase[np.searchsorted((peaks[:-1]+peaks[1:])/2, bins)]+inphase-inphase[nearest]
        else:
            phase = inphase.copy() if reset else phase+hop*frequency
        rotations.append(((phase-inphase+np.pi) % (2*np.pi)-np.pi).tolist())
        times.append(float(t))
        previous_peaks, previous_frequency, previous_mag = peaks, frequency.copy(), magnitude
    return {'method': 'phase_locked', 'window': size, 'hop': hop, 'times': times,
            'rotations': rotations, 'attacks': events}


def spectral_warp(x, sr, plan):
    from scipy import fft
    from .pitchtime import _stft
    size, hop = plan['window'], plan['hop']
    spec, win = _stft(attack_mask(x, plan['attacks']), size, hop)
    omega = 2*np.pi*np.arange(size//2+1)/size
    out, norm = np.zeros((len(x)+size*2, x.shape[1])), np.zeros(len(x)+size*2)
    for index, (time, rotation) in enumerate(zip(plan['times'], plan['rotations'])):
        i, u = int(time), time-int(time)
        mag = (1-u)*abs(spec[i])+u*abs(spec[i+1])
        delta = np.angle(spec[i+1]*np.conj(spec[i]))-hop*omega[:, None]
        frequency = omega[:, None]+((delta+np.pi) % (2*np.pi)-np.pi)/hop
        phase = np.angle(spec[i])+u*hop*frequency+np.asarray(rotation)[:, None]
        block = fft.irfft(mag*np.exp(1j*phase), n=size, axis=0, workers=1)*win[:, None]
        a = index*hop
        out[a:a+size] += block
        norm[a:a+size] += win*win
    out /= np.maximum(norm[:, None], 1e-20)
    y = out[size//2:size//2+len(x)]
    remaining = x.copy()
    for a, b, shift in plan['attacks']:
        event = remaining[a:b]*signal.windows.tukey(b-a, .5)[:, None]
        remaining[a:b] -= event
        lo, hi = max(0, a+shift), min(len(x), b+shift)
        if hi > lo:
            y[lo:hi] += event[lo-a-shift:hi-a-shift]
    return y


def pitch_schedule(x, sr, track, cents, mapping, formant=True):
    """One source-closure->destination-cycle pass performs pitch and time."""
    from .psola import pitch_marks
    from .pitch import sample_pitch
    from .delayline import read_samples
    marks = pitch_marks(x, sr, track)
    if len(marks) < 3:
        return {'grains': [], 'blend': [], 'formant': formant}
    samples = np.arange(len(x))
    knots = np.asarray(mapping)
    source = np.interp(samples, knots[:, 1], knots[:, 0])
    hz, voiced, confidence = sample_pitch(track, source)
    periods = np.diff(marks)
    stable = ndimage.gaussian_filter1d(ndimage.median_filter(periods, size=5, mode='nearest'), 1, mode='nearest')
    refined = np.interp(source, (marks[:-1]+marks[1:])/2, np.where(periods < 1.5*sr/70, sr/stable, np.nan))
    hz = np.where(np.isfinite(refined), refined, hz)
    correction = np.interp(source, track.samples, cents)
    ratio = 2**(correction/1200)
    active = voiced & (confidence >= .6)
    target = np.where(active, np.nan_to_num(hz, nan=70)*ratio, 70.)
    if np.any(target >= sr/2):
        raise ValueError('aligned pitch exceeds Nyquist')
    phase = np.r_[0., np.cumsum(target[:-1]/sr)]
    centers = np.interp(np.arange(0, np.floor(phase[-1])+1), phase, samples)
    grains = []
    for center in centers:
        k = min(len(x)-1, round(center))
        if not active[k]:
            continue
        position = source[k]
        j = int(np.searchsorted(marks, position))
        choices = [min(len(marks)-1, j), max(0, j-1)]
        mark = min(choices, key=lambda i: (abs(marks[i]-position), i))
        period = sr/max(70, float(hz[k]))
        # A 1.5-period support avoids cancellation between repeated closure
        # neighborhoods after retuning, retaining the source formant envelope.
        radius = period*(.75 if formant else 1.)
        grains.append([float(center), float(marks[mark]), float(radius), float(ratio[k])])
    # Blend is serialized on its fixed pitch grid; exact inactive samples use dry.
    distance = ndimage.distance_transform_edt(np.pad(active, (1, 1)))[1:-1]
    blend = .5-.5*np.cos(np.pi*np.clip((distance-1)/max(1, .010*sr), 0, 1))
    changed = (abs(correction) > 1e-9) | (abs(source-samples) > 1e-6)
    blend[~changed] = 0
    # RLE keeps the exact voice transitions without sample-sized recipes.
    changes = np.flatnonzero(np.diff(blend) != 0)
    # Keep both ends of constant runs: linear replay must not ramp across
    # an inactive hole or a constant voiced plateau.
    keep = np.unique(np.r_[0, changes, changes+1, len(x)-1])
    control = [[int(k), float(blend[k])] for k in keep]
    return {'grains': grains, 'blend': control, 'formant': formant}


def synthesize_pitch(x, sr, plan, dry):
    from .delayline import read_samples
    out, norm = np.zeros_like(x), np.zeros(len(x))
    for center, mark, period, ratio in plan['grains']:
        a, b = max(0, int(np.ceil(center-period))), min(len(x), int(np.floor(center+period))+1)
        offsets = np.arange(a, b)-center
        w = .5+.5*np.cos(np.pi*offsets/period)
        grain = read_samples(x, mark+offsets*(1 if plan['formant'] else ratio), method='sinc8')
        out[a:b] += grain*w[:, None]
        norm[a:b] += w
    out /= np.maximum(norm[:, None], 1e-20)
    if not plan['blend']:
        return dry
    control = np.asarray(plan['blend'])
    blend = np.interp(np.arange(len(x)), control[:, 0], control[:, 1])[:, None]
    return dry+blend*(out-dry)
