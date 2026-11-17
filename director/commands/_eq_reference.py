"""Read-only spectral evidence shared by the W4a direction commands.

Welch frames use refstudy's estimator, independently per channel; silent
frames are omitted. Reference digests are never treated as full spectra.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

import numpy as np

from mankomix.core import audio_io
from mankomix.core.errors import InputError
from mankomix.core.measure.bands import Band, Spectrum
from mankomix.core.measure.spectral import band_crest
from mankomix.director import query as Q, refstudy as RS, stemobs as S

METHOD = 'welch_active_v1'
LOW_NOTE = '低音は音符ごとに変わる。見るべきは最低音の動き。'


def project_root(args):
    return getattr(args, 'project', None) or '.'


def number(value, lo, hi, name):
    if not np.isfinite(value) or not lo <= value <= hi:
        raise InputError(f'{name} must be in [{lo:g}, {hi:g}]')
    return value


def band_arg(value, default=(20, 20000)):
    lo, hi = value or default
    number(lo, 20, 20000, '--band-hz')
    number(hi, 20, 20000, '--band-hz')
    if lo >= hi:
        raise InputError('--band-hz requires lo < hi')
    return float(lo), float(hi)


def add_section(parser):
    parser.add_argument('--section')


def add_references(parser, *, audio=False, required=False):
    group = parser.add_mutually_exclusive_group(required=required)
    group.add_argument('--refsheet')
    group.add_argument('--ref-kb', nargs='+')
    if audio:
        group.add_argument('--ref', nargs='+')
    parser.add_argument('--kb', default=RS.DEFAULT_KB, help='KB root for work IDs')


def section_audio(x, sr, root, section):
    from mankomix.director.direction import _Project
    if len(x) < round(.4 * sr):
        raise InputError('at least 0.4 seconds of audio is required')
    spec = section
    if section == 'loudest':
        # Existing K-weighted block engine, 30 s windows on its 100 ms grid.
        from mankomix.core.measure.loudness import _Blocks
        width = min(len(x), 30 * sr)
        hop = max(1, round(.1 * sr))
        loudness = _Blocks(x, sr).lufs(30.) if len(x) >= 30*sr else np.empty(0)
        start = int(np.argmax(loudness))*hop if len(loudness) else 0
        spec = {'t0_s': start/sr, 't1_s': (start+width)/sr}
    elif isinstance(section, str) and ',' in section:
        try:
            a, b = map(float, section.split(','))
            if not np.isfinite([a, b]).all() or not 0 <= a < b <= len(x)/sr:
                raise ValueError
            spec = {'t0_s': a, 't1_s': b}
        except ValueError:
            raise InputError('--section requires a section ID or t0,t1 within the audio') from None
    try:
        t0, t1 = Q.section_range(spec, _Project(root).sections(), len(x)/sr)
    except Q.QueryError as e:
        raise InputError(str(e)) from None
    return x[round(t0*sr):round(t1*sr)], [t0, t1]


def source(args, target=None):
    """Return audio, rate, provenance; StemSource preflights cleanup caches."""
    target = target or getattr(args, 'audio', None) or getattr(args, 'target', None) or 'mix'
    p = Path(target)
    if target == 'master':
        from mankomix.director.direction import _Project, _render_file
        ctx = _Project(project_root(args))
        variant = ctx.variant()
        rendered = _render_file(Path(project_root(args)), variant['id']) if variant else None
        if rendered is None:
            raise InputError('master measurement requires an existing master render; use --target mix for the premaster bus')
        p = rendered
    if p.is_file():
        try:
            x, sr = RS.read_audio(p)
        except (RS.RefStudyError, OSError, RuntimeError) as e:
            raise InputError(str(e)) from None
        signal = 'rendered_master' if target == 'master' else 'audio'
    else:
        src = S.StemSource(project_root(args))
        try:
            if target == 'mix':
                x, sr = src.mix()
                signal = 'mix_bus_before_master'
            elif target.startswith('trk_'):
                src.check_track(target)
                stems, sr = src.dry()
                x = stems[target]
                signal = 'mix_stage_dry'
            else:
                raise InputError('--target must be mix, master, trk_<stem> or an audio file')
        except S.StemObsError as e:
            raise InputError(str(e)) from None
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 1:
        x = x[:, None]
    if not np.isfinite(x).all():
        raise InputError('audio must be finite')
    x, interval = section_audio(x, sr, project_root(args), getattr(args, 'section', None))
    return x, sr, {'signal': signal, 'section_s': interval, 'sample_rate': sr}


def spectrum(x, sr):
    """Mean active-frame PSD, level matched with the existing integrated LUFS."""
    n = min(8192, len(x))
    if n < 256:
        raise InputError('audio is too short for Welch analysis')
    starts = np.arange(0, len(x)-n+1, max(1, n//2))
    levels = np.array([np.mean(x[i:i+n]**2) for i in starts])
    active = levels > max(1e-10, float(levels.max(initial=0))*1e-6)
    lufs = RS._lufs(x, sr)
    gain = -23.-lufs if lufs is not None else 0.
    powers = []
    f = np.fft.rfftfreq(n, 1/sr)
    for i in starts[active]:
        channel_power = []
        for ch in range(x.shape[1]):
            _, p = RS._welch(x[i:i+n, ch:ch+1], sr)
            channel_power.append(p)
        powers.append(np.mean(channel_power, axis=0))
    p = np.mean(powers, axis=0) if powers else np.zeros(len(f))
    p *= 10**(gain/10)
    return {'method': METHOD, 'frequencies_hz': f.tolist(), 'power_density': p.tolist(),
            'sample_rate': int(sr), 'lufs_i': lufs, 'gain_db': gain,
            'active_frames': int(active.sum()), 'total_frames': len(starts),
            'window_samples': n, 'hop_samples': n//2}


def arrays(spec):
    return np.asarray(spec['frequencies_hz']), np.asarray(spec['power_density'])


def db(power):
    return float(10*np.log10(max(float(power), 1e-30)))


def power(spec, lo, hi):
    f, p = arrays(spec)
    # Fractional edge-bin integration avoids empty narrow low bands.
    df = f[1]-f[0]
    weights = np.maximum(0., np.minimum(f+df/2, hi)-np.maximum(f-df/2, lo))
    return float(np.dot(weights, p))


def smooth_db(spec, frequencies, width):
    from mankomix.dspx.bb.stft import smooth_frequency
    f, p = arrays(spec)
    levels = smooth_frequency((10*np.log10(np.maximum(p, 1e-30)))[None, :], f, width)[0]
    return np.interp(np.log2(frequencies), np.log2(np.maximum(f, .001)), levels)


def bands(mode, sr):
    top = min(20000., sr/2)
    if mode == '4':
        edges = [20., 250., 2000., 8000., top]
    elif mode == 'lowend':
        edges = (20*2**(np.arange(9)/2)).tolist()
    else:
        step = 3 if mode == 'third' else 6
        edges = (20*2**(np.arange(int(np.ceil(step*np.log2(top/20)))+1)/step)).tolist()
        edges[-1] = top
    return [(float(a), float(min(b, top))) for a, b in zip(edges, edges[1:]) if a < top and b > a]


def levels(spec, mode):
    base = power(spec, 300, 3000) if mode == 'lowend' else power(spec, 20, 20000)
    if base <= 0:
        return [None for _ in bands(mode, spec['sample_rate'])]
    return [db(power(spec, a, b)/base) for a, b in bands(mode, spec['sample_rate'])]


def low_crest(x, sr):
    result = band_crest(Spectrum(x, sr), [Band('low', 20., min(250., sr/2))], x=x)
    return result['bands']['low']['crest_db']


def distribution(value, values):
    vals = [float(v) for v in values if v is not None and np.isfinite(v)]
    if not vals or value is None:
        return {'target_db': value, 'n': len(vals), 'median_db': None, 'q1_db': None,
                'q3_db': None, 'min_db': None, 'max_db': None, 'inside': None, 'outside_db': None}
    q1, median, q3 = np.percentile(vals, [25, 50, 75])
    delta = float(value-q1 if value < q1 else value-q3 if value > q3 else 0.)
    if abs(delta) <= 1e-6:
        delta = 0.
    return {'target_db': value, 'n': len(vals), 'median_db': float(median),
            'q1_db': float(q1), 'q3_db': float(q3), 'min_db': min(vals), 'max_db': max(vals),
            'inside': delta == 0., 'outside_db': delta}


def confidence(n):
    return 'high' if n >= 3 else 'low' if n else 'unknown'


def move(target, processor, params, index=1, basis='measured spectral evidence'):
    return {'id': f'm{index:02}', 'aim': 'a1', 'op': 'chain_add', 'stage': 'mix',
            'target': target, 'processor': processor, 'params': params,
            'basis': basis, 'origin': 'new'}


def reference_paths(args):
    tokens = getattr(args, 'ref', None) or getattr(args, 'ref_kb', None) or []
    if isinstance(tokens, str):
        tokens = [tokens]
    if getattr(args, 'refsheet', None):
        tokens = [args.refsheet]
    found = []
    for token in tokens:
        p = Path(token)
        if not p.exists():
            slug = token.removeprefix('work_')
            try:
                RS.check_slug(slug)
            except RS.RefStudyError as e:
                raise InputError(str(e)) from None
            p = RS.work_dir(Path(args.kb), slug)/'refstudy.md'
        if p.is_dir():
            studies = sorted(p.rglob('refstudy.md'))
            pths = studies or sorted(q for q in p.iterdir() if q.suffix.lower() in ('.json', '.wav', '.flac', '.aiff', '.mp3'))
            found.extend(pths)
        elif p.is_file():
            found.append(p)
        else:
            raise InputError('reference file or refstudy ID was not found')
    # Duplicate material never increases the reference count.
    return sorted(set(p.resolve() for p in found))


def references(args):
    out, seen = [], set()
    for p in reference_paths(args):
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        if audio_io.is_audio_file(p):
            try:
                x, sr = RS.read_audio(p)
            except (RS.RefStudyError, OSError, RuntimeError) as e:
                raise InputError(str(e)) from None
            # Reference sections use numeric intervals/loudest, never project section IDs.
            section = getattr(args, 'section', None)
            if section and section != 'loudest' and ',' not in section:
                section = None
            x, interval = section_audio(x, sr, project_root(args), section)
            out.append({'spectrum': spectrum(x, sr), 'low_crest_db': low_crest(x, sr),
                        'sha256': digest, 'section_s': interval, 'source': 'audio'})
        elif p.suffix.lower() == '.json':
            try:
                data = json.loads(p.read_text(encoding='utf-8'))
                rows = data.get('references', [data])
                for row in rows:
                    spec = row.get('spectrum', row)
                    f, power_values = arrays(spec)
                    if (spec.get('method') != METHOD or len(f) < 2 or f.ndim != 1
                            or f.shape != power_values.shape or not np.isfinite([f, power_values]).all()
                            or f[0] != 0 or np.any(np.diff(f) <= 0) or np.any(power_values < 0)
                            or not np.allclose(np.diff(f), f[1]-f[0])
                            or not np.isfinite(spec['sample_rate']) or spec['sample_rate'] <= 0):
                        raise ValueError
                    crest = row.get('low_crest_db')
                    if crest is not None and (not isinstance(crest, (int, float)) or not np.isfinite(crest)):
                        raise ValueError
                    out.append({'spectrum': spec, 'low_crest_db': crest,
                                'source': 'measurement', 'sha256': digest})
            except (ValueError, KeyError, TypeError, AttributeError):
                raise InputError('reference JSON requires a welch_active_v1 spectrum (frequencies_hz/power_density/sample_rate)') from None
        else:
            md = p.read_text(encoding='utf-8')
            vals = RS.study_values(md)
            # Existing ref compare identifies the source work and its study hash.
            if 'refsheet' in md:
                match = re.search(r'参照: `work_([a-z0-9_-]+)`', md)
                if match:
                    study = RS.work_dir(Path(args.kb), match[1])/'refstudy.md'
                    if study.is_file():
                        vals = RS.study_values(study.read_text(encoding='utf-8'))
            out.append({'values': vals, 'source': 'refstudy_digest', 'sha256': digest,
                        'note': 'Digest contains coarse aggregates, not a Welch spectrum.'})
    if not out:
        raise InputError('a nonempty user-measured reference collection is required')
    unique = {}
    for row in out:
        identity = json.dumps(clean(row.get('spectrum', row.get('values'))), sort_keys=True, allow_nan=False)
        unique.setdefault(identity, row)
    return list(unique.values())


def require_spectra(refs):
    if any('spectrum' not in r for r in refs):
        raise InputError('refstudy digest has no full Welch spectrum; supply reference audio or welch_active_v1 measurements')


def clean(value):
    """Finite, deterministically ordered JSON; preserve existing meter values.

    Python's round-trip float representation keeps PSD and existing meters
    exact. Quantizing tiny PSD values would destroy a reusable spectrum.
    """
    if isinstance(value, dict):
        return {k: clean(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [clean(v) for v in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    return value
