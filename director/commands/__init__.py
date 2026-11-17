"""Discover CLI-only direction commands and enforce their project write contract."""
from __future__ import annotations

import argparse
import hashlib
from importlib import import_module
import json
from pathlib import Path
from pkgutil import iter_modules
import re

from mankomix.core.errors import InputError

COMMANDS: list[dict] = []
_loaded = False
CLI_ONLY_REASON = "Direction layer (director/, outside the core): CLI only; MCP exposure is a separate delivery"


def declarations():
    global _loaded
    if not _loaded:
        found = []
        for module in sorted(iter_modules(__path__), key=lambda m: m.name):
            if module.name.startswith('_'):
                continue
            rows = getattr(import_module(f'{__name__}.{module.name}'), 'COMMANDS', None)
            if not isinstance(rows, list):
                raise ImportError(f'{module.name}: expected COMMANDS list')
            found.extend(rows)
        _validate([*COMMANDS, *found])
        COMMANDS.extend(found)
        _loaded = True
    return _validate(COMMANDS)


def _validate(rows):
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ImportError('command declaration must be a dict')
        path = row.get('path')
        if not isinstance(path, tuple) or not path or not all(
                isinstance(p, str) and re.fullmatch(r'[a-z][a-z0-9_-]*', p) for p in path):
            raise ImportError('command path must be a nonempty tuple of CLI names')
        if path in seen or any(path[:len(p)] == p or p[:len(path)] == path for p in seen):
            raise ImportError(f'duplicate/overlapping direction command: {path}')
        seen.add(path)
        if not isinstance(row.get('help'), str) or not callable(row.get('add_args')) or not callable(row.get('run')):
            raise ImportError(f'{path}: help, add_args and run are required')
        if row.get('writes') is not False and row.get('writes') != 'out_only':
            raise ImportError(f'{path}: writes must be False or out_only')
        if row.get('project', 'required') not in ('required', 'optional', 'none'):
            raise ImportError(f'{path}: project must be required, optional or none')
        if not isinstance(row.get('inputs', ('audio',)), tuple) or not all(
                isinstance(name, str) and name for name in row.get('inputs', ('audio',))):
            raise ImportError(f'{path}: inputs must be a tuple of argument names')
        if not isinstance(row.get('mcp_planned', '_'.join(('direction', *path))), str):
            raise ImportError(f'{path}: mcp_planned must be a string')
    return sorted(rows, key=lambda r: r['path'])


def cli_only():
    """Planned names and reasons for the existing MCP coverage tests, not MCP tools."""
    return {'direction ' + ' '.join(r['path']): (
        r.get('mcp_planned', '_'.join(('direction', *r['path']))), CLI_ONLY_REASON)
        for r in declarations()}


def _snapshot(root):
    """Include directory entries, symlinks and file hashes; no timestamps."""
    root = Path(root)
    out = {}
    def visit(p, ancestors):
        key = p.relative_to(root).as_posix()
        prefix = ()
        if p.is_symlink():
            prefix = ('link', str(p.readlink()))
            out[key] = prefix
        if p.is_file():
            h = hashlib.sha256()
            with p.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    h.update(chunk)
            out[key] = (*prefix, 'file', h.hexdigest())
        elif p.is_dir():
            out[key] = (*prefix, 'dir')
            resolved = p.resolve()
            if resolved not in ancestors:
                for child in sorted(p.iterdir()):
                    visit(child, ancestors | {resolved})
    if root.exists() or root.is_symlink():
        visit(root, set())
    return out


def execute(row, args, project):
    """Detect project writes, including on exceptions; out_only permits just --out."""
    if project is None:
        return _execute_files(row, args)
    root = Path(project).resolve()
    inputs = []
    if row.get('project', 'required') != 'required':
        for name in row.get('inputs', ('audio',)):
            value = getattr(args, name, None)
            inputs.extend(Path(p).absolute() for p in (value if isinstance(value, (list, tuple)) else [value])
                          if p is not None)
    input_before = {p: _snapshot(p) for p in inputs}
    output = None
    if row['writes'] == 'out_only' and getattr(args, 'out', None):
        output = Path(args.out).resolve()
        if any(output == p.resolve() or output in p.resolve().parents or p.resolve() in output.parents for p in inputs):
            raise InputError('--out overlaps input files')
        protected = [root / name for name in ('project.json', 'journal.jsonl', 'directions')]
        if output == root or any(output == p or output in p.parents or p in output.parents for p in protected):
            raise InputError('--out overlaps project state or the directions ledger')
        # Existing project files, including assets/cache, cannot become an output target.
        if root in output.parents and output.exists():
            raise InputError('--out must not overwrite an existing project path')
    before = _snapshot(root)
    output_parent = output.parent if output is not None and root not in output.parents else None
    outside_before = _snapshot(output_parent) if output_parent is not None else None
    try:
        result = row['run'](args)
        if not isinstance(result, dict):
            raise InputError('direction commands must return a JSON object')
        # Round-trip fixes key order and rejects nonfinite/non-JSON results.
        return json.loads(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
    finally:
        if any(_snapshot(p) != old for p, old in input_before.items()):
            raise InputError('direction command violated its input file write contract')
        after = _snapshot(root)
        changed = {key for key in before.keys() | after.keys() if before.get(key) != after.get(key)}
        if output is not None:
            changed = {key for key in changed if not (
                root / key == output or output in (root / key).parents
                or root / key in output.parents and key not in before)}
        if changed:
            raise InputError('direction command violated its write contract',
                             details={'paths': sorted(changed), 'writes': row['writes']})
        if output_parent is not None:
            outside_after = _snapshot(output_parent)
            outside_changed = {key for key in outside_before.keys() | outside_after.keys()
                               if outside_before.get(key) != outside_after.get(key)}
            outside_changed = {key for key in outside_changed if not (
                output_parent / key == output or output in (output_parent / key).parents
                or output_parent / key in output.parents and key not in outside_before)}
            if outside_changed:
                raise InputError('direction command wrote outside --out', details={'paths': sorted(outside_changed)})


def _execute_files(row, args):
    """Guard standalone inputs, cwd and input/output siblings without a project."""
    inputs = []
    for name in row.get('inputs', ('audio',)):
        value = getattr(args, name, None)
        for item in value if isinstance(value, (list, tuple)) else [value]:
            if item is not None:
                inputs.append(Path(item).absolute())
    output = (Path(args.out).resolve() if row['writes'] == 'out_only'
              and getattr(args, 'out', None) else None)
    cwd = Path.cwd().resolve()
    if output is not None and (output == cwd or any(
            output == p or output in p.parents or p in output.parents
            for p in [*(p.resolve() for p in inputs), *(cwd / n for n in ('project.json', 'journal.jsonl', 'directions'))])):
        raise InputError('--out overlaps input files or project state')
    scopes = {cwd, *(p.parent for p in inputs), *(p.resolve().parent for p in inputs)}
    if output is not None:
        # Watch the nearest existing ancestor so missing output parents cannot
        # hide sibling writes.
        parent = output.parent
        while not parent.exists() and parent != parent.parent:
            parent = parent.parent
        scopes.add(parent)
    scopes = sorted(p for p in scopes if not any(q in p.parents for q in scopes))
    before = {p: _snapshot(p) for p in scopes}
    try:
        result = row['run'](args)
        if not isinstance(result, dict):
            raise InputError('direction commands must return a JSON object')
        return json.loads(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
    finally:
        changed = set()
        for root, old in before.items():
            new = _snapshot(root)
            for key in old.keys() | new.keys():
                path = root / key
                if old.get(key) == new.get(key):
                    continue
                if output is not None and (path == output or output in path.parents
                                          or path in output.parents and key not in old):
                    continue
                changed.add(key)
        if changed:
            raise InputError('direction command violated its write contract',
                             details={'paths': sorted(changed), 'writes': row['writes']})


def _subparsers(parser):
    return next((a for a in parser._actions if isinstance(a, argparse._SubParsersAction)), None)


def register(direction_parser, common, project):
    """Register nested leaves, reusing existing groups without replacing commands."""
    branches = {}
    for row in declarations():
        parser = direction_parser
        for depth, part in enumerate(row['path']):
            action = _subparsers(parser)
            # query already accepts <audio> <spec>. Dispatch only known new names
            # to a separate parser so the old positional invocation stays intact.
            if action is None and parser.get_default('func') is not None:
                if row['path'][:depth] != ('query',):
                    raise ImportError(f'command collides with existing executable: {row["path"]}')
                if parser not in branches:
                    branch = type(parser)(prog=parser.prog, parents=[common], description=parser.description,
                                          epilog='Legacy invocation: direction query AUDIO SPEC')
                    sub = branch.add_subparsers(dest='xcommand_query', metavar='SUBCOMMAND', required=True)
                    old_parse = parser.parse_known_args

                    def dispatch(args=None, namespace=None, *, branch=branch, old=old_parse, sub=sub):
                        _, remaining = common.parse_known_args(args)
                        if remaining and remaining[0] in sub.choices or remaining == ['--help'] or args == ['--help']:
                            return branch.parse_known_args(args, namespace)
                        return old(args, namespace)

                    parser.parse_known_args = dispatch
                    branches[parser] = branch
                parser = branches[parser]
                action = _subparsers(parser)
            if action is None:
                action = parser.add_subparsers(dest=f'xcommand_{depth}', metavar='SUBCOMMAND', required=True)
            leaf = depth == len(row['path']) - 1
            if leaf:
                if part in action.choices:
                    raise ImportError(f'duplicate direction command: {row["path"]}')
                child = action.add_parser(part, parents=[common], help=row['help'], description=row['help'])
                row['add_args'](child)
                if row['writes'] == 'out_only' and not any('--out' in a.option_strings for a in child._actions):
                    raise ImportError(f'{row["path"]}: out_only requires --out')

                def run(args, row=row):
                    mode = row.get('project', 'required')
                    root = (project(args) if mode == 'required' or mode == 'optional'
                            and (getattr(args, 'project', None) or Path('project.json').is_file()) else None)
                    return execute(row, args, root)

                child.set_defaults(func=run)
            else:
                if part not in action.choices:
                    action.add_parser(part, parents=[common], help=f'direction {part} commands')
                parser = action.choices[part]
