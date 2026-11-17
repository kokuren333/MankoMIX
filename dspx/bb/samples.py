"""BB-24 original synthetic drum samples and verified local BYO catalogue.

Only mathematical synthesis is shipped. synthetic_bytes pins PCM32 WAV data;
load_sample verifies the catalogue/file on each call before resampling.
"""
import io
import wave
import numpy as np
from mankomix import repo_data_root
from mankomix.dsp.errors import ParamError
from .asset_registry import AssetRegistry


def synthetic_sample(id, sr=48000, seed=2411):
    t = np.arange(round(.4*sr))/sr
    rng = np.random.Generator(np.random.PCG64(seed))
    noise = rng.integers(-32768, 32768, len(t)).astype(np.float64)/32768
    if id == 'synth_kick_a':
        y = np.sin(2*np.pi*(55*t+5*(1-np.exp(-t*70))))*np.exp(-t*18)
        y += .3*noise*np.exp(-t*1200)
    elif id == 'synth_snare_a':
        y = .45*np.sin(2*np.pi*190*t)*np.exp(-t*30)+.55*noise*np.exp(-t*26)
    elif id == 'synth_hat_a':
        y = np.r_[0, np.diff(noise)]*np.exp(-t*65)
    else:
        raise ParamError('unknown original sample generator')
    y *= np.minimum(1, t/.0003)
    return (y/max(np.max(np.abs(y)), 1e-30)*.8)[:, None]


def synthetic_bytes(id, sr=48000, seed=2411):
    x = synthetic_sample(id, sr, seed)
    out = io.BytesIO()
    with wave.open(out, 'wb') as f:
        f.setnchannels(1)
        f.setsampwidth(4)
        f.setframerate(sr)
        f.writeframes(np.rint(x*2**31).astype('<i4').tobytes())
    return out.getvalue()


def decode(data):
    import soundfile as sf
    try:
        x, sr = sf.read(io.BytesIO(data), dtype='float64', always_2d=True)
    except (RuntimeError, ValueError) as exc:
        raise ParamError('sample must be readable audio') from exc
    if not len(x) or x.shape[1] not in (1, 2) or not np.isfinite(x).all():
        raise ParamError('sample requires finite nonempty mono/stereo audio')
    return x, sr


def metadata(data):
    x, sr = decode(data)
    return {'sr': sr, 'channels': x.shape[1], 'length_s': len(x)/sr}


def validate(e):
    if type(e.get('sr')) is not int or e['sr'] <= 0 or e.get('channels') not in (1, 2):
        raise ParamError('invalid sample rate or channels')
    if not isinstance(e.get('length_s'), (int, float)) or not np.isfinite(e['length_s']) or e['length_s'] <= 0:
        raise ParamError('invalid sample length')
    if e['tier'] == 'official' and (e['origin'].get('type') != 'synthetic' or
            e['origin'].get('generator') != 'tools/generate_synthetic_samples.py'):
        raise ParamError('official sample requires original generator')


SAMPLES = AssetRegistry('samples', repo_data_root()/'registry'/'samples.json', metadata,
                       generate=lambda e: synthetic_bytes(e['id'], **e['origin']['args']), validate=validate)

# Installing this registry changes no existing resolver or processor definition.
from mankomix.dspx import assets as _assets
if 'samples' not in _assets.RESOLVERS:
    _assets.register('samples', SAMPLES.resolve)


def load_sample(id, sr):
    from mankomix.dsp.reference.export import resample_poly_hq
    data, record, notes = SAMPLES.load(id)
    x, source_sr = decode(data)
    return resample_poly_hq(x, source_sr, sr), record, notes
