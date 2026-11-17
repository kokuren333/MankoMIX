"""Generic RC/LC program equalizer networks, not a particular circuit replica.

Public API: sections(kind, p) -> tuple[Section]; analog_response(kind,p,hz)
-> complex array; design_sos(kind,p,sr) -> SOS at 2*sr; process(kind,x,sr,p)
-> (audio,sr,stats); bandwidth(p) -> half-gain bandwidth in octaves.
Section.coefficients() uses u=s/(2*pi*freq_hz). Section.response(s) evaluates
the continuous-time transfer. Each section is independently prewarped.

Nodal reduction: an RC node satisfies (s/w+1)*v=x. Feedforward/feedback
mixing gives (u+sqrt(G))/(u+1/sqrt(G)) and its high-shelf dual. A normalized
series RLC branch satisfies (u*u+u/Q+1)*v=(u/Q)*x; balanced feedforward and
feedback damping gives the peak ratio below. Buffers isolate the sections.
These are general normalized networks with unity insertion-loss makeup;
component ratios are explicitly chosen here, not measured from equipment.
Background: doi:10.3390/app6050129, sections 3 and 6.1. No code copied.
Uses scipy.signal public API (SciPy 1.18.1, BSD-3-Clause).
See third_party/W2a2_APIS.md.
"""
from dataclasses import dataclass
import numpy as np
from scipy import signal
from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _f


@dataclass(frozen=True)
class Section:
    """A normalized RC shelf, series-RLC peak, or first-order RC highpass."""
    kind: str
    freq_hz: float
    gain_db: float = 0
    bw_oct: float = 1

    def coefficients(self):
        g = 10.0**(self.gain_db/20)
        a = np.sqrt(g)
        if self.kind == 'low_shelf':
            return np.array([1., a]), np.array([1., 1/a])
        if self.kind == 'high_shelf':
            return np.array([g, a]), np.array([1., a])
        if self.kind == 'peak':
            q = 1/(2*np.sinh(np.log(2)*self.bw_oct/2))
            return np.array([1., a/q, 1.]), np.array([1., 1/(a*q), 1.])
        if self.kind == 'highpass':
            return np.array([1., 0.]), np.array([1., 1.])
        raise ParamError('unknown analog EQ section')

    def response(self, s):
        """Evaluate H(s) at complex radian frequencies (not digital Hz)."""
        b, a = self.coefficients()
        u = np.asarray(s)/(2*np.pi*self.freq_hz)
        return np.polyval(b, u)/np.polyval(a, u)


def bandwidth(p):
    """Linear interpolation in |gain|/12, from bw_max_oct to bw_min_oct."""
    if p['bw_min_oct'] > p['bw_max_oct']:
        raise ParamError('proportional_eq: bw_min_oct must not exceed bw_max_oct')
    return p['bw_max_oct']+(p['bw_min_oct']-p['bw_max_oct'])*abs(p['gain_db'])/12


def sections(kind, p):
    """Return non-unity continuous-time sections in fixed signal-flow order.

    Passive low cut has four times the boost corner, giving a broad dip.
    High peak width is .35+2.65*high_bw oct; inductor mid width is 1.5 oct.
    All constants are generic design choices pending circuit-source research.
    """
    result = []
    def add(shape, hz, gain=0, width=1):
        if gain != 0 or shape == 'highpass':
            result.append(Section(shape, float(hz), float(gain), float(width)))
    if kind == 'passive_eq':
        add('low_shelf', p['low_freq_hz'], p['low_boost_db'])
        add('low_shelf', 4*p['low_freq_hz'], -p['low_atten_db'])
        add('peak', p['high_freq_hz'], p['high_boost_db'], .35+2.65*p['high_bw'])
        add('high_shelf', p['high_atten_freq_hz'], -p['high_atten_db'])
    elif kind == 'inductor_eq':
        if p['hpf_hz']:
            add('highpass', p['hpf_hz'])
        add('low_shelf', p['low_freq_hz'], p['low_db'])
        add('peak', p['mid_freq_hz'], p['mid_db'], 1.5)
        add('high_shelf', 12000, p['high_db'])
    elif kind == 'proportional_eq':
        add(p['shape'], p['freq_hz'], p['gain_db'], bandwidth(p))
    elif kind == 'baxandall_eq':
        add('low_shelf', p['bass_hz'], p['bass_db'])
        add('high_shelf', p['treble_hz'], p['treble_db'])
    else:
        raise ParamError('unknown analog EQ type')
    return tuple(result)


def analog_response(kind, p, hz):
    """Unwarped physical H(j*2*pi*f), before saturation and output gain."""
    s = 2j*np.pi*np.asarray(hz, dtype=np.float64)
    h = np.ones(s.shape, dtype=np.complex128)
    for sec in sections(kind, p):
        h *= sec.response(s)
    return h


def design_sos(kind, p, sr):
    """Bilinear SOS at 2*sr; prewarp each section's physical corner/center."""
    result = []
    for sec in sections(kind, p):
        if sec.freq_hz >= .98*sr:
            raise ParamError('analog EQ corner must be below 0.98 * internal Nyquist')
        b, a = sec.coefficients()
        w = 4*sr*np.tan(np.pi*sec.freq_hz/(2*sr))
        bd, ad = signal.bilinear(b, a, fs=2*sr/w)
        result.extend(signal.tf2sos(bd, ad))
    return np.asarray(result, dtype=np.float64).reshape(-1, 6)


def common_params():
    """Fresh T02-10 common parameter definitions; no user OS selector."""
    return [_f('drive_db', 'dB', 0, 12, 0, 'Post-EQ tanh drive; zero bypasses saturation.'),
            _f('output_db', 'dB', -24, 12, 0, 'Output gain.')]


def definition(kind, params, description):
    """Fresh EQ registration, initially withheld pending acceptance."""
    return dict(type=kind, params=params+common_params(), description=description,
                implemented=False, stages=['track', 'bus', 'master'], master_slot=1,
                backends=['reference'], offline_only=False, channel_ok=True,
                realtime=dict(block_ok=False, allocates=True, latency_samples=0,
                              latency_rule='2x FIR round trip 64 samples, compensated offline; neutral bypass.'))


def process(kind, x, sr, p):
    """Whole-context 2x EQ, optional existing normalized tanh, then gain.

    Uses BB-13 unchanged. Neutral avoids both SOS and resampling. IIR phase
    is preserved; only the fixed FIR transport delay is compensated.
    """
    from mankomix.dspx.bb.nonlinear import oversampled, oversampling_info
    sos = design_sos(kind, p, sr)
    drive = p['drive_db']
    active = len(sos) != 0 or drive != 0
    def callback(u):
        wet = signal.sosfilt(sos, u, axis=0) if len(sos) else u
        if drive:
            g = 10.0**(drive/20)
            wet = np.tanh(g*wet)/g
        return wet
    y = oversampled(x, 2, callback) if active else x.copy()
    if p['output_db']:
        y = y*10.0**(p['output_db']/20)
    stats = dict(oversampling_info(2 if active else 1), eq_oversample=2,
                 saturation_bypassed=drive == 0, eq_bypassed=len(sos) == 0,
                 section_count=len(sos), model='generic_normalized_rc_rlc',
                 circuit_source_verified=False)
    return y, sr, stats
