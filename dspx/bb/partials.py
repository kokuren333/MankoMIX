"""Harmonic grouping and peak-region translation for offline poly retuning.

Independent implementation: Laroche & Dolson, WASPAA 1999, sections 3.4-3.5
(region translation and phase continuity); Klapuri, ISMIR 2006, Eq. (1)
(harmonic salience). The grouping weights/thresholds here are explicitly
local heuristics, not a reproduction of the trained salience model.
"""
import numpy as np
from scipy import fft, signal
from mankomix.dsp.errors import ParamError


def harmonic_groups(frequencies, amplitudes, bin_hz, *, max_harmonic=12):
    """Return (fundamentals, owner indices, ambiguous peak count).

    Sorted peaks in Hz, amplitudes >=0. Observed peaks are F0 candidates.
    Require >=3 harmonics within max(.6 bin, .006*f); salience sums A/sqrt(h).
    Greedily consume >=2 unexplained peaks. Ownership minimizes cents error
    plus 4*harmonic index, breaking ties by F0 order. Unowned indices are -1.
    Coincident harmonics cannot be separated and are counted as ambiguous.
    """
    f, amp = np.asarray(frequencies, float), np.asarray(amplitudes, float)
    if (f.ndim != 1 or f.shape != amp.shape or np.any(np.diff(f) <= 0)
            or np.any(f <= 0) or np.any(amp < 0) or not np.isfinite(f).all()
            or not np.isfinite(amp).all() or bin_hz <= 0):
        raise ParamError('sorted positive peaks and finite nonnegative amplitudes required')
    owner = np.full(len(f), -1, dtype=int)
    if not len(f):
        return np.empty(0), owner, 0
    candidates = []
    for index, base in enumerate(f):
        harmonic = np.maximum(1, np.rint(f/base)).astype(int)
        error = abs(f-harmonic*base)
        match = (harmonic <= max_harmonic) & (error <= np.maximum(.6*bin_hz, .006*f))
        if np.count_nonzero(match) >= 3:
            candidates.append((float(np.sum(amp[match]/np.sqrt(harmonic[match]))), index, match))
    claimed = np.zeros(len(f), dtype=bool)
    selected = []
    for _, index, match in sorted(candidates, key=lambda c: (-c[0], c[1])):
        if claimed[index] or np.count_nonzero(match & ~claimed) < 2:
            continue
        selected.append(index)
        claimed |= match
    selected.sort()
    best = np.full(len(f), np.inf)
    count = np.zeros(len(f), dtype=int)
    for group, index in enumerate(selected):
        base = f[index]
        harmonic = np.maximum(1, np.rint(f/base)).astype(int)
        error = abs(f-harmonic*base)
        match = (harmonic <= max_harmonic) & (error <= np.maximum(.6*bin_hz, .006*f))
        score = abs(1200*np.log2(f/(harmonic*base)))+4*harmonic
        choose = match & (score < best)
        owner[choose], best[choose] = group, score[choose]
        count += match
    return f[selected], owner, int(np.count_nonzero(count > 1))


def retune_regions(analysis, mapping, *, a4_hz=440, strength=1, lo_hz=60,
                   hi_hz=12000, min_peak_db=-60, transients=.7, resolve_close=False):
    """Return (delta spectra, diagnostics) on the existing BB-06 WOLA grid.

    Shared energy reference preserves stereo/antiphase. Frequencies come from
    adjacent-frame phase differences. Each peak region is translated using
    exact periodic DFT interpolation (IFFT, complex modulation, FFT), with
    integrated shift phase and identical channel operations. Unshifted bins
    are never subtracted. Outside the effect band delta is exactly zero.
    resolve_close=True jointly fits neighboring lobes, including group-predicted
    hidden peaks; the default retains the original region-only behavior.
    """
    from mankomix.dspx.bb.pitchtime import _reference
    from mankomix.dspx.bb import stft
    a = analysis
    mapping = np.asarray(mapping, dtype=float)
    if (mapping.shape != (12,) or not np.isfinite(mapping).all() or np.any(abs(mapping) > 6)
            or not 400 <= a4_hz <= 480 or not 0 <= strength <= 1
            or not 0 < lo_hz < hi_hz or not 0 <= transients <= 1):
        raise ParamError('invalid retuning map, band or strength')
    delta = np.zeros_like(a.spectra)
    if not np.any(mapping) or strength == 0 or not len(a.spectra):
        return delta, dict(group_count_max=0, ambiguous_peak_frames=0, shifted_peak_frames=0)
    # Reuse BB-11's cancelled-mid reference choice on reconstructed context.
    reference = stft.analyze(_reference(stft.synthesize(a))[:, None], a.sr,
                             window=len(a.window), hop=a.hop_samples).spectra[:, :, 0]
    n, hop = len(a.window), a.hop_samples
    bin_hz = a.sr/n
    coordinate = (np.arange(n)-n//2)/a.sr
    bin_numbers = np.arange(n//2+1)
    band = (a.frequencies_hz >= lo_hz) & (a.frequencies_hz <= hi_hz)
    taper = stft.band_weights(a.frequencies_hz, lo_hz, hi_hz)
    previous_peaks = np.empty(0)
    previous_shifts = np.empty(0)
    previous_phase = np.empty(0)
    group_max = ambiguous = shifted = 0
    previous_mag = np.zeros(n//2+1)
    for t, spectrum in enumerate(a.spectra):
        mag = abs(reference[t])
        all_peaks = signal.find_peaks(mag)[0]
        if not len(all_peaks) or not np.any(mag):
            previous_peaks = np.empty(0)
            continue
        # Include weak peaks in boundaries, so strong neighbors cannot consume them.
        peaks = all_peaks[mag[all_peaks] >= mag.max()*10**(min_peak_db/20)]
        peaks = peaks[band[peaks]]
        if not len(peaks):
            previous_peaks = np.empty(0)
            continue
        frequency = a.frequencies_hz[peaks].copy()
        if t:
            diff = np.angle(reference[t, peaks]*np.conj(reference[t-1, peaks]))
            expected = 2*np.pi*peaks*hop/n
            frequency += ((diff-expected+np.pi) % (2*np.pi)-np.pi)*a.sr/(2*np.pi*hop)
        else:
            lm = np.log(np.maximum(mag, 1e-30))
            den = lm[peaks-1]-2*lm[peaks]+lm[peaks+1]
            frequency += .5*(lm[peaks-1]-lm[peaks+1])/np.where(abs(den) > 1e-20, den, 1)*bin_hz
        # Sorted bin order remains the grouping order; clamp phase outliers locally.
        frequency = np.clip(frequency, (peaks-.5)*bin_hz, (peaks+.5)*bin_hz)
        bases, owner, overlap = harmonic_groups(frequency, mag[peaks], bin_hz)
        observed = np.ones(len(peaks), dtype=bool)
        if resolve_close and len(bases):
            # Use the isolated root to reduce phase bias in close harmonics.
            for i in np.flatnonzero(owner >= 0):
                base = bases[owner[i]]
                h = round(frequency[i]/base)
                if h > 1 and abs(frequency[i]-h*base) < .6*bin_hz:
                    frequency[i] = h*base
            # A close pair can form one observed maximum. Permit a second
            # lobe only when an observed harmonic group predicts it beside
            # that maximum. Its fitted amplitude still has to clear min_peak.
            extra_f, extra_o = [], []
            for group, base in enumerate(bases):
                for h in range(2, 13):
                    candidate = base*h
                    distance = np.min(abs(frequency-candidate))
                    if lo_hz <= candidate <= min(hi_hz, a.sr/2-bin_hz) and .5*bin_hz < distance < 2.5*bin_hz:
                        if all(abs(candidate-v) > .65*bin_hz for v in extra_f):
                            extra_f.append(candidate)
                            extra_o.append(group)
            if extra_f:
                frequency = np.r_[frequency, extra_f]
                owner = np.r_[owner, extra_o]
                observed = np.r_[observed, np.zeros(len(extra_f), dtype=bool)]
                peaks = np.r_[peaks, np.rint(np.array(extra_f)/bin_hz).astype(int)]
                order = np.argsort(frequency, kind='stable')
                frequency, owner, peaks = frequency[order], owner[order], peaks[order]
                observed = observed[order]
        group_max = max(group_max, len(bases))
        ambiguous += int(overlap > 0)
        root = frequency.copy()
        use = owner >= 0
        root[use] = bases[owner[use]]
        midi = 69+12*np.log2(np.maximum(root, 1e-20)/a4_hz)
        note = np.ceil(midi-.5).astype(int)  # exact ties choose the lower note
        amount = mapping[note % 12]
        interval = strength*(note-midi+amount)
        # A zero map entry preserves that group, including its original detuning.
        shifts = frequency*(2**(interval/12)-1)*(amount != 0)
        phase = np.zeros(len(peaks))
        if len(previous_peaks):
            nearest = np.abs(frequency[:, None]-previous_peaks[None, :]).argmin(axis=1)
            linked = abs(frequency-previous_peaks[nearest]) < 1.5*bin_hz
            phase[linked] = previous_phase[nearest[linked]]+2*np.pi*hop/a.sr*.5*(
                previous_shifts[nearest[linked]]+shifts[linked])
        flux = np.sum(np.maximum(mag-previous_mag, 0))/max(float(np.sum(previous_mag)), 1e-30)
        broadband = np.mean(mag > mag.max()*.1) > .2
        opening = transients if broadband and flux > 1.05-transients else 0.
        resolved = set()
        if resolve_close and not opening:
            # Fit neighboring window lobes jointly instead of cutting their
            # overlapping energy at a midpoint. Legacy callers stay unchanged.
            for cluster in np.split(np.arange(len(peaks)), np.flatnonzero(np.diff(peaks) > 4)+1):
                if not 2 <= len(cluster) <= 6 or not np.any(abs(shifts[cluster]) > 1e-10):
                    continue
                correction = _resolve_cluster(spectrum, a.window, a.sr,
                    frequency[cluster], shifts[cluster], phase[cluster],
                    mag.max()*10**(min_peak_db/20))
                if correction is not None:
                    delta[t] += correction
                    resolved.update(cluster.tolist())
                    shifted += int(np.count_nonzero(abs(shifts[cluster]) > 1e-10))
        for i, peak in enumerate(peaks):
            if i in resolved:
                continue
            if abs(shifts[i]) < 1e-10:
                continue
            if not observed[i]:
                continue
            where = int(np.searchsorted(all_peaks, peak))
            left = 1 if where == 0 else int((all_peaks[where-1]+peak)//2+1)
            right = n//2 if where == len(all_peaks)-1 else int((peak+all_peaks[where+1])//2+1)
            bins = bin_numbers[left:right]
            bins = bins[band[bins]]
            if not len(bins):
                continue
            full = np.zeros((n, spectrum.shape[1]), dtype=np.complex128)
            full[bins] = spectrum[bins]
            modulation = np.exp(1j*(2*np.pi*shifts[i]*coordinate+phase[i]))
            moved = fft.fft(fft.ifft(full, axis=0, workers=1)*modulation[:, None], axis=0, workers=1)
            correction = moved[:n//2+1]
            correction[bins] -= spectrum[bins]
            delta[t] += (1-opening)*correction
            shifted += 1
        delta[t, ~band] = 0
        delta[t] *= taper[:, None]
        delta[t, 0] = delta[t, 0].real
        delta[t, -1] = delta[t, -1].real
        previous_peaks, previous_shifts = frequency, shifts
        previous_phase = (phase+np.pi) % (2*np.pi)-np.pi
        previous_mag = mag
    return delta, dict(group_count_max=group_max, ambiguous_peak_frames=ambiguous,
                       shifted_peak_frames=shifted)


def _resolve_cluster(spectrum, window, sr, frequencies, shifts, phases, min_magnitude=0):
    """Fit distinct neighboring positive-frequency lobes with serial solves.

    Rejected ill-separated or poorly fitted clusters use the original region
    translation. This is a local sinusoidal model, not shared-harmonic source
    separation. All channels share the frequencies, with independent weights.
    """
    from mankomix.dspx.bb.dereverberation import _loaded_solve
    n = len(window)
    if np.min(np.diff(frequencies)) < .5*sr/n:
        return None
    time = (np.arange(n)-n//2)/sr
    waves = window[:, None]*np.exp(2j*np.pi*time[:, None]*frequencies)
    atoms = fft.fft(waves, axis=0, workers=1)[:n//2+1]
    left = max(1, int(np.floor(frequencies.min()*n/sr))-5)
    right = min(n//2, int(np.ceil(frequencies.max()*n/sr))+6)
    design = atoms[left:right]
    target = spectrum[left:right]
    normal = np.einsum('ti,tj->ij', design.conj(), design, optimize=False)
    cross = np.einsum('ti,tc->ic', design.conj(), target, optimize=False)
    coef = _loaded_solve(normal+np.eye(len(frequencies))*float(np.trace(normal).real)*1e-10, cross)
    residual = target-np.einsum('ti,ic->tc', design, coef, optimize=False)
    if np.sum(abs(residual)**2) > .02*np.sum(abs(target)**2):
        return None
    correction = np.zeros_like(spectrum)
    for i in range(len(frequencies)):
        if (abs(shifts[i]) < 1e-10
                or np.max(abs(coef[i]))*np.max(abs(atoms[:, i])) < min_magnitude):
            continue
        moved = fft.fft(waves[:, i]*np.exp(1j*(2*np.pi*shifts[i]*time+phases[i])), workers=1)[:n//2+1]
        correction += (moved-atoms[:, i])[:, None]*coef[i]
    return correction
