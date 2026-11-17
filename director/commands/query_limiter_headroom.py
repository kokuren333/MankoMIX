"""Hypothetical slot-5 adaptive limiter renders, preserving the final limiter."""
from copy import deepcopy
import numpy as np
from mankomix.core import mastering as M
from mankomix.core.errors import InputError
from mankomix.core.measure import loudness as L
from mankomix.dsp.engine import render_chain
from . import _measurement as W


def add_args(parser):
    pass


def hypothetical_chain(chain, drive):
    chain = deepcopy(chain)
    active = [c for c in chain if c.get('type') == 'adaptive_limiter'
              and c.get('enabled', True) and not c.get('bypass')]
    if active:
        active[0].setdefault('params', {})['drive_db'] = drive
        M.validate_master_chain(chain)
        return chain
    final = next((i for i, c in enumerate(chain) if M._master_slot(c.get('type')) == 6), None)
    if final is None or chain[final].get('type') != 'limiter':
        raise InputError('headroom preview requires the existing final limiter')
    chain.insert(final, {'id': 'preview_adaptive_headroom', 'type': 'adaptive_limiter',
                         'params': {'drive_db': drive}, 'enabled': True})
    M.validate_master_chain(chain)
    return chain


def low_distortion(before, after, sr):
    """Low-band nonlinear residual estimate, not harmonic THD of a music mix.

    Least-squares remove the linear gain of the 20..250 Hz reference. Residual
    includes modulation and any downstream processing, so confidence is low.
    """
    from mankomix.core.master_analysis import band_filter
    ref = band_filter(before, sr, 20, min(250, sr/2*.99))
    out = band_filter(after, sr, 20, min(250, sr/2*.99))
    energy = float(np.sum(ref**2))
    if energy <= 1e-20:
        return None
    g = float(np.sum(ref*out))/energy
    fundamental = float(np.sum((ref*g)**2))
    return float(np.sqrt(np.sum((out-ref*g)**2)/fundamental)) if fundamental > 1e-20 else None


def run(args):
    p, v = W.project(args)
    chain = (v or {}).get('master', {}).get('chain') or []
    x, sr = W.master_input(p, v)
    baseline = render_chain(x, sr, M.engine_chain(chain), stage='master', seed=0)
    rows = []
    for drive in range(13):
        planned = hypothetical_chain(chain, drive)
        result = render_chain(x, sr, M.engine_chain(planned), stage='master', seed=0)
        step = next(s for s in result.steps if s['type'] == 'adaptive_limiter' and not s.get('bypass'))
        stats = step['stats']
        rows.append({'drive_db': drive, 'lufs_i': L.integrated(result.audio, result.sr),
                     'max_gr_db': stats['gain_reduction']['max_db'],
                     'frac_gr_over_3db': stats['frac_gr_over_3db'],
                     'low_thd_estimate': low_distortion(baseline.audio, result.audio, result.sr),
                     'true_peak_dbtp': L.true_peak_dbtp(result.audio, result.sr),
                     'chain': planned, 'adaptive_params': step['params']})
    return W.clean({'kind': 'direction_query_limiter_headroom', 'confidence': 'medium',
                    'rows': rows, 'seed': 0, 'sample_rate': sr,
                    'low_thd_confidence': 'low',
                    'note': 'Existing first active adaptive limiter retains its settings; otherwise insert default settings before final limiter. '
                            '20..250 Hz gain-fitted residual is an estimate, not harmonic THD for polyphonic music.'})


COMMANDS = [{'path': ('query', 'limiter_headroom'), 'help': 'Measure hypothetical adaptive limiter drives 0..12 dB',
             'add_args': add_args, 'run': run, 'writes': False}]
