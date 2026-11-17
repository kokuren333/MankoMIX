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


def validate(p):
    if 0 < p['out_lowcut_hz'] < 500:
        raise ParamError('out_lowcut_hz must be zero or 500..20000 Hz')


def exciter(x, sr, p, *, seed=0):
    validate(p)
    info = N.oversampling_info(p['oversample'])
    if p['amount_db'] == -60 or not len(x):
        return x.copy(), sr, info
    factor = p['oversample']
    g = 10**(p['drive_db']/20)
    def generate(u):
        side = N.filter_audio(u, sr*factor, p['freq_hz'], 'highpass', 2)
        env = D.detector(side, sr*factor, 'rms', 10, False)
        # Multiply the shaped normalized signal by the same envelope, giving
        # amplitude homogeneity when dynamic=1 (not constant added loudness).
        norm = np.maximum(env, 1e-12)**p['dynamic']
        v = side/norm
        if p['harmonics'] == 'even':
            wet = np.abs(v)
        elif p['harmonics'] == 'odd':
            wet = np.tanh(g*v)/g-v
        else:
            bias = .3
            wet = (np.tanh(g*v+bias)-np.tanh(bias))/(g*(1-np.tanh(bias)**2))-v
        wet *= norm
        return N.filter_audio(wet, sr*factor, p['out_lowcut_hz'] or p['freq_hz'], 'highpass', 2)
    wet = N.dc_block(N.oversampled(x, factor, generate), sr)
    return x + wet*10**(p['amount_db']/20), sr, info


IMPLS = {'exciter': exciter}
CROSS_VALIDATE = {'exciter': validate}
