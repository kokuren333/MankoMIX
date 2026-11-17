"""Clean / BBD / dual / tri / ensemble chorus with shared delay elements."""
import numpy as np
from mankomix.dspx.params import _e, _f, _i


class BBDVoice:
    """Bounded event rendering with the analytic infinite-clock limit.

    Below 32 events per host sample this is the unchanged shared BBD model.
    Above it, blend its residual against the continuous two-filter cascade.
    The transport delay remains the requested delay, including exactly zero;
    no minimum delay or infinite event array is introduced. The residual is
    zero at infinite clock and joins the event model with zero slope.
    """
    def __init__(self, frames, sr, delays):
        from mankomix.dspx.bb.bbd import BBDPlan
        self.sr = sr
        self.delays = np.broadcast_to(np.asarray(delays, dtype=np.float64).reshape(-1), (frames,))
        self.threshold = 1024/(2*32)
        self.limit = np.any(self.delays < self.threshold)
        self.plan = None
        if np.any(self.delays > 0):
            bounded = np.maximum(self.delays, self.threshold) if self.limit else self.delays
            self.plan = BBDPlan(frames, sr, bounded, stages=1024)

    def continuous(self, x, delays):
        """Impulse-invariant H(s)^2 at cutoff .18 sr, at retarded times.

        For H(s)=sum(r_i/(s-p_i)), its squared impulse response is
        sum((a_i+r_i^2*t)*exp(p_i*t)), a_i=2*r_i*sum(r_j/(p_i-p_j)).
        This is the exact zero-clock-period limit of the two analog filters,
        rather than dry bypass (the host cutoff cap still applies).
        """
        from scipy import signal
        times = np.arange(len(x))-delays
        indices = np.maximum(0, np.floor(times).astype(np.int64))
        fractions = np.where(times < 0, 0, times-indices)
        b, a = signal.butter(5, 1., analog=True)
        residues, poles, _ = signal.residue(b, a)
        rate = 2*np.pi*.18
        result = np.zeros_like(x, dtype=np.complex128)
        for i, (residue, pole) in enumerate(zip(residues, poles)):
            others = np.arange(len(poles)) != i
            simple = 2*residue*np.sum(residues[others]/(pole-poles[others]))
            decay = np.exp(pole*rate)
            state = signal.lfilter([1], [1, -decay], x, axis=0)[indices]
            moment = signal.lfilter([0, decay], [1, -2*decay, decay*decay], x, axis=0)[indices]
            result += rate*np.exp(pole*rate*fractions)[:, None]*(simple*state+
                rate*residue*residue*(moment+fractions[:, None]*state))
        result[times < 0] = 0
        return result.real

    def process(self, x, *, compander=True):
        from mankomix.dspx.bb.bbd import envelope_compand
        if not len(x):
            return x.copy()
        source = envelope_compand(x, self.sr) if compander else x
        if not self.limit:
            wet = self.plan.process(source)
        else:
            wet = self.continuous(source, self.delays)
            if self.plan is not None:
                bounded = np.maximum(self.delays, self.threshold)
                fraction = np.minimum(self.delays/self.threshold, 1)
                weight = fraction*fraction*(3-2*fraction)
                wet += weight[:, None]*(self.plan.process(source)-self.continuous(source, bounded))
        return envelope_compand(wet, self.sr, inverse=True) if compander else wet


def voice_motion(frames, sr, p, *, seed=0, start_sample=0):
    """Return frames x 2 x voices sample delays on the absolute clock."""
    from mankomix.dspx.bb.modulation import mod_lfo
    count = {'dual':2, 'tri':3, 'ensemble':3}.get(p['model'], p['voices'])
    delays = []
    for v in range(count):
        q = dict(p, phase=(p['phase']+v/count)%1)
        # Dual voices have identical L/R clock and opposing voice phases;
        # cross-routing supplies the stereo image, preserving mono symmetry.
        if p['model'] == 'dual':
            q['stereo_phase'] = 0
        wave = mod_lfo(frames, sr, q, 2, seed=seed, start_sample=start_sample)
        if p['model'] == 'ensemble':
            q.update(rate_hz=p['rate_hz']*10, note='none')
            from mankomix.dspx.bb.modulation import mod_rate
            q['rate_hz'] = mod_rate(p)*10
            fast = mod_lfo(frames, sr, q, 2, seed=seed, start_sample=start_sample)
            wave = .5*(wave+fast)
        delays.append(np.maximum(0, p['delay_ms']+p['depth_ms']*p['depth']*wave)*sr/1000)
    return np.stack(delays, axis=2)


def chorus(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.delayfx import feedback_audio, finish
    from mankomix.dspx.bb.delayline import LoopFilter
    from mankomix.dspx.bb.modulation import validate_mod
    validate_mod(p)
    if not p['mix']:
        return finish(x, x, sr, p)
    dry = np.repeat(x, 2, axis=1) if x.shape[1] == 1 else x
    motion = voice_motion(len(x), sr, p, seed=seed)
    count = motion.shape[2]
    wet = np.zeros_like(dry)
    for v in range(count):
        d = motion[:, :, v]
        if p['model']=='bbd':
            from mankomix.dspx.bb.bbd import envelope_compand
            # Each channel has its own event clock. The capacitor stage count
            # is fixed for chorus; stage count is not an additional user knob.
            plans = [BBDVoice(len(x), sr, d[:, c]) for c in range(2)]
            def traverse(source):
                return np.column_stack([plan.process(source[:, c:c+1], compander=False)[:, 0]
                                        for c, plan in enumerate(plans)])
            compressed = envelope_compand(dry, sr)
            voice = traverse(compressed)
            # Feedback traverses the BBD again, with the same event clocks.
            # Companding surrounds the linear loop: envelope transients must
            # not become a gain stage on every feedback traversal.
            if p['feedback']:
                for _ in range(128):
                    source = compressed+p['feedback']*voice
                    update = traverse(source)
                    delta = np.max(np.abs(update-voice), initial=0)
                    voice = update
                    # Modal cancellation has a roundoff floor proportional
                    # to compressed amplitude. This is a solver tolerance,
                    # not an audio gain change or an acceptance threshold.
                    tolerance = 128*np.finfo(np.float64).eps*max(1., np.max(np.abs(update), initial=0))
                    if delta < tolerance:
                        break
                else:
                    from mankomix.dsp.errors import ParamError
                    raise ParamError('BBD chorus full-context feedback solve did not converge')
            voice = envelope_compand(voice, sr, inverse=True)
        else:
            voice = feedback_audio(dry, d, p['feedback'])
        # Symmetric cross-distribution. Width=0 preserves the centred sum.
        pan = 0 if count == 1 else 2*v/(count-1)-1
        gains = np.array([1-p['width']*max(0,pan), 1+p['width']*min(0,pan)])
        wet += voice*gains
    # Fixed energy normalization, with no signal-dependent gain riding.
    routing = np.array([[1-p['width']*max(0, 0 if count==1 else 2*v/(count-1)-1),
                         1+p['width']*min(0, 0 if count==1 else 2*v/(count-1)-1)] for v in range(count)])
    wet /= np.sqrt(np.sum(routing*routing, axis=0))
    wet = LoopFilter(sr, 2, min(p['lowcut_hz'], .49*sr), p['highcut_hz'])(wet)
    return finish(x, wet, sr, p, dict(voices_effective=count, voice_normalization='inverse_sqrt_routing_energy'))


def _declarations():
    from mankomix.dspx.bb.modulation import mod_params, modulation_definition
    return [modulation_definition('chorus', mod_params(.6, .5, .25, .5) + [
        _e('model', ['clean','bbd','dual','tri','ensemble'], 'clean', 'Chorus topology.'),
        _f('delay_ms', 'ms', 2, 40, 12, 'Centre delay.'),
        _f('depth_ms', 'ms', 0, 10, 3, 'Deviation at depth=1, clipped at zero.'),
        _i('voices', None, 1, 4, 2, 'Clean / BBD voices.'),
        _f('feedback', None, -.5, .5, 0, 'Signed per-voice feedback.'),
        _f('highcut_hz', 'Hz', 0, 20000, 0, 'Wet lowpass.'),
        _f('lowcut_hz', 'Hz', 0, 1000, 0, 'Wet highpass.'),
        _f('width', None, 0, 1, 1, 'Voice stereo distribution.')], channel=False)]


SPECS = _declarations()
IMPLS = {'chorus': chorus}
TIME_VARYING = {'chorus'}


def cross_validate(p):
    from mankomix.dspx.bb.modulation import validate_mod
    validate_mod(p)


CROSS_VALIDATE = {'chorus': cross_validate}
