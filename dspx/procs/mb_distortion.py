"""Four-band nonlinear palette; generated harmonics leave their source band."""
import numpy as np
from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _a, _e
from mankomix.dspx.bb import nonlinear as N, crossover as C

KINDS = ['off', 'tanh', 'hard', 'fold', 'rectify', 'fuzz', 'crush']
DEFAULTS = dict(drive_db=0, tone_hz=20000, level_db=0, mix=1)
SPECS = [N.specification('mb_distortion', [
    _a('crossovers_hz', 'Hz', 20, 20000, 3, [200, 2000], 'Strictly ascending band edges.'),
    _e('phase', ['minimum', 'linear'], 'linear', 'Crossover phase.')]+[
    _e('kind_'+str(i), KINDS, 'off', 'Band distortion; unused bands must be off.') for i in range(1, 5)]+[
    _a('drive_db', 'dB', 0, 48, 4, [], 'Empty means zero per band.'),
    _a('tone_hz', 'Hz', 200, 20000, 4, [], 'Empty means 20000 Hz per band.'),
    _a('level_db', 'dB', -36, 12, 4, [], 'Empty means zero per band.'),
    _a('mix', '0..1', 0, 1, 4, [], 'Empty means one per band.'),
    _e('oversample', [2, 4, 8], 8, 'Oversampling factor.', unit='x')],
    'Independent nonlinear curves followed by band tone filters.')]
SPECS[0]['implemented'] = True


def validate(p):
    n = C.validate_mb(p)
    if n > 4:
        raise ParamError('mb_distortion supports at most four bands')
    C.expand_band_params(p, DEFAULTS)
    if any(p['kind_'+str(i)] != 'off' for i in range(n+1, 5)):
        raise ParamError('unused band kinds must be off')


def _internal_factor(kind, drive_db, factor):
    """Reserve extra rate for DC-generating curves and each 12 dB above 24."""
    multiplier = 4 if kind in ('rectify', 'fuzz') else 2
    return int(factor)*multiplier*2**max(0, int(np.ceil((drive_db-24)/12)))


def distort_band(x, sr, kind, drive_db, factor):
    """hard/fold use centered ADAA: average backward/forward interval integrals.

    At the oversampled rate this has zero group delay. Both endpoints require
    whole-context rendering; the reusable causal ADAA1 retains its half delay.
    crush uses 8 bits (the specification does not expose a bits parameter).
    hard/fold divide by drive gain, preserving their unit small-signal slope.
    """
    if kind == 'off':
        return x.copy()
    factor = _internal_factor(kind, drive_db, factor)
    g = 10**(drive_db/20)
    def process(u):
        from .fuzz import antialiased_fuzz_curve
        from .bitcrush import quantize
        v = u*g
        if kind == 'tanh':
            return N.centered_adaa1(v, np.tanh, N.tanh_primitive)/g
        if kind in ('hard', 'fold', 'rectify'):
            curve, primitive = {'hard': (N.hard_clip, N.hard_clip_primitive),
                                'fold': (N.fold, N.fold_primitive),
                                'rectify': (np.abs, N.rectify_primitive)}[kind]
            wet = N.centered_adaa1(v, curve, primitive)
            return wet/g if kind in ('hard', 'fold') else wet
        if kind == 'fuzz':
            return antialiased_fuzz_curve(u, drive_db, .2, .2, 'hard')
        return N.centered_adaa1(v, lambda z: quantize(z, 8),
            lambda z: (np.rint(z*128)*(z*128)-.5*np.rint(z*128)**2)/128**2)
    wet = N.precision_oversampled(x, factor, process)
    return N.dc_block(wet, sr) if kind in ('rectify', 'fuzz') else wet


def mb_distortion(x, sr, p, *, seed=0):
    validate(p)
    C.validate_mb(p, sr)
    bp = C.expand_band_params(p, DEFAULTS)
    kinds = [p['kind_'+str(i)] for i in range(1, len(p['crossovers_hz'])+2)]
    info = N.precision_oversampling_info(max(_internal_factor(kind, drive, p['oversample'])
        for kind, drive in zip(kinds, bp['drive_db'])))
    info['oversample'] = p['oversample']
    if all(kind == 'off' for kind in kinds):
        return x.copy(), sr, info
    bands, meta = C.split_mb(x, sr, p)
    for i, band in enumerate(bands):
        if kinds[i] != 'off':
            wet = distort_band(band, sr, kinds[i], bp['drive_db'][i], p['oversample'])
            wet = N.filter_audio(wet, sr, bp['tone_hz'][i])
            bands[i] = N.mix_output(band, wet, bp['mix'][i], bp['level_db'][i])
    return C.recombine_bands(bands), sr, dict(info,
        crossover_latency_samples=meta['latency_samples'], harmonics_resplit=False)


IMPLS = {'mb_distortion': mb_distortion}
CROSS_VALIDATE = {'mb_distortion': validate}
