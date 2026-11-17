"""Built-in creative kernels; no processor/parameter automation dispatcher.

repeat_step(x, sr, start, end, count, ...) returns one causal repeated step.
read_positions(x, positions, current_samples=None) performs bounded-memory
causal BB-09 reads; optional clocks share the positions' local coordinate.
balance(x, position) reuses the fixed pan law, preserving centered input.
"""
import numpy as np


def read_positions(x, positions, current_samples=None):
    """Read full-context positions with BB-09 and a causal interpolation kernel."""
    from mankomix.dspx.bb.time_creative import causal_read
    out = np.empty((len(positions), x.shape[1]), dtype=np.float64)
    for a in range(0, len(out), 1024):
        b = min(a+1024, len(out))
        now = np.arange(a, b) if current_samples is None else current_samples[a:b]
        out[a:b] = causal_read(x, positions[a:b], now)
    return out


def balance(x, position):
    """Stereo balance; a mono step keeps its single channel."""
    from mankomix.dsp.reference.basic import pan
    if position == 0 or x.shape[1] != 2:
        return x.copy()
    return pan(x, 48000, dict(position=position, center_db=-3))[0]


def repeat_step(x, sr, start, end, count, *, source_start=None, gate=1,
                level_db=0, pitch_semitones=0, reverse=False, pan=0,
                decay_db=0, fade_ms=2):
    """Capture the first 1/count; first pass is live, later passes may reverse.

    Faster repeats stop at the captured buffer end (no wrapping); slower ones
    are cut at the repeat boundary. Source buffers never include later steps.
    Pattern mode may reuse an already captured earlier buffer.
    """
    from mankomix.dspx.bb.time_creative import seam_gain
    length = end-start
    if count == 0:
        return x[start:min(end, len(x))].copy()
    source_start = start if source_start is None else source_start
    boundaries = np.rint(np.arange(count+1)*length/count).astype(int)
    captured = boundaries[1]
    source = x[max(0, source_start):max(0, source_start)+captured]
    wet = np.zeros((min(end, len(x))-start, x.shape[1]), dtype=np.float64)
    speed = 2.**(pitch_semitones/12)
    for j, (a, b) in enumerate(zip(boundaries, boundaries[1:])):
        if a >= len(wet):
            break
        u = np.arange(min(b, len(wet))-a)
        if j == 0 and source_start == start:
            v = x[start+a:start+a+len(u)].copy()
        else:
            pos = u*speed
            if reverse:
                pos = captured-1-pos
            valid = (pos >= 0) & (pos < captured) & (pos < len(source))
            v = np.zeros((len(u), x.shape[1]))
            if len(source) and np.any(valid):
                v[valid] = read_positions(source, pos[valid], start+a+u[valid]-source_start)
        v[u >= (b-a)*gate] = 0
        v *= seam_gain(u, b-a, fade_ms*sr/1000)[:, None]
        gain = 10.**((level_db-j*decay_db)/20)
        wet[a:a+len(u)] = balance(v, pan)*gain
    return wet
