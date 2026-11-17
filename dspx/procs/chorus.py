"""Clean / BBD / dual / tri / ensemble chorus with shared delay elements."""
import numpy as np
from mankomix.dspx.params import _e, _f, _i


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
    from mankomix.dspx.bb.modulation import combined_seed, validate_mod
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
            from mankomix.dspx.bb.bbd import bbd_audio
            if np.any(d <= 0):
                from mankomix.dsp.errors import ParamError
                raise ParamError('the zero-delay BBD clock limit is not implemented')
            # Each channel has its own event clock. The capacitor stage count
            # is fixed for chorus; stage count is not an additional user knob.
            voice = np.column_stack([bbd_audio(dry[:, c:c+1], sr, d[:,c],
                                      stages=1024, compander=True, seed=combined_seed(seed,p))[:,0]
                                     for c in range(2)])
            # Feedback traverses the BBD again, with the same event clocks.
            if p['feedback']:
                for _ in range(128):
                    source = dry+p['feedback']*voice
                    update = np.column_stack([bbd_audio(source[:,c:c+1], sr, d[:,c],
                                               stages=1024, compander=True, seed=combined_seed(seed,p))[:,0]
                                              for c in range(2)])
                    delta = np.max(np.abs(update-voice), initial=0)
                    voice = update
                    if delta < 2e-14:
                        break
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
