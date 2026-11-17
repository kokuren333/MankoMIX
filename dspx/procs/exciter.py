"""High-passed parallel even/odd harmonic generator."""
import numpy as np
from mankomix.dspx.params import _f, _e
from mankomix.dspx.bb import nonlinear as N, dynamics as D
from mankomix.dsp.errors import ParamError

SPECS = [N.specification('exciter', [
    _f('freq_hz', 'Hz', 500, 12000, 3000, 'Sidechain 12 dB/oct highpass.'),
    _f('amount_db', 'dB', -60, 0, -60, 'Added harmonic level; -60 bypasses.'),
    _e('harmonics', ['even', 'odd', 'both'], 'both', 'Generator symmetry.'),
    _f('drive_db', 'dB', 0, 36, 12, 'Generator drive.'),
    _f('dynamic', '0..1', 0, 1, .5, 'Envelope normalization blend.'),
    _f('out_lowcut_hz', 'Hz', 0, 20000, 0, 'Zero follows freq_hz; otherwise >=500 Hz.'),
    _e('oversample', [2, 4, 8], 4, 'Oversampling factor.', unit='x')],
    'Parallel high-frequency harmonic excitation.')]
SPECS[0]['implemented'] = True


def validate(p):
    if 0 < p['out_lowcut_hz'] < 500:
        raise ParamError('out_lowcut_hz must be zero or 500..20000 Hz')


def exciter(x, sr, p, *, seed=0):
    from scipy import signal
    validate(p)
    factor = int(p['oversample'])*4*2**max(0, int(np.ceil((p['drive_db']-12)/12)))
    info = N.precision_oversampling_info(factor)
    info['oversample'] = p['oversample']
    if p['amount_db'] == -60 or not len(x):
        return x.copy(), sr, info
    g = 10**(p['drive_db']/20)
    # Stopband guard before envelope normalization: the specified two-pole
    # HPF alone leaks sub-cutoff energy which normalization can amplify.
    taps, beta = signal.kaiserord(120, min(.25*p['freq_hz']/(sr/2), .9))
    taps = max(3, taps | 1)
    guard = signal.firwin(taps, min(.75*p['freq_hz'], .49*sr),
                          fs=sr, pass_zero=False, window=('kaiser', beta))
    source = signal.oaconvolve(x, guard[:, None], mode='full', axes=0)
    source = source[taps//2:taps//2+len(x)]
    def generate(u):
        side = N.filter_audio(u, sr*factor, p['freq_hz'], 'highpass', 2)
        env = D.detector(side, sr*factor, 'rms', 10, False)
        # Multiply the shaped normalized signal by the same envelope, giving
        # amplitude homogeneity when dynamic=1 (not constant added loudness).
        norm = np.maximum(env, 1e-12)**p['dynamic']
        v = side/norm
        if p['harmonics'] == 'even':
            wet = N.centered_adaa1(v, np.abs, N.rectify_primitive)
        elif p['harmonics'] == 'odd':
            wet = N.centered_adaa1(v, lambda z: np.tanh(g*z)/g-z,
                lambda z: N.tanh_primitive(g*z)/g**2-.5*z*z)
        else:
            bias = .3
            tb = np.tanh(bias)
            slope = 1-tb*tb
            wet = N.centered_adaa1(v,
                lambda z: (np.tanh(g*z+bias)-tb)/(g*slope)-z,
                lambda z: N.tanh_primitive(g*z+bias)/(g*g*slope)-tb*z/(g*slope)-.5*z*z)
        wet *= norm
        # Remove the best coherent linear component and its quadrature.
        # This cancels the source fundamental without spectral deletion of
        # the generated harmonics or any change to the dry signal.
        quadrature = np.zeros_like(side)
        quadrature[1:-1] = (side[2:]-side[:-2])*.5
        for basis in (side, quadrature):
            energy = np.sum(basis*basis, axis=0)
            coefficient = np.zeros_like(energy)
            np.divide(np.sum(wet*basis, axis=0), energy,
                      out=coefficient, where=energy > 1e-24)
            wet -= coefficient*basis
        return N.filter_audio(wet, sr*factor, p['out_lowcut_hz'] or p['freq_hz'], 'highpass', 2)
    wet = N.dc_block(N.precision_oversampled(source, factor, generate), sr)
    info.update(sidechain_guard_taps=taps, sidechain_guard_latency_samples=taps//2,
                sidechain_guard_latency_compensated=True)
    return x + wet*10**(p['amount_db']/20), sr, info


IMPLS = {'exciter': exciter}
CROSS_VALIDATE = {'exciter': validate}
