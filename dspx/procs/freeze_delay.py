"""Scheduled integer-loop freeze with one-time seam baking and bounded overdub."""
import numpy as np
from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _a, _b, _e, _f


def intervals(p, sr=None):
    """Resolve validated half-open intervals; sample quantisation is recorded."""
    from mankomix.dspx.bb.delayfx import duration
    starts, ends = p['freeze_start_s'], p['freeze_end_s']
    if len(starts) != len(ends):
        raise ParamError('freeze arrays must have equal lengths')
    if any(b <= a for a, b in zip(starts, ends)) or any(b >= a for b, a in zip(ends, starts[1:])):
        raise ParamError('freeze intervals must be ordered, separated, and nonempty')
    period = duration(p, 8000)/1000
    if sr is None:
        resolved = [(a, b) for a, b in zip(starts, ends)]
        if p['quantize'] == 'loop':
            resolved = [(p['origin_s']+round((a-p['origin_s'])/period)*period,
                         p['origin_s']+round((b-p['origin_s'])/period)*period) for a, b in resolved]
    else:
        length = max(1, round(period*sr))
        origin = round(p['origin_s']*sr)
        resolved = [(round(a*sr), round(b*sr)) for a, b in zip(starts, ends)]
        if p['quantize'] == 'loop':
            resolved = [(origin+round((a-origin)/length)*length,
                         origin+round((b-origin)/length)*length) for a, b in resolved]
    if any(a < 0 or b <= a for a, b in resolved) or any(b >= a for (_, b), (a, _) in zip(resolved, resolved[1:])):
        raise ParamError('quantized freeze intervals overlap, collapse, or precede zero')
    return resolved


def cross_validate(p):
    from mankomix.dspx.bb.delayfx import validate_delay
    intervals(p)
    validate_delay(p, 8000)


def check_runtime(p, sr, input_peak=1.):
    """Reject worst-case overdub beyond +12 dBFS before allocating a buffer.

    There is no extension runtime hook in the current registry. This check is
    called at processor entry, using the measured input peak; default peak=1
    also makes it independently callable for a conservative preflight.
    """
    from mankomix.dspx.bb.delayfx import duration
    windows = intervals(p, sr)
    d = max(1, round(duration(p, 8000)*sr/1000))
    if p['freeze_input'] == 'overdub' and p['overdub_decay'] == 1:
        bound = input_peak/(1-p['feedback'])
        if any(bound+np.ceil((b-a)/d)*input_peak > 10**(12/20) for a, b in windows):
            raise ParamError('freeze overdub worst-case peak exceeds +12 dBFS')
    return windows


def bake_seam(loop, fade_samples):
    """Bake a smooth periodic endpoint once, retaining the integer loop length."""
    out = loop.copy()
    f = min(max(1, fade_samples), max(1, len(loop)//2))
    u = np.linspace(0, 1, f)
    w = (u*u*(3-2*u))[:, None]
    anchor = (loop[0]+loop[-1])/2
    out[-f:] = (1-w)*loop[-f:]+w*anchor
    out[:f] = (1-w)*anchor+w*loop[:f]
    return out


def freeze_delay(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.delayfx import duration, finish
    from mankomix.dspx.bb.delayline import LoopFilter
    cross_validate(p)
    windows = check_runtime(p, sr, float(np.max(np.abs(x), initial=0)))
    if not p['mix']:
        return finish(x, x, sr, p)
    d = max(1, round(duration(p, 8000)*sr/1000))
    if not windows:
        # Preserve the existing simple delay's exact arithmetic, including EQ.
        from mankomix.dsp.reference.space import delay
        wet, _, _ = delay(x, sr, dict(time_ms=duration(p, 8000), note='none', bpm=0,
                                     feedback=p['feedback'], mix=1, route='both',
                                     lowcut_hz=p['lowcut_hz'], highcut_hz=p['highcut_hz']))
        return finish(x, wet, sr, p, dict(delay_samples=d, freeze_intervals_samples=[]))
    wet = np.zeros_like(x)
    buffer = np.zeros((d, x.shape[1]))
    normal = LoopFilter(sr, x.shape[1], min(p['lowcut_hz'], .49*sr), p['highcut_hz'])
    dry_gain = np.ones((len(x), 1))
    fade = max(1, round(p['freeze_fade_ms']*sr/1000))
    boundaries = sorted({0, len(x)} | {min(len(x), n) for ab in windows for n in ab})
    for start, end in zip(boundaries, boundaries[1:]):
        active = next(((a, b) for a, b in windows if a <= start < b), None)
        if active:
            order = (start+np.arange(d)) % d
            entry = buffer[order].copy()
            captured = entry.copy()
            if p['freeze_input']=='mute':
                count = min(fade, d, len(x)-start)
                ramp = np.minimum(1., (np.arange(count)+1)/fade)
                ramp = ramp*ramp*(3-2*ramp)
                # Burn the input fade into the capture BEFORE the seam is
                # baked, so the first lap cannot subsequently damage it.
                captured[:count] += x[start:start+count]*(1-ramp[:, None])
            buffer[order] = bake_seam(captured, fade)
        for a in range(start, end, d):
            b = min(a+d, end)
            indices = np.arange(a, b) % d
            previous = buffer[indices].copy()
            if active:
                begin, stop = active
                ramp = np.minimum(1., (np.arange(a, b)-begin+1)/fade)
                ramp = ramp*ramp*(3-2*ramp)
                phase = (np.arange(a,b)-begin) % d
                wet[a:b] = (1-ramp[:,None])*entry[phase]+ramp[:,None]*previous
                decay = p['overdub_decay'] if p['freeze_input']=='overdub' else 1
                injection = x[a:b] if p['freeze_input']=='overdub' else 0
                buffer[indices] = decay*previous+injection
                if p['dry_in_freeze']=='mute':
                    dry_gain[a:b, 0] = 1-ramp
            else:
                # Crossfade the return from freeze to the ordinary decaying loop.
                recent_end = max([b0 for _, b0 in windows if b0 <= a] or [-fade])
                ramp = np.minimum(1., (np.arange(a, b)-recent_end+1)/fade)
                ramp = ramp*ramp*(3-2*ramp)
                if p['dry_in_freeze']=='mute' and recent_end >= 0:
                    dry_gain[a:b,0] = ramp
                wet[a:b] = previous
                filtered = normal(previous)
                f = p['feedback'] + (1-ramp[:, None])*(1-p['feedback']) if recent_end >= 0 else p['feedback']
                buffer[indices] = x[a:b] + f*filtered
    return finish(x, wet, sr, p, dict(delay_samples=d, freeze_intervals_samples=[list(ab) for ab in windows],
                                    freeze_intervals_s=[[a/sr,b/sr] for a,b in windows]), dry_gain=dry_gain)


def _declarations():
    from mankomix.dspx.bb.delayfx import definition, dl_parameters
    return [definition('freeze_delay', dl_parameters(time_ms=dict(min=10, max=8000, default=500)) + [
        _a('freeze_start_s', 's', 0, 36000, 32, [], 'Ordered freeze starts.'),
        _a('freeze_end_s', 's', 0, 36000, 32, [], 'Matching exclusive ends.'),
        _f('freeze_fade_ms', 'ms', 1, 500, 10, 'One-time seam and entry/exit crossfade.'),
        _e('freeze_input', ['mute','overdub'], 'mute', 'Frozen input mode.'),
        _f('overdub_decay', None, 0, 1, 1, 'Existing loop gain per overdub lap.'),
        _e('quantize', ['off','loop'], 'off', 'Round events to the loop sample lattice.'),
        _f('origin_s', 's', 0, 36000, 0, 'Loop grid origin.'),
        _e('dry_in_freeze', ['pass','mute'], 'pass', 'Dry path during freeze.')], implemented=True)]


SPECS = _declarations()
IMPLS = {'freeze_delay': freeze_delay}
CROSS_VALIDATE = {'freeze_delay': cross_validate}
TIME_VARYING = {'freeze_delay'}
