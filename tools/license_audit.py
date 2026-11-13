#!/usr/bin/env python3
"""Dependency and third-party license audit (docs/SPEC.md 13, 13.3, 13.4, 16.4).

Checks, in one run:

1. Python dependencies. The dependency closure of the core runtime
   (``project.dependencies`` in pyproject.toml) and, reported separately, of
   each extra (``test``, ``test-crosscheck``, ``separation``). Licenses come
   from the installed distributions' metadata (License-Expression, License,
   trove classifiers, the license file for an unspecified "BSD"), normalised
   to SPDX and judged against the allowlist below. GPL / AGPL / LGPL packages
   fail everywhere (LGPL is only acceptable as an external process such as
   FFmpeg). MPL-2.0 is accepted as an unmodified dependency and flagged.
   Unknown licenses fail unless ``licenses/exceptions.json`` holds a reviewed
   record (reason + evidence URL).
2. In-process native components that package metadata does not show
   (libsndfile inside soundfile, OpenBLAS / GCC runtime inside numpy and
   scipy). Static table below, judged by the same policy.
3. Import boundary (D-057, D-060): no package in the core closure may be one
   of the rejected or worker-only distributions, and an AST scan of core/,
   dsp/, cli/, mcp/ and mankomix/ must not find imports of librosa, soxr,
   torch, ... outside the separation worker (core/separation/worker.py,
   core/separation/archs*).
4. npm: every package in gui/package-lock.json (runtime and dev separated),
   same allowlist. BlueOak-1.0.0 is permissive but not allowlisted (the GUI
   dependency set was chosen to avoid it) and fails.
5. third_party/: every folder has LICENSE (MIT / BSD / ISC / Apache-2.0 text)
   and ORIGIN.md (with a source URL) and is listed in third_party/README.md.
6. Model registry: registry/models.json through core.registry's catalogue
   validation plus the license fields of the official entries.
7. FFmpeg is never bundled (SPEC 13.3): no ffmpeg executables or libav*
   shared libraries in the tree.

Determinism. The generated files must not depend on the machine that wrote
them, because CI compares them with the committed copies on Windows, Linux
and macOS:

- environment markers are evaluated for the union of the supported targets
  (CPython 3.11 / 3.12 on Windows x64, Linux x86_64 / aarch64, macOS arm64 /
  x86_64), not just for the running interpreter;
- installed versions are not recorded (only names, licenses and edges);
- a package that is required on some target but not installed here (e.g.
  colorama off Windows, the separation extra in CI) keeps the license and the
  dependency edges of the committed report. Packages that were never
  installed where the report was generated are listed as "unverified"; that
  fails for the core and the test extras and is a warning for the optional,
  worker-only separation extra.

Outputs (generated, do not edit): licenses/THIRD_PARTY_LICENSES.md,
licenses/python.json, licenses/npm.json. Input: licenses/exceptions.json.

Usage:
    python -I tools/license_audit.py           audit and (re)write the generated files
    python -I tools/license_audit.py --check   audit and compare with the committed files (CI)

Exit code 0 when there is no violation (and, with --check, no drift); 1
otherwise. Only repository-relative paths and SPDX ids are written; nothing
is copied from license texts.
"""

from __future__ import annotations

import argparse
import ast
import difflib
import importlib.metadata as md
import itertools
import json
import os
import re
import sys
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent

REPORT_MD = "licenses/THIRD_PARTY_LICENSES.md"
PYTHON_JSON = "licenses/python.json"
NPM_JSON = "licenses/npm.json"
EXCEPTIONS_JSON = "licenses/exceptions.json"
GENERATED = (REPORT_MD, PYTHON_JSON, NPM_JSON)

OK, FLAG, UNVERIFIED, FAIL = "ok", "flag", "unverified", "fail"
_RANK = {OK: 0, FLAG: 1, UNVERIFIED: 2, FAIL: 3}

# --- policy ---------------------------------------------------------------------------------

# Permissive licenses accepted for dependencies (Python and npm).
ALLOW = frozenset({
    "MIT", "MIT-0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "Apache-2.0", "PSF-2.0", "Python-2.0",
    "Unlicense", "0BSD", "Zlib", "HPND", "CC0-1.0",
})
# Accepted only as an unmodified dependency; always flagged in the report.
WEAK_COPYLEFT = {"MPL-2.0": "weak copyleft, allowed unmodified"}
# License exceptions that make the base license acceptable.
WITH_EXCEPTIONS = {
    "LLVM-exception": {"Apache-2.0"},
    "GCC-exception-3.1": {"GPL-3.0-or-later", "GPL-3.0-only"},  # GCC runtime library exception
}
# Extra licenses accepted for components bundled inside a binary wheel (LAPACK).
BUNDLED_ALLOW = frozenset({"BSD-3-Clause-Open-MPI"})
# SPEC 13.1: code copied into third_party/.
VENDORED_ALLOW = frozenset({"MIT", "BSD-2-Clause", "BSD-3-Clause", "ISC", "Apache-2.0"})
NOT_ALLOWLISTED_NOTE = {
    "BlueOak-1.0.0": "permissive but not on the allowlist (the GUI dependency set is pinned to avoid it)",
}
COPYLEFT = ("GPL", "AGPL", "LGPL")

# Target environments for marker evaluation (CI matrix and supported platforms).
TARGET_PYTHONS = ("3.11", "3.12")
TARGET_PLATFORMS = (
    ("win32", "Windows", "nt", "AMD64"),
    ("linux", "Linux", "posix", "x86_64"),
    ("linux", "Linux", "posix", "aarch64"),
    ("darwin", "Darwin", "posix", "arm64"),
    ("darwin", "Darwin", "posix", "x86_64"),
)
# Extras whose unverified packages are only a warning (optional, worker-only, D-060).
OPTIONAL_EXTRAS = frozenset({"separation"})

# Distributions rejected outright (SPEC 13.2, D-057, D-060), in any closure.
REJECTED_DISTS = {
    "librosa": "D-057: pulls python-soxr (LGPL-2.1) into the process",
    "soxr": "D-057: LGPL-2.1; resample with scipy or FFmpeg (external process)",
    "audio-separator": "D-060: requires CC BY-NC diffq-fixed on Windows and pulls librosa/soxr",
    "diffq": "CC BY-NC 4.0 (non-commercial)",
    "diffq-fixed": "CC BY-NC 4.0 (non-commercial)",
    "pedalboard": "SPEC 13.2: GPL-3.0",
    "essentia": "SPEC 13.2: AGPL-3.0",
    "essentia-tensorflow": "SPEC 13.2: AGPL-3.0",
    "matchering": "SPEC 13.2: GPL-3.0",
    "madmom": "SPEC 13.2: CC BY-NC-SA models",
    "aubio": "SPEC 13.2: GPL-3.0",
    "pyrubberband": "SPEC 13.2: wraps Rubber Band (GPL)",
}
# Distributions allowed only in the separation worker's closure (D-060).
WORKER_ONLY_DISTS = {
    "torch": "D-060", "torchaudio": "D-060", "openunmix": "D-060", "onnxruntime": "D-060",
    "onnxruntime-gpu": "D-060",
}

# Modules the core process must never import (AST scan).
FORBIDDEN_MODULES = {
    "librosa": "D-057 (pulls soxr, LGPL, into the process)",
    "soxr": "D-057 (LGPL; resample with scipy or FFmpeg)",
    "torch": "D-060 (inference stack only in the separation worker)",
    "torchaudio": "D-060 (inference stack only in the separation worker)",
    "openunmix": "D-060 (inference stack only in the separation worker)",
    "onnxruntime": "D-060 (inference stack only in the separation worker)",
    "audio_separator": "D-060 (python-audio-separator is not used)",
    "diffq": "non-commercial license",
    "demucs": "research-only official weights; not used",
    "pedalboard": "SPEC 13.2 (GPL-3.0)",
    "essentia": "SPEC 13.2 (AGPL-3.0)",
    "matchering": "SPEC 13.2 (GPL-3.0)",
    "madmom": "SPEC 13.2 (non-commercial models)",
    "aubio": "SPEC 13.2 (GPL-3.0)",
    "rubberband": "SPEC 13.2 (GPL)",
    "pyrubberband": "SPEC 13.2 (GPL)",
}
WORKER_ALLOWED_MODULES = frozenset({"torch", "torchaudio", "openunmix", "onnxruntime"})
WORKER_MODULES = ("core.separation.worker", "core.separation.archs")
SCAN_DIRS = ("core", "dsp", "cli", "mcp", "mankomix")

# In-process native libraries that a package loads but its metadata does not name.
NATIVE_COMPONENTS = (
    {"package": "numpy", "component": "OpenBLAS", "license": "BSD-3-Clause",
     "note": "bundled in the binary wheels"},
    {"package": "numpy", "component": "LAPACK (inside OpenBLAS)", "license": "BSD-3-Clause-Open-MPI",
     "note": "bundled in the binary wheels"},
    {"package": "numpy", "component": "GCC runtime (libgfortran)",
     "license": "GPL-3.0-or-later WITH GCC-exception-3.1",
     "note": "bundled in some binary wheels; the runtime library exception applies"},
    {"package": "scipy", "component": "OpenBLAS", "license": "BSD-3-Clause",
     "note": "bundled in the binary wheels"},
    {"package": "scipy", "component": "LAPACK (inside OpenBLAS)", "license": "BSD-3-Clause-Open-MPI",
     "note": "bundled in the binary wheels"},
    {"package": "scipy", "component": "GCC runtime (libgfortran)",
     "license": "GPL-3.0-or-later WITH GCC-exception-3.1",
     "note": "bundled in some binary wheels; the runtime library exception applies"},
    {"package": "soundfile", "component": "libsndfile", "license": "LGPL-2.1-or-later",
     "note": "shared library loaded in-process through cffi; bundled in the wheels or provided by the system"},
    {"package": "soundfile", "component": "libmp3lame, libmpg123 (inside libsndfile)",
     "license": "LGPL-2.0-or-later AND LGPL-2.1-only",
     "note": "MP3 codecs compiled into the bundled libsndfile"},
    {"package": "soundfile", "component": "libFLAC, libogg, libvorbis, libopus (inside libsndfile)",
     "license": "BSD-3-Clause", "note": "codecs compiled into the bundled libsndfile"},
)

EXTERNAL_TOOLS = (
    {"name": "FFmpeg", "license": "LGPL-2.1-or-later (GPL-2.0-or-later with --enable-gpl; nonfree builds are not redistributable)",
     "handling": "External process only; never bundled, redistributed or downloaded. The standard route uses only "
                 "features of an LGPL build; LGPL builds are recommended. A GPL build still runs: doctor warns and the "
                 "build configuration is recorded; an optional strict mode refuses non-LGPL builds (SPEC 13.3, D-043)."},
)

# --- license names -> SPDX -------------------------------------------------------------------

BSD_UNSPECIFIED = "LicenseRef-BSD-unspecified"

_ALIASES = {
    "mit": "MIT", "mit license": "MIT", "the mit license": "MIT", "mit licence": "MIT",
    "the mit license (mit)": "MIT", "expat": "MIT", "expat license": "MIT",
    "mit-0": "MIT-0", "mit no attribution": "MIT-0",
    "bsd": BSD_UNSPECIFIED, "bsd license": BSD_UNSPECIFIED, "bsd licence": BSD_UNSPECIFIED,
    "bsd-2-clause": "BSD-2-Clause", "bsd 2-clause": "BSD-2-Clause", "bsd 2-clause license": "BSD-2-Clause",
    "2-clause bsd": "BSD-2-Clause", "2-clause bsd license": "BSD-2-Clause", "simplified bsd": "BSD-2-Clause",
    "freebsd": "BSD-2-Clause",
    "bsd-3-clause": "BSD-3-Clause", "bsd 3-clause": "BSD-3-Clause", "bsd 3-clause license": "BSD-3-Clause",
    "3-clause bsd": "BSD-3-Clause", "3-clause bsd license": "BSD-3-Clause", "new bsd": "BSD-3-Clause",
    "new bsd license": "BSD-3-Clause", "modified bsd": "BSD-3-Clause", "modified bsd license": "BSD-3-Clause",
    "bsd-3": "BSD-3-Clause", "revised bsd": "BSD-3-Clause",
    "apache-2.0": "Apache-2.0", "apache 2.0": "Apache-2.0", "apache 2": "Apache-2.0",
    "apache license 2.0": "Apache-2.0", "apache license, version 2.0": "Apache-2.0",
    "apache license version 2.0": "Apache-2.0", "apache software license": "Apache-2.0",
    "apache software license 2.0": "Apache-2.0", "apache license": "Apache-2.0", "asl 2.0": "Apache-2.0",
    "apache-2": "Apache-2.0", "apache2": "Apache-2.0", "apache software license (apache 2.0)": "Apache-2.0",
    "isc": "ISC", "isc license": "ISC", "isc license (iscl)": "ISC", "iscl": "ISC",
    "psf": "PSF-2.0", "psf-2.0": "PSF-2.0", "psfl": "PSF-2.0", "python software foundation license": "PSF-2.0",
    "python-2.0": "Python-2.0",
    "mpl-2.0": "MPL-2.0", "mpl 2.0": "MPL-2.0", "mozilla public license 2.0": "MPL-2.0",
    "mozilla public license 2.0 (mpl 2.0)": "MPL-2.0",
    "unlicense": "Unlicense", "the unlicense": "Unlicense", "the unlicense (unlicense)": "Unlicense",
    "0bsd": "0BSD", "hpnd": "HPND", "historical permission notice and disclaimer (hpnd)": "HPND",
    "cc0-1.0": "CC0-1.0", "cc0": "CC0-1.0", "cc0 1.0 universal": "CC0-1.0",
    "zlib": "Zlib", "zlib license": "Zlib", "zlib/libpng license": "Zlib",
    "blueoak-1.0.0": "BlueOak-1.0.0", "bsl-1.0": "BSL-1.0", "boost software license 1.0 (bsl-1.0)": "BSL-1.0",
    "other/proprietary license": "LicenseRef-Proprietary", "proprietary": "LicenseRef-Proprietary",
    "public domain": "LicenseRef-Public-Domain",
    "gnu general public license (gpl)": "GPL", "gnu general public license v2 (gplv2)": "GPL-2.0-only",
    "gnu general public license v2 or later (gplv2+)": "GPL-2.0-or-later",
    "gnu general public license v3 (gplv3)": "GPL-3.0-only",
    "gnu general public license v3 or later (gplv3+)": "GPL-3.0-or-later",
    "gnu lesser general public license v2 (lgplv2)": "LGPL-2.0-only",
    "gnu lesser general public license v2 or later (lgplv2+)": "LGPL-2.0-or-later",
    "gnu lesser general public license v3 (lgplv3)": "LGPL-3.0-only",
    "gnu lesser general public license v3 or later (lgplv3+)": "LGPL-3.0-or-later",
    "gnu library or lesser general public license (lgpl)": "LGPL",
    "gnu affero general public license v3": "AGPL-3.0-only",
    "gnu affero general public license v3 or later (agplv3+)": "AGPL-3.0-or-later",
}
_SPDX_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+-]*$")
_KNOWN_IDS = {v.lower(): v for v in (*ALLOW, *WEAK_COPYLEFT, *BUNDLED_ALLOW, *NOT_ALLOWLISTED_NOTE,
                                     "BSL-1.0", "MIT-CMU", "CC-BY-4.0", "Artistic-2.0")}


def canonical_id(token: str) -> str | None:
    """Map one license name to an SPDX id (or LicenseRef-*), None when unrecognised."""
    t = " ".join(token.strip().split())
    if not t:
        return None
    low = t.lower()
    if low in _ALIASES:
        return _ALIASES[low]
    if low in _KNOWN_IDS:
        return _KNOWN_IDS[low]
    if low.startswith("licenseref-"):
        return t
    m = re.match(r"^(a|l)?gpl[- ]?v?(\d(?:\.\d)?)?(\+|-or-later|-only)?$", low)
    if m:
        fam = {"a": "AGPL", "l": "LGPL"}.get(m.group(1) or "", "GPL")
        if not m.group(2):
            return fam
        ver = m.group(2) if "." in m.group(2) else m.group(2) + ".0"
        suffix = "-or-later" if m.group(3) in ("+", "-or-later") else "-only"
        return f"{fam}-{ver}{suffix}"
    if re.match(r"^(gnu\s+)?(affero\s+|lesser\s+|library\s+)?general public licen[cs]e", low):
        if "affero" in low:
            return "AGPL"
        return "LGPL" if ("lesser" in low or "library" in low) else "GPL"
    if _SPDX_TOKEN.match(t) and "-" in t:  # looks like an SPDX id we do not know (judged later)
        return t
    return None


_EXPR_SPLIT = re.compile(r"(\(|\)|\s+AND\s+|\s+OR\s+|\s+and\s+|\s+or\s+|\s+WITH\s+|\s+with\s+)")


def parse_expression(text: str) -> Any:
    """Parse a license expression into a tree.

    Leaves are ("id", spdx_or_None, raw, with_exception_or_None); inner nodes are
    ("and"|"or", [children]). Raises ValueError on malformed input.
    """
    tokens: list[Any] = []
    for part in _EXPR_SPLIT.split(text.strip()):
        word = part.strip()
        if not word:
            continue
        if word in ("(", ")"):
            tokens.append(word)
        elif part != word and word.upper() in ("AND", "OR", "WITH"):
            tokens.append(word.upper())
        else:
            tokens.append(("leaf", word))
    pos = 0

    def peek() -> Any:
        return tokens[pos] if pos < len(tokens) else None

    def take() -> Any:
        nonlocal pos
        tok = tokens[pos]
        pos += 1
        return tok

    def atom() -> Any:
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
            exc = None
            if peek() == "WITH":
                take()
                nxt = take() if pos < len(tokens) else None
                if not isinstance(nxt, tuple):
                    raise ValueError("WITH without an exception id")
                exc = nxt[1]
            return ("id", canonical_id(tok[1]), tok[1], exc)
        raise ValueError(f"unexpected token {tok!r}")

    def and_expr() -> Any:
        items = [atom()]
        while peek() == "AND":
            take()
            items.append(atom())
        return items[0] if len(items) == 1 else ("and", items)

    def or_expr() -> Any:
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
        base = tree[1] or "UNKNOWN"
        return f"{base} WITH {tree[3]}" if tree[3] else base
    joiner = " AND " if tree[0] == "and" else " OR "
    return joiner.join(expression_text(c) if c[0] == "id" else f"({expression_text(c)})" for c in tree[1])


def _leaves(tree: Any) -> list[Any]:
    if tree[0] == "id":
        return [tree]
    return [leaf for c in tree[1] for leaf in _leaves(c)]


def _map_leaves(tree: Any, fn) -> Any:
    if tree[0] == "id":
        return fn(tree)
    return (tree[0], [_map_leaves(c, fn) for c in tree[1]])


def is_copyleft(spdx: str | None) -> bool:
    return bool(spdx) and spdx.upper().startswith(COPYLEFT)


def classify_id(spdx: str | None, exc: str | None = None, *, bundled: bool = False) -> tuple[str, str]:
    """Status and reason for one license id."""
    if exc:
        if exc in WITH_EXCEPTIONS and spdx in WITH_EXCEPTIONS[exc]:
            return OK, ""
        st, why = classify_id(spdx, bundled=bundled)
        if st == OK:
            return OK, ""
        return FAIL, f"{spdx} WITH {exc} is not accepted" if spdx else "unrecognised license"
    if spdx is None:
        return FAIL, "unrecognised license"
    if spdx == BSD_UNSPECIFIED:
        return FAIL, "BSD variant could not be identified from the license file"
    if spdx in ALLOW or (bundled and spdx in BUNDLED_ALLOW):
        return OK, ""
    if spdx in WEAK_COPYLEFT:
        return FLAG, WEAK_COPYLEFT[spdx]
    if spdx.upper().startswith("LGPL"):
        return FAIL, "LGPL is only allowed as an external process (SPEC 13.1)"
    if spdx.upper().startswith(("GPL", "AGPL")):
        return FAIL, f"{spdx} is not allowed (SPEC 13.1)"
    if spdx in NOT_ALLOWLISTED_NOTE:
        return FAIL, NOT_ALLOWLISTED_NOTE[spdx]
    return FAIL, f"{spdx} is not on the allowlist"


def evaluate(tree: Any, *, bundled: bool = False) -> tuple[str, str]:
    """AND takes the worst branch, OR the best one."""
    if tree[0] == "id":
        return classify_id(tree[1], tree[3], bundled=bundled)
    results = [evaluate(c, bundled=bundled) for c in tree[1]]
    pick = max if tree[0] == "and" else min
    status = pick((r[0] for r in results), key=_RANK.get)
    reasons = sorted({r[1] for r in results if r[0] == status and r[1]})
    return status, "; ".join(reasons)


def normalise(text: str | None) -> Any | None:
    """Parse a short license string; None for empty, full-text or unparsable values."""
    if not text or not text.strip():
        return None
    one_line = " ".join(text.split())
    if len(one_line) > 120 or "\n" in text.strip():
        return None
    try:
        tree = parse_expression(one_line)
    except ValueError:
        return None
    return tree if all(leaf[1] for leaf in _leaves(tree)) else None


_TEXT_SIGNATURES = (
    ("Apache-2.0", re.compile(r"apache license,? version 2\.0")),
    ("MIT", re.compile(r"permission is hereby granted, free of charge")),
    ("ISC", re.compile(r"permission to use, copy, modify, and/?or distribute this software for any purpose")),
    ("BSD", re.compile(r"redistribution and use in source and binary forms")),
)


def identify_text(text: str) -> str | None:
    """Recognise the primary license of a license text (the earliest signature wins)."""
    low = " ".join(text[:6000].lower().split())
    hits = sorted((m.start(), name) for name, rx in _TEXT_SIGNATURES for m in [rx.search(low)] if m)
    if not hits:
        return None
    name = hits[0][1]
    if name != "BSD":
        return name
    start = hits[0][0]
    window = low[start:start + 2500]
    if re.search(r"neither the name|names of (its|the) contributors|may be used to endorse", window):
        return "BSD-3-Clause"
    if "advertising materials" in window:
        return "BSD-4-Clause"
    return "BSD-2-Clause"


# --- distributions ------------------------------------------------------------------------------

def norm_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def find_distribution(name: str) -> Any | None:
    """Installed distribution for a project name (tests monkeypatch this)."""
    try:
        return md.distribution(name)
    except md.PackageNotFoundError:
        return None


_LICENSE_FILE = re.compile(r"^(LICEN[CS]E|COPYING)", re.I)


def _primary_license_texts(dist: Any) -> list[str]:
    """Texts of the distribution's own license files (dist-info only, not vendored copies)."""
    out = []
    for f in getattr(dist, "files", None) or []:
        parts = Path(str(f)).parts
        if not parts or not parts[0].endswith(".dist-info"):
            continue
        if not _LICENSE_FILE.match(parts[-1]) or len(parts) > 3:
            continue
        try:
            out.append(Path(dist.locate_file(f)).read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return out


def license_of(dist: Any) -> Any | None:
    """License tree from distribution metadata, or None when it cannot be determined."""
    meta = dist.metadata
    tree = normalise(meta.get("License-Expression"))
    if tree is None:
        tree = normalise(meta.get("License"))
    if tree is None:
        ids = []
        for c in meta.get_all("Classifier") or []:
            if c.startswith("License ::") and c.split("::")[-1].strip() != "OSI Approved":
                ids.append(canonical_id(c.split("::")[-1].strip()))
        ids = sorted({i or "LicenseRef-Unrecognised-Classifier" for i in ids})
        if ids:
            leaves = [("id", i, i, None) for i in ids]
            tree = leaves[0] if len(leaves) == 1 else ("and", leaves)  # conservative: all of them apply
    texts: list[str] | None = None

    def texts_once() -> list[str]:
        nonlocal texts
        if texts is None:
            raw = meta.get("License") or ""
            texts = ([raw] if len(raw) > 120 else []) + _primary_license_texts(dist)
        return texts

    if tree is None:
        for text in texts_once():
            found = identify_text(text)
            if found:
                return ("id", found, found, None)
        return None
    if any(leaf[1] == BSD_UNSPECIFIED for leaf in _leaves(tree)):
        found = next((x for x in (identify_text(t) for t in texts_once()) if x and x.startswith("BSD")), None)
        if found:
            tree = _map_leaves(tree, lambda leaf: ("id", found, leaf[2], leaf[3]) if leaf[1] == BSD_UNSPECIFIED else leaf)
    return tree


# --- environment markers (PEP 508 subset, stdlib only) ------------------------------------------

_MARKER_TOKEN = re.compile(
    r"\s*(\(|\)|===|==|!=|<=|>=|~=|<|>|not\s+in\b|in\b|and\b|or\b|'[^']*'|\"[^\"]*\"|[A-Za-z_][A-Za-z0-9_.]*)"
)
_VERSION_VARS = {"python_version", "python_full_version", "implementation_version"}


def target_environments() -> list[dict[str, str]]:
    envs = []
    for py, (plat, system, osname, machine) in itertools.product(TARGET_PYTHONS, TARGET_PLATFORMS):
        envs.append({
            "os_name": osname, "sys_platform": plat, "platform_system": system, "platform_machine": machine,
            "platform_python_implementation": "CPython", "implementation_name": "cpython",
            "python_version": py, "python_full_version": py + ".0", "implementation_version": py + ".0",
            "platform_release": "", "platform_version": "", "extra": "",
        })
    return envs


TARGET_ENVS = target_environments()


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
            keep = max(1, len(rb) - 1)
            return a >= b and _vtuple(left)[:keep] == rb[:keep]
        return {"==": a == b, "!=": a != b, "<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]
    return {"==": left == right, "!=": left != right}.get(op, False)


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
        return env.get(tok, ""), tok in _VERSION_VARS

    def comparison() -> bool:
        nonlocal i
        if tokens[i] == "(":
            i += 1
            r = disj()
            i += 1  # ")"
            return r
        ltok = tokens[i]
        left, lv = value()
        op = tokens[i]
        i += 1
        rtok = tokens[i]
        right, rv = value()
        if "extra" in (ltok, rtok):
            left, right = norm_name(left), norm_name(right)
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


@lru_cache(maxsize=None)
def marker_possible(marker: str | None, extras: tuple[str, ...] = ()) -> bool:
    """True when the marker holds on at least one target environment (with one of the extras)."""
    if not marker:
        return True
    for env in TARGET_ENVS:
        for extra in ("", *extras):
            if eval_marker(marker, {**env, "extra": extra}):
                return True
    return False


_REQ = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[([^\]]*)\])?(.*)$")


def parse_requirement(req: str) -> tuple[str, frozenset[str], str | None]:
    m = _REQ.match(req)
    if not m:
        raise ValueError(f"bad requirement: {req}")
    rest = m.group(3)
    marker = rest.split(";", 1)[1].strip() if ";" in rest else None
    extras = frozenset(norm_name(e) for e in (m.group(2) or "").split(",") if e.strip())
    return norm_name(m.group(1)), extras, marker


def _spec(name: str, extras: Iterable[str]) -> str:
    ex = sorted(extras)
    return f"{name}[{','.join(ex)}]" if ex else name


# --- Python closure and audit -------------------------------------------------------------------

def resolve_closure(roots: list[tuple[str, str]], carried: dict[str, dict]) -> dict[str, dict]:
    """Dependency closure over the target environments.

    roots: (requirement, parent label). Returns {name: {"extras", "required_by",
    "requires", "installed"}}. Installed distributions give their requirements;
    others fall back to the edges of the committed report (``carried``).
    """
    nodes: dict[str, dict] = {}
    queue: list[tuple[str, frozenset[str], str]] = []
    for req, parent in roots:
        name, extras, marker = parse_requirement(req)
        if marker_possible(marker):
            queue.append((name, extras, parent))
    while queue:
        name, extras, parent = queue.pop(0)
        node = nodes.get(name)
        if node is None:
            node = nodes[name] = {"extras": set(), "required_by": set(), "requires": set(), "expanded": None}
        node["required_by"].add(parent)
        node["extras"] |= extras
        key = frozenset(node["extras"])
        if node["expanded"] == key:
            continue
        node["expanded"] = key
        dist = find_distribution(name)
        node["installed"] = dist is not None
        children: list[tuple[str, frozenset[str]]] = []
        if dist is not None:
            for child in dist.requires or []:
                cname, cextras, cmarker = parse_requirement(child)
                if marker_possible(cmarker, tuple(sorted(node["extras"]))):
                    children.append((cname, cextras))
        elif name in carried:
            for spec in carried[name].get("requires") or []:
                cname, cextras, _ = parse_requirement(spec)
                children.append((cname, cextras))
        node["requires"] = {_spec(c, e) for c, e in children}
        for cname, cextras in children:
            queue.append((cname, cextras, name))
    return nodes


def load_exceptions(root: Path) -> tuple[dict, list[str]]:
    """Reviewed exceptions and the problems of the file itself."""
    path = root / EXCEPTIONS_JSON
    empty = {"python": {}, "npm": {}, "native": {}}
    if not path.is_file():
        return empty, []
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return empty, [f"{EXCEPTIONS_JSON}: not valid JSON ({exc.msg})"]
    out: dict[str, dict] = {"python": {}, "npm": {}, "native": {}}
    problems = []
    for section in out:
        for i, e in enumerate(doc.get(section) or []):
            where = f"{EXCEPTIONS_JSON}: {section}[{i}]"
            key = e.get("component") if section == "native" else e.get("name")
            if not isinstance(key, str) or not key:
                problems.append(f"{where}: missing {'component' if section == 'native' else 'name'}")
                continue
            if not e.get("license") or not e.get("reason"):
                problems.append(f"{where}: license and reason are required")
                continue
            ev = e.get("evidence")
            ev = [ev] if isinstance(ev, str) else ev
            if not ev or not all(isinstance(u, str) and u.startswith("https://") for u in ev):
                problems.append(f"{where}: evidence must list https:// URLs")
                continue
            out[section][norm_name(key) if section == "python" else key] = {**e, "evidence": list(ev)}
    return out, problems


def _carried_records(root: Path) -> dict[str, dict]:
    path = root / PYTHON_JSON
    if not path.is_file():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    out: dict[str, dict] = {}
    for scope in doc.get("scopes") or []:
        for p in scope.get("packages") or []:
            if isinstance(p, dict) and p.get("name") and p.get("status") != UNVERIFIED:
                out.setdefault(p["name"], p)
    return out


def audit_package(name: str, node: dict, scope: str, carried: dict, exceptions: dict,
                  used_exceptions: set) -> dict:
    entry: dict[str, Any] = {"name": name}
    tree = None
    if node.get("installed"):
        tree = license_of(find_distribution(name))
    elif name in carried and carried[name].get("license") not in (None, "UNKNOWN", "UNVERIFIED"):
        tree = normalise(carried[name]["license"])
    exc = exceptions["python"].get(name)
    if exc:
        used_exceptions.add(("python", name))
        etree = normalise(exc["license"])
        entry["license"] = expression_text(etree) if etree else exc["license"]
        if etree and any(is_copyleft(leaf[1]) for leaf in _leaves(etree)):
            status, reason = evaluate(etree)
        else:
            status, reason = FLAG, f"reviewed exception: {exc['reason']}"
    elif tree is not None:
        entry["license"] = expression_text(tree)
        status, reason = evaluate(tree)
    elif node.get("installed") or name in carried:
        entry["license"] = "UNKNOWN"
        status, reason = FAIL, "license unknown (no usable metadata and no reviewed exception)"
    else:
        entry["license"] = "UNVERIFIED"
        if scope in OPTIONAL_EXTRAS:
            status, reason = UNVERIFIED, ("not installed where this report was generated (platform-specific or "
                                          "optional); verify on a platform that installs it")
        else:
            status, reason = FAIL, "not installed and not in the committed report; license could not be verified"
    if name in REJECTED_DISTS:
        status, reason = FAIL, f"rejected dependency: {REJECTED_DISTS[name]}"
    elif scope == "core" and name in WORKER_ONLY_DISTS:
        status, reason = FAIL, f"worker-only dependency in the core closure ({WORKER_ONLY_DISTS[name]})"
    entry.update(status=status, note=reason, required_by=sorted(node["required_by"]),
                 requires=sorted(node["requires"]))
    return entry


def audit_python(root: Path, exceptions: dict, used_exceptions: set) -> dict:
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    carried = _carried_records(root)
    core_reqs = list(project.get("dependencies") or [])
    core = resolve_closure([(r, "(core)") for r in core_reqs], carried)
    scopes = [{"name": "core", "requirements": core_reqs,
               "packages": [audit_package(n, core[n], "core", carried, exceptions, used_exceptions)
                            for n in sorted(core)]}]
    for extra, reqs in sorted((project.get("optional-dependencies") or {}).items()):
        closure = resolve_closure([(r, "(core)") for r in core_reqs] + [(r, f"(extra:{extra})") for r in reqs],
                                  carried)
        only = {n: v for n, v in closure.items() if n not in core}
        for v in only.values():
            v["required_by"].discard("(core)")
        scopes.append({"name": extra, "requirements": list(reqs),
                       "packages": [audit_package(n, only[n], extra, carried, exceptions, used_exceptions)
                                    for n in sorted(only)]})
    env_notes = []
    for scope in scopes:
        for p in scope["packages"]:
            if find_distribution(p["name"]) is None and p["status"] != UNVERIFIED:
                env_notes.append(f"{scope['name']}: {p['name']} is not installed here; "
                                 f"license and edges taken from the committed {PYTHON_JSON}")
    core_names = set(core)
    for name in sorted({*REJECTED_DISTS, *WORKER_ONLY_DISTS}):
        if name not in core_names and find_distribution(name) is not None:
            env_notes.append(f"{name} is installed in this environment but not required by the core")
    return {"scopes": scopes, "env_notes": env_notes}


def audit_native(core_names: set[str], exceptions: dict, used_exceptions: set) -> list[dict]:
    out = []
    for comp in NATIVE_COMPONENTS:
        if comp["package"] not in core_names:
            continue
        tree = normalise(comp["license"])
        status, reason = evaluate(tree, bundled=True) if tree else (FAIL, "unrecognised license")
        exc = exceptions["native"].get(comp["component"])
        if exc and status == FAIL:
            used_exceptions.add(("native", comp["component"]))
            status, reason = FLAG, f"reviewed exception ({exc.get('decision', 'accepted')}): {exc['reason']}"
        elif exc:
            used_exceptions.add(("native", comp["component"]))
        out.append({**comp, "status": status, "reason": reason})
    return out


# --- import boundary ----------------------------------------------------------------------------

def _is_worker_file(rel: str) -> bool:
    return rel == "core/separation/worker.py" or rel.startswith("core/separation/archs")


def _imports_of(tree: ast.AST, rel: str) -> list[tuple[int, str]]:
    """(line, absolute module name) for every import in a module (any nesting level)."""
    pkg_parts = rel[:-3].split("/")[:-1]
    found: list[tuple[int, str]] = []

    def strip(name: str) -> str:
        return name[len("mankomix."):] if name.startswith("mankomix.") else name

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, strip(a.name)) for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = pkg_parts[: len(pkg_parts) - (node.level - 1)] if node.level > 1 else list(pkg_parts)
                prefix = ".".join(base + ([node.module] if node.module else []))
                if node.module:
                    found.append((node.lineno, prefix))
                found.extend((node.lineno, f"{prefix}.{a.name}") for a in node.names)
            elif node.module:
                found.append((node.lineno, strip(node.module)))
                found.extend((node.lineno, strip(f"{node.module}.{a.name}")) for a in node.names)
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant) \
                and isinstance(node.args[0].value, str):
            fn = node.func
            fname = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if fname in ("import_module", "__import__"):
                found.append((node.lineno, strip(node.args[0].value)))
    return found


def scan_imports(root: Path, dirs: Iterable[str] = SCAN_DIRS) -> dict:
    findings: list[dict] = []
    worker: set[tuple[str, str]] = set()
    for d in dirs:
        base = root / d
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            rel = path.relative_to(root).as_posix()
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
            except (SyntaxError, UnicodeDecodeError) as exc:
                findings.append({"file": rel, "line": 0, "module": "", "reason": f"cannot parse ({type(exc).__name__})"})
                continue
            worker_side = _is_worker_file(rel)
            seen = set()
            for line, mod in _imports_of(tree, rel):
                head = mod.split(".")[0]
                if head in FORBIDDEN_MODULES and (line, head) not in seen:
                    seen.add((line, head))
                    if worker_side and head in WORKER_ALLOWED_MODULES:
                        worker.add((rel, head))
                        continue
                    findings.append({"file": rel, "line": line, "module": head, "reason": FORBIDDEN_MODULES[head]})
                if not worker_side and any(mod == w or mod.startswith(w + ".") for w in WORKER_MODULES) \
                        and (line, "worker") not in seen:
                    seen.add((line, "worker"))
                    findings.append({"file": rel, "line": line, "module": mod,
                                     "reason": "worker-side module imported outside the separation worker (D-060)"})
    findings.sort(key=lambda f: (f["file"], f["line"], f["module"]))
    return {"scanned": list(dirs), "findings": findings,
            "worker_imports": [{"file": f, "module": m} for f, m in sorted(worker)]}


# --- npm ----------------------------------------------------------------------------------------

def _npm_license_value(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get("type")
    if isinstance(value, list):
        names = [n for n in (_npm_license_value(v) for v in value) if n]
        return " OR ".join(f"({n})" if " " in n else n for n in names) if names else None
    return None


def audit_npm(root: Path, exceptions: dict, used_exceptions: set) -> dict:
    lock = root / "gui" / "package-lock.json"
    if not lock.is_file():
        return {"source": None, "packages": [], "problem": "gui/package-lock.json is missing"}
    doc = json.loads(lock.read_text(encoding="utf-8"))
    merged: dict[tuple[str, str], dict] = {}
    for key, info in (doc.get("packages") or {}).items():
        if not key or info.get("link") or "node_modules/" not in key:
            continue
        name = info.get("name") or key.rsplit("node_modules/", 1)[-1]
        version = info.get("version") or ""
        scope = "dev" if (info.get("dev") or info.get("devOptional")) else "runtime"
        raw = _npm_license_value(info.get("license")) or _npm_license_value(info.get("licenses"))
        rec = merged.setdefault((name, version), {"name": name, "version": version, "raw": raw,
                                                  "scopes": set(), "optional": True})
        rec["scopes"].add(scope)
        rec["optional"] = rec["optional"] and bool(info.get("optional") or info.get("devOptional"))
    packages = []
    for (name, version), rec in sorted(merged.items()):
        scope = "runtime" if "runtime" in rec["scopes"] else "dev"
        exc = exceptions["npm"].get(name)
        tree = normalise(rec["raw"])
        if exc:
            used_exceptions.add(("npm", name))
            etree = normalise(exc["license"])
            lic = expression_text(etree) if etree else exc["license"]
            if etree and any(is_copyleft(leaf[1]) for leaf in _leaves(etree)):
                status, reason = evaluate(etree)
            else:
                status, reason = FLAG, f"reviewed exception: {exc['reason']}"
        elif tree is None:
            lic, status, reason = "UNKNOWN", FAIL, "license missing or unrecognised in the lockfile"
        else:
            lic = expression_text(tree)
            status, reason = evaluate(tree)
        packages.append({"name": name, "version": version, "license": lic, "scope": scope,
                         "optional": rec["optional"], "status": status, "note": reason})
    return {"source": "gui/package-lock.json", "lockfile_version": doc.get("lockfileVersion"),
            "packages": packages}


# --- third_party ---------------------------------------------------------------------------------

def audit_third_party(root: Path) -> list[dict]:
    base = root / "third_party"
    readme = (base / "README.md").read_text(encoding="utf-8") if (base / "README.md").is_file() else ""
    items = []
    if not base.is_dir():
        return items
    for d in sorted((p for p in base.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))),
                    key=lambda p: p.name):
        lic_file = next((d / n for n in ("LICENSE", "LICENSE.txt", "LICENSE.md") if (d / n).is_file()), None)
        problems, spdx = [], None
        if lic_file is None:
            problems.append("LICENSE is missing")
        else:
            spdx = identify_text(lic_file.read_text(encoding="utf-8", errors="replace"))
            if spdx not in VENDORED_ALLOW:
                problems.append("license text is not MIT / BSD-2-Clause / BSD-3-Clause / ISC / Apache-2.0")
        origin = d / "ORIGIN.md"
        if not origin.is_file():
            problems.append("ORIGIN.md is missing")
        elif "https://" not in origin.read_text(encoding="utf-8", errors="replace"):
            problems.append("ORIGIN.md does not name a source URL")
        if f"`{d.name}/`" not in readme:
            problems.append("not listed in third_party/README.md")
        items.append({"folder": f"third_party/{d.name}", "license": spdx or "UNKNOWN",
                      "status": FAIL if problems else OK, "note": "; ".join(problems)})
    return items


# --- model registry -------------------------------------------------------------------------------

def audit_registry(root: Path) -> dict:
    path = root / "registry" / "models.json"
    if not path.is_file():
        return {"issues": [{"level": "error", "where": "registry/models.json", "message": "missing"}], "models": []}
    doc = json.loads(path.read_text(encoding="utf-8"))
    issues: list[dict] = []
    try:
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from mankomix.core import registry as _registry
        for i in _registry.catalog_issues(doc):
            issues.append({"level": i.get("level") or "error", "where": str(i.get("path") or "/"),
                           "message": str(i.get("message") or i)})
    except Exception as exc:  # report it; the rest of the audit still runs
        issues.append({"level": "error", "where": "core.registry",
                       "message": f"catalogue validation could not run ({type(exc).__name__})"})
    models = []
    for idx, m in enumerate(doc.get("models") or []):
        if not isinstance(m, dict):
            continue
        lic = m.get("license") if isinstance(m.get("license"), dict) else {}
        problems = []
        if m.get("tier") == "official":
            weights = lic.get("weights")
            tree = normalise(str(weights)) if weights else None
            if tree is None:
                problems.append("license.weights missing or unknown")
            elif evaluate(tree)[0] == FAIL:
                problems.append(f"weights license: {evaluate(tree)[1]}")
            if lic.get("usage_restrictions") != "none":
                problems.append("usage_restrictions is not 'none'")
            evidence = [e for e in lic.get("evidence") or [] if isinstance(e, dict)]
            if not evidence:
                problems.append("no license evidence")
            elif any(not str(e.get("url") or "").startswith("https://") for e in evidence):
                problems.append("evidence item without an https URL")
        for p in problems:
            issues.append({"level": "error", "where": f"/models/{idx}/license", "message": f"{m.get('id')}: {p}"})
        models.append({"id": m.get("id"), "status": m.get("status"), "code": lic.get("code"),
                       "weights": lic.get("weights"), "usage_restrictions": lic.get("usage_restrictions"),
                       "evidence": sorted({str(e.get("kind")) for e in lic.get("evidence") or [] if isinstance(e, dict)}),
                       "result": FAIL if problems else OK})
    issues.sort(key=lambda i: (i["level"], i["where"], i["message"]))
    return {"issues": issues, "models": models, "defaults": doc.get("defaults") or {}}


# --- FFmpeg bundling ------------------------------------------------------------------------------

_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".pytest_cache", ".venv", "venv", "tmp", "_private",
              "_handoff", "models", "out", "dist", "build", ".mypy_cache", ".ruff_cache"}
_FFMPEG_NAME = re.compile(r"^(ffmpeg|ffprobe|ffplay)(\.exe)?$|^(lib)?(avcodec|avformat|avutil|avfilter|avdevice|"
                          r"swresample|swscale|postproc)[-.0-9]*\.(dll|so|dylib|lib|a)([.0-9]*)$", re.I)


def audit_ffmpeg(root: Path) -> list[str]:
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        for f in filenames:
            if _FFMPEG_NAME.match(f):
                found.append((Path(dirpath) / f).relative_to(root).as_posix())
    return sorted(found)


# --- run ----------------------------------------------------------------------------------------

def run_audit(root: Path = ROOT) -> dict:
    exceptions, exc_problems = load_exceptions(root)
    used: set[tuple[str, str]] = set()
    python = audit_python(root, exceptions, used)
    core_names = {p["name"] for p in python["scopes"][0]["packages"]}
    native = audit_native(core_names, exceptions, used)
    imports = scan_imports(root)
    npm = audit_npm(root, exceptions, used)
    third_party = audit_third_party(root)
    registry = audit_registry(root)
    ffmpeg = audit_ffmpeg(root)

    violations: list[str] = list(exc_problems)
    warnings: list[str] = []
    for scope in python["scopes"]:
        label = "python core" if scope["name"] == "core" else f"python extra '{scope['name']}'"
        for p in scope["packages"]:
            line = f"{label}: {p['name']} [{p['license']}]: {p['note']}"
            if p["status"] == FAIL:
                violations.append(line)
            elif p["status"] == UNVERIFIED:
                warnings.append(line)
    for c in native:
        if c["status"] == FAIL:
            violations.append(f"native component of {c['package']}: {c['component']} [{c['license']}]: {c['reason']}")
    for f in imports["findings"]:
        violations.append(f"import: {f['file']}:{f['line']}: {f['module']}: {f['reason']}")
    if npm.get("problem"):
        violations.append(f"npm: {npm['problem']}")
    for p in npm["packages"]:
        if p["status"] == FAIL:
            violations.append(f"npm ({p['scope']}): {p['name']}@{p['version']} [{p['license']}]: {p['note']}")
    for t in third_party:
        if t["status"] == FAIL:
            violations.append(f"{t['folder']}: {t['note']}")
    for i in registry["issues"]:
        (violations if i["level"] == "error" else warnings).append(f"registry {i['where']}: {i['message']}")
    for f in ffmpeg:
        violations.append(f"ffmpeg: {f}: FFmpeg binaries must not be bundled (SPEC 13.3)")
    for section, entries in exceptions.items():
        for key in sorted(entries):
            if (section, key) not in used:
                warnings.append(f"unused exception in {EXCEPTIONS_JSON}: {section} '{key}'")
    return {"python": python, "native": native, "imports": imports, "npm": npm, "third_party": third_party,
            "registry": registry, "ffmpeg": ffmpeg, "exceptions": exceptions,
            "violations": violations, "warnings": warnings}


# --- rendering ------------------------------------------------------------------------------------

def _dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2) + "\n"


def _policy() -> dict:
    return {
        "allow": sorted(ALLOW),
        "weak_copyleft_allowed_unmodified": sorted(WEAK_COPYLEFT),
        "with_exceptions": {k: sorted(v) for k, v in sorted(WITH_EXCEPTIONS.items())},
        "bundled_component_allow": sorted(BUNDLED_ALLOW),
        "vendored_code_allow": sorted(VENDORED_ALLOW),
        "lgpl": "external process only (FFmpeg); never in the core or worker process",
        "gpl_agpl": "never",
        "unknown": f"fails unless a reviewed record is in {EXCEPTIONS_JSON}",
    }


def render_python_json(result: dict) -> str:
    py = result["python"]
    doc = {
        "generated_by": "tools/license_audit.py",
        "note": "Generated file; do not edit. Versions are deliberately not recorded (see the tool docstring).",
        "policy": _policy(),
        "target_environments": {"python": list(TARGET_PYTHONS),
                                "platforms": [f"{p[1]} {p[3]}" for p in TARGET_PLATFORMS]},
        "scopes": py["scopes"],
        "native_components": result["native"],
        "import_boundary": result["imports"],
    }
    return _dumps(doc)


def render_npm_json(result: dict) -> str:
    npm = result["npm"]
    doc = {"generated_by": "tools/license_audit.py", "note": "Generated file; do not edit.",
           "source": npm.get("source"), "lockfile_version": npm.get("lockfile_version"),
           "packages": npm["packages"]}
    return _dumps(doc)


def _md(text: Any) -> str:
    return str(text if text not in (None, "") else "-").replace("|", "\\|").replace("\n", " ")


def _status_label(status: str) -> str:
    return {OK: "ok", FLAG: "allowed (flagged)", UNVERIFIED: "unverified", FAIL: "VIOLATION"}.get(status, status)


def _counts(items: Iterable[dict], key: str = "status") -> str:
    c: dict[str, int] = {}
    for i in items:
        c[i[key]] = c.get(i[key], 0) + 1
    return ", ".join(f"{_status_label(k)} {c[k]}" for k in sorted(c, key=_RANK.get)) or "none"


def render_markdown(result: dict) -> str:
    out: list[str] = []
    w = out.append
    w("# Third-party licenses")
    w("")
    w("Generated by `python -I tools/license_audit.py`; do not edit by hand. CI runs it with `--check` and fails "
      "when this file is out of date or a license is outside the policy. Policy: `docs/SPEC.md` §13 "
      "(D-043, D-057, D-060); reviewed exceptions: `licenses/exceptions.json`; machine-readable lists: "
      "`licenses/python.json`, `licenses/npm.json`.")
    w("")
    w("- Allowed: " + ", ".join(sorted(ALLOW)) + ".")
    w("- MPL-2.0: weak copyleft, allowed unmodified (flagged). GPL / AGPL: never. LGPL: only as an external "
      "process (FFmpeg). Unknown: not adopted until reviewed.")
    w("- Code copied into `third_party/`: " + ", ".join(sorted(VENDORED_ALLOW)) + " only.")
    w(f"- Python markers are evaluated for CPython {' / '.join(TARGET_PYTHONS)} on "
      + ", ".join(f"{p[1]} {p[3]}" for p in TARGET_PLATFORMS)
      + ". Versions are not recorded (they are whatever pip resolves); only names, licenses and edges.")
    w("")
    w("## Result")
    w("")
    if result["violations"]:
        w(f"**{len(result['violations'])} violation(s).**")
        w("")
        for v in result["violations"]:
            w(f"- {_md(v)}")
    else:
        w("No violations.")
    if result["warnings"]:
        w("")
        w("Warnings:")
        w("")
        for v in result["warnings"]:
            w(f"- {_md(v)}")
    w("")
    w("| Section | Result |")
    w("|---|---|")
    for scope in result["python"]["scopes"]:
        title = "Python core runtime" if scope["name"] == "core" else f"Python extra `{scope['name']}` (additional packages)"
        w(f"| {title} | {_counts(scope['packages'])} |")
    w(f"| In-process native components | {_counts(result['native'])} |")
    w(f"| Import boundary (D-057, D-060) | {'VIOLATION ' + str(len(result['imports']['findings'])) if result['imports']['findings'] else 'ok'} |")
    for scope in ("runtime", "dev"):
        pk = [p for p in result["npm"]["packages"] if p["scope"] == scope]
        w(f"| npm {scope} (gui) | {_counts(pk)} |")
    w(f"| third_party/ | {_counts(result['third_party'])} |")
    reg_errors = [i for i in result["registry"]["issues"] if i["level"] == "error"]
    w(f"| Model registry | {'VIOLATION ' + str(len(reg_errors)) if reg_errors else 'ok'} |")
    w(f"| FFmpeg not bundled | {'VIOLATION' if result['ffmpeg'] else 'ok'} |")

    for scope in result["python"]["scopes"]:
        w("")
        if scope["name"] == "core":
            w("## Python: core runtime")
            w("")
            w("Closure of `project.dependencies`: " + ", ".join(f"`{r}`" for r in scope["requirements"]) + ".")
        else:
            w(f"## Python: extra `{scope['name']}`")
            w("")
            w("Requirements: " + ", ".join(f"`{r}`" for r in scope["requirements"])
              + ". Only packages that the core closure does not already contain are listed.")
            if scope["name"] in OPTIONAL_EXTRAS:
                w("")
                w("Optional and worker-only (D-060): these packages are loaded only by the separation worker "
                  "subprocess, never by the core process, and are installed by the user. Packages that were not "
                  "installed where this report was generated are listed as unverified (a warning, not a failure).")
        w("")
        w("| Package | License | Status | Note | Required by |")
        w("|---|---|---|---|---|")
        for p in scope["packages"]:
            w(f"| {_md(p['name'])} | {_md(p['license'])} | {_status_label(p['status'])} | {_md(p['note'])} "
              f"| {_md(', '.join(p['required_by']))} |")

    w("")
    w("## In-process native components")
    w("")
    w("Shared libraries that core dependencies load into the process but that package metadata does not name.")
    w("")
    w("| Package | Component | License | Status | Note |")
    w("|---|---|---|---|---|")
    for c in result["native"]:
        note = c["note"] + (f"; {c['reason']}" if c["reason"] else "")
        w(f"| {_md(c['package'])} | {_md(c['component'])} | {_md(c['license'])} | {_status_label(c['status'])} | {_md(note)} |")

    w("")
    w("## Import boundary (D-057, D-060)")
    w("")
    w("AST scan of " + ", ".join(f"`{d}/`" for d in result["imports"]["scanned"])
      + ". Forbidden modules: " + ", ".join(f"`{m}`" for m in sorted(FORBIDDEN_MODULES))
      + ". The separation worker (`core/separation/worker.py`, `core/separation/archs*`) may import "
      + ", ".join(f"`{m}`" for m in sorted(WORKER_ALLOWED_MODULES)) + "; nothing else may import the worker modules.")
    w("")
    if result["imports"]["findings"]:
        for f in result["imports"]["findings"]:
            w(f"- VIOLATION `{f['file']}:{f['line']}` imports `{f['module']}`: {_md(f['reason'])}")
    else:
        w("No forbidden import outside the worker.")
    if result["imports"]["worker_imports"]:
        w("")
        w("Worker-side imports (allowed): " + ", ".join(
            f"`{x['module']}` in `{x['file']}`" for x in result["imports"]["worker_imports"]) + ".")
    w("")
    w("Rejected distributions (must not appear in any closure): " + ", ".join(f"`{d}`" for d in sorted(REJECTED_DISTS))
      + ". Worker-only distributions (must not appear in the core closure): "
      + ", ".join(f"`{d}`" for d in sorted(WORKER_ONLY_DISTS)) + ".")

    for scope in ("runtime", "dev"):
        pk = [p for p in result["npm"]["packages"] if p["scope"] == scope]
        w("")
        w(f"## npm: {scope} dependencies (gui/)")
        w("")
        w(f"From `{result['npm'].get('source')}`. "
          + ("Shipped in the built GUI and the Pages demo." if scope == "runtime"
             else "Build and test tooling only; not shipped. Optional entries are platform-specific binaries."))
        w("")
        w("| Package | Version | License | Status | Note |")
        w("|---|---|---|---|---|")
        for p in pk:
            name = p["name"] + (" (optional)" if p["optional"] else "")
            w(f"| {_md(name)} | {_md(p['version'])} | {_md(p['license'])} | {_status_label(p['status'])} | {_md(p['note'])} |")

    w("")
    w("## third_party/ (code copied into the repository)")
    w("")
    w("| Folder | License | Status | Note |")
    w("|---|---|---|---|")
    for t in result["third_party"]:
        w(f"| `{t['folder']}/` | {_md(t['license'])} | {_status_label(t['status'])} | {_md(t['note'])} |")

    reg = result["registry"]
    w("")
    w("## Model registry (weights are never bundled)")
    w("")
    w("Validated with `core.registry.catalog_issues` (schema and catalogue rules) plus the license fields of "
      "official entries. Defaults: " + ", ".join(f"{k} = `{v}`" for k, v in sorted(reg["defaults"].items())) + ".")
    w("")
    w("| Model | Status | Code | Weights | Usage restrictions | Evidence kinds | Result |")
    w("|---|---|---|---|---|---|---|")
    for m in reg["models"]:
        w(f"| `{_md(m['id'])}` | {_md(m['status'])} | {_md(m['code'])} | {_md(m['weights'])} | "
          f"{_md(m['usage_restrictions'])} | {_md(', '.join(m['evidence']))} | {_status_label(m['result'])} |")
    if reg["issues"]:
        w("")
        for i in reg["issues"]:
            w(f"- {i['level']}: `{_md(i['where'])}`: {_md(i['message'])}")

    w("")
    w("## External tools (not bundled)")
    w("")
    w("| Tool | License | Handling |")
    w("|---|---|---|")
    for t in EXTERNAL_TOOLS:
        w(f"| {t['name']} | {_md(t['license'])} | {_md(t['handling'])} |")
    w("")
    w("FFmpeg binaries in the tree: " + (", ".join(f"`{f}`" for f in result["ffmpeg"]) if result["ffmpeg"] else "none") + ".")

    w("")
    w("## Reviewed exceptions")
    w("")
    rows = [(s, k, e) for s in ("python", "npm", "native") for k, e in sorted(result["exceptions"][s].items())]
    if not rows:
        w("None.")
    else:
        w("| Ecosystem | Item | License | Decision | Reason | Evidence |")
        w("|---|---|---|---|---|---|")
        for s, k, e in rows:
            w(f"| {s} | {_md(k)} | {_md(e['license'])} | {_md(e.get('decision', 'accepted'))} | {_md(e['reason'])} "
              f"| {_md(' '.join(e['evidence']))} |")
    w("")
    return "\n".join(out)


def render_all(result: dict) -> dict[str, str]:
    return {REPORT_MD: render_markdown(result), PYTHON_JSON: render_python_json(result),
            NPM_JSON: render_npm_json(result)}


# --- main -----------------------------------------------------------------------------------------

def _drift(root: Path, files: dict[str, str]) -> list[str]:
    msgs = []
    for rel, text in files.items():
        path = root / rel
        if not path.is_file():
            msgs.append(f"{rel}: missing (run python -I tools/license_audit.py and commit the result)")
            continue
        current = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        if current != text:
            diff = list(difflib.unified_diff(current.splitlines(), text.splitlines(),
                                             f"{rel} (committed)", f"{rel} (generated)", lineterm="", n=1))
            msgs.append(f"{rel}: out of date")
            msgs.extend("    " + d for d in diff[:60])
            if len(diff) > 60:
                msgs.append(f"    ... {len(diff) - 60} more diff lines")
    return msgs


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Dependency and third-party license audit (SPEC 13.4).")
    parser.add_argument("--check", action="store_true",
                        help="do not write; fail when the committed files differ from the generated ones")
    args = parser.parse_args(argv)

    result = run_audit(ROOT)
    files = render_all(result)

    for note in result["python"]["env_notes"]:
        print(f"note: {note}")
    for w in result["warnings"]:
        print(f"warning: {w}")
    for v in result["violations"]:
        print(f"VIOLATION: {v}")

    status = 1 if result["violations"] else 0
    if args.check:
        drift = _drift(ROOT, files)
        for line in drift:
            print(line)
        if drift:
            print("Generated license files are out of date: run `python -I tools/license_audit.py` and commit licenses/.")
            status = 1
    else:
        for rel, text in files.items():
            path = ROOT / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
            print(f"wrote {rel}")

    print("License audit " + ("FAILED." if status else "passed."))
    return status


if __name__ == "__main__":
    sys.exit(main())
