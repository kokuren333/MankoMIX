"""Generic passive program EQ with offset low boost/cut corners."""
from mankomix.dspx.params import _e, _f


def passive_eq(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.analog_eq import process
    return process('passive_eq', x, sr, p)


def _spec():
    from mankomix.dspx.bb.analog_eq import definition
    return definition('passive_eq', [
        _e('low_freq_hz', [20, 30, 60, 100], 60, 'Low boost corner.', unit='Hz'),
        _f('low_boost_db', 'dB', 0, 14, 0, 'Low boost.'),
        _f('low_atten_db', 'dB', 0, 18, 0, 'Low attenuation, at four times the boost corner.'),
        _e('high_freq_hz', [3000, 4000, 5000, 8000, 10000, 12000, 16000], 8000, 'High boost center.', unit='Hz'),
        _f('high_boost_db', 'dB', 0, 18, 0, 'High boost.'),
        _f('high_bw', '0..1', 0, 1, .5, 'High width; zero is sharpest.'),
        _e('high_atten_freq_hz', [5000, 10000, 20000], 10000, 'High attenuation corner.', unit='Hz'),
        _f('high_atten_db', 'dB', 0, 16, 0, 'High attenuation.')],
        'Generic LC/RC program equalizer with simultaneous low boost and cut.')


SPECS = [_spec()]
IMPLS = {'passive_eq': passive_eq}
