"""Generic proportional bandwidth equalizer."""
from mankomix.dspx.params import _e, _f


def check(p):
    from mankomix.dspx.bb.analog_eq import bandwidth
    bandwidth(p)


def proportional_eq(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.analog_eq import process
    return process('proportional_eq', x, sr, p)


def _spec():
    from mankomix.dspx.bb.analog_eq import definition
    return definition('proportional_eq', [
        _f('freq_hz', 'Hz', 30, 20000, 1000, 'Filter center/corner.'),
        _f('gain_db', 'dB', -12, 12, 0, 'Filter gain.'),
        _e('shape', ['peak', 'low_shelf', 'high_shelf'], 'peak', 'Filter shape.'),
        _f('bw_min_oct', 'oct', .3, 2, .6, 'Half-gain width at maximum gain.'),
        _f('bw_max_oct', 'oct', 1, 4, 2.5, 'Half-gain width near zero gain.')],
        'Generic proportional-Q EQ; stronger changes use narrower bandwidth.')


SPECS = [_spec()]
IMPLS = {'proportional_eq': proportional_eq}
CROSS_VALIDATE = {'proportional_eq': check}
