"""Absolute-clock delay modulation with a peak-limited TPT SVF loop."""
import numpy as np
from mankomix.dspx.params import _e, _f


def mod_params(p):
    return dict(rate_hz=p['mod_rate_hz'], note=p['mod_note'], bpm=p['bpm'],
                lfo_shape=p['mod_shape'], phase=0, origin_s=0,
                stereo_phase=p['stereo_phase'], seed=p['seed'])


def cross_validate(p):
    from mankomix.dspx.bb.modulation import mod_rate
    from mankomix.dspx.bb.delayfx import validate_delay, duration
    mod_rate(mod_params(p))
    validate_delay(dict(p, feedback=effective_feedback(p)), longest=duration(p)+p['mod_depth_ms'])


def effective_feedback(p):
    return min(p['feedback'], .98*10**(-p['filter_res_db']/20)) if p['filter_hz'] else p['feedback']


def motion(frames, sr, p, channels=1, *, seed=0, start_sample=0):
    """Return (delay_samples, cutoff_hz), evaluated on the absolute clock."""
    from mankomix.dspx.bb.modulation import mod_lfo
    from mankomix.dspx.bb.delayfx import duration
    wave = mod_lfo(frames, sr, mod_params(p), channels, seed=seed, start_sample=start_sample)
    delay = np.maximum(0, duration(p)+p['mod_depth_ms']*wave)*sr/1000
    return delay, p['filter_hz']*2**(p['filter_mod_oct']*wave)


class ModLoop:
    """Persistent TPT lowpass; damping chosen from the desired peak gain."""
    def __init__(self, sr, channels, p, cutoff):
        from mankomix.dspx.bb.delayline import LoopFilter
        self.eq = LoopFilter(sr, channels, min(p['lowcut_hz'], .49*sr), p['highcut_hz'])
        self.cutoff, self.sr, self.offset = cutoff, sr, 0
        peak = 10**(p['filter_res_db']/20)
        self.k = np.sqrt(2-2*np.sqrt(max(0, 1-1/peak**2)))
        self.s1, self.s2 = np.zeros(channels), np.zeros(channels)
        self.enabled = bool(p['filter_hz'])

    def __call__(self, x):
        y = self.eq(x)
        if not self.enabled:
            return y
        out = np.empty_like(y)
        for i, v in enumerate(y):
            g = np.tan(np.pi*np.minimum(self.cutoff[self.offset+i], .45*self.sr)/self.sr)
            a1 = 1/(1+g*(g+self.k))
            v1 = a1*(self.s1+g*(v-self.s2))
            v2 = self.s2+g*v1
            self.s1, self.s2 = 2*v1-self.s1, 2*v2-self.s2
            out[i] = v2
        self.offset += len(x)
        return out


def mod_delay(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.delayfx import feedback_audio, finish
    cross_validate(p)
    if not p['mix']:
        return finish(x, x, sr, p)
    delays, cutoffs = motion(len(x), sr, p, x.shape[1], seed=seed)
    f = effective_feedback(p)
    wet = feedback_audio(x, delays, f, lambda: ModLoop(sr, x.shape[1], p, cutoffs))
    return finish(x, wet, sr, p, dict(feedback_requested=p['feedback'], feedback_effective=f,
                                    feedback_reduction_db=float(20*np.log10(f/p['feedback'])) if f else 0.))


def _declarations():
    from mankomix.dspx.bb.delayfx import definition, dl_parameters
    return [definition('mod_delay', dl_parameters() + [
        _f('mod_depth_ms', 'ms', 0, 20, 1, 'Delay deviation clipped at zero delay.'),
        _f('mod_rate_hz', 'Hz', .01, 20, .5, 'LFO rate.'),
        _e('mod_note', [s for s in dl_parameters() if s['id']=='note'][0]['choices'], 'none', 'LFO cycle note.'),
        _e('mod_shape', ['sine', 'triangle', 'random'], 'sine', 'Absolute-clock waveform.'),
        _f('stereo_phase', None, 0, 1, .25, 'Right LFO phase in cycles.'),
        _f('filter_hz', 'Hz', 0, 20000, 0, 'TPT loop lowpass; zero bypasses.'),
        _f('filter_mod_oct', 'oct', 0, 4, 0, 'Cutoff excursion.'),
        _f('filter_res_db', 'dB', 0, 12, 0, 'Loop filter peak resonance.')], implemented=True)]


SPECS = _declarations()
IMPLS = {'mod_delay': mod_delay}
CROSS_VALIDATE = {'mod_delay': cross_validate}
TIME_VARYING = {'mod_delay'}
