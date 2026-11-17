"""Read-only mix plans and apply-time registration via the existing core APIs."""
from __future__ import annotations

import copy
import hashlib
import io
import json
from pathlib import Path

import numpy as np

from mankomix.core import audio_io, mixrender as mr, remix
from mankomix.core.project import Project
from mankomix.core.errors import MankoError
from .. import derived as B


def _name(value):
    B._identifier(value)
    return value


def audio_bytes(x, frames, rate):
    carrier = np.zeros((frames, x.shape[1]), dtype=np.float64)
    carrier[:len(x)] = x
    stream = io.BytesIO()
    with audio_io.sf.SoundFile(stream, 'w', rate, x.shape[1], subtype='DOUBLE', format='WAV') as f:
        audio_io._no_peak_chunk(f)
        f.write(carrier)
    return stream.getvalue()


def prepare(project, doc_id, move, result):
    """Materialize finite data in memory. Return pending data and public hashes/IDs."""
    from . import AudioPlan, ControlPlan, NodePlan
    ref = f"{doc_id}/{move['id']}"
    pending = {'nodes': None, 'controls': {}}
    for plan in result.controls:
        if not isinstance(plan, ControlPlan) or plan.name in pending['controls']:
            raise B.DerivedError('controls must have unique local names')
        _name(plan.name)
        pending['controls'][plan.name] = B.prepare_control(
            project.root, track=plan.track, start=plan.start, end=plan.end, op=move['op'],
            params=plan.params, code_version=plan.code_version, calculate=plan.calculate)
    public = {}
    if pending['controls']:
        public['controls'] = {name: {k: copy.deepcopy(v) for k, v in entry.items() if k != 'payload'}
                              for name, entry in pending['controls'].items()}
    if result.nodes is not None:
        plan = result.nodes
        if not isinstance(plan, NodePlan) or not plan.tracks or not plan.assets:
            raise B.DerivedError('nodes must be a NodePlan with new tracks and audio assets')
        frames = mr.timeline_length(project.data, project.rate)
        assets, tracks, clips = {}, {}, []
        for a in plan.assets:
            if not isinstance(a, AudioPlan) or a.name in assets:
                raise B.DerivedError('audio plans must have unique local names')
            _name(a.name)
            x = np.asarray(a.audio, dtype=np.float64)
            if (x.ndim != 2 or x.shape[1] not in (1, 2) or not 0 < len(x) <= frames
                    or not np.isfinite(x).all() or type(a.sample_rate) is not int or a.sample_rate != project.rate
                    or not isinstance(a.params, dict) or not a.code_version):
                raise B.DerivedError('node audio must be finite project-rate mono/stereo within the timeline')
            for source in a.sources:
                B._verify_sources(Project.open(project.root), {'assets': [source]})
            source = {'assets': a.sources, 'audio_sha256': B._audio_hash(x), 'frames': len(x)}
            key = B.cache_key(source, move['op'], a.params, a.code_version, kind='node_audio',
                              sample_rate=project.rate, carrier_frames=frames)
            # Full-timeline carriers avoid manufacturing short-source ingest exceptions.
            content = audio_bytes(x, frames, project.rate)
            assets[a.name] = {'key': key, 'sha256': hashlib.sha256(content).hexdigest(), 'content': content,
                              'source': source, 'params': json.loads(B._json(a.params)),
                              'code_version': a.code_version, 'frames': len(x),
                              'sample_rate': project.rate, 'carrier_frames': frames}
        for t in plan.tracks:
            name = _name(t.get('name'))
            if name in tracks or set(t) - {'name', 'role', 'output'}:
                raise B.DerivedError('new tracks need unique names, role and output only')
            if t.get('output') not in project.buses():
                raise B.DerivedError('new track output must be an existing bus')
            tid = 'trk_x' + B._hash({'ref': ref, 'name': name})[:20]
            if tid in project.tracks():
                raise B.DerivedError('planned track ID already exists')
            tracks[name] = {'id': tid, 'name': name, 'kind': 'audio', 'role': t['role'], 'is_lead': False,
                            'output': t['output'], 'clips': [], 'chain': [], 'sends': [], 'gain_db': 0.0,
                            'owner': 'director', 'move_ref': ref}
        for i, c in enumerate(plan.clips):
            if (not isinstance(c, dict) or set(c) - {'track', 'asset', 'timeline_start', 'source_start',
                                                     'length', 'gain_db', 'fade_in', 'fade_out'}):
                raise B.DerivedError('invalid node clip fields')
            t, a = tracks[c['track']], assets[c['asset']]
            start = B._sample(c['timeline_start'], 'timeline_start')
            ss = B._sample(c.get('source_start', 0), 'source_start')
            length = B._sample(c['length'], 'length')
            if not length or start + length > frames or ss + length > a['frames']:
                raise B.DerivedError('node clip leaves source audio or existing timeline')
            clip = {'id': 'clp_x' + B._hash({'ref': ref, 'clip': i})[:20], 'asset': c['asset'],
                    'source_start': ss, 'timeline_start': start, 'length': length,
                    'gain_db': c.get('gain_db', 0.0), 'fade_in': c.get('fade_in', 0),
                    'fade_out': c.get('fade_out', 0), 'muted': False, 'owner': 'director', 'move_ref': ref}
            t['clips'].append(clip)
            clips.append(clip['id'])
        if not clips:
            raise B.DerivedError('node plan needs at least one clip')
        public['nodes'] = {'tracks': [t['id'] for t in tracks.values()], 'clips': clips,
                           'assets': {name: {k: v for k, v in a.items() if k != 'content'} for name, a in assets.items()}}
        pending['nodes'] = {'assets': assets, 'tracks': tracks, 'frames': frames}
    if public:
        pending['target'] = move['target']
        pending['automation_before'] = copy.deepcopy(project.tracks().get(move['target'], {}).get('automation'))
    return pending, public


def chain(result, pending):
    """Replace only explicit control-name references; ordinary parameter values stay intact."""
    def replace(value):
        if isinstance(value, dict):
            if set(value) == {'control'}:
                return pending['controls'][value['control']]['result']['asset']
            return {k: replace(v) for k, v in value.items()}
        if isinstance(value, list):
            return [replace(v) for v in value]
        return value
    return replace(copy.deepcopy(result.chain))


def planned_controls(pending):
    return {entry['result']['asset']: entry['payload'] for entry in pending['controls'].values()}


def apply(root, doc, move, pending, *, actor):
    """Register all resources of one move, compensating partial core failures."""
    root = Path(root)
    with B.transaction(root, actor=actor):
        for name, entry in pending['controls'].items():
            B.apply_control(root, doc['id'], move['id'], name, entry, actor=actor)
        nodes = pending['nodes']
        if nodes is not None:
            ledger = B._ledger(root, doc['id'])
            if move['id'] in ledger.get('nodes', {}):
                raise B.DerivedError('move already has node resources')
            assets, added_assets = {}, []
            for name, a in nodes['assets'].items():
                project = Project.open(root)
                for source in a['source']['assets']:
                    B._verify_sources(project, {'assets': [source]})
                path = root / 'cache' / 'derived' / f"{a['key']}.node.wav"
                if path.is_file() and B.sha256_file(path) != a['sha256']:
                    raise B.DerivedError('node cache sha256 mismatch')
                path.parent.mkdir(parents=True, exist_ok=True)
                if not path.is_file():
                    path.write_bytes(a['content'])
                old = next((v for v in project.data['assets'] if v['sha256'] == a['sha256']), None)
                if old:
                    dest = project.asset_path(old['id'])
                    if not dest.is_file() and not old.get('linked'):
                        B._restore(path, dest, a['sha256'])
                    if B.sha256_file(dest) != a['sha256']:
                        raise B.DerivedError('node registered asset sha256 mismatch')
                    assets[name] = old['id']
                    continue
                staged, rec, asset = remix._stage_import(project, path, role='other', mode='copy', actor=actor)
                imported = set(rec.get('tracks_added') or [])
                staged['tracks'] = [t for t in staged['tracks'] if t['id'] not in imported]
                if staged['timebase']['length_samples'] != nodes['frames']:
                    raise B.DerivedError('node import would extend timeline')
                asset.update(owner='director', move_ref=f"{doc['id']}/{move['id']}")
                remix._refresh_unused(staged)
                remix._commit(project, staged, actor=actor, op='direction_node_import',
                              reason=f"direction {doc['id']} move {move['id']}: node audio")
                assets[name] = asset['id']
                added_assets.append(asset['id'])
            project = Project.open(root)
            data = copy.deepcopy(project.data)
            tracks = copy.deepcopy(list(nodes['tracks'].values()))
            for t in tracks:
                for c in t['clips']:
                    c['asset'] = assets[c['asset']]
                t['clips'].sort(key=lambda c: (c['timeline_start'], c['id']))
            data['tracks'].extend(tracks)
            remix._refresh_unused(data)
            seq = remix._commit(project, data, actor=actor, op='direction_node_place',
                                reason=f"direction {doc['id']} move {move['id']}: additive clips")
            # Re-read after control saves/imports; don't overwrite their ledger rows.
            ledger = B._ledger(root, doc['id'])
            row = {'kind': 'nodes', 'op': move['op'], 'owner': 'director',
                   'move_ref': f"{doc['id']}/{move['id']}", 'status': 'applied', 'tracks': tracks,
                   'assets': {name: {**{k: v for k, v in a.items() if k != 'content'}, 'asset': assets[name]}
                              for name, a in nodes['assets'].items()},
                   'added_assets': added_assets, 'journal_seq': seq}
            ledger.setdefault('nodes', {})[move['id']] = row
            ledger['reverted'] = False
            B._save(B._path(root, doc['id']), ledger)
        ledger = B._ledger(root, doc['id'])
        ledger.setdefault('resource_targets', {})[move['id']] = {
            'track': pending['target'], 'automation_before': pending['automation_before']}
        B._save(B._path(root, doc['id']), ledger)


def check(root, direction, move, resources):
    try:
        ledger = B._ledger(root, direction)
        project = Project.open(root)
        for name, recorded in resources.get('controls', {}).items():
            row = ledger['controls'][f'{move}__{name}']
            if (row['status'] != 'applied' or row.get('owner') != 'director' or row['move_ref'] != f'{direction}/{move}'
                    or any(row.get(k) != v for k, v in recorded.items())):
                return False
            with B.control_context(root):
                B.resolve_control(row['result']['asset'])
            B._verify_sources(project, row['source'])
        if 'nodes' in resources:
            row = ledger['nodes'][move]
            if row['status'] != 'applied' or row.get('owner') != 'director' or row['move_ref'] != f'{direction}/{move}':
                return False
            if [t['id'] for t in row['tracks']] != resources['nodes']['tracks']:
                return False
            for t in row['tracks']:
                actual = mr.find_track(project.data, t['id'])
                if any(actual.get(k) != t.get(k) for k in ('role', 'output', 'clips', 'owner', 'move_ref')):
                    return False
            for name, a in row['assets'].items():
                if a['sha256'] != resources['nodes']['assets'][name]['sha256']:
                    return False
                if B.sha256_file(project.asset_path(a['asset'])) != a['sha256']:
                    return False
                B._verify_sources(project, a['source'])
                if a['asset'] in row['added_assets']:
                    asset = project.asset(a['asset'])
                    if asset.get('owner') != 'director' or asset.get('move_ref') != f'{direction}/{move}':
                        return False
        return True
    except (KeyError, ValueError, OSError, LookupError, MankoError):
        return False


def revert(root, direction, move=None, *, actor='human'):
    """Remove node placements/owned chain references; retain reusable audio/control caches."""
    ledger = B._ledger(root, direction)
    selected_nodes = {mid: row for mid, row in ledger.get('nodes', {}).items()
                      if row['status'] == 'applied' and (move is None or mid == move)}
    controls = {key: row for key, row in ledger.get('controls', {}).items()
                if row['status'] == 'applied' and (move is None or row['move_ref'] == f'{direction}/{move}')}
    refs = {f'{direction}/{mid}' for mid in selected_nodes} | {r['move_ref'] for r in controls.values()}
    if not refs:
        return []
    project = Project.open(root)
    data = copy.deepcopy(project.data)
    tids = set()
    for row in selected_nodes.values():
        for expected in row['tracks']:
            actual = mr.find_track(data, expected['id'])
            if actual != expected:
                raise B.DerivedError('node track changed; restore later changes before revert')
            tids.add(expected['id'])
    data['tracks'] = [t for t in data['tracks'] if t['id'] not in tids]
    for holder in [*data['tracks'], *data.get('buses', [])]:
        if holder.get('output') in tids or any(s.get('bus') in tids for s in holder.get('sends', [])):
            raise B.DerivedError('node track has foreign routing dependencies')
        if 'chain' in holder:
            holder['chain'] = [item for item in holder['chain'] if not (
                item.get('owner') == 'director' and item.get('move_ref') in refs)]
        auto = holder.get('automation') or {}
        auto_refs = auto.get('move_ref') or []
        auto_refs = auto_refs if isinstance(auto_refs, list) else [auto_refs]
        if refs.intersection(auto_refs):
            # A composed curve cannot be partially restored without changing
            # another move. Refuse before the one commit instead of guessing.
            if set(auto_refs) - refs:
                raise B.DerivedError('resource automation shares later moves; revert their dependencies first')
            before = next(ledger['resource_targets'][r.split('/', 1)[1]]['automation_before']
                          for r in auto_refs if r in refs)
            if before is None:
                holder.pop('automation', None)
            else:
                holder['automation'] = copy.deepcopy(before)
    remix._refresh_unused(data)
    seq = remix._commit(project, data, actor=actor, op='direction_resource_revert',
                        reason=f'direction {direction}: revert mix resources')
    for row in [*selected_nodes.values(), *controls.values()]:
        row.update(status='reverted', reverted_journal_seq=seq)
    ledger['reverted'] = not any(row.get('status') == 'applied'
                                 for kind in ('moves', 'derived', 'clip_edits', 'derived_groups', 'nodes', 'controls')
                                 for row in ledger.get(kind, {}).values())
    B._save(B._path(root, direction), ledger)
    return sorted({r.split('/', 1)[1] for r in refs})


def regenerate(root, direction, move, name, *, audio=None):
    root = Path(root)
    a = B._ledger(root, direction).get('nodes', {}).get(move, {}).get('assets', {}).get(name)
    if a is None:
        raise B.DerivedError('unknown node audio recipe')
    project = Project.open(root)
    asset = project.asset(a['asset'])
    if asset['sha256'] != a['sha256'] or asset.get('linked'):
        raise B.DerivedError('registered node asset changed')
    dest = project.asset_path(asset['id'])
    if dest.is_file():
        if B.sha256_file(dest) != a['sha256']:
            raise B.DerivedError('registered node sha256 mismatch')
        return {'asset': asset['id'], 'sha256': a['sha256'], 'regenerated': False}
    cache = root / 'cache' / 'derived' / f"{a['key']}.node.wav"
    if cache.is_file():
        if B.sha256_file(cache) != a['sha256']:
            raise B.DerivedError('node cache sha256 mismatch')
    else:
        if audio is None:
            raise B.DerivedError(f"audio required at version {a['code_version']}")
        B._verify_sources(project, a['source'])
        x = np.asarray(audio, dtype=np.float64)
        if (x.ndim != 2 or len(x) != a['frames'] or not np.isfinite(x).all()
                or B._audio_hash(x) != a['source']['audio_sha256']):
            raise B.DerivedError('regenerated node audio differs from recipe')
        content = audio_bytes(x, a['carrier_frames'], a['sample_rate'])
        if hashlib.sha256(content).hexdigest() != a['sha256']:
            raise B.DerivedError('regenerated node sha256 differs from ledger')
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(content)
    B._restore(cache, dest, a['sha256'])
    return {'asset': asset['id'], 'sha256': a['sha256'], 'regenerated': True}
