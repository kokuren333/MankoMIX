"""Analytically integrated power-law stop/start with silent stopped regions."""
import numpy as np
from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _f, _a, _e
from mankomix.dspx.bb.time_creative import definition


def validate(p):
    stops, starts = p['stop_s'], p['start_s']
    if any(b <= a for a, b in zip(stops, stops[1:])) or any(b <= a for a, b in zip(starts, starts[1:])):
        raise ParamError('stop_s and start_s must be strictly ascending')
    if len(starts) not in (len(stops), max(0, len(stops)-1)):
        raise ParamError('only the last start may be omitted')
    for k, stop in enumerate(stops):
        if k < len(starts):
            if starts[k] <= stop+p['stop_ms']/1000:
                raise ParamError('start must follow completed stop')
            if k+1 < len(stops) and starts[k]+p['start_ms']/1000 >= stops[k+1]:
                raise ParamError('restart overlaps the next stop')
        elif k+1 < len(stops):
            raise ParamError('missing intermediate restart')


def speed_map(frames, sr, p):
    """Return absolute input positions, speeds and affected mask, closed form."""
    validate(p)
    t = np.arange(frames)/sr
    pos, speed, affected = t.copy(), np.ones(frames), np.zeros(frames, dtype=bool)
    power, duration = p['curve'], p['stop_ms']/1000
    for i, stop in enumerate(p['stop_s']):
        start = p['start_s'][i] if i < len(p['start_s']) else np.inf
        next_stop = p['stop_s'][i+1] if i+1 < len(p['stop_s']) else np.inf
        u = np.clip((t-stop)/duration, 0, 1)
        slowing = (t >= stop) & (t < stop+duration)
        pos[slowing] = stop+duration*(u[slowing]-u[slowing]**(power+1)/(power+1))
        speed[slowing] = 1-u[slowing]**power
        held = (t >= stop+duration) & (t < start)
        stopped_pos = stop+duration*power/(power+1)
        pos[held], speed[held] = stopped_pos, 0
        affected |= slowing | held
        if not np.isfinite(start):
            continue
        ramp = p['start_ms']/1000
        restarting = (t >= start) & (t < min(start+ramp, next_stop))
        z = np.clip((t-start)/max(ramp, 1/sr), 0, 1)
        if p['resume'] == 'live':
            pos[restarting] = start+ramp*z[restarting]**(power+1)/(power+1)
            speed[restarting] = z[restarting]**power
        else:
            # Ramp 0->2 then run at 2 until the analytic read clock catches live.
            pos[restarting] = stopped_pos+2*ramp*z[restarting]**(power+1)/(power+1)
            speed[restarting] = 2*z[restarting]**power
            ramp_end_pos = stopped_pos+2*ramp/(power+1)
            lag = max(0, start+ramp-ramp_end_pos)
            catch = (t >= start+ramp) & (t < min(start+ramp+lag, next_stop))
            pos[catch] = ramp_end_pos+2*(t[catch]-start-ramp)
            speed[catch] = 2
            affected |= catch
        affected |= restarting
    return pos*sr, speed, affected


def tape_stop(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.time_creative import causal_read
    validate(p)
    if not p['stop_s']:
        return x.copy(), sr, {}
    pos, speed, affected = speed_map(len(x), sr, p)
    y = x.copy()
    # Variable-bandwidth sinc: scale the reconstruction bandwidth when >1.
    for a in range(0, len(x), 1024):
        ids = np.arange(a, min(a+1024, len(x)))
        ids = ids[affected[ids] & (speed[ids] > 0)]
        if not len(ids):
            continue
        slow = ids[speed[ids] <= 1]
        y[slow] = causal_read(x, pos[slow], slow)
        fast = ids[speed[ids] > 1]
        if len(fast):
            offsets = np.arange(-127, 129)
            base = np.floor(pos[fast]).astype(np.int64)
            distance = pos[fast, None]-(base[:, None]+offsets)
            bw = (.94/speed[fast])[:, None]
            w = bw*np.sinc(bw*distance)*(.5+.5*np.cos(np.pi*distance/128))
            w *= (base[:, None]+offsets) <= fast[:, None]
            w /= w.sum(axis=1, keepdims=True)
            iy = base[:, None]+offsets
            for c in range(x.shape[1]):
                samples = np.where((iy >= 0) & (iy < len(x)), x[np.clip(iy, 0, len(x)-1), c], 0)
                y[fast, c] = np.sum(samples*w, axis=1)
    y[affected & (speed == 0)] = 0
    fade = p['fade_ms']/1000
    if fade:
        t = np.arange(len(x))/sr
        for i, stop in enumerate(p['stop_s']):
            end = stop+p['stop_ms']/1000
            gain = np.clip((end-t)/fade, 0, 1)
            mask = (t >= max(stop, end-fade)) & (t < end)
            y[mask] *= gain[mask, None]
            if i < len(p['start_s']):
                start = p['start_s'][i]
                mask = (t >= start) & (t < start+fade)
                y[mask] *= np.clip((t[mask]-start)/fade, 0, 1)[:, None]
                if p['start_ms']:
                    finish = start+p['start_ms']/1000
                    mask = (t >= max(start, finish-fade)) & (t < finish)
                    y[mask] *= np.clip((finish-t[mask])/fade, 0, 1)[:, None]
                    mask = (t >= finish) & (t < finish+fade)
                    y[mask] *= np.clip((t[mask]-finish)/fade, 0, 1)[:, None]
    return y, sr, {'resume': p['resume'], 'stop_count': len(p['stop_s']), 'position_rule': 'closed-form power integral'}


SPECS = [definition('tape_stop', [
    _a('stop_s', 's', 0, 36000, 32, [], 'Strictly ascending stop onset times.'),
    _a('start_s', 's', 0, 36000, 32, [], 'Restart times; final restart may be omitted.'),
    _f('stop_ms', 'ms', 10, 5000, 400, 'Deceleration duration.'),
    _f('start_ms', 'ms', 0, 5000, 0, 'Acceleration duration.'),
    _f('curve', None, .25, 4, 1, 'v=1-u**curve during deceleration.'),
    _e('resume', ['live', 'catchup'], 'live', 'Live position or 2x catch-up.'),
    _f('fade_ms', 'ms', 0, 50, 5, 'Fade near stop and restart transitions.')], implemented=True)]
TIME_VARYING = {'tape_stop'}
IMPLS = {'tape_stop': tape_stop}
CROSS_VALIDATE = {'tape_stop': validate}
