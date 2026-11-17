"""Generic switched-frequency RC/LC console equalizer."""
from mankomix.dspx.params import _e, _f


def inductor_eq(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.analog_eq import precision_process
    return precision_process('inductor_eq', x, sr, p)


def _spec():
    from mankomix.dspx.bb.analog_eq import definition
    return definition('inductor_eq', [
        _e('hpf_hz', [0, 50, 80, 160, 300], 0, 'Input highpass; zero bypasses.', unit='Hz'),
        _e('low_freq_hz', [35, 60, 110, 220], 110, 'Low shelf corner.', unit='Hz'),
        _f('low_db', 'dB', -16, 16, 0, 'Low shelf gain.'),
        _e('mid_freq_hz', [360, 700, 1600, 3200, 4800, 7200], 1600, 'LC mid center.', unit='Hz'),
        _f('mid_db', 'dB', -18, 18, 0, 'Mid gain.'),
        _f('high_db', 'dB', -16, 16, 0, 'Fixed 12 kHz high shelf gain.')],
        'Generic inductor console EQ with switched frequencies.')


SPECS = [_spec()]
SPECS[0]['implemented'] = True
SPECS[0]['realtime']['latency_rule'] = '32x precision FIR round trip 352 samples, compensated offline; neutral bypass.'
IMPLS = {'inductor_eq': inductor_eq}
