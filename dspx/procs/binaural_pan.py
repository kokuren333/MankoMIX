"""T05-02 deterministic structural/BYO binaural renderer on a 64-sample grid."""
import numpy as np
from mankomix.dspx.params import _f, _e, _b


def _params():
    from mankomix.dspx.bb.motion import curve_param
    return [dict(id="hrtf", type="asset", registry="hrtfs", unit=None,
                 default="model_sphere", description="Pinned structural or local measured HRTF ID."),
            _f("azimuth_deg", "deg", -180, 180, 0, "Positive azimuth points right."),
            _f("elevation_deg", "deg", -90, 90, 0, "Elevation above horizontal."),
            _f("distance_m", "m", .2, 50, 1.5, "Source distance."),
            curve_param("path", "s", 0, 1e12, -180, 180, 4096, []),
            curve_param("elevation_path", "s", 0, 1e12, -90, 90, 4096, []),
            _b("distance_gain", False, "Apply 1/r gain and air lowpass, referenced to 1.5 m."),
            _f("room", None, 0, 1, 0, "Amount of six fixed early reflections."),
            _e("input", ["mono_sum", "stereo"], "mono_sum", "Stereo uses two spread sources."),
            _f("spread_deg", "deg", 0, 90, 30, "Two-source angular offset."),
            _f("lo_bypass_hz", "Hz", 0, 300, 0, "Centre low frequencies; zero disables.")]


def control_nodes(p, sr, samples):
    """Evaluate azimuth/elevation on absolute integer sample positions."""
    from mankomix.dspx.bb.curves import sample_curve
    # BB-05 fixes the seconds-to-sample rounding and endpoint extension.
    def one(key, fallback):
        if not p[key]:
            return np.full(len(samples), p[fallback])
        return np.array([sample_curve(p[key], 1, sr, start_sample=int(i))[0] for i in samples])
    return one("path", "azimuth_deg"), one("elevation_path", "elevation_deg")


def _source(x, sr, p, dataset, offset):
    from mankomix.dspx.bb.fir import fft_convolve
    n = len(x)
    if not n:
        return np.zeros((0, 2))
    nodes = np.arange(0, n+64, 64)
    az, el = control_nodes(p, sr, nodes)
    az = az+offset
    az = np.where(np.abs(az) > 180, az-np.sign(az)*360, az)
    if np.all(az == az[0]) and np.all(el == el[0]):
        return fft_convolve(x, dataset.kernel(float(az[0]), float(el[0]), sr)[:, None, :], "same")
    y = np.zeros((n, 2))
    old = dataset.kernel(float(az[0]), float(el[0]), sr)
    for j, a in enumerate(nodes[:-1]):
        b = min(a+64, n)
        new = dataset.kernel(float(az[j+1]), float(el[j+1]), sr)
        values = []
        for h in (old, new):
            first = max(0, int(a)-len(h)+1)
            wet = fft_convolve(x[first:b], h[:, None, :], "same")
            values.append(wet[a-first:b-first])
        t = (np.arange(a, b)-a)[:, None]/64
        y[a:b] = values[0]*(1-t)+values[1]*t
        old = new
    return y


def binaural_pan(x, sr, p, *, seed=0):
    from scipy import signal
    from mankomix.dspx.bb.hrtf import load_hrtf
    from mankomix.dspx.bb.delayline import fractional_delay, spatial_stats
    dataset, provenance = load_hrtf(p["hrtf"], sr)
    dry = np.mean(x, axis=1, keepdims=True)
    sources = x if p["input"] == "stereo" and x.shape[1] == 2 else dry
    low = np.zeros_like(sources)
    if p["lo_bypass_hz"] and len(x):
        sos = signal.butter(1, min(p["lo_bypass_hz"], sr*.49), fs=sr, output="sos")
        low = signal.sosfilt(sos, sources, axis=0)
        sources = sources-low
    if p["input"] == "stereo":
        left, right = sources[:, :1], sources[:, -1:]
        y = .5*(_source(left, sr, p, dataset, -p["spread_deg"])
                +_source(right, sr, p, dataset, p["spread_deg"]))
    else:
        y = _source(sources, sr, p, dataset, 0)
    y += np.mean(low, axis=1, keepdims=True)*np.sqrt(.5)
    if p["distance_gain"]:
        y *= 1.5/p["distance_m"]
        extra = max(0., p["distance_m"]-1.5)
        if extra and len(y):
            sos = signal.butter(1, min(sr*.49, 20000/(1+.12*extra)), fs=sr, output="sos")
            y = signal.sosfilt(sos, y, axis=0)
    if p["room"]:
        reflected = np.zeros_like(y)
        for j, (delay, gain) in enumerate(zip((7, 11, 17, 23, 31, 43), (.14, .11, .09, .07, .05, .04))):
            feed = y if j % 2 == 0 else y[:, ::-1]
            reflected += gain*fractional_delay(feed, delay*sr/1000)
        y += p["room"]*reflected
    stats = spatial_stats(y, sr)
    stats.update(provenance, coefficient_hop_samples=64,
                 binaural_note="Headphones only; mono fold can cancel. Individual front/back and elevation cues are not guaranteed. No perceptual claim.",
                 room_reflections=6 if p["room"] else 0,
                 context="Full input history from song start; excerpt by context replay.")
    return y, sr, stats


def render_excerpt(x, sr, p, start, stop, *, seed=0):
    """Render [start:stop] with full input from sample zero; no state reset."""
    from mankomix.dsp.errors import ParamError
    if not 0 <= start <= stop <= len(x):
        raise ParamError("excerpt must lie within the supplied full context")
    return binaural_pan(x, sr, p, seed=seed)[0][start:stop]


# Install the resolver without importing another processor or loading any data.
from mankomix.dspx import assets as _assets


def _resolve(id):
    from mankomix.dspx.bb.hrtf import HRTFS
    return HRTFS.resolve(id)


if "hrtfs" not in _assets.RESOLVERS:
    _assets.register("hrtfs", _resolve)

SPECS = [dict(type="binaural_pan", implemented=True,
              description="Structural or local measured binaural panning.", params=_params(),
              stages=["track", "bus"], master_slot=None, channel_ok=False,
              offline_only=False, backends=["reference"],
              realtime=dict(block_ok=False, latency_samples=0, allocates=True))]
IMPLS = {"binaural_pan": binaural_pan}
TIME_VARYING = {"binaural_pan"}
