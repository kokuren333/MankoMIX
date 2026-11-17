"""Array adapter for the existing separation worker; no project registration.

The child runs core.separation.worker's protocol unchanged. CPU startup settings
are applied in that child only; model code remains in the existing separation
layer. Temporary WAV/request/result files never enter the project.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile

import numpy as np

from mankomix.core import audio_io
from mankomix.core.errors import EnvironmentProblem, InputError, ValidationError
from mankomix.core.separation import pipeline


# This is subprocess startup code, never evaluated in the director process.
CPU_STARTUP = """import sys
import torch
torch.set_num_threads(1)
torch.set_num_interop_threads(1)
torch.manual_seed(0)
torch.use_deterministic_algorithms(True)
from mankomix.core.separation.worker import main
sys.exit(main())
"""


def run_worker(request, work):
    """Use the existing worker with fixed CPU settings and offline environment."""
    request_path = work / 'request.json'
    request_path.write_text(json.dumps(request, sort_keys=True), encoding='utf-8')
    if request['backend'] == 'mankomix_torch':
        cmd = [sys.executable, '-c', CPU_STARTUP, '--request', str(request_path)]
    else:
        cmd = [sys.executable, '-m', pipeline.WORKER_MODULE, '--request', str(request_path)]
    env = pipeline._worker_env()
    env.update({key: '1' for key in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS',
                                   'NUMEXPR_NUM_THREADS', 'TRANSFORMERS_OFFLINE')})
    env['PYTHONHASHSEED'] = '0'
    try:
        proc = subprocess.run(cmd, cwd=work, env=env, capture_output=True, text=True,
                              encoding='utf-8', errors='replace', timeout=pipeline.DEFAULT_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise EnvironmentProblem('edit_isolate could not finish the separation worker') from exc
    try:
        result = json.loads((Path(request['output_dir']) / 'result.json').read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise EnvironmentProblem('edit_isolate worker failed without a result',
                                 details={'exit_code': proc.returncode}) from exc
    if not result.get('ok'):
        cls = InputError if result.get('kind') == 'input' else EnvironmentProblem
        raise cls(f"separation failed: {result.get('error')}")
    if proc.returncode or result.get('protocol') != 1 or result.get('device') != 'cpu':
        raise EnvironmentProblem('edit_isolate requires a successful protocol-1 CPU result')
    return result


def separate_segment(x, sr, resolved):
    """Return every declared stem at the input rate/shape and stable run metadata."""
    entry = resolved['entry']
    rt = entry['runtime']
    rate = pipeline._model_rate(entry, sr)
    if np.any(x):
        try:
            gain, pre = pipeline._normalise_gain(x, sr)
        except InputError:
            # Integrated loudness is undefined below its gate or for clips
            # shorter than 400 ms. These are still valid separation inputs.
            peak = float(np.max(np.abs(x)))
            gain = min(1., 10 ** (pipeline.TARGET_PEAK_DBFS / 20) / peak)
            pre = {'gain_db': round(float(20*np.log10(gain)), 9),
                   'source_lufs': None, 'normalization': 'peak_only',
                   'reason': 'integrated_loudness_unavailable'}
    else:
        gain, pre = 1., {'gain_db': 0., 'silent': True}
    with tempfile.TemporaryDirectory(prefix='mmx_isolate_') as directory:
        work = Path(directory)
        source = pipeline._resample(x * gain, sr, rate).astype(np.float32)
        audio_io.write(work / 'input.wav', source, rate, subtype='FLOAT')
        request = {'protocol': 1, 'backend': rt['backend'], 'architecture': entry.get('architecture'),
                   'config': rt.get('config') or {},
                   'weights': {name: str(p) for name, p in resolved['paths'].items()},
                   'roles': resolved['roles'], 'input': str(work / 'input.wav'),
                   'output_dir': str(work / 'out'), 'device': 'cpu'}
        result = run_worker(request, work)
        produced = result.get('stems') or {}
        outs = {}
        for stem in entry['stems']:
            name = produced.get(stem)
            if not isinstance(name, str):
                raise EnvironmentProblem(f'separation worker did not produce {stem}')
            path = (work / 'out' / name).resolve()
            if not path.is_relative_to((work / 'out').resolve()):
                raise ValidationError('separation worker returned an invalid output path')
            y, ysr = audio_io.read(path)
            if ysr != rate or not len(y) or not np.all(np.isfinite(y)):
                raise ValidationError('separation worker returned invalid audio')
            y = pipeline._resample(y, ysr, sr) / gain
            if len(y) < len(x):
                y = np.pad(y, ((0, len(x)-len(y)), (0, 0)))
            y = y[:len(x)]
            if y.shape[1] != x.shape[1]:
                y = np.repeat(y.mean(axis=1, keepdims=True), x.shape[1], axis=1)
            outs[stem] = np.asarray(y, dtype=np.float64)
        total = sum(outs.values())
        lag = pipeline._head_offset(x, total, sr)
        if lag:
            outs = {key: pipeline._shift(value, lag) for key, value in outs.items()}
        return outs, {'provider': 'cpu', 'backend': rt['backend'], 'model_sample_rate': rate,
                      'worker_versions': result.get('versions') or {}, 'preprocess': pre,
                      'head_offset_samples': lag, 'notes': result.get('notes') or []}
