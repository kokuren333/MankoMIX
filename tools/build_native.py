#!/usr/bin/env python3
"""Build the MankoMIX native DSP core (dsp/native/) in Release mode.

Usage:
    python -I tools/build_native.py [--clean] [--verbose]

What it does:
  1. Finds CMake: on PATH, else (Windows) the copy bundled with Visual Studio,
     located through vswhere.
  2. On Windows, if no compiler environment is active, loads the MSVC x64
     environment from vcvars64.bat of the same Visual Studio installation.
  3. Configures with Ninja when available (PATH or bundled with Visual
     Studio), else NMake (Windows) or the CMake default generator.
  4. Builds into dsp/build/ (gitignored) and copies the shared library to
     dsp/build/lib/, where dsp/native_backend.py looks for it.

Only project-relative paths are printed; tool output is shown (with the
repository root replaced by ".") on failure or with --verbose.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "dsp" / "native"
BUILD_ROOT = ROOT / "dsp" / "build"
LIB_DIR = BUILD_ROOT / "lib"
LIB_NAMES = ("mankomix_dsp.dll", "mankomix_dsp.so", "mankomix_dsp.dylib")
IS_WINDOWS = os.name == "nt"


def rel(path: Path | str) -> str:
    p = Path(path)
    try:
        return p.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return p.name


def sanitize(text: str) -> str:
    """Hide absolute locations of the checkout and the home directory."""
    replacements: dict[str, str] = {}
    for base, label in ((ROOT, "."), (Path.home(), "~")):
        for form in (str(base), base.as_posix()):
            replacements[form] = label
            # Ninja names objects of out-of-tree sources like "C_\dir\..."
            if len(form) > 1 and form[1] == ":":
                replacements[form[0] + "_" + form[2:]] = label
    for old, new in sorted(replacements.items(), key=lambda kv: -len(kv[0])):
        if old:
            text = text.replace(old, new)
    return text


# --------------------------------------------------------------------------- tools


def find_vs_installation() -> Path | None:
    """Return the newest Visual Studio installation with the x64 C++ tools."""
    if not IS_WINDOWS:
        return None
    candidates = []
    for var in ("ProgramFiles(x86)", "ProgramFiles"):
        base = os.environ.get(var)
        if base:
            candidates.append(Path(base) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe")
    vswhere = next((c for c in candidates if c.is_file()), None)
    if vswhere is None:
        found = shutil.which("vswhere")
        vswhere = Path(found) if found else None
    if vswhere is None:
        return None
    queries = (
        ["-latest", "-products", "*", "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64"],
        ["-latest", "-products", "*", "-prerelease"],
    )
    for query in queries:
        res = subprocess.run(
            [str(vswhere), *query, "-property", "installationPath", "-utf8"],
            capture_output=True,
        )
        out = res.stdout.decode("utf-8", errors="replace").strip().splitlines()
        if res.returncode == 0 and out and Path(out[0]).is_dir():
            return Path(out[0])
    return None


def vs_bundled(vs: Path | None, *parts: str) -> Path | None:
    if vs is None:
        return None
    path = vs.joinpath(*parts)
    return path if path.is_file() else None


def find_cmake(vs: Path | None) -> Path | None:
    on_path = shutil.which("cmake")
    if on_path:
        return Path(on_path)
    return vs_bundled(vs, "Common7", "IDE", "CommonExtensions", "Microsoft", "CMake", "CMake", "bin", "cmake.exe")


def find_ninja(vs: Path | None, env: dict[str, str]) -> Path | None:
    on_path = shutil.which("ninja", path=env.get("PATH"))
    if on_path:
        return Path(on_path)
    return vs_bundled(vs, "Common7", "IDE", "CommonExtensions", "Microsoft", "CMake", "Ninja", "ninja.exe")


def msvc_environment(vs: Path | None) -> dict[str, str] | None:
    """Environment after vcvars64.bat (what `cmd /c "call vcvars64.bat && ..."` sees)."""
    vcvars = vs_bundled(vs, "VC", "Auxiliary", "Build", "vcvars64.bat")
    if vcvars is None:
        return None
    # cmd /u makes the built-in `set` write UTF-16, so non-ASCII PATH entries survive.
    command = f'cmd /u /c "call "{vcvars}" >nul 2>&1 && set"'
    res = subprocess.run(command, capture_output=True)
    if res.returncode != 0:
        return None
    env: dict[str, str] = {}
    for line in res.stdout.decode("utf-16-le", errors="replace").splitlines():
        key, sep, value = line.partition("=")
        if sep and key:
            env[key] = value
    return env if "INCLUDE" in env else None


# --------------------------------------------------------------------------- build


def display_arg(arg: str) -> str:
    """Render one command-line argument without absolute paths."""
    prefix, value = "", arg
    if arg.startswith("-D") and "=" in arg:
        prefix, _, value = arg.partition("=")
        prefix += "="
    if Path(value).is_absolute():
        return prefix + rel(value)
    return arg


def run(cmd: list[str], env: dict[str, str], verbose: bool) -> None:
    shown = " ".join(display_arg(c) for c in cmd)
    print(f"$ {sanitize(shown)}")
    res = subprocess.run(cmd, env=env, capture_output=True)
    output = res.stdout.decode("utf-8", errors="replace") + res.stderr.decode("utf-8", errors="replace")
    if verbose or res.returncode != 0:
        print(sanitize(output).rstrip())
    if res.returncode != 0:
        raise SystemExit(f"build_native: command failed with exit code {res.returncode}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--clean", action="store_true", help="delete dsp/build/ before building")
    parser.add_argument("--verbose", action="store_true", help="show CMake and compiler output")
    args = parser.parse_args()

    if args.clean and BUILD_ROOT.exists():
        shutil.rmtree(BUILD_ROOT)
        print(f"removed {rel(BUILD_ROOT)}/")

    vs = find_vs_installation()
    cmake = find_cmake(vs)
    if cmake is None:
        print("build_native: CMake not found (install CMake or the Visual Studio C++ workload).")
        return 2

    env = dict(os.environ)
    if IS_WINDOWS and shutil.which("cl") is None:
        msvc = msvc_environment(vs)
        if msvc is None:
            print("build_native: no MSVC environment (vcvars64.bat) found.")
            return 2
        env = msvc
        print("using the MSVC x64 environment from Visual Studio (vcvars64)")

    ninja = find_ninja(vs, env)
    if ninja is not None:
        generator, gen_args = "Ninja", ["-DCMAKE_MAKE_PROGRAM=" + str(ninja)]
    elif IS_WINDOWS:
        generator, gen_args = "NMake Makefiles", []
    else:
        generator, gen_args = None, []

    build_dir = BUILD_ROOT / ("cmake-" + (generator or "default").lower().replace(" ", "-"))
    configure = [str(cmake), "-S", str(SRC_DIR), "-B", str(build_dir), "-DCMAKE_BUILD_TYPE=Release"]
    if generator:
        configure += ["-G", generator]
    configure += gen_args
    run(configure, env, args.verbose)
    run([str(cmake), "--build", str(build_dir), "--config", "Release", "--parallel"], env, args.verbose)

    built = [p for name in LIB_NAMES for p in build_dir.rglob(name) if p.is_file()]
    if not built:
        print(f"build_native: no shared library found under {rel(build_dir)}/")
        return 1
    LIB_DIR.mkdir(parents=True, exist_ok=True)
    for lib in built:
        target = LIB_DIR / lib.name
        shutil.copy2(lib, target)
        print(f"built {rel(target)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
