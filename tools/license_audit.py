#!/usr/bin/env python3
"""Dependency license audit (docs/SPEC.md sections 13 and 16.4).

Checks, in one run:

1. Python dependencies: the installed closure of the core runtime
   (``project.dependencies`` in pyproject.toml) and, separately, of each extra
   (``project.optional-dependencies``). Every distribution's license is read
   from its metadata (License-Expression, License, classifiers), normalised to
   SPDX ids and judged against the allowlist. Human-verified records in
   ``tools/license_exceptions.json`` override the metadata. License files that
   contain GPL/LGPL/AGPL text must have a reviewed record there too.
2. Forbidden imports (D-057, D-060): an AST scan of core/, dsp/, cli/, mcp/
   for librosa, soxr, torch and the other modules that must never be loaded in
   the core process. The separation worker (core/separation/worker.py and
   core/separation/archs*) may import the inference stack because it runs in
   its own subprocess; nothing else may import those worker-side modules.
3. npm dependencies of gui/ (production and development), from
   gui/package-lock.json, or gui/node_modules when there is no lock file.
4. third_party/: every folder has LICENSE and ORIGIN.md, the license text is
   one of the allowed licenses, and the folder is listed in the README.
5. The model registry (registry/models.json): core.registry's catalogue rules
   plus the license fields of official entries (weights license, evidence
   URLs, usage_restrictions == "none").
6. FFmpeg is never bundled: no ffmpeg/ffprobe executables or libav* shared
   libraries in the source tree.

Usage:
    python -I tools/license_audit.py              summary on stdout
    python -I tools/license_audit.py --markdown   full Markdown report on stdout
    python -I tools/license_audit.py --json       full result as JSON on stdout
    python -I tools/license_audit.py --write      also write docs/LICENSES_THIRD_PARTY.md
Options:
    --require-extras   fail (instead of warn) when an extra is not installed
    --no-npm           skip the npm part

Exit code 0 when nothing failed (flags are allowed), 1 otherwise. Only
repository-relative paths are printed. Standard library only (the registry
check imports core.registry, which needs the core dependencies installed).
"""

from __future__ import annotations

import argparse
import ast
import importlib.metadata as md
import json
import os
import platform
import re
import sys
import tomllib
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = "docs/LICENSES_THIRD_PARTY.md"
EXCEPTIONS_PATH = "tools/license_exceptions.json"

OK, FLAG, FAIL = "ok", "flag", "fail"
_RANK = {OK: 0, FLAG: 1, FAIL: 2}

# --- license policy -----------------------------------------------------------------

# Permissive licenses accepted everywhere (SPEC 13.1 plus the usual Python ones).
ALLOWED = {
    "MIT", "MIT-0", "BSD-2-Clause", "BSD-3-Clause", "BSD", "ISC", "Apache-2.0",
    "PSF-2.0", "Python-2.0", "Unlicense", "0BSD", "HPND",
}
# Accepted with a visible flag. MPL-2.0 is file-level copyleft: acceptable for
# unmodified use outside the core runtime only.
FLAGGED = {
    "MPL-2.0": "file-level copyleft; acceptable only for unmodified use outside the core runtime",
    "CC0-1.0": "public-domain dedication; acceptable for data-only content",
    "CC-BY-4.0": "attribution license for data; acceptable for data-only packages",
    "BlueOak-1.0.0": "permissive, outside the base allowlist",
    "Zlib": "permissive, outside the base allowlist",
    "BSL-1.0": "permissive, outside the base allowlist",
}
COPYLEFT_PREFIXES = ("GPL", "AGPL", "LGPL")

# Free-text license names -> SPDX ids (keys are lower-case, whitespace-collapsed).
_ALIASES = {
    "mit": "MIT", "mit license": "MIT", "the mit license": "MIT", "mit licence": "MIT",
    "the mit license (mit)": "MIT", "expat": "MIT", "expat license": "MIT",
    "mit-0": "MIT-0", "mit no attribution": "MIT-0",
    "bsd": "BSD", "bsd license": "BSD", "bsd licence": "BSD",
    "bsd-2-clause": "BSD-2-Clause", "bsd 2-clause": "BSD-2-Clause", "bsd 2-clause license": "BSD-2-Clause",
    "2-clause bsd": "BSD-2-Clause", "2-clause bsd license": "BSD-2-Clause", "simplified bsd": "BSD-2-Clause",
    "freebsd": "BSD-2-Clause",
    "bsd-3-clause": "BSD-3-Clause", "bsd 3-clause": "BSD-3-Clause", "bsd 3-clause license": "BSD-3-Clause",
    "3-clause bsd": "BSD-3-Clause", "3-clause bsd license": "BSD-3-Clause", "new bsd": "BSD-3-Clause",
    "new bsd license": "BSD-3-Clause", "modified bsd": "BSD-3-Clause", "modified bsd license": "BSD-3-Clause",
    "bsd-3": "BSD-3-Clause",
    "apache-2.0": "Apache-2.0", "apache 2.0": "Apache-2.0", "apache 2": "Apache-2.0",
    "apache license 2.0": "Apache-2.0", "apache license, version 2.0": "Apache-2.0",
    "apache license version 2.0": "Apache-2.0", "apache software license": "Apache-2.0",
    "apache software license 2.0": "Apache-2.0", "apache license": "Apache-2.0", "asl 2.0": "Apache-2.0",
    "apache-2": "Apache-2.0", "apache2": "Apache-2.0",
    "isc": "ISC", "isc license": "ISC", "isc license (iscl)": "ISC", "iscl": "ISC",
    "psf": "PSF-2.0", "psf-2.0": "PSF-2.0", "psfl": "PSF-2.0", "python software foundation license": "PSF-2.0",
    "python-2.0": "Python-2.0",
    "mpl-2.0": "MPL-2.0", "mpl 2.0": "MPL-2.0", "mozilla public license 2.0": "MPL-2.0",
    "mozilla public license 2.0 (mpl 2.0)": "MPL-2.0",
    "unlicense": "Unlicense", "the unlicense": "Unlicense",
    "0bsd": "0BSD", "hpnd": "HPND",
    "cc0-1.0": "CC0-1.0", "cc0": "CC0-1.0", "cc-by-4.0": "CC-BY-4.0",
    "blueoak-1.0.0": "BlueOak-1.0.0", "zlib": "Zlib", "zlib license": "Zlib", "bsl-1.0": "BSL-1.0",
}

# Trove classifiers -> SPDX ids.
_CLASSIFIERS = {
    "MIT License": "MIT", "MIT No Attribution License (MIT-0)": "MIT-0",
    "BSD License": "BSD", "Apache Software License": "Apache-2.0",
    "ISC License (ISCL)": "ISC", "Python Software Foundation License": "PSF-2.0",
    "Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0", "The Unlicense (Unlicense)": "Unlicense",
    "Historical Permission Notice and Disclaimer (HPND)": "HPND", "zlib/libpng License": "Zlib",
    "Boost Software License 1.0 (BSL-1.0)": "BSL-1.0", "MIT-0": "MIT-0",
}


def _canonical_id(token: str) -> str | None:
    """Map one license name to an SPDX-ish id, or None when unrecognised."""
    t = " ".join(token.strip().split())
    if not t:
        return None
    low = t.lower()
    if low in _ALIASES:
        return _ALIASES[low]
    for spdx in ALLOWED | set(FLAGGED):
        if low == spdx.lower():
            return spdx
    # GNU family: keep the family and the version when present.
    m = re.match(r"^(?:gnu\s+)?(affero|lesser|library)?\s*(?:general public license|gpl)\s*v?(\d(?:\.\d)?)?", low)
    fam = None
    if re.match(r"^(a|l)?gpl", low):
        fam = {"a": "AGPL", "l": "LGPL"}.get(low[0], "GPL")
        ver = re.search(r"(\d(?:\.\d)?)", low)
        return f"{fam}-{ver.group(1)}" if ver else fam
    if m and ("general public license" in low):
        fam = {"affero": "AGPL", "lesser": "LGPL", "library": "LGPL"}.get(m.group(1) or "", "GPL")
        return f"{fam}-{m.group(2)}" if m.group(2) else fam
    if low.startswith("licenseref-"):
        return t
    return None


# --- SPDX expression parsing and evaluation -----------------------------------------------

_EXPR_SPLIT = re.compile(r"(\(|\)|\s+AND\s+|\s+OR\s+|\s+and\s+|\s+or\s+|\s+WITH\s+)")


def parse_expression(text: str) -> Any:
    """Parse a license expression into a tree.

    Leaves are ("id", spdx_or_None, raw[, with_exception]); inner nodes are
    ("and"|"or", [children]). Free-text names with spaces are allowed as
    leaves ("Apache 2.0 or MIT"). Raises ValueError on malformed input.
    """
    parts = [p for p in _EXPR_SPLIT.split(text.strip()) if p is not None and p.strip() != ""]
    tokens = []
    for p in parts:
        s = p.strip()
        if s.upper() in ("AND", "OR", "WITH") and p != s or s in ("(", ")"):
            tokens.append(s.upper() if s not in ("(", ")") else s)
        elif s.upper() in ("AND", "OR", "WITH"):
            tokens.append(s.upper())
        else:
            tokens.append(("leaf", s))
    pos = 0

    def peek():
        return tokens[pos] if pos < len(tokens) else None

    def take():
        nonlocal pos
        tok = tokens[pos]
        pos += 1
        return tok

    def atom():
        tok = peek()
        if tok == "(":
            take()
            node = or_expr()
            if peek() != ")":
                raise ValueError("unbalanced parentheses")
            take()
            return node
        if isinstance(tok, tuple):
            take()
            raw = tok[1]
            leaf = ("id", _canonical_id(raw), raw)
            if peek() == "WITH":
                take()
                exc = take()
                if not isinstance(exc, tuple):
                    raise ValueError("WITH without exception id")
                leaf = ("id", leaf[1], raw, exc[1])
            return leaf
        raise ValueError(f"unexpected token {tok!r}")

    def and_expr():
        items = [atom()]
        while peek() == "AND":
            take()
            items.append(atom())
        return items[0] if len(items) == 1 else ("and", items)

    def or_expr():
        items = [and_expr()]
        while peek() == "OR":
            take()
            items.append(and_expr())
        return items[0] if len(items) == 1 else ("or", items)

    if not tokens:
        raise ValueError("empty expression")
    tree = or_expr()
    if pos != len(tokens):
        raise ValueError("trailing tokens")
    return tree


def expression_text(tree: Any) -> str:
    if tree[0] == "id":
        base = tree[1] or f"?{tree[2]}"
        return f"{base} WITH {tree[3]}" if len(tree) > 3 else base
    joiner = " AND " if tree[0] == "and" else " OR "
    return joiner.join(expression_text(c) if c[0] == "id" else f"({expression_text(c)})" for c in tree[1])


def tree_complete(tree: Any) -> bool:
    if tree[0] == "id":
        return tree[1] is not None
    return all(tree_complete(c) for c in tree[1])


def classify_id(spdx: str | None, context: str, *, external_process: bool = False) -> tuple[str, str]:
    """Status and reason for one license id. context: core | extra | npm | model."""
    if spdx is None:
        return FAIL, "unrecognised license"
    if spdx in ALLOWED:
        return OK, ""
    if spdx == "MPL-2.0" and context == "core":
        return FAIL, "MPL-2.0 is not accepted in the core runtime"
    if spdx in FLAGGED:
        return FLAG, FLAGGED[spdx]
    if spdx.startswith("LGPL"):
        if external_process:
            return FLAG, "LGPL, used only as an external process (recorded exception)"
        return FAIL, "LGPL is only allowed as an external process (SPEC 13.1)"
    if spdx.startswith(COPYLEFT_PREFIXES):
        return FAIL, f"{spdx} is not allowed (SPEC 13.1)"
    return FAIL, f"{spdx} is not on the allowlist"


def evaluate(tree: Any, context: str, *, external_process: bool = False) -> tuple[str, str]:
    """AND takes the worst branch, OR the best one."""
    if tree[0] == "id":
        return classify_id(tree[1], context, external_process=external_process)
    results = [evaluate(c, context, external_process=external_process) for c in tree[1]]
    pick = max if tree[0] == "and" else min
    status = pick(r[0] for r in results)
    reasons = sorted({r[1] for r in results if r[0] == status and r[1]})
    return status, "; ".join(reasons)


def normalise_license(text: str | None) -> tuple[Any | None, str]:
    """Parse a free-text or SPDX license string. Returns (tree or None, normalised text)."""
    if not text or not text.strip():
        return None, ""
    one_line = " ".join(text.split())
    if len(one_line) > 200:  # a full license text pasted into the License field
        return None, ""
    try:
        tree = parse_expression(one_line)
    except ValueError:
        return None, ""
    if not tree_complete(tree):
        return None, expression_text(tree)
    return tree, expression_text(tree)


def _identify_text(text: str) -> str | None:
    """Recognise a license from its full text (only the common permissive ones)."""
    low = " ".join(text.lower().split())
    if "apache license" in low and "version 2.0" in low:
        return "Apache-2.0"
    if "permission is hereby granted, free of charge" in low:
        return "MIT"
    if "permission to use, copy, modify, and/or distribute this software for any purpose" in low:
        return "ISC"
    if "redistribution and use in source and binary forms" in low:
        return "BSD-3-Clause" if "neither the name" in low or "names of its contributors" in low else "BSD-2-Clause"
    return None


def license_from_metadata(meta: Any) -> dict:
    """Pick the best license statement from distribution metadata."""
    expr = meta.get("License-Expression")
    raw_license = meta.get("License") or ""
    classifiers = [c.split("::")[-1].strip() for c in (meta.get_all("Classifier") or [])
                   if c.startswith("License ::")]
    if expr:
        tree, text = normalise_license(expr)
        return {"source": "License-Expression", "raw": expr, "tree": tree, "expression": text or expr}
    tree, text = normalise_license(raw_license)
    if tree is not None:
        return {"source": "License", "raw": raw_license, "tree": tree, "expression": text}
    ids = [_CLASSIFIERS.get(c) or _canonical_id(c) for c in classifiers if c != "OSI Approved"]
    ids = [i for i in ids if i]
    if ids:
        uniq = sorted(set(ids))
        tree = ("id", uniq[0], uniq[0]) if len(uniq) == 1 else ("or", [("id", i, i) for i in uniq])
        return {"source": "classifier", "raw": "; ".join(classifiers), "tree": tree, "expression": expression_text(tree)}
    if raw_license and len(raw_license) > 200:
        found = _identify_text(raw_license)
        if found:
            return {"source": "License (full text)", "raw": raw_license[:60] + "...", "tree": ("id", found, found),
                    "expression": found}
    return {"source": "none", "raw": (raw_license or "")[:80], "tree": None, "expression": "UNKNOWN"}


# --- environment markers and requirements (PEP 508 subset, stdlib only) -----------------

_MARKER_TOKEN = re.compile(
    r"\s*(\(|\)|===|==|!=|<=|>=|~=|<|>|not\s+in\b|in\b|and\b|or\b|'[^']*'|\"[^\"]*\"|[A-Za-z_][A-Za-z0-9_.]*)"
)
_VERSION_VARS = {"python_version", "python_full_version", "implementation_version"}


def marker_environment() -> dict[str, str]:
    impl = sys.implementation
    iv = impl.version
    impl_version = f"{iv.major}.{iv.minor}.{iv.micro}"
    if iv.releaselevel != "final":
        impl_version += iv.releaselevel[0] + str(iv.serial)
    return {
        "os_name": os.name,
        "sys_platform": sys.platform,
        "platform_machine": platform.machine(),
        "platform_python_implementation": platform.python_implementation(),
        "platform_release": platform.release(),
        "platform_system": platform.system(),
        "platform_version": platform.version(),
        "python_version": ".".join(platform.python_version_tuple()[:2]),
        "python_full_version": platform.python_version(),
        "implementation_name": impl.name,
        "implementation_version": impl_version,
        "extra": "",
    }


def _vtuple(v: str) -> tuple[int, ...]:
    out = []
    for part in v.split("."):
        m = re.match(r"\d+", part)
        if not m:
            break
        out.append(int(m.group(0)))
    return tuple(out)


def _compare(left: str, op: str, right: str, version: bool) -> bool:
    if op == "in":
        return left in right
    if op == "not in":
        return left not in right
    if op == "===":
        return left == right
    if version or op in ("<", "<=", ">", ">=", "~="):
        if right.endswith(".*") and op in ("==", "!="):
            prefix = _vtuple(right[:-2])
            hit = _vtuple(left)[: len(prefix)] == prefix
            return hit if op == "==" else not hit
        a, b = _vtuple(left), _vtuple(right)
        n = max(len(a), len(b))
        a, b = a + (0,) * (n - len(a)), b + (0,) * (n - len(b))
        if op == "~=":
            rb = _vtuple(right)
            return a >= b and _vtuple(left)[: max(1, len(rb) - 1)] == rb[: max(1, len(rb) - 1)]
        return {"==": a == b, "!=": a != b, "<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]
    return {"==": left == right, "!=": left != right}.get(op, False)


def _norm_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def eval_marker(marker: str, env: dict[str, str]) -> bool:
    tokens = []
    pos = 0
    text = marker.strip()
    while pos < len(text):
        m = _MARKER_TOKEN.match(text, pos)
        if not m or m.end() == pos:
            raise ValueError(f"bad marker: {marker}")
        tokens.append(" ".join(m.group(1).split()))
        pos = m.end()
        while pos < len(text) and text[pos].isspace():
            pos += 1
    i = 0

    def value() -> tuple[str, bool]:
        nonlocal i
        tok = tokens[i]
        i += 1
        if tok[0] in "'\"":
            return tok[1:-1], False
        if tok == "extra":
            return env.get("extra", ""), False
        return env.get(tok, ""), tok in _VERSION_VARS

    def comparison() -> bool:
        nonlocal i
        if tokens[i] == "(":
            i += 1
            r = disj()
            i += 1  # ")"
            return r
        left, lv = value()
        op = tokens[i]
        i += 1
        right, rv = value()
        if op in ("==", "!=") and (tokens[i - 1] == "extra" or tokens[i - 3] == "extra"):
            left, right = _norm_name(left), _norm_name(right)
        return _compare(left, op, right, lv or rv)

    def conj() -> bool:
        nonlocal i
        r = comparison()
        while i < len(tokens) and tokens[i] == "and":
            i += 1
            r = comparison() and r
        return r

    def disj() -> bool:
        nonlocal i
        r = conj()
        while i < len(tokens) and tokens[i] == "or":
            i += 1
            r = conj() or r
        return r

    return disj()


_REQ = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[([^\]]*)\])?(.*)$")


def parse_requirement(req: str) -> tuple[str, set[str], str | None]:
    m = _REQ.match(req)
    if not m:
        raise ValueError(f"bad requirement: {req}")
    rest = m.group(3)
    marker = rest.split(";", 1)[1].strip() if ";" in rest else None
    extras = {_norm_name(e) for e in (m.group(2) or "").split(",") if e.strip()}
    return m.group(1), extras, marker


def _marker_ok(marker: str | None, env: dict[str, str], extras: Iterable[str]) -> bool:
    if not marker:
        return True
    for extra in ("", *sorted(extras)):
        if eval_marker(marker, {**env, "extra": extra}):
            return True
    return False


def resolve_closure(requirements: list[str], env: dict[str, str]) -> dict[str, dict]:
    """Installed dependency closure: {normalised name: {"dist", "extras", "required_by"}}."""
    out: dict[str, dict] = {}
    queue: list[tuple[str, str]] = [(r, "(project)") for r in requirements]
    while queue:
        req, parent = queue.pop(0)
        name, extras, marker = parse_requirement(req)
        if not _marker_ok(marker, env, []):
            continue
        key = _norm_name(name)
        node = out.get(key)
        if node is None:
            try:
                dist = md.distribution(name)
            except md.PackageNotFoundError:
                dist = None
            node = out[key] = {"name": name, "dist": dist, "extras": set(), "required_by": set()}
            new_extras = set(extras)
            first = True
        else:
            new_extras = extras - node["extras"]
            first = False
        node["required_by"].add(parent)
        node["extras"] |= extras
        if node["dist"] is None or not (first or new_extras):
            continue
        meta_name = node["dist"].metadata["Name"] or name
        for child in node["dist"].requires or []:
            _, _, cmarker = parse_requirement(child)
            if first:
                wanted = _marker_ok(cmarker, env, node["extras"])
            else:  # only requirements unlocked by the newly requested extras
                wanted = bool(cmarker) and not _marker_ok(cmarker, env, []) and _marker_ok(cmarker, env, new_extras)
            if wanted:
                queue.append((child, meta_name))
    return out


# --- Python dependency audit ----------------------------------------------------------

COPYLEFT_TEXT = re.compile(
    r"GNU\s+(?:LESSER\s+|LIBRARY\s+|AFFERO\s+)?GENERAL\s+PUBLIC\s+LICEN[CS]E|\b(?:A|L)?GPL-?[23]", re.I
)
_LICENSE_FILE = re.compile(r"(LICEN[CS]E|COPYING|NOTICE|license_notes)", re.I)


def _license_files_with_copyleft(dist: md.Distribution) -> list[str]:
    hits = []
    for f in dist.files or []:
        if not _LICENSE_FILE.search(f.name):
            continue
        try:
            text = Path(dist.locate_file(f)).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if COPYLEFT_TEXT.search(text):
            hits.append(str(f).replace("\\", "/"))
    return sorted(hits)


def load_exceptions(root: Path) -> dict:
    path = root / EXCEPTIONS_PATH
    if not path.is_file():
        return {"python": {}, "npm": {}}
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["python"] = {_norm_name(k): v for k, v in (doc.get("python") or {}).items()}
    doc.setdefault("npm", {})
    return doc


FORBIDDEN_IN_CORE_CLOSURE = {"librosa", "soxr", "torch", "torchaudio", "openunmix", "onnxruntime",
                             "pedalboard", "matchering", "essentia", "aubio", "madmom", "pyrubberband"}


def audit_python_package(key: str, node: dict, context: str, exceptions: dict) -> dict:
    dist = node["dist"]
    entry: dict[str, Any] = {
        "name": node["name"] if dist is None else (dist.metadata["Name"] or node["name"]),
        "version": None if dist is None else dist.version,
        "required_by": sorted(node["required_by"]),
        "notes": [],
    }
    exc = exceptions["python"].get(key)
    if dist is None:
        entry.update(license="(not installed)", source="none", status=FAIL if context == "core" else FLAG,
                     reason="not installed in this environment; not audited")
        return entry
    meta = license_from_metadata(dist.metadata)
    entry["metadata_license"] = meta["expression"]
    external = bool(exc and exc.get("external_process"))
    if exc and exc.get("license"):
        tree, text = normalise_license(exc["license"])
        entry["license"] = text or exc["license"]
        entry["source"] = "verified record"
        status, reason = evaluate(tree, context, external_process=external) if tree else (FAIL, "bad record")
        if exc.get("checked_version") and exc["checked_version"] != dist.version:
            entry["notes"].append(f"record checked on version {exc['checked_version']}")
    else:
        entry["license"] = meta["expression"]
        entry["source"] = meta["source"]
        if meta["tree"] is None:
            status, reason = FAIL, "license unknown (no recognisable metadata and no verified record)"
        else:
            status, reason = evaluate(meta["tree"], context, external_process=external)
    copyleft_files = _license_files_with_copyleft(dist)
    if copyleft_files:
        entry["copyleft_text_in"] = copyleft_files
        if exc and exc.get("license_files_reviewed"):
            entry["notes"].append("license files mention GPL-family text; reviewed: " + exc["license_files_reviewed"])
        else:
            status, reason = FAIL, ("license files contain GPL-family text and no reviewed record exists in "
                                    f"{EXCEPTIONS_PATH} ({', '.join(copyleft_files[:3])})")
    if exc and exc.get("attention") and status != FAIL:
        status = FLAG
        reason = (reason + "; " if reason else "") + exc["attention"]
    if context == "core" and key in FORBIDDEN_IN_CORE_CLOSURE:
        status, reason = FAIL, "this package must not be in the core runtime (D-057, D-060)"
    entry["status"] = status
    entry["reason"] = reason
    return entry


def audit_python(root: Path, exceptions: dict, *, require_extras: bool) -> dict:
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    env = marker_environment()
    core_reqs = list(project.get("dependencies") or [])
    groups = []
    core = resolve_closure(core_reqs, env)
    groups.append({
        "name": "core", "requirements": core_reqs, "installed": True,
        "packages": [audit_python_package(k, core[k], "core", exceptions) for k in sorted(core)],
    })
    for extra, reqs in sorted((project.get("optional-dependencies") or {}).items()):
        top_missing = []
        for r in reqs:
            n, _, mk = parse_requirement(r)
            if _marker_ok(mk, env, []):
                try:
                    md.distribution(n)
                except md.PackageNotFoundError:
                    top_missing.append(n)
        closure = resolve_closure(core_reqs + list(reqs), env)
        extra_only = {k: v for k, v in closure.items() if k not in core}
        group = {"name": extra, "requirements": list(reqs), "installed": not top_missing,
                 "missing": top_missing, "packages": []}
        if top_missing:
            group["status"] = FAIL if require_extras else FLAG
            group["reason"] = f"extra not installed ({', '.join(top_missing)}); not audited"
        else:
            group["packages"] = [audit_python_package(k, extra_only[k], "extra", exceptions)
                                 for k in sorted(extra_only)]
        groups.append(group)
    return {"environment": {"python": env["python_full_version"], "platform": env["platform_system"],
                            "machine": env["platform_machine"]}, "groups": groups}


# --- forbidden imports --------------------------------------------------------------------

SCAN_DIRS = ("core", "dsp", "cli", "mcp")
FORBIDDEN_MODULES = {
    "librosa": "D-057 (pulls soxr, LGPL, into the process)",
    "soxr": "D-057 (LGPL; resample with scipy or FFmpeg)",
    "torch": "D-060 (inference stack only in the separation worker)",
    "torchaudio": "D-060 (inference stack only in the separation worker)",
    "openunmix": "D-060 (inference stack only in the separation worker)",
    "onnxruntime": "D-060 (inference stack only in the separation worker)",
    "pedalboard": "SPEC 13.2 (GPL-3.0)",
    "matchering": "SPEC 13.2 (GPL-3.0)",
    "essentia": "SPEC 13.2 (AGPL-3.0)",
    "aubio": "SPEC 13.2 (GPL-3.0)",
    "madmom": "SPEC 13.2 (non-commercial models)",
    "rubberband": "SPEC 13.2 (GPL)",
    "pyrubberband": "SPEC 13.2 (GPL)",
}
# Modules that only the separation worker subprocess may import.
WORKER_ALLOWED = {"torch", "torchaudio", "openunmix", "onnxruntime"}
WORKER_MODULES = ("core.separation.worker", "core.separation.archs")


def _is_worker_file(rel: str) -> bool:
    return rel == "core/separation/worker.py" or rel.startswith("core/separation/archs")


def _imports_of(tree: ast.AST, rel: str) -> list[tuple[int, str, bool]]:
    """(line, absolute module name, top_level) for every import in a module."""
    pkg_parts = rel[:-3].split("/")
    if pkg_parts[-1] == "__init__":
        pkg_parts = pkg_parts[:-1]
    else:
        pkg_parts = pkg_parts[:-1]
    module_level = {id(n) for n in getattr(tree, "body", [])}
    found: list[tuple[int, str, bool]] = []

    def strip(name: str) -> str:
        return name[len("mankomix."):] if name.startswith("mankomix.") else name

    for node in ast.walk(tree):
        top = id(node) in module_level
        if isinstance(node, ast.Import):
            for a in node.names:
                found.append((node.lineno, strip(a.name), top))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = pkg_parts[: len(pkg_parts) - (node.level - 1)] if node.level > 1 else list(pkg_parts)
                prefix = ".".join(base + ([node.module] if node.module else []))
                if node.module:
                    found.append((node.lineno, prefix, top))
                for a in node.names:
                    found.append((node.lineno, f"{prefix}.{a.name}", top))
            elif node.module:
                found.append((node.lineno, strip(node.module), top))
                for a in node.names:
                    found.append((node.lineno, strip(f"{node.module}.{a.name}"), top))
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant) \
                and isinstance(node.args[0].value, str):
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if name in ("import_module", "__import__"):
                found.append((node.lineno, strip(node.args[0].value), top))
    return found


def scan_forbidden_imports(root: Path, dirs: Iterable[str] = SCAN_DIRS) -> dict:
    findings: list[dict] = []
    worker_imports: list[dict] = []
    files = 0
    for d in dirs:
        base = root / d
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            rel = path.relative_to(root).as_posix()
            files += 1
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
            except (SyntaxError, UnicodeDecodeError) as exc:
                findings.append({"file": rel, "line": 0, "module": "", "reason": f"cannot parse: {exc.__class__.__name__}"})
                continue
            worker_side = _is_worker_file(rel)
            seen = set()
            for line, mod, top in _imports_of(tree, rel):
                head = mod.split(".")[0]
                if head in FORBIDDEN_MODULES and (line, head) not in seen:
                    seen.add((line, head))
                    if worker_side and head in WORKER_ALLOWED:
                        worker_imports.append({"file": rel, "line": line, "module": head,
                                               "module_level": top})
                        continue
                    findings.append({"file": rel, "line": line, "module": head,
                                     "reason": FORBIDDEN_MODULES[head]})
                if not worker_side and any(mod == w or mod.startswith(w + ".") for w in WORKER_MODULES) \
                        and (line, "worker") not in seen:
                    seen.add((line, "worker"))
                    findings.append({"file": rel, "line": line, "module": mod,
                                     "reason": "worker-side module imported outside the separation worker (D-060)"})
    return {"files_scanned": files, "findings": findings, "worker_imports": worker_imports,
            "status": FAIL if findings else OK}


# --- npm -------------------------------------------------------------------------------------

def _npm_license_value(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get("type")
    if isinstance(value, list):
        names = [_npm_license_value(v) for v in value]
        names = [n for n in names if n]
        return " OR ".join(names) if names else None
    return None


def audit_npm(root: Path, exceptions: dict) -> dict:
    gui = root / "gui"
    lock = gui / "package-lock.json"
    nm = gui / "node_modules"
    packages: list[dict] = []
    if lock.is_file():
        source = "gui/package-lock.json"
        doc = json.loads(lock.read_text(encoding="utf-8"))
        for key, info in sorted((doc.get("packages") or {}).items()):
            if not key or info.get("link"):
                continue
            name = key.split("node_modules/")[-1]
            lic = _npm_license_value(info.get("license")) or _npm_license_value(info.get("licenses"))
            if lic is None and (gui / key / "package.json").is_file():
                pj = json.loads((gui / key / "package.json").read_text(encoding="utf-8"))
                lic = _npm_license_value(pj.get("license")) or _npm_license_value(pj.get("licenses"))
            packages.append({"name": name, "version": info.get("version"), "license_raw": lic,
                             "scope": "dev" if info.get("dev") else "prod",
                             "optional": bool(info.get("optional"))})
    elif nm.is_dir():
        source = "gui/node_modules"
        for pj_path in sorted(nm.glob("*/package.json")) + sorted(nm.glob("@*/*/package.json")):
            pj = json.loads(pj_path.read_text(encoding="utf-8"))
            packages.append({"name": pj.get("name") or pj_path.parent.name, "version": pj.get("version"),
                             "license_raw": _npm_license_value(pj.get("license")) or _npm_license_value(pj.get("licenses")),
                             "scope": "unknown", "optional": False})
    else:
        return {"status": "skipped", "reason": "no gui/package-lock.json or gui/node_modules", "packages": []}
    for p in packages:
        exc = (exceptions.get("npm") or {}).get(p["name"])
        raw = (exc or {}).get("license") or p["license_raw"]
        tree, text = normalise_license(raw)
        p["license"] = text or (raw or "UNKNOWN")
        p["source"] = "verified record" if exc else "package metadata"
        if tree is None:
            p["status"], p["reason"] = FAIL, "license unknown"
        else:
            p["status"], p["reason"] = evaluate(tree, "npm")
    status = max((p["status"] for p in packages), key=_RANK.get, default=OK)
    return {"status": status, "source": source, "packages": packages}


# --- third_party ------------------------------------------------------------------------------

def audit_third_party(root: Path) -> dict:
    base = root / "third_party"
    readme = (base / "README.md").read_text(encoding="utf-8") if (base / "README.md").is_file() else ""
    items = []
    if base.is_dir():
        for d in sorted(p for p in base.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))):
            rel = f"third_party/{d.name}"
            lic_file = next((d / n for n in ("LICENSE", "LICENSE.txt", "LICENSE.md", "COPYING") if (d / n).is_file()), None)
            problems = []
            spdx = None
            if lic_file is None:
                problems.append("LICENSE is missing")
            else:
                spdx = _identify_text(lic_file.read_text(encoding="utf-8", errors="replace"))
                if spdx is None:
                    problems.append("license text not recognised as MIT / BSD / ISC / Apache-2.0")
            if not (d / "ORIGIN.md").is_file():
                problems.append("ORIGIN.md is missing")
            if f"`{d.name}/`" not in readme and f"{d.name}/" not in readme:
                problems.append("not listed in third_party/README.md")
            items.append({"folder": rel, "license": spdx or "UNKNOWN",
                          "status": FAIL if problems else OK, "reason": "; ".join(problems)})
    status = max((i["status"] for i in items), key=_RANK.get, default=OK)
    return {"status": status, "folders": items}


# --- model registry -----------------------------------------------------------------------------

def audit_registry(root: Path) -> dict:
    path = root / "registry" / "models.json"
    if not path.is_file():
        return {"status": FAIL, "issues": [{"level": "error", "where": "registry/models.json", "message": "missing"}],
                "models": []}
    doc = json.loads(path.read_text(encoding="utf-8"))
    issues: list[dict] = []
    try:
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from mankomix.core import registry as _registry  # noqa: WPS433 (needs the repo on sys.path)
        for i in _registry.catalog_issues(doc):
            issues.append({"level": i.get("level") or i.get("severity") or "error",
                           "where": "/".join(str(p) for p in (i.get("path") or [])),
                           "message": i.get("message") or str(i)})
    except Exception as exc:  # the audit must still report the rest
        issues.append({"level": "error", "where": "core.registry",
                       "message": f"catalogue validation could not run: {exc.__class__.__name__}: {exc}"})
    models = []
    for idx, m in enumerate(doc.get("models") or []):
        if not isinstance(m, dict):
            continue
        lic = m.get("license") if isinstance(m.get("license"), dict) else {}
        problems = []
        if m.get("tier") == "official":
            weights = lic.get("weights")
            if not weights or str(weights).lower() in ("unknown", "noassertion"):
                problems.append("license.weights missing or unknown")
            else:
                tree, _ = normalise_license(str(weights))
                st, why = evaluate(tree, "model") if tree else (FAIL, "unrecognised weights license")
                if st == FAIL:
                    problems.append(f"weights license: {why}")
            if lic.get("usage_restrictions") != "none":
                problems.append("usage_restrictions is not 'none'")
            evidence = lic.get("evidence") or []
            if not evidence:
                problems.append("no license evidence")
            for e in evidence:
                url = (e or {}).get("url") if isinstance(e, dict) else None
                if not isinstance(url, str) or not url.startswith(("https://", "http://")):
                    problems.append("evidence item without an http(s) URL")
                    break
        for p in problems:
            issues.append({"level": "error", "where": f"models/{idx}/license", "message": f"{m.get('id')}: {p}"})
        models.append({"id": m.get("id"), "status": m.get("status"), "tier": m.get("tier"),
                       "code": lic.get("code"), "weights": lic.get("weights"),
                       "usage_restrictions": lic.get("usage_restrictions"),
                       "evidence": len(lic.get("evidence") or []), "result": FAIL if problems else OK})
    errors = [i for i in issues if i["level"] == "error"]
    status = FAIL if errors else (FLAG if issues else OK)
    return {"status": status, "issues": issues, "models": models}


# --- FFmpeg bundling ------------------------------------------------------------------------------

_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".pytest_cache", ".venv", "venv", "tmp", "_private",
              "_handoff", "models", "out", "dist", "build", ".mypy_cache", ".ruff_cache"}
_FFMPEG_NAME = re.compile(r"^(ffmpeg|ffprobe|ffplay)(\.exe)?$|^(lib)?(avcodec|avformat|avutil|avfilter|avdevice|"
                          r"swresample|swscale|postproc)[-.0-9]*\.(dll|so|dylib|lib|a)([.0-9]*)$", re.I)


def audit_ffmpeg(root: Path) -> dict:
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for f in filenames:
            if _FFMPEG_NAME.match(f):
                found.append((Path(dirpath) / f).relative_to(root).as_posix())
    return {"status": FAIL if found else OK, "files": sorted(found)}


# --- run and report -----------------------------------------------------------------------------

def run_audit(root: Path = ROOT, *, require_extras: bool = False, npm: bool = True) -> dict:
    exceptions = load_exceptions(root)
    result: dict[str, Any] = {
        "python": audit_python(root, exceptions, require_extras=require_extras),
        "imports": scan_forbidden_imports(root),
        "npm": audit_npm(root, exceptions) if npm else {"status": "skipped", "reason": "--no-npm", "packages": []},
        "third_party": audit_third_party(root),
        "registry": audit_registry(root),
        "ffmpeg": audit_ffmpeg(root),
    }
    failures: list[str] = []
    flags: list[str] = []
    for g in result["python"]["groups"]:
        label = "python core" if g["name"] == "core" else f"python extra '{g['name']}'"
        if g.get("status"):
            (failures if g["status"] == FAIL else flags).append(f"{label}: {g['reason']}")
        for p in g["packages"]:
            if p["status"] == FAIL:
                failures.append(f"{label}: {p['name']} {p['version'] or ''} [{p['license']}]: {p['reason']}")
            elif p["status"] == FLAG:
                flags.append(f"{label}: {p['name']} {p['version'] or ''} [{p['license']}]: {p['reason']}")
    for f in result["imports"]["findings"]:
        failures.append(f"import: {f['file']}:{f['line']}: {f['module']}: {f['reason']}")
    for p in result["npm"]["packages"]:
        if p["status"] in (FAIL, FLAG):
            (failures if p["status"] == FAIL else flags).append(
                f"npm ({p['scope']}): {p['name']} {p['version']} [{p['license']}]: {p['reason']}")
    for t in result["third_party"]["folders"]:
        if t["status"] == FAIL:
            failures.append(f"{t['folder']}: {t['reason']}")
    for i in result["registry"]["issues"]:
        (failures if i["level"] == "error" else flags).append(f"registry {i['where']}: {i['message']}")
    for f in result["ffmpeg"]["files"]:
        failures.append(f"ffmpeg: {f}: FFmpeg binaries must not be bundled (SPEC 13.3)")
    result["failures"] = failures
    result["flags"] = flags
    result["ok"] = not failures
    return result


def _counts(items: Iterable[dict], key: str = "status") -> dict[str, int]:
    c = {OK: 0, FLAG: 0, FAIL: 0}
    for i in items:
        if i.get(key) in c:
            c[i[key]] += 1
    return c


def summary_rows(result: dict) -> list[tuple[str, str, dict]]:
    rows = []
    for g in result["python"]["groups"]:
        label = "Python core runtime" if g["name"] == "core" else f"Python extra `{g['name']}` (additional)"
        c = _counts(g["packages"])
        if g.get("status"):
            c[g["status"]] += 1
        rows.append((label, FAIL if c[FAIL] else (FLAG if c[FLAG] else OK), c))
    imp = result["imports"]
    rows.append(("Forbidden imports", imp["status"],
                 {OK: imp["files_scanned"] - len({f["file"] for f in imp["findings"]}), FLAG: 0, FAIL: len(imp["findings"])}))
    npm = result["npm"]
    if npm["status"] == "skipped":
        rows.append(("npm (gui)", "skipped", {OK: 0, FLAG: 0, FAIL: 0}))
    else:
        for scope, label in (("prod", "npm production (gui)"), ("dev", "npm development (gui)"), ("unknown", "npm (gui)")):
            ps = [p for p in npm["packages"] if p["scope"] == scope]
            if ps:
                c = _counts(ps)
                rows.append((label, FAIL if c[FAIL] else (FLAG if c[FLAG] else OK), c))
    tp = result["third_party"]
    rows.append(("third_party/", tp["status"], _counts(tp["folders"])))
    reg = result["registry"]
    rc = _counts(reg["models"], "result")
    rc[FLAG] += sum(1 for i in reg["issues"] if i["level"] != "error")
    rows.append(("Model registry", reg["status"], rc))
    ff = result["ffmpeg"]
    rows.append(("FFmpeg not bundled", ff["status"], {OK: 0 if ff["files"] else 1, FLAG: 0, FAIL: len(ff["files"])}))
    return rows


def _md_escape(text: Any) -> str:
    return str(text if text is not None else "").replace("|", "\\|").replace("\n", " ")


def render_markdown(result: dict) -> str:
    env = result["python"]["environment"]
    out: list[str] = []
    w = out.append
    w("# Third-party licenses (generated)")
    w("")
    w("Generated by `python -I tools/license_audit.py --write`. Do not edit by hand. Policy: `docs/SPEC.md` "
      "§13 (allowlist MIT / BSD / ISC / Apache-2.0 and the usual permissive Python licenses; no GPL / AGPL; "
      "LGPL only as an external process; unknown licenses are not adopted until checked). Human-verified "
      f"records live in `{EXCEPTIONS_PATH}`.")
    w("")
    w(f"Environment of this run: Python {env['python']} on {env['platform']} ({env['machine']}). Python versions "
      "and the platform-specific part of the dependency closure reflect that environment.")
    w("")
    w(f"**Result: {'PASS' if result['ok'] else 'FAIL'}** "
      f"({len(result['failures'])} failed, {len(result['flags'])} flagged)")
    w("")
    w("| Check | Result | OK | Flagged | Failed |")
    w("|---|---|---|---|---|")
    for label, status, c in summary_rows(result):
        w(f"| {label} | {status} | {c[OK]} | {c[FLAG]} | {c[FAIL]} |")
    w("")
    if result["failures"]:
        w("## Failures")
        w("")
        for f in result["failures"]:
            w(f"- {_md_escape(f)}")
        w("")
    w("## Flagged (allowed, needs attention)")
    w("")
    if result["flags"]:
        for f in result["flags"]:
            w(f"- {_md_escape(f)}")
    else:
        w("None.")
    w("")
    for g in result["python"]["groups"]:
        if g["name"] == "core":
            w("## Python: core runtime")
            w("")
            w("Closure of `project.dependencies` (`pip install mankomix`). Loaded in the core process.")
        else:
            w(f"## Python: extra `{g['name']}`")
            w("")
            w(f"Requirements: {', '.join(f'`{r}`' for r in g['requirements'])}. Packages listed here are the "
              "ones this extra adds to the core closure.")
            if g["name"] == "separation":
                w("Loaded only in the separation worker subprocess (D-060).")
            elif g["name"].startswith("test"):
                w("Development and test only; not part of the installed runtime.")
        w("")
        if g.get("status"):
            w(f"Not audited: {g['reason']}.")
            w("")
            continue
        w("| Package | Version | License | Source | Result | Notes |")
        w("|---|---|---|---|---|---|")
        for p in g["packages"]:
            notes = [p.get("reason") or ""] + p["notes"]
            if p.get("metadata_license") and p.get("source") == "verified record" \
                    and p["metadata_license"] != p["license"]:
                notes.append(f"metadata: {p['metadata_license']}")
            w(f"| {_md_escape(p['name'])} | {_md_escape(p['version'])} | {_md_escape(p['license'])} | "
              f"{_md_escape(p['source'])} | {p['status']} | {_md_escape('; '.join(n for n in notes if n))} |")
        w("")
    imp = result["imports"]
    w("## Forbidden imports (core process)")
    w("")
    w(f"AST scan of {', '.join(f'`{d}/`' for d in SCAN_DIRS)}: {imp['files_scanned']} files. Forbidden: "
      f"{', '.join(f'`{m}`' for m in sorted(FORBIDDEN_MODULES))}. The separation worker "
      "(`core/separation/worker.py`, `core/separation/archs*`) runs in its own subprocess and may import "
      f"{', '.join(f'`{m}`' for m in sorted(WORKER_ALLOWED))}; no other module may import the worker-side modules.")
    w("")
    if imp["findings"]:
        for f in imp["findings"]:
            w(f"- FAIL `{f['file']}:{f['line']}` imports `{f['module']}`: {f['reason']}")
    else:
        w("No forbidden imports.")
    w("")
    if imp["worker_imports"]:
        w("Worker-side imports (allowed):")
        w("")
        for f in imp["worker_imports"]:
            where = "module level" if f["module_level"] else "inside a function"
            w(f"- `{f['file']}:{f['line']}` `{f['module']}` ({where})")
        w("")
    npm = result["npm"]
    w("## npm (gui)")
    w("")
    if npm["status"] == "skipped":
        w(f"Skipped: {npm['reason']}.")
        w("")
    else:
        by_lic: dict[tuple[str, str], int] = {}
        for p in npm["packages"]:
            by_lic[(p["scope"], p["license"])] = by_lic.get((p["scope"], p["license"]), 0) + 1
        w(f"Source: `{npm['source']}`. {len(npm['packages'])} packages.")
        w("")
        w("| Scope | License | Packages |")
        w("|---|---|---|")
        for (scope, lic), n in sorted(by_lic.items()):
            w(f"| {scope} | {_md_escape(lic)} | {n} |")
        w("")
        w("<details><summary>All npm packages</summary>")
        w("")
        w("| Package | Version | Scope | License | Result |")
        w("|---|---|---|---|---|")
        for p in npm["packages"]:
            scope = p["scope"] + (" (optional)" if p["optional"] else "")
            w(f"| {_md_escape(p['name'])} | {_md_escape(p['version'])} | {scope} | {_md_escape(p['license'])} | "
              f"{p['status']} |")
        w("")
        w("</details>")
        w("")
    w("## third_party/")
    w("")
    w("| Folder | License | Result | Notes |")
    w("|---|---|---|---|")
    for t in result["third_party"]["folders"]:
        w(f"| `{t['folder']}` | {t['license']} | {t['status']} | {_md_escape(t['reason'])} |")
    w("")
    reg = result["registry"]
    w("## Model registry (`registry/models.json`)")
    w("")
    w("Weights are never stored in the repository. Official entries need a weights license, "
      "`usage_restrictions: none` and evidence with URLs.")
    w("")
    w("| Model | Status | Code | Weights | Usage restrictions | Evidence | Result |")
    w("|---|---|---|---|---|---|---|")
    for m in reg["models"]:
        w(f"| {_md_escape(m['id'])} | {_md_escape(m['status'])} | {_md_escape(m['code'])} | {_md_escape(m['weights'])} | "
          f"{_md_escape(m['usage_restrictions'])} | {m['evidence']} | {m['result']} |")
    w("")
    if reg["issues"]:
        for i in reg["issues"]:
            w(f"- {i['level']}: `{i['where']}`: {_md_escape(i['message'])}")
        w("")
    w("## FFmpeg")
    w("")
    w("FFmpeg is called as an external process and is never bundled or redistributed (SPEC 13.3). "
      + ("No FFmpeg binaries or libav* libraries in the source tree." if not result["ffmpeg"]["files"]
         else "Found: " + ", ".join(f"`{f}`" for f in result["ffmpeg"]["files"])))
    w("")
    return "\n".join(out)


def _jsonable(result: dict) -> dict:
    return json.loads(json.dumps(result, default=lambda o: sorted(o) if isinstance(o, set) else str(o)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MankoMIX dependency license audit (SPEC 13.4)")
    parser.add_argument("--write", action="store_true", help=f"write {REPORT_PATH}")
    parser.add_argument("--json", action="store_true", help="print the full result as JSON")
    parser.add_argument("--markdown", action="store_true", help="print the Markdown report")
    parser.add_argument("--require-extras", action="store_true", help="fail when an extra is not installed")
    parser.add_argument("--no-npm", action="store_true", help="skip the npm part")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(errors="backslashreplace")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

    result = run_audit(ROOT, require_extras=args.require_extras, npm=not args.no_npm)
    report = render_markdown(result)
    if args.write:
        (ROOT / REPORT_PATH).write_text(report, encoding="utf-8", newline="\n")
    if args.json:
        print(json.dumps(_jsonable(result), indent=2, ensure_ascii=False))
    elif args.markdown:
        print(report)
    else:
        for label, status, c in summary_rows(result):
            print(f"{label:42s} {status:8s} ok={c[OK]} flagged={c[FLAG]} failed={c[FAIL]}")
        if result["flags"]:
            print("\nFlagged:")
            for f in result["flags"]:
                print("  " + f)
        if result["failures"]:
            print("\nFailures:")
            for f in result["failures"]:
                print("  " + f)
        if args.write:
            print(f"\nwrote {REPORT_PATH}")
        print("\nLicense audit " + ("passed." if result["ok"] else "FAILED."))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
