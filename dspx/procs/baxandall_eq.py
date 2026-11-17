"""Generic first-order feedback bass and treble tone controls."""
from mankomix.dspx.params import _e, _f


def baxandall_eq(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.analog_eq import process
    return process('baxandall_eq', x, sr, p)


def _spec():
    from mankomix.dspx.bb.analog_eq import definition
    return definition('baxandall_eq', [
        _e('bass_hz', [74, 84, 130, 166, 230, 361], 84, 'Bass midpoint.', unit='Hz'),
        _f('bass_db', 'dB', -5, 5, 0, 'Bass gain.'),
        _e('treble_hz', [1600, 2100, 3400, 4800, 7100, 18000], 7100, 'Treble midpoint.', unit='Hz'),
        _f('treble_db', 'dB', -5, 5, 0, 'Treble gain.')],
        'Generic gentle first-order feedback tone controls.')


SPECS = [dict(_spec(), implemented=True)]
IMPLS = {'baxandall_eq': baxandall_eq}
