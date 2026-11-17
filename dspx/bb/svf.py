"""TPT state-variable filter, independently derived trapezoidal integrators.

API: SVF(sr, channels, mode='lowpass', slope=12).process(x, cutoff_hz,
resonance_db=0) retains integrator state across calls. Controls are scalar,
frames, or frames x channels. svf(...) is the zero-state convenience call.
Lowpass cutoff denotes the final falling -3 dB crossing; resonance denotes
the maximum gain above the DC passband. Cutoff is capped at .45*sr.
"""
import numpy as np
from mankomix.dsp.errors import ParamError


class SVF:
    def __init__(self, sr, channels, mode='lowpass', slope=12):
        if sr <= 0 or channels < 1 or mode not in ('lowpass', 'bandpass', 'highpass', 'notch') or slope not in (12, 24):
            raise ParamError('invalid SVF configuration')
        self.sr, self.channels, self.mode = sr, channels, mode
        self.stages = slope//12
        self.state = np.zeros((self.stages, 2, channels))

    def process(self, x, cutoff_hz, resonance_db=0):
        x = np.asarray(x, dtype=np.float64)
        def control(v):
            a = np.asarray(v, dtype=np.float64)
            if a.ndim == 1:
                a = a[:, None]
            return np.broadcast_to(a, x.shape)
        f, res = control(cutoff_hz), control(resonance_db)
        if not np.isfinite(f).all() or not np.isfinite(res).all() or np.any(f <= 0) or np.any((res < 0) | (res > 24)):
            raise ParamError('invalid SVF control')
        gain = 10**(res/(20*self.stages))
        q = np.sqrt((gain**2+gain*np.sqrt(np.maximum(0, gain**2-1)))/2)
        damp = 1/q
        # Solve the final lowpass magnitude crossing in the prewarped domain.
        d = damp*damp-2
        r2 = (-d+np.sqrt(d*d+4*(2**(1/self.stages)-1)))/2
        g = np.tan(np.pi*np.minimum(f, .45*self.sr)/self.sr)
        if self.mode == 'lowpass':
            g = g/np.sqrt(r2)
        elif self.mode == 'highpass':
            g = g*np.sqrt(r2)
        a1 = 1/(1+g*(g+damp))
        a2, a3 = g*a1, g*g*a1
        y = np.empty_like(x)
        for n in range(len(x)):
            v = x[n]
            for s in range(self.stages):
                s1, s2 = self.state[s]
                v3 = v-s2
                bp = a1[n]*s1+a2[n]*v3
                lp = s2+a2[n]*s1+a3[n]*v3
                self.state[s, 0] = 2*bp-s1
                self.state[s, 1] = 2*lp-s2
                hp = v-damp[n]*bp-lp
                v = {'lowpass': lp, 'highpass': hp,
                     'bandpass': bp*damp[n]*gain[n], 'notch': hp+lp}[self.mode]
            y[n] = v
        return y


def svf(x, sr, cutoff_hz, resonance_db=0, mode='lowpass', slope=12):
    return SVF(sr, x.shape[1], mode, slope).process(x, cutoff_hz, resonance_db)
