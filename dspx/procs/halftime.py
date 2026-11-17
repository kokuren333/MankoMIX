"""Length-preserving grid-synchronised fractional-rate playback."""
import numpy as np
from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _f, _e
from mankomix.dspx.bb.time_creative import definition, curve_param, note_choices


def validate(p, *, resolve_tempo=False):
    from mankomix.dspx.bb.curves import period_ms
    from mankomix.dspx.bb.time_creative import validate_active
    note = p['loop_note'] if resolve_tempo or p['bpm'] else 'none'
    period_ms(p['loop_ms'], note=note, bpm=p['bpm'])
    validate_active(p)
    if p['band_hi_hz'] and p['band_lo_hz'] >= p['band_hi_hz']:
        raise ParamError('band_lo_hz must be below band_hi_hz')


def halftime(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.time_creative import grid, seam_gain, mix_active, active_mask
    from mankomix.dspx.bb.time_creative import causal_read
    validate(p, resolve_tempo=True)
    if p['mix'] == 0 or not np.any(active_mask(p, len(x), sr)):
        return x.copy(), sr, {}
    gp = dict(step_ms=p['loop_ms'], step_note=p['loop_note'], bpm=p['bpm'], origin_s=p['origin_s'])
    k, start, end = grid(len(x), sr, gp)
    speed = {'1/2': .5, '1/4': .25, '2/3': 2/3, '3/4': .75}[p['speed']]
    source, remainder = x, np.zeros_like(x)
    if p['band_lo_hz'] or p['band_hi_hz']:
        from mankomix.dspx.bb.crossover import split_bands
        edges = sorted(set(f for f in (p['band_lo_hz'], p['band_hi_hz']) if 0 < f < sr*.49))
        parts, _ = split_bands(x, sr, edges, 'linear')
        source = np.zeros_like(x)
        bounds = [0]+edges+[sr/2]
        for i, part in enumerate(parts):
            if bounds[i] >= p['band_lo_hz'] and (not p['band_hi_hz'] or bounds[i+1] <= p['band_hi_hz']):
                source += part
        remainder = x-source
    pos = start+(np.arange(len(x))-start)*speed
    # Chunk reads avoid allocating frames*channels*256 for a whole song.
    wet = np.empty_like(x)
    for a in range(0, len(x), 2048):
        wet[a:a+2048] = causal_read(source, pos[a:a+2048], np.arange(a, min(a+2048, len(x))))
    wet *= seam_gain(np.arange(len(x))-start, end-start, p['fade_ms']*sr/1000)[:, None]
    wet += remainder
    wet[k < 0] = x[k < 0]
    return mix_active(x, wet, p, sr), sr, {'speed': speed, 'grid_clock': 'absolute rounded boundaries'}


SPECS = [definition('halftime', [
    _e('loop_note', note_choices(), '1/1', 'Loop note; none uses loop_ms.'),
    _f('bpm', 'BPM', 0, 400, 0, 'Explicit fixed tempo.'),
    _f('loop_ms', 'ms', 50, 16000, 2000, 'Free loop duration.'),
    _f('origin_s', 's', 0, 36000, 0, 'Absolute loop origin.'),
    _e('speed', ['1/2', '1/4', '2/3', '3/4'], '1/2', 'Playback ratio.'),
    _f('fade_ms', 'ms', .5, 50, 5, 'Seam fade duration.'),
    _f('band_lo_hz', 'Hz', 0, 20000, 0, 'Band lower edge; zero is open.'),
    _f('band_hi_hz', 'Hz', 0, 24000, 0, 'Band upper edge; zero is open.'),
    curve_param('active', 256, 0, 36000, 0, 1),
    _f('mix', None, 0, 1, 1, 'Wet proportion.')], implemented=True)]
TIME_VARYING = {'halftime'}
IMPLS = {'halftime': halftime}
CROSS_VALIDATE = {'halftime': validate}
