"""Parallel virtual bass using reset integration, rectification or clipping."""
import numpy as np
from mankomix.dspx.params import _f, _e


def reset_integrator(x, sr):
    """Integrate absolute input, reset on positive crossings; zero initial state.

    Dividing by a homogeneous analytic amplitude later removes the quadratic
    level dependence. Full-cycle resets retain both even and odd harmonics.
    """
    out = np.zeros_like(x)
    for c in range(x.shape[1]):
        acc, previous = 0., 0.
        for i, v in enumerate(x[:, c]):
            if previous <= 0 < v:
                acc = 0.
            acc += abs(v)/sr
            out[i, c] = acc
            previous = v
    return out


def validate(p):
    if p['hi_limit_hz'] <= p['freq_hz']:
        from mankomix.dsp.errors import ParamError
        raise ParamError('hi_limit_hz must exceed freq_hz')


def bass_enhancer(x, sr, p, *, seed=0):
    from mankomix.dspx.bb import nonlinear as N
    from mankomix.dspx.bb.lowend import band_fir, amplitude_envelope
    validate(p)
    info = N.precision_oversampling_info(int(p['oversample']))
    if (p['amount_db'] == -60 and p['original_db'] == 0) or not len(x):
        return x.copy(), sr, info
    low, lp_info = band_fir(x, sr, hi=p['freq_hz'])
    info['source_fir'] = lp_info
    y = x.copy() if p['original_db'] == 0 else x+(10**(p['original_db']/20)-1)*low
    if p['amount_db'] == -60:
        return y, sr, info
    env = amplitude_envelope(low, sr, p['attack_ms'], p['release_ms'])
    factor = int(p['oversample'])
    def generate(u):
        if p['harmonics'] == 'integrator':
            return reset_integrator(u, sr*factor)
        if p['harmonics'] == 'rectifier':
            return N.centered_adaa1(u, np.abs, N.rectify_primitive)
        # A homogeneous threshold keeps generated bass proportional to source.
        norm = amplitude_envelope(u, sr*factor, p['attack_ms'], p['release_ms'])
        norm = np.maximum(norm, 1e-12)
        return norm*N.centered_adaa1(4*u/norm, N.hard_clip, N.hard_clip_primitive)
    wet = N.precision_oversampled(low, factor, generate)
    wet, bp_info = band_fir(wet, sr, p['freq_hz'], p['hi_limit_hz'], 3*p['decay'])
    generated_env = amplitude_envelope(wet, sr, p['attack_ms'], p['release_ms'])
    gain = np.zeros_like(env)
    np.divide(env, generated_env, out=gain, where=generated_env > 1e-12)
    wet *= gain
    # Reapply the same spectral envelope after level matching: modulation must
    # not reopen the declared generated-harmonic stopband.
    wet, _ = band_fir(wet, sr, p['freq_hz'], p['hi_limit_hz'], 3*p['decay'])
    wet = N.dc_block(wet, sr)
    info['harmonic_fir'] = bp_info
    return y+wet*10**(p['amount_db']/20), sr, info


def _spec():
    from mankomix.dspx.bb.lowend import definition
    return definition('bass_enhancer', [
        _f('freq_hz', 'Hz', 40, 250, 90, 'Source lowpass and harmonic lower edge.'),
        _f('amount_db', 'dB', -60, 12, -60, 'Added harmonics; -60 disables.'),
        _f('original_db', 'dB', -60, 0, 0, 'Original low-frequency gain.'),
        _e('harmonics', ['integrator', 'rectifier', 'clipper'], 'integrator', 'Harmonic generator.'),
        _f('hi_limit_hz', 'Hz', 150, 1000, 400, 'Generated upper edge.'),
        _f('decay', '0..1', 0, 1, .5, 'Higher-harmonic rolloff.'),
        _f('attack_ms', 'ms', 1, 100, 10, 'Envelope attack.'),
        _f('release_ms', 'ms', 20, 500, 120, 'Envelope release.'),
        _e('oversample', [2, 4], 4, 'Generator oversampling.', unit='x')],
        'Missing-fundamental bass harmonics; original low band has independent gain.')


SPECS = [_spec()]
SPECS[0]['implemented'] = True
IMPLS = {'bass_enhancer': bass_enhancer}
CROSS_VALIDATE = {'bass_enhancer': validate}
