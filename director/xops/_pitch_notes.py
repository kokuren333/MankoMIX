"""Shared read-only BB-12 note measurements for CLI and pitch editing."""
import math
import numpy as np
from scipy import signal
from mankomix.core.errors import InputError


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def clean(value):
    if isinstance(value, dict):
        return {k: clean(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [clean(v) for v in value]
    if isinstance(value, (float, np.floating)):
        return round(float(value), 9) if np.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    return value


def vibrato(values, rate):
    if len(values) < 16 or rate <= 16:
        return np.zeros(len(values))
    sos = signal.butter(2, [4, 8], btype='bandpass', fs=rate, output='sos')
    return signal.sosfiltfilt(sos, values-np.median(values), padlen=min(24, len(values)-1))


def observe(x, sr, *, lo_hz=70, hi_hz=1000, a4=440):
    """Absolute sample IDs; confidence is measured pYIN probability, not advice."""
    from mankomix.dspx.bb.psola import voice_track
    from scipy.ndimage import median_filter
    if (not all(number(v) for v in (lo_hz, hi_hz, a4)) or
            not 40 <= lo_hz <= 400 or not 200 <= hi_hz <= 2000 or
            not lo_hz < hi_hz < sr/2 or not 400 <= a4 <= 480):
        raise InputError('pitch range needs lo_hz 40..400 < hi_hz 200..2000 below Nyquist; a4 400..480')
    track = voice_track(x, sr, fmin=lo_hz, fmax=hi_hz)
    # A short median rejects individual bad frames without the low-pass ramps
    # between large leaps becoming spurious intermediate notes.
    midi = np.where(track.voiced, 69+12*np.log2(track.f0_hz/a4), np.nan)
    labels = np.full(len(midi), -999, dtype=int)
    edges = np.diff(np.r_[False, track.voiced, False].astype(int))
    dwell = max(1, int(np.ceil(.060*sr/track.hop_samples)))
    for left, right in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
        center = median_filter(midi[left:right], size=max(1, dwell//2*2+1), mode='nearest')
        raw = np.floor(center+.5).astype(int)
        current, j = raw[0], 0
        while j < len(raw):
            stop = j+1
            while stop < len(raw) and raw[stop] == raw[j]:
                stop += 1
            if stop-j >= dwell:
                current = raw[j]
            labels[left+j:left+stop] = current
            j = stop
    changes = np.r_[0, np.flatnonzero(np.diff(labels))+1, len(labels)]
    notes = []
    for left, right in zip(changes[:-1], changes[1:]):
        if right <= left or labels[left] == -999 or not np.any(track.probability[left:right] >= .6):
            continue
        a = int(track.samples[left])
        b = int(track.samples[right]) if right < len(labels) else len(x)
        if b-a >= round(.060*sr):
            notes.append({'start_sample': a, 'end_sample': b, 't0': a/sr, 't1': b/sr,
                          'pitch_midi': float(np.nanmedian(midi[left:right])),
                          'confidence': float(np.mean(track.probability[left:right]))})
    # The dwell decision is confirmed later than the actual crossing. Place a
    # shared voiced boundary at the midpoint of its two measured note centers.
    for previous, following in zip(notes[:-1], notes[1:]):
        if previous['end_sample'] != following['start_sample']:
            continue
        edge = following['start_sample']
        candidates = np.flatnonzero(track.voiced & (abs(track.samples-edge) <= round(.100*sr)) &
                                    (track.samples > previous['start_sample']) &
                                    (track.samples < following['end_sample']))
        if not len(candidates):
            continue
        midpoint = (previous['pitch_midi']+following['pitch_midi'])/2
        best = candidates[np.argmin(abs(midi[candidates]-midpoint))]
        boundary = int(track.samples[best])
        previous.update(end_sample=boundary, t1=boundary/sr)
        following.update(start_sample=boundary, t0=boundary/sr)
    rows = []
    for note in notes:
        a, b = note['start_sample'], note['end_sample']
        ix = (track.samples >= a) & (track.samples < b) & track.voiced
        times = track.samples[ix]/sr
        cents = 1200*np.log2(track.f0_hz[ix]/a4)+6900
        center = float(np.median(cents))
        fast = vibrato(cents, sr/track.hop_samples)
        slope = float(np.polyfit(times-times[0], cents, 1)[0]) if len(times) > 1 else 0.
        freq = 0.
        if len(fast) >= 16 and np.max(abs(fast)) > .1:
            from scipy.fft import rfft, rfftfreq
            spectrum = abs(rfft(fast*np.hanning(len(fast)), workers=1))
            frequencies = rfftfreq(len(fast), track.hop_samples/sr)
            candidates = np.flatnonzero((frequencies >= 4) & (frequencies <= 8))
            if len(candidates):
                freq = float(frequencies[candidates[np.argmax(spectrum[candidates])]])
        rows.append({**note, 'id': f'n_{a}', 'cents_off': center-100*math.floor(center/100+.5),
                     'drift_cents': slope*(b-a)/sr,
                     'vibrato': {'hz': freq, 'width_cents': float(np.ptp(fast))},
                     'level_db': float(10*np.log10(max(1e-30, float(np.mean(x[a:b]**2)))))})
    return track, clean(rows)


def accounting(x, y, sr):
    from mankomix.core.measure import loudness as L
    return clean({'before_frames': len(x), 'after_frames': len(y),
                  'before_lufs': float(L.integrated(x, sr)), 'after_lufs': float(L.integrated(y, sr)),
                  'before_peak_dbfs': float(L.sample_peak_dbfs(x)),
                  'after_peak_dbfs': float(L.sample_peak_dbfs(y))})
