"""Atomic multi-track BB-18 plans; private registry helper, no operation declarations."""
from __future__ import annotations

import copy
import json

from mankomix.core import journal, mixrender as mr, remix
from mankomix.core.project import Project
from mankomix.core.errors import MankoError
from .. import derived as B


def tracks(row):
    return set(row.get('members', {})) if row.get('kind') == 'derived_group' else {row.get('track')}


def apply(root, doc, move, spec, bundle, *, actor):
    from . import DerivedPlan
    plans = bundle.plans
    expected = [move['target'], *(move.get('params', {}).get('group') or [])]
    if (not isinstance(plans, dict) or set(plans) != set(expected) or len(expected) != len(set(expected))
            or not all(isinstance(p, DerivedPlan) for p in plans.values())):
        raise B.DerivedError('bundle must cover target and each unique group track exactly once')
    # Individual op validators own their smaller limits; the seam supports 16 peers.
    if len(expected) > 17 or not isinstance(bundle.mapping, dict):
        raise B.DerivedError('invalid group size or mapping')
    mapping = json.loads(B._json(bundle.mapping))
    if not mapping:
        raise B.DerivedError('group requires a frozen shared mapping/cut list')
    placement = {(p.start, p.end, p.timeline_start, p.fit) for p in plans.values()}
    if len(placement) != 1 or any(p.fit != 'keep_length' for p in plans.values()):
        raise B.DerivedError('group plans must share range, placement and keep_length')
    ledger = B._ledger(root, doc['id'])
    if any(move['id'] in ledger.get(k, {}) for k in ('moves', 'derived', 'clip_edits', 'derived_groups')):
        raise B.DerivedError('move already has an edit ledger record')
    project = Project.open(root)
    for tid in expected:
        mr.find_track(project.data, tid)
    members = {}
    # All failures, including a calculator/import/core failure on a later peer,
    # compensate every preceding registration and restore the original ledger.
    with B.transaction(root, actor=actor):
        for i, tid in enumerate(expected):
            p = plans[tid]
            params = json.loads(B._json(p.params))
            if 'group_mapping' in params and params['group_mapping'] != mapping:
                raise B.DerivedError('per-track mapping differs from shared group mapping')
            params['group_mapping'] = copy.deepcopy(mapping)
            child = f"{move['id']}__g{i:02d}"
            row = B.apply(root, doc['id'], child, tid, p.start, p.end, op=move['op'], params=params,
                          code_version=spec.code_version, calculate=p.calculate, fit=p.fit,
                          timeline_start=p.timeline_start, actor=actor)
            members[tid] = {'move': child, 'key': row['key'], 'result': row['result'], 'clip': row['clip']}
        ledger = B._ledger(root, doc['id'])
        row = {'kind': 'derived_group', 'op': move['op'], 'track': move['target'], 'members': members,
               'mapping': mapping, 'mapping_sha256': B._hash(mapping), 'status': 'applied',
               'owner': 'director', 'move_ref': f"{doc['id']}/{move['id']}",
               'details': json.loads(B._json(bundle.record))}
        project = Project.open(root)
        data = copy.deepcopy(project.data)
        for tid, member in members.items():
            child = ledger['derived'][member['move']]
            child.update(group=move['id'], owner='director', move_ref=row['move_ref'])
            track = mr.find_track(data, tid)
            clip = next(c for c in track['clips'] if c['id'] == member['clip'])
            clip.update(owner='director', move_ref=row['move_ref'])
            child['after_clips'] = copy.deepcopy(track['clips'])
        remix._commit(project, data, actor=actor, op='derived_group_trace',
                      reason=f"direction {doc['id']} move {move['id']}: group ownership")
        ledger.setdefault('derived_groups', {})[move['id']] = row
        B._save(B._path(root, doc['id']), ledger)
    return row


def revert(root, direction, move, *, actor):
    ledger = B._ledger(root, direction)
    row = ledger['derived_groups'][move]
    project = Project.open(root)
    data = copy.deepcopy(project.data)
    for tid, member in row['members'].items():
        child = ledger['derived'][member['move']]
        track = mr.find_track(data, tid)
        if child['status'] != 'applied' or track['clips'] != child['after_clips']:
            raise B.DerivedError(f'{move}: group clip layout changed; revert later moves first')
        track['clips'] = copy.deepcopy(child['source']['clips'])
    remix._refresh_unused(data)
    # One patch for all members: validation/staleness cannot partially revert.
    seq = remix._commit(project, data, actor=actor, op='derived_group_revert',
                        reason=f'direction {direction} move {move}: revert group')
    row.update(status='reverted', reverted_journal_seq=seq)
    for member in row['members'].values():
        ledger['derived'][member['move']].update(status='reverted', reverted_journal_seq=seq)
    B._save(B._path(root, direction), ledger)


def check(root, direction, move, recorded):
    try:
        ledger = B._ledger(root, direction)
        row = ledger['derived_groups'][move]
        if (row['status'] != 'applied' or row['members'] != recorded['members']
                or row['mapping'] != recorded['mapping'] or B._hash(row['mapping']) != row['mapping_sha256']
                or row['mapping_sha256'] != recorded['mapping_sha256']
                or row.get('owner') != 'director' or row.get('move_ref') != f'{direction}/{move}'):
            return False
        p = Project.open(root)
        for tid, member in row['members'].items():
            child = ledger['derived'][member['move']]
            B._verify_sources(p, child['source'])
            asset = p.asset(member['result']['asset'])
            if (child['status'] != 'applied' or child['group'] != move or child['track'] != tid
                    or child.get('owner') != 'director' or child.get('move_ref') != row['move_ref']
                    or child['key'] != member['key'] or child['result'] != member['result']
                    or child['params'].get('group_mapping') != row['mapping']
                    or asset['sha256'] != member['result']['sha256']
                    or B.sha256_file(p.asset_path(asset['id'])) != asset['sha256']):
                return False
            # Later edits can split/mute this clip. The recipe/hash remains traced.
            if not any(c.get('asset') == asset['id'] and c.get('owner') == 'director'
                       and c.get('move_ref') == row['move_ref'] for c in mr.find_track(p.data, tid)['clips']):
                return False
        return True
    except (KeyError, ValueError, OSError, MankoError):
        return False


def regenerate(root, direction, move, *, calculators=None):
    row = B._ledger(root, direction).get('derived_groups', {}).get(move)
    if row is None:
        raise B.DerivedError('unknown derived group')
    return {tid: B.regenerate(root, direction, member['move'], calculate=(calculators or {}).get(tid))
            for tid, member in row['members'].items()}
