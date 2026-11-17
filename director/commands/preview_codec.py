"""Listen to the exact codec round trip used by S-02; never add an encoder."""
import hashlib
import json
from pathlib import Path
import numpy as np

from mankomix.core import audio_io, config
from mankomix.core.errors import InputError
from mankomix.core.measure import loudness as L
from mankomix.core.measure.bands import third_octave_grid
from mankomix.dsp import ffmpeg_backend as FB
from mankomix.dspx.bb import onsets
from . import _measurement as W
from .query_meters import welch_bands, db

DEFAULT_BITRATES = {'aac': 256, 'opus': 128, 'mp3': 320, 'ogg_vorbis': 160}


def add_args(parser):
    parser.add_argument('--audio')
    parser.add_argument('--codec', nargs='+', choices=tuple(DEFAULT_BITRATES))
    parser.add_argument('--bitrate-kbps', nargs='+', type=int)
    parser.add_argument('--normalize-lufs', nargs='+', default=['off'])
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--section')
    group.add_argument('--excerpt', action='append')
    parser.add_argument('--out')
    parser.add_argument('--match', choices=('on', 'off'), default='on')


def roundtrip(x, sr, codec, bitrate):
    """Same entry point and return_info flag as core.render.codec_true_peaks."""
    if not FB.available():
        return None
    return FB.encode_decode_roundtrip(x, sr, codec, f'{bitrate}k', return_info=True)


def analyze(x, decoded, sr, info):
    # S-02 already aligns its result, so re-alignment here would change the TP.
    tp, original_tp = float(L.true_peak_dbtp(decoded, sr)), float(L.true_peak_dbtp(x, sr))
    li, lo = float(L.integrated(decoded, sr)), float(L.integrated(x, sr))
    diff = decoded-x
    edges = np.array([[b.lo_hz, b.hi_hz] for b in third_octave_grid(sr)])
    original_power = welch_bands(x, sr, edges)
    decoded_power = welch_bands(decoded, sr, edges)
    active = original_power > max(float(original_power.max(initial=0))*1e-5, 1e-20)
    retained = active & (decoded_power >= original_power*.01)
    # This is an energy-retention estimate, undefined for a narrowband source.
    upper = float(edges[retained, 1].max()) if retained.sum() >= 4 else None
    events = onsets.detect_onsets(x, sr)
    pre = []
    for e in events:
        n = e['sample']
        seg = diff[max(0, n-round(.02*sr)):n]
        if len(seg):
            pre.append({'onset': e['id'], 'energy': float(np.sum(seg**2)/sr),
                        'rms_dbfs': float(db(np.mean(seg**2)))})
    return {'true_peak_dbtp': round(tp, 3), 'true_peak_raw_dbtp': tp,
            'true_peak_delta_db': tp-original_tp,
            'lufs_i': li, 'loudness_delta_lu': li-lo,
            'difference_rms_dbfs': float(db(np.mean(diff**2))),
            'difference_third_octave_dbfs': db(welch_bands(diff, sr, edges)),
            'bands_hz': edges, 'estimated_upper_hz': upper,
            'pre_echo': pre, 'roundtrip': info}, diff


def write_group(dest, signals, sr, index, identity):
    """FB2 listen-pack ordering, blind names and down-only level matching."""
    order = sorted(signals, key=lambda name: hashlib.sha256(f'{identity}:{name}'.encode()).digest())
    rows = {}
    for slot, name in enumerate(order):
        token = hashlib.sha256(f'{identity}:{slot}'.encode()).hexdigest()[:6]
        filename = f'x{index:02d}_k{slot+1}{token}.wav'
        audio_io.write(dest/filename, signals[name], sr, subtype='PCM_24')
        rows[filename] = {'member': name}
    return rows


def run(args):
    for br in args.bitrate_kbps or []:
        W.number(br, 32, 512, '--bitrate-kbps')
    norms = []
    for token in args.normalize_lufs:
        try:
            val = None if token == 'off' else float(token)
        except ValueError:
            raise InputError('--normalize-lufs requires off or a number') from None
        if val is not None:
            W.number(val, -30, -8, '--normalize-lufs')
        norms.append(val)
    standalone = args.audio and not args.project and not Path('project.json').is_file()
    p, v = (None, None) if standalone else W.project(args, preflight=not bool(args.audio))
    pid = (v or {}).get('master', {}).get('profile') or (v or {}).get('profile')
    profile = config.get_profile(pid) if pid else {}
    codecs = list(dict.fromkeys(args.codec or profile.get('codec_checks') or (list(DEFAULT_BITRATES) if standalone else [])))
    # Load once, then extract from the full context using project sections.
    fullargs = type('SourceArgs', (), dict(project=args.project, audio=args.audio, target='master', section=None))()
    full, sr, _, _, meta = W.source(fullargs)
    ranges = [W.interval(full, sr, p.root if p else None, s) for s in (args.excerpt or [args.section])]
    result = {'kind': 'direction_preview_codec', **meta, 'confidence': 'medium',
              'note': 'Same aligned S-02 round trip. Bandwidth/pre-echo are descriptive estimates.',
              'rows': [], 'files': [], 'available': False}
    dest = Path(args.out) if args.out else None
    entries, index = {}, 0
    for a, b in ranges:
        original = full[a:b]
        original_lufs = float(L.integrated(original, sr))
        for norm in norms:
            down = max(0., original_lufs-norm) if norm is not None and np.isfinite(original_lufs) else 0.
            # Distribution normalization is a playback attenuation. Encode the
            # unchanged source so S-02 TP remains exactly comparable at all targets.
            x = original
            for codec in codecs:
                for br in list(dict.fromkeys(args.bitrate_kbps or [DEFAULT_BITRATES.get(codec, 256)])):
                    row = {'codec': codec, 'bitrate_kbps': br, 'normalize_lufs': norm,
                           'normalization_down_db': down, 'range_s': [a/sr, b/sr],
                           'normalized_original_true_peak_dbtp': float(L.true_peak_dbtp(x*10**(-down/20), sr))}
                    try:
                        rt = roundtrip(x, sr, codec, br)
                    except Exception as e:
                        rt = None
                        row['reason'] = f'使えない: codec round trip failed ({type(e).__name__})'
                    if rt is None:
                        row.update(status='unavailable', confidence='low')
                        row.setdefault('reason', '使えない: encoder unavailable in the existing verification backend')
                    else:
                        decoded, rate, info = rt
                        if rate != sr or decoded.shape != x.shape:
                            raise InputError('verification round trip returned an unexpected shape/rate')
                        measures, diff = analyze(x, decoded, sr, info)
                        row.update(status='measured', confidence='medium', **measures)
                        row['normalized_decoded_true_peak_dbtp'] = float(L.true_peak_dbtp(decoded*10**(-down/20), sr))
                        row['normalized_decoded_lufs_i'] = float(L.integrated(decoded*10**(-down/20), sr))
                        result['available'] = True
                        # Same experimental flags / Opus rate handling as the existing backend.
                        enc = info.get('encoder')
                        row['encoder_arguments'] = ['-c:a', enc, '-b:a', f'{br}k']
                        if enc in FB._EXPERIMENTAL:
                            row['encoder_arguments'] += ['-strict', 'experimental']
                        if codec == 'opus' and sr not in FB._OPUS_RATES:
                            row['encoder_arguments'] += ['-ar', '48000']
                        levels = {'original': float(L.integrated(x, sr)), 'decoded': float(L.integrated(decoded, sr))}
                        gains = {name: min(0., round(min(levels.values())-value, 3))
                                 if args.match == 'on' and all(np.isfinite(list(levels.values()))) else 0.
                                 for name, value in levels.items()}
                        row['listen_gain_db'] = gains
                        if dest:
                            dest.mkdir(parents=True, exist_ok=True)
                            signals = {'original': x*10**((gains['original']-down)/20),
                                       'decoded': decoded*10**((gains['decoded']-down)/20),
                                       'difference': diff*10**(-down/20)}
                            identity = hashlib.sha256(x.tobytes()+json.dumps([codec, br, norm, a, b]).encode()).hexdigest()
                            index += 1
                            rows = write_group(dest, signals, sr, index, identity)
                            for r in rows.values():
                                r.update(codec=codec, bitrate_kbps=br, range_s=[a/sr, b/sr], normalize_lufs=norm)
                            entries.update(rows)
                    result['rows'].append(row)
    if not result['available']:
        result['reason'] = '使えるものなし'
    if entries:
        (dest/'key').mkdir(parents=True, exist_ok=True)
        (dest/'key'/'key.json').write_text(json.dumps(W.clean(entries), ensure_ascii=False, sort_keys=True, allow_nan=False)+'\n', encoding='utf-8', newline='\n')
        result['files'] = sorted([*entries, 'key/key.json'])
    return W.clean(result)


COMMANDS = [{'path': ('preview', 'codec'), 'help': 'Preview the existing verification codec round trip',
             'add_args': add_args, 'run': run, 'writes': 'out_only', 'project': 'optional'}]
