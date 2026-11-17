"""BB-15 ERB power, excitation and masking; independent of the floor path.

ERB layout / fractional bin integration duplicate core.analysis.erb. The
two-slope spreading and -6 dB masking margin duplicate the P-02 model v1
(knowledge/masking_model.json). These are coarse model constants, not an
ISO auditory-filter implementation. Digital power has an explicitly supplied
SPL offset; P-02 uses 96 dB after its own mix-level matching. This module
does NOT perform that matching, so raw processor scores are not P-02 scores.

API: erb_band_edges, band_matrix, band_powers, excitation, masking_threshold,
signal_to_mask_db, quiet_threshold, pink_reference, interpolate_gains.
iso_loudness / iso_levels expose the duplicated ISO 532-1 prototype, with
mandatory full-scale-sine calibration. The ISO and excitation models remain
distinct. References: Glasberg & Moore (1990), Terhardt-style two-slope
spreading; provenance of the ISO transcription is in _auditory_iso532.py.
"""
import math
import numpy as np
from mankomix.dsp.errors import ParamError


def hz_to_erb_number(f):
    return 21.4 * np.log10(1.0 + .00437 * np.asarray(f, dtype=np.float64))


def erb_number_to_hz(e):
    return (10.0 ** (np.asarray(e, dtype=np.float64) / 21.4) - 1.0) / .00437


def hz_to_bark(f):
    f = np.asarray(f, dtype=np.float64)
    return 26.81 * f / (1960.0 + f) - .53


def erb_band_edges(sr, n_fft=None, *, fmin=20., fmax=None, step=1.):
    """P-02-compatible edges/centres; merge bands narrower than one bin."""
    if sr <= 0 or step <= 0:
        raise ParamError('positive sample rate and ERB step required')
    fmax = min(20000., .475*sr) if fmax is None else min(float(fmax), sr/2)
    if not 0 < fmin < fmax:
        raise ParamError('invalid ERB frequency range')
    e0, e1 = float(hz_to_erb_number(fmin)), float(hz_to_erb_number(fmax))
    n = max(1, int(math.floor((e1-e0)/step+1e-9)))
    edges = erb_number_to_hz(e0+step*np.arange(n+1))
    edges[-1] = min(edges[-1], fmax)
    if n_fft is not None:
        if n_fft < 4:
            raise ParamError('n_fft must be at least four')
        keep = [edges[0]]
        for hi in edges[1:]:
            if hi-keep[-1] >= sr/n_fft:
                keep.append(hi)
        if len(keep) == 1:
            keep.append(edges[-1])
        elif keep[-1] != edges[-1]:
            keep[-1] = edges[-1]
        edges = np.asarray(keep, dtype=np.float64)
    centers = erb_number_to_hz(.5*(hz_to_erb_number(edges[:-1])+hz_to_erb_number(edges[1:])))
    return edges, centers


def band_matrix(sr, n_fft, edges):
    """P-02 fractional bin overlap weights, shape (band, bin)."""
    edges = np.asarray(edges, dtype=np.float64)
    if sr <= 0 or n_fft < 4 or edges.ndim != 1 or len(edges) < 2 or np.any(np.diff(edges) <= 0):
        raise ParamError('invalid band matrix grid')
    df = sr/n_fft
    f = np.arange(n_fft//2+1)*df
    lo = np.maximum(f[None, :]-df/2, edges[:-1, None])
    hi = np.minimum(f[None, :]+df/2, edges[1:, None])
    return np.clip(hi-lo, 0, None)/df


def bin_powers(analysis):
    """One-sided mean-square power, (time,bin,ch), Parseval calibrated."""
    n = len(analysis.window)
    scale = np.full(n//2+1, 2./(n*np.sum(analysis.window**2)))
    scale[0] *= .5
    scale[-1] *= .5
    return abs(analysis.spectra)**2 * scale[None, :, None]


def band_powers(analysis, *, edges=None):
    """Return (power[time,band,ch], edges, centres), mean-square units."""
    n = len(analysis.window)
    if edges is None:
        edges, centers = erb_band_edges(analysis.sr, n)
    else:
        edges = np.asarray(edges, dtype=np.float64)
        centers = erb_number_to_hz(.5*(hz_to_erb_number(edges[:-1])+hz_to_erb_number(edges[1:])))
    matrix = band_matrix(analysis.sr, n, edges)
    return np.einsum('tfc,bf->tbc', bin_powers(analysis), matrix, optimize=False), edges, centers


def excitation(power, centers_hz, *, spl_offset_db, exclude_self=False, exported=False):
    """P-02 two-slope power spread, last axis=bands; optional self removal.

    Upper slope clip(24+230/f-.2*L_SPL,4,40); lower slope 27 dB/Bark.
    exported=True returns each source band's contribution summed over all
    destination bands instead of each destination's received excitation.
    Work is chunked so a long render does not allocate frames*bands^2.
    """
    p = np.asarray(power, dtype=np.float64)
    f = np.asarray(centers_hz, dtype=np.float64)
    if p.ndim < 1 or p.shape[-1] != len(f) or np.any(p < 0) or not np.isfinite(p).all() or not np.isfinite(spl_offset_db) or np.any(f <= 0):
        raise ParamError('finite nonnegative band powers and explicit SPL offset required')
    z = hz_to_bark(f)
    dz = z[None, :]-z[:, None]
    flat = p.reshape(-1, len(f))
    out = np.empty_like(flat)
    for start in range(0, len(flat), 128):
        chunk = flat[start:start+128]
        level = 10*np.log10(np.maximum(chunk, 1e-20))+spl_offset_db
        upper = np.clip(24+230/f[None, :]-.2*level, 4, 40)
        att = np.where(dz[None] >= 0, upper[:, :, None]*dz[None], -27*dz[None])
        spread = 10**(-att/10)
        if exclude_self:
            spread[:, np.arange(len(f)), np.arange(len(f))] = 0
        out[start:start+128] = (chunk*np.sum(spread, axis=2) if exported else
                               np.matmul(chunk[:, None, :], spread)[:, 0, :])
    return out.reshape(p.shape)


def quiet_threshold(centers_hz, *, spl_offset_db):
    """P-02 threshold in quiet, converted from dB SPL to mean-square power."""
    k = np.asarray(centers_hz, dtype=np.float64)/1000
    if np.any(k <= 0) or not np.isfinite(spl_offset_db):
        raise ParamError('positive centers and finite SPL offset required')
    ath = 3.64*k**-.8-6.5*np.exp(-.6*(k-3.3)**2)+.001*k**4
    return 10**((ath-spl_offset_db)/10)


def masking_threshold(masker_excitation, *, offset_db=-6., quiet_power=None):
    """P-02 masker power * 10^(offset/10); optional threshold-in-quiet max."""
    p = np.asarray(masker_excitation, dtype=np.float64)
    if np.any(p < 0) or not np.isfinite(p).all() or not np.isfinite(offset_db):
        raise ParamError('invalid masker excitation')
    out = p*10**(offset_db/10)
    return out if quiet_power is None else np.maximum(out, quiet_power)


def signal_to_mask_db(power, masker_excitation, *, offset_db=-6.):
    """Unclipped SMR; negative means below the P-02-style masked threshold."""
    p = np.asarray(power, dtype=np.float64)
    if np.any(p < 0) or not np.isfinite(p).all():
        raise ParamError('finite nonnegative signal powers required')
    return 10*np.log10((p+1e-20)/(masking_threshold(masker_excitation, offset_db=offset_db)+1e-20))


def pink_reference(analysis, edges):
    """Expected 1/f power summed on exactly the same fractional bin grid."""
    f = analysis.frequencies_hz
    p = np.divide(1., f, out=np.zeros_like(f), where=f > 0)
    return band_matrix(analysis.sr, len(analysis.window), edges) @ p


def interpolate_gains(gain_db, centers_hz, frequencies_hz):
    """Log-Hz interpolation from (time,band,ch) to (time,bin,ch), dB."""
    g = np.asarray(gain_db, dtype=np.float64)
    fc = np.asarray(centers_hz, dtype=np.float64)
    f = np.asarray(frequencies_hz, dtype=np.float64)
    out = np.empty((len(g), len(f), g.shape[2]))
    for t in range(len(g)):
        for c in range(g.shape[2]):
            out[t, :, c] = np.interp(np.log(np.maximum(f, fc[0])), np.log(fc), g[t, :, c])
    return out


def iso_loudness(x, sr, *, calibration_db_spl, **kwargs):
    """Duplicated ISO prototype signal API; calibration is never implicit."""
    from ._auditory_iso532 import loudness_zwicker
    return loudness_zwicker(x, sr, calibration_db_spl=calibration_db_spl, **kwargs)


def iso_levels(levels_db, field='free'):
    """Duplicated ISO stationary core from 28 third-octave SPL levels."""
    from ._auditory_iso532 import loudness_from_third_octave_levels
    return loudness_from_third_octave_levels(levels_db, field)
