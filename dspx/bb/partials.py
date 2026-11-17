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
                   hi_hz=12000, min_peak_db=-60, transients=.7):
    """Return (delta spectra, diagnostics) on the existing BB-06 WOLA grid.

    Shared energy reference preserves stereo/antiphase. Frequencies come from
    adjacent-frame phase differences. Each peak region is translated using
    exact periodic DFT interpolation (IFFT, complex modulation, FFT), with
    integrated shift phase and identical channel operations. Unshifted bins
    are never subtracted. Outside the effect band delta is exactly zero.
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
        for i, peak in enumerate(peaks):
            if abs(shifts[i]) < 1e-10:
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
