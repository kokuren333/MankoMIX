#!/usr/bin/env python3
"""Build the official sample set from the tool's own commands (docs/SPEC.md 15.1-15.4, 16.2).

Every audio file is produced by MankoMIX itself; nothing is hand-made:

* each sample variant of ``samples/sample_set.json`` (objective x media profile, intensity 0.5,
  genre ``hiphop``, no references: D-039, D-040, D-053) is one ``python -m mankomix.cli run``
  in its own project (one project per variant, so that a send-back or a failed verification of
  one variant never stops the others; the mix of a variant is planned with its own objective);
* "before" (SPEC 15.2, D-036) is the core's unity-gain stem sum (``listen``, core/api.py
  ``audio_set``); the conformed full mix is the reference; the level-match gain lowers the louder
  side; the cleanup delta belongs to the main sample;
* measurements come from ``measure`` (``measure_audio``), the translation gate from ``gate``
  (``gate_check``), verification and Mix Reports from ``run`` (``verify`` / ``report``).

Outputs
-------
``samples/public/`` (``--public``)
    ``manifest.json`` (machine-readable list of every audio item with measurements, level-match
    gains, verification, translation gate, the verification-only profiles table, input hashes and
    the regeneration commands), ``reports/vNN/`` (Mix Report JSON + Markdown ja/en, verification)
    and ``audio/*.mp3``: MP3 320 kbps LISTENING COPIES made by an external ffmpeg process
    (libmp3lame). They are not masters (SPEC 5.3, 15.3) and are not committed until the owner
    approves the M9 public audit (D-061; ``*.mp3`` is gitignored).
``tmp/release_assets/`` (``--release``, gitignored)
    the lossless masters in their delivery formats, nothing else (future Release attachment).
``tmp/sample_build/<kind>/`` (``--work``, gitignored)
    the projects, run logs and the prepared input folder.

Inputs (never written into any output; give them from outside)
-------------------------------------------------------------
``--source-kind conformed`` (default, the canonical set): ``MANKOMIX_SAMPLE_DIR`` or ``--source``.
    The 12 stems and ``fullmix_conformed.wav`` are selected by name. ``other`` and ``no_vocals``
    (derived sums, D-037) and ``0_fullmix`` (the unaligned download; a folder import would take it
    as the full mix) are excluded explicitly and the exclusion is recorded in the manifest.
``--source-kind export``: ``MANKOMIX_SAMPLE_EXPORT_DIR`` or ``--source``. The Suno Studio
    download folder is passed to ``run`` exactly as downloaded (SPEC 15.1: "drop it in as-is").

Usage::

    MANKOMIX_SAMPLE_DIR=<folder> python -I tools/build_samples.py [--variants 1,8] [--jobs 2]
    MANKOMIX_SAMPLE_EXPORT_DIR=<folder> python -I tools/build_samples.py --source-kind export

Exit codes: 0 manifest written (failed verifications are legitimate outcomes and are recorded),
1 a run errored or the outputs would leak a local path, 2 usage / input errors.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import copy
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))   # -I drops the script folder; the package lives at the repo root

GENERATOR = "tools/build_samples.py"
MANIFEST_SCHEMA_VERSION = 1
DEFAULT_SAMPLE_SET = REPO / "samples" / "sample_set.json"
ENV_DIR = {"conformed": "MANKOMIX_SAMPLE_DIR", "export": "MANKOMIX_SAMPLE_EXPORT_DIR"}
PLACEHOLDER = {k: f"${v}" for k, v in ENV_DIR.items()}
WORK_PLACEHOLDER = "$WORK"
AUDIO_SUFFIXES = {".wav", ".flac", ".aif", ".aiff"}

# The conform set (SPEC 15.1, D-031, D-037).
CONFORM_STEMS = ("backing_vocals", "bass", "brass", "drums", "fx", "guitar", "keyboard", "percussion",
                 "strings", "synth", "vocals", "woodwinds")
CONFORM_FULLMIX = "fullmix_conformed.wav"
EXCLUDED_REASONS = {
    "other": {"code": "derived_sum", "decision": "D-037",
              "en": "derived file: sum of the 8 stems other than vocals, drums and bass; including it would add the "
                    "same audio twice"},
    "no_vocals": {"code": "derived_sum", "decision": "D-037",
                  "en": "derived file: sum of every stem except the vocals; including it would add the same audio twice"},
    "0_fullmix": {"code": "unaligned_fullmix", "decision": "D-031",
                  "en": "the as-downloaded full mix, not time-aligned to the conform set; fullmix_conformed is the "
                        "reference instead (a folder import would take this file as the full mix)"},
}

MP3_BITRATE_KBPS = 320
MP3_RATES = (32000, 44100, 48000)
MP3_OPTIONS = ["-c:a", "libmp3lame", "-b:a", f"{MP3_BITRATE_KBPS}k", "-map_metadata", "-1", "-id3v2_version", "0",
               "-write_id3v1", "0", "-fflags", "+bitexact", "-flags:a", "+bitexact"]
RUN_TIMEOUT_S = 6 * 3600
ACTOR = "agent"
# D-062: the sample audio and input stems are not under the repository's Apache-2.0.
TERMS = {"ja": "Suno で生成。利用条件は Suno の規約に従う。AI の学習への利用は許諾しない。本体の Apache-2.0 の対象外。",
         "en": "Generated with Suno. Use is subject to Suno's terms. Not licensed for AI training. Not covered by "
               "the repository's Apache-2.0 license.",
         "applies_to": "every audio file of the sample set (listening copies, masters, before, delta, reference) "
                       "and the input stems",
         "decision": "D-062"}

_FORBIDDEN = {
    "windows absolute path": re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]"),
    "UNC path": re.compile(r"\\\\[^\\\s]+\\"),
    "posix absolute path": re.compile(
        r"(?:^|[\s\"'(=,;])/(?:Users|home|mnt|media|Volumes|private|tmp|var|opt|root|srv|usr|etc|c|d)/"),
    "file URL": re.compile(r"file:/", re.IGNORECASE),
}


class BuildError(Exception):
    """A build failure whose message never contains an absolute path."""


def _T(ja: str, en: str) -> dict:
    return {"ja": ja, "en": en}


def _r(v: Any, nd: int = 2) -> Any:
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        return round(float(v), nd) if math.isfinite(float(v)) else None
    return v


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _rel_to(path: Path, base: Path) -> str:
    return path.resolve().relative_to(base.resolve()).as_posix()


def _display(path: Path) -> str:
    """A location for console messages: repo-relative when possible, else the bare name."""
    try:
        return _rel_to(path, REPO)
    except ValueError:
        return f"<{path.name}>"


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_") or "x"


# ---------------------------------------------------------------------------
# hygiene
# ---------------------------------------------------------------------------

def _local_roots(extra: list[Path]) -> list[str]:
    roots = set(extra) | {REPO, Path.home(), Path.cwd(), Path(tempfile.gettempdir())}
    out: set[str] = set()
    for r in roots:
        try:
            s = str(Path(r).resolve())
        except OSError:
            continue
        if len(s) > 3:
            out.add(s.lower())
            out.add(s.replace("\\", "/").lower())
    user = Path.home().name.lower()
    if len(user) >= 3:
        out.add(f"/{user}/")
        out.add(f"\\{user}\\")
    return sorted(out, key=len, reverse=True)


def find_leaks(text: str, roots: list[str]) -> list[str]:
    low = text.lower()
    found = [f"local folder ({len(r)} chars)" for r in roots if r in low]
    found += [what for what, pat in _FORBIDDEN.items() if pat.search(text)]
    return found


# ---------------------------------------------------------------------------
# inputs
# ---------------------------------------------------------------------------

def _audio_files(folder: Path) -> list[Path]:
    return sorted((p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_SUFFIXES),
                  key=lambda p: p.name)


def select_inputs(kind: str, folder: Path) -> dict:
    """{files: [Path], inputs: [{file, role}], excluded: [{file, ...}], pass_folder_as_is: bool}."""
    if not folder.is_dir():
        raise BuildError(f"the sample folder given by {ENV_DIR[kind]} / --source is not a folder")
    audio = _audio_files(folder)
    if kind == "export":
        if not audio:
            raise BuildError("no audio files in the export folder")
        return {"files": audio, "inputs": [{"file": p.name, "role": None} for p in audio], "excluded": [],
                "pass_folder_as_is": True}
    by_stem = {p.stem: p for p in audio}
    missing = [f"{n}.wav" for n in CONFORM_STEMS if n not in by_stem] + \
              ([CONFORM_FULLMIX] if (folder / CONFORM_FULLMIX).is_file() is False else [])
    if missing:
        raise BuildError("the conform set is incomplete; missing: " + ", ".join(missing))
    chosen = [by_stem[n] for n in CONFORM_STEMS] + [folder / CONFORM_FULLMIX]
    chosen_names = {p.name for p in chosen}
    inputs = [{"file": by_stem[n].name, "role": "stem"} for n in CONFORM_STEMS] + \
             [{"file": CONFORM_FULLMIX, "role": "reference_fullmix"}]
    excluded = []
    for p in audio:
        if p.name in chosen_names:
            continue
        why = EXCLUDED_REASONS.get(p.stem, {"code": "not_in_conform_set", "decision": "SPEC 15.1",
                                            "en": "not one of the 12 stems or the conformed full mix"})
        excluded.append({"file": p.name, **why})
    return {"files": chosen, "inputs": inputs, "excluded": excluded, "pass_folder_as_is": False}


def input_records_of(sel: dict) -> list[dict]:
    """The input records with content hashes (sha256 of the files as found in the sample folder)."""
    return [{**rec, "sha256": _sha256(p), "bytes": p.stat().st_size} for p, rec in zip(sel["files"], sel["inputs"])]


def run_sources(sel: dict, folder: Path) -> list[str]:
    """What ``run`` gets: the export folder as downloaded, or the explicit list of the 13 selected
    files of the conform set (loose files are imported as one set)."""
    return [str(folder)] if sel["pass_folder_as_is"] else [str(p) for p in sel["files"]]


# ---------------------------------------------------------------------------
# listening copies (external ffmpeg + libmp3lame)
# ---------------------------------------------------------------------------

class Mp3Encoder:
    def __init__(self, exe: str):
        self.exe = exe
        from mankomix.core import api
        ver = subprocess.run([exe, "-hide_banner", "-version"], capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=60, stdin=subprocess.DEVNULL)
        enc = subprocess.run([exe, "-hide_banner", "-encoders"], capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=60, stdin=subprocess.DEVNULL)
        if not re.search(r"^\s*A\S*\s+libmp3lame\s", enc.stdout or "", re.MULTILINE):
            raise BuildError("ffmpeg has no libmp3lame encoder")
        build = api.parse_ffmpeg_build(ver.stdout or "")
        self.info = {"tool": "ffmpeg (external process)", "version": build.get("version"),
                     "license": build.get("license"), "codec": "libmp3lame", "bitrate_kbps": MP3_BITRATE_KBPS,
                     "mode": "CBR", "options": list(MP3_OPTIONS)}

    @staticmethod
    def rate(src: Path) -> int:
        import soundfile as sf
        sr = int(sf.info(str(src)).samplerate)
        return sr if sr in MP3_RATES else (44100 if sr % 44100 == 0 else 48000)

    def encode(self, src: Path, dst: Path, gain_db: float | None = None) -> None:
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(f".{dst.stem}.{os.getpid()}.tmp.mp3")
        cmd = [self.exe, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), "-map", "0:a:0", "-vn"]
        if gain_db:
            cmd += ["-af", f"volume={gain_db:.2f}dB"]
        cmd += ["-ar", str(self.rate(src))] + MP3_OPTIONS + [str(tmp)]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                 timeout=1800, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError) as e:
            raise BuildError(f"ffmpeg failed on {src.name}: {type(e).__name__}") from None
        if res.returncode != 0 or not tmp.is_file():
            tmp.unlink(missing_ok=True)
            raise BuildError(f"ffmpeg failed on {src.name} (exit {res.returncode})")
        os.replace(tmp, dst)


def find_ffmpeg(explicit: str | None) -> str | None:
    if explicit:
        return explicit if Path(explicit).is_file() else shutil.which(explicit)
    from mankomix.core import audio_io
    return audio_io.ffmpeg_path() or shutil.which("ffmpeg")


# ---------------------------------------------------------------------------
# measurements (core ``measure``)
# ---------------------------------------------------------------------------

def proxies(vector: dict) -> dict:
    """Loudness, true peak and the key proxies of a measurement vector (SPEC 4.2)."""
    p03 = vector.get("P-03") or {}
    p05 = vector.get("P-05") or {}
    p06 = vector.get("P-06") or {}
    p07 = vector.get("P-07") or {}
    p14 = vector.get("P-14") or {}
    health = vector.get("health") or {}
    lbp = p05.get("low_band_persistence") or {}
    return {
        "lufs_i": _r(p03.get("integrated_lufs")),
        "true_peak_dbtp": _r(p14.get("true_peak_dbtp", p03.get("true_peak_dbtp"))),
        "sample_peak_dbfs": _r(p03.get("sample_peak_dbfs")),
        "lra_lu": _r(p03.get("lra_lu")),
        "short_term_max_lufs": _r(p03.get("short_term_max_lufs")),
        "plr_db": _r(p03.get("plr_db")),
        "psr_db": _r(p03.get("psr_db")),
        "correlation_full_band": _r((p05.get("full_band") or {}).get("correlation"), 3),
        "low_band_min_correlation": _r(lbp.get("min_correlation"), 3),
        "mono_loss_db_full_band": _r((p06.get("full_band") or {}).get("mono_loss_db"), 3),
        "band_balance_ratio_db": {b: _r(v.get("ratio_db")) for b, v in (p07.get("bands") or {}).items()
                                  if isinstance(v, dict)},
        "clipped_samples": health.get("clipped_samples"),
        "over_full_scale_samples": health.get("over_full_scale_samples"),
        "duration_s": _r(vector.get("duration_s"), 3),
        "sample_rate": vector.get("sample_rate"),
    }


def measure(path: Path, cache: dict) -> dict:
    key = str(path.resolve())
    if key not in cache:
        from mankomix.core import api
        m = api.measure_audio(str(path))
        cache[key] = {"info": {k: m["info"].get(k) for k in ("sample_rate", "channels", "frames", "subtype",
                                                             "container")},
                      "measured": proxies(m["vector"])}
    return cache[key]


def level_match(before_lufs: float | None, after_lufs: float | None) -> dict:
    """SPEC 15.2 / R-01: equal integrated loudness by lowering the louder side."""
    if before_lufs is None or after_lufs is None:
        return {"gain_db": None, "target": None}
    if before_lufs > after_lufs:
        return {"gain_db": round(after_lufs - before_lufs, 2), "target": "before"}
    return {"gain_db": round(before_lufs - after_lufs, 2), "target": "after"}


# ---------------------------------------------------------------------------
# the build
# ---------------------------------------------------------------------------

class Builder:
    def __init__(self, args, sample_set: dict, variants: list[dict], source: Path, work: Path, public: Path,
                 release: Path, encoder: Mp3Encoder | None, log=print):
        self.a = args
        self.kind = args.source_kind
        self.sample_set = sample_set
        self.variants = variants
        self.source = source
        self.work = work
        self.public = public
        self.release = release
        self.encoder = encoder
        self.log = log
        self.title = str(args.title or sample_set.get("title") or "sample")
        self.genre = str(sample_set.get("genre") or "hiphop")
        self.intensity = float(sample_set.get("intensity", 0.5))
        self.mcache: dict = {}
        self.timings: dict = {}
        self.errors: list[str] = []

    # -- commands --

    def _variant_spec(self, s: dict) -> dict:
        prof = s["profile"]
        dels = s.get("deliveries") or [self._default_delivery(prof)]
        return {"objective": f"{s['objective']}:{self.intensity:g}", "profile": prof, "delivery": list(dels)}

    @staticmethod
    def _default_delivery(profile: str) -> str:
        from mankomix.core import config
        return config.get_profile(profile).get("default_delivery") or "hires_native"

    def _pid(self, s: dict) -> str:
        return f"sample_{'export_' if self.kind == 'export' else ''}v{int(s['n']):02d}"

    def _run_args(self, s: dict, sources: list[str], proj_ref: str, out_ref: str) -> tuple[list[str], list[str]]:
        init = ["init", proj_ref, "--title", self.title, "--genre", self.genre, "--project-id", self._pid(s)]
        run = ["run", *sources, "--project", proj_ref, "--out", out_ref, "--genre", self.genre, "--title", self.title,
               "--variants", json.dumps([self._variant_spec(s)], separators=(",", ":"))]
        if self.a.mix_max_iter is not None:
            run += ["--mix-max-iter", str(self.a.mix_max_iter)]
        if self.a.max_iter is not None:
            run += ["--max-iter", str(self.a.max_iter)]
        return init, run

    def _cli(self, argv: list[str], log_file: Path, timeout: float) -> tuple[int, Any]:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(REPO) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        env["PYTHONIOENCODING"] = "utf-8"
        env["MANKOMIX_HOME"] = str(self.work / "home")
        cmd = [sys.executable, "-m", "mankomix.cli", *argv]
        res = subprocess.run(cmd, cwd=str(REPO), env=env, capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=timeout, stdin=subprocess.DEVNULL)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.write_text(res.stdout + ("\n--- stderr ---\n" + res.stderr if res.stderr else ""), encoding="utf-8")
        try:
            out = json.loads(res.stdout)
        except ValueError:
            out = None
        return res.returncode, out

    def vdir(self, s: dict) -> Path:
        return self.work / f"v{int(s['n']):02d}"

    def run_variant(self, s: dict, sources: list[str]) -> dict:
        vd = self.vdir(s)
        done = vd / "run_result.json"
        if self.a.resume and done.is_file():
            rec = json.loads(done.read_text(encoding="utf-8"))
            if rec.get("argv_key") == self._argv_key(s) and rec.get("exit_code") in (0, 1):
                self.log(f"  v{int(s['n']):02d}: reusing the previous run (--resume)")
                return rec
        if vd.exists():
            shutil.rmtree(vd)
        vd.mkdir(parents=True)
        proj, out = vd / "song.mmx", vd / "out"
        init, run = self._run_args(s, sources, str(proj), str(out))
        t0 = time.perf_counter()
        code, res = self._cli(init, vd / "init.log.json", 300)
        if code != 0:
            rec = {"exit_code": code, "result": res, "stage": "init"}
        else:
            code, res = self._cli(run, vd / "run.log.json", RUN_TIMEOUT_S)
            rec = {"exit_code": code, "result": res, "stage": "run"}
        rec["wall_s"] = round(time.perf_counter() - t0, 1)
        rec["argv_key"] = self._argv_key(s)
        done.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        self.log(f"  v{int(s['n']):02d} {s['objective']} x {s['profile']}: exit {code} "
                 f"({(res or {}).get('status') if isinstance(res, dict) else 'no result'}) in {rec['wall_s']} s")
        return rec

    def _argv_key(self, s: dict) -> str:
        init, run = self._run_args(s, ["$IN"], "$P", "$O")
        return hashlib.sha256(json.dumps([init, run, self._input_key], sort_keys=True).encode()).hexdigest()[:16]

    # -- shared items (before, reference, delta) --

    def _proj(self, s: dict) -> Path:
        return (self.vdir(s) / "song.mmx").resolve()

    def _file(self, proj: Path, rel: str | None) -> Path | None:
        if not rel:
            return None
        p = Path(rel)
        for cand in ([p] if p.is_absolute() else [proj / p, REPO / p]):
            if cand.is_file():
                return cand
        return None

    def build(self) -> dict:
        from mankomix import ENGINE_VERSION

        t_build = time.perf_counter()
        sel = select_inputs(self.kind, self.source)
        self.work.mkdir(parents=True, exist_ok=True)
        sources = run_sources(sel, self.source)
        input_records = input_records_of(sel)
        self._input_key = [(r["file"], r["sha256"]) for r in input_records]
        self.log(f"inputs: {len(input_records)} files ({self.kind}); excluded: "
                 + (", ".join(e["file"] for e in sel["excluded"]) or "none"))

        # ---- runs (independent projects, optionally in parallel)
        runs: dict[int, dict] = {}
        jobs = max(1, int(self.a.jobs))
        with cf.ThreadPoolExecutor(max_workers=jobs) as ex:
            futs = {ex.submit(self.run_variant, s, sources): s for s in self.variants}
            for f in cf.as_completed(futs):
                s = futs[f]
                try:
                    runs[s["n"]] = f.result()
                except Exception as e:   # noqa: BLE001 - recorded, the other variants go on
                    runs[s["n"]] = {"exit_code": None, "result": None, "stage": "builder",
                                    "error": f"{type(e).__name__}"}

        # ---- per-variant results
        self.public.mkdir(parents=True, exist_ok=True)
        audio_dir = self.public / "audio"
        report_root = self.public / "reports"
        for d in (audio_dir, report_root):
            if d.exists():
                shutil.rmtree(d)
        if self.release.exists():
            for f in self.release.iterdir():
                if f.is_file() and f.suffix.lower() in AUDIO_SUFFIXES:
                    f.unlink()
        self.release.mkdir(parents=True, exist_ok=True)

        main_s = next((s for s in self.variants if s.get("role") == "main"), None)
        before_shas: dict[str, str] = {}
        shared: dict[str, Any] = {}
        items = []
        mp3_jobs: list[tuple[Path, Path, float | None]] = []
        for s in self.variants:
            t0 = time.perf_counter()
            items.append(self._variant_item(s, runs[s["n"]], before_shas, shared, mp3_jobs))
            self.timings.setdefault(f"v{int(s['n']):02d}", {})["postprocess_s"] = round(time.perf_counter() - t0, 1)

        # ---- shared audio: before, before level-matched (main pair), fullmix reference, delta
        audio = self._shared_audio(main_s, items, shared, mp3_jobs)
        verify_only = self._verify_only(main_s, items)

        # ---- listening copies
        t0 = time.perf_counter()
        if self.encoder is not None:
            for src, dst, gain in mp3_jobs:
                self.encoder.encode(src, dst, gain)
            for rec in self._mp3_records(items, audio):
                p = self.public / rec["file"]
                rec["mp3_sha256"] = _sha256(p)
                rec["mp3_measured"] = {k: measure(p, self.mcache)["measured"][k] for k in ("lufs_i", "true_peak_dbtp")}
        self.timings["listening_copies_s"] = round(time.perf_counter() - t0, 1)

        consistent = len(set(before_shas.values())) <= 1
        manifest = self._manifest(ENGINE_VERSION, sel, input_records, items, audio, verify_only, before_shas,
                                  consistent)
        self.timings["total_s"] = round(time.perf_counter() - t_build, 1)
        manifest["timings"] = self.timings
        self._write_manifest(manifest)
        return manifest

    # ------------------------------------------------------------------

    def _variant_item(self, s: dict, run: dict, before_shas: dict, shared: dict, mp3_jobs: list) -> dict:
        from mankomix.core import api
        vnn = f"v{int(s['n']):02d}"
        res = run.get("result") if isinstance(run.get("result"), dict) else {}
        spec = self._variant_spec(s)
        item: dict[str, Any] = {
            "id": vnn, "n": s["n"], "role": s.get("role"), "objective": s["objective"], "profile": s["profile"],
            "intensity": self.intensity, "deliveries": spec["delivery"], "project_variant": None,
            "run": {"exit_code": run.get("exit_code"), "status": res.get("status"),
                    "stopped_at": res.get("stopped_at"), "reason": res.get("reason"),
                    "error": (res.get("error") or {}).get("code") if isinstance(res.get("error"), dict)
                    else (res.get("error") if res.get("error") else run.get("error")),
                    "route": res.get("route")},
            "stages": {}, "masters": [], "listening_copy": None, "level_match": None,
            "verification": None, "translation_gate": None, "report": None, "send_back": None,
            "unresolved": [{k: u.get(k) for k in ("stage", "code", "rule", "rules", "failed") if u.get(k) is not None}
                           for u in res.get("unresolved") or [] if isinstance(u, dict)],
        }
        self.timings.setdefault(vnn, {}).update({"run_wall_s": run.get("wall_s"),
                                                 "stages_s": res.get("timings") or {}})
        if run.get("exit_code") not in (0, 1) or not res:
            self.errors.append(f"{vnn}: run errored (exit {run.get('exit_code')}, stage {run.get('stage')})")
            return item
        for st in res.get("stages") or []:
            name = st.get("stage")
            brief = {"status": st.get("status")}
            if isinstance(st.get("gate"), dict):
                g = st["gate"]
                brief["gate"] = {k: g.get(k) for k in ("status", "constraints_failed", "of5", "failed", "check",
                                                       "send_back") if k in g}
            if name == "clean":
                brief["cleaned"] = st.get("cleaned") or []
            item["stages"][name] = brief
        vid = (res.get("variants") or [{}])[0].get("id")
        item["project_variant"] = vid
        r = (res.get("results") or {}).get(vid) or {}
        sb = (r.get("master") or {}).get("send_back")
        if sb:
            item["send_back"] = {"rules": sb.get("rules"), "reason": sb.get("reason")}
        master_gate = (r.get("master") or {}).get("gate") or {}
        proj = self._proj(s)
        out_dir = self.vdir(s) / "out" / vid if vid else None

        # verification (run's verify stage)
        if r.get("verify"):
            v = r["verify"]
            item["verification"] = {"passed": v.get("passed"), "overall": v.get("overall"),
                                    "outputs": [{k: o.get(k) for k in ("profile", "delivery", "overall", "failed")}
                                                for o in v.get("outputs") or []]}
        # translation gate: planner's last evaluation (run) + gate on the rendered master
        tg: dict[str, Any] = {"planner": (master_gate.get("of5") or None)}
        if r.get("outputs"):
            try:
                g = api.gate_check(str(proj), vid)
                tg.update({"status": g.get("status"), "source": g.get("source"),
                           "failed": sorted(c.get("id") for c in g.get("checks") or []
                                            if isinstance(c, dict) and c.get("status") == "fail"),
                           "not_evaluated": sorted(c.get("id") for c in g.get("checks") or []
                                                   if isinstance(c, dict) and c.get("status") in
                                                   ("not_evaluated", "not_run"))})
            except api.MankoError as e:
                tg["error"] = e.code
        item["translation_gate"] = tg

        # reports (Mix Report ja + en, JSON + Markdown; verification)
        item["report"] = self._copy_reports(vnn, vid, proj, out_dir, r)

        # masters
        delivered = bool(r.get("verify", {}).get("passed"))
        first = None
        for o in r.get("outputs") or []:
            f = self._file(proj, o.get("file"))
            if f is None:
                continue
            m = measure(f, self.mcache)
            rec = {"delivery": o.get("delivery"), "profile": o.get("profile"), "format": m["info"],
                   "sha256": _sha256(f), "measured": m["measured"], "render_status": o.get("status"),
                   "release_file": None, "withheld": None}
            if delivered:
                name = f"{vnn}_{_slug(s['objective'])}__{_slug(o.get('profile') or '')}__{_slug(o.get('delivery') or '')}{f.suffix}"
                shutil.copyfile(f, self.release / name)
                rec["release_file"] = name
            else:
                rec["withheld"] = "verification failed: not a deliverable master (kept out of the release staging)"
            item["masters"].append(rec)
            if first is None:
                first = (f, rec)
        if first is None:
            return item

        # before (core stem sum) and level match against this variant's listening master
        aset = api.audio_set(str(proj), vid)
        bf = self._file(proj, (aset.get("files") or {}).get("before"))
        if bf is not None:
            before_shas[vnn] = _sha256(bf)
            shared.setdefault("before", (bf, aset.get("before_kind")))
            if aset.get("files", {}).get("fullmix_reference"):
                shared.setdefault("fullmix_reference", self._file(proj, aset["files"]["fullmix_reference"]))
            b = measure(bf, self.mcache)["measured"]
            lm = level_match(b["lufs_i"], first[1]["measured"]["lufs_i"])
            item["level_match"] = {**lm, "after_master": first[1]["delivery"],
                                   "core_audio_set": {"gain_db": aset.get("match_gain_db"),
                                                      "target": aset.get("match_target"),
                                                      "after": "archive_f32 master"}}
        name = f"audio/{vnn}_{_slug(s['objective'])}__{_slug(s['profile'])}.mp3"
        item["listening_copy"] = {"file": name if self.encoder else None, "of_master": first[1]["delivery"],
                                  "is_master": False,
                                  "verification_failed_master": not delivered}
        if self.encoder is not None:
            mp3_jobs.append((first[0], self.public / name, None))
        if s.get("role") == "main":
            shared["main"] = {"item": item, "proj": proj, "vid": vid, "after": first[0], "aset": aset,
                              "cleaned": item["stages"].get("clean", {}).get("cleaned") or []}
        return item

    def _copy_reports(self, vnn: str, vid: str, proj: Path, out_dir: Path | None, r: dict) -> dict:
        from mankomix.core import api
        paths = dict(r.get("report") or {})
        if not paths:
            # the run stopped before the report stage (e.g. a send-back): ask the core for one anyway
            try:
                paths = api.report(str(proj), vid, lang="both", write=True).get("paths") or {}
            except api.MankoError as e:
                return {"status": "not_generated", "reason": e.code}
        dest = self.public / "reports" / vnn
        dest.mkdir(parents=True, exist_ok=True)
        files = {}
        names = {"json": "report.json", "md_ja": "report.ja.md", "md_en": "report.en.md"}
        for key, rel in sorted(paths.items()):
            f = self._file(proj, rel) if isinstance(rel, str) else None
            if f is None:
                continue
            nm = names.get(key) or f"report.{_slug(key)}{f.suffix}"
            shutil.copyfile(f, dest / nm)
            files[key] = f"reports/{vnn}/{nm}"
        vrel = (r.get("verify") or {}).get("path")
        vf = self._file(proj, vrel)
        if vf is not None:
            shutil.copyfile(vf, dest / "verify.json")
            files["verification"] = f"reports/{vnn}/verify.json"
        rep_json = self.public / files["json"] if "json" in files else None
        states = None
        if rep_json is not None:
            txt = rep_json.read_text(encoding="utf-8")
            codes = {n.get("code") for n in (json.loads(txt).get("notes") or []) if isinstance(n, dict)}
            states = {"no_references_note": "generic_prior" in codes, "genre_prior_note": "genre_prior" in codes}
        return {"status": "ok", "files": files, "languages": ["ja", "en"], "states": states}

    def _shared_audio(self, main_s: dict | None, items: list[dict], shared: dict, mp3_jobs: list) -> dict:
        from mankomix.core import api
        out: dict[str, Any] = {}
        b = shared.get("before")
        if b is not None:
            bf, kind = b
            m = measure(bf, self.mcache)
            out["before"] = {"file": "audio/before.mp3" if self.encoder else None,
                             "definition": "unity-gain sum of the 12 stems, stereo as-is, no processing (D-036)",
                             "kind": kind, "made_by": "core listen (audio_set): static stem sum, gain 0 dB",
                             "lossless": {"format": m["info"], "sha256": _sha256(bf)}, "measured": m["measured"]}
            if self.encoder:
                mp3_jobs.append((bf, self.public / "audio/before.mp3", None))
        fm = shared.get("fullmix_reference")
        if fm is not None:
            m = measure(fm, self.mcache)
            out["fullmix_reference"] = {"file": "audio/fullmix_reference.mp3" if self.encoder else None,
                                        "definition": "the service's full mix (conformed), reference only; never "
                                                      "the before baseline (the stem sum does not equal it)",
                                        "lossless": {"format": m["info"], "sha256": _sha256(fm)},
                                        "measured": m["measured"]}
            if self.encoder:
                mp3_jobs.append((fm, self.public / "audio/fullmix_reference.mp3", None))
        main = shared.get("main")
        if main is None or b is None:
            return out
        item = main["item"]
        lm = item.get("level_match") or {}
        if lm.get("gain_db") is not None:
            if lm["target"] == "before":
                name, src = "audio/before_level_matched.mp3", b[0]
            else:
                name, src = f"audio/{item['id']}_level_matched.mp3", main["after"]
            out["level_matched_pair"] = {"file": name if self.encoder else None, "pair": ["before", item["id"]],
                                         "lowered": lm["target"], "gain_db": lm["gain_db"],
                                         "applied_by": "ffmpeg volume filter on the listening copy (static gain)"}
            if self.encoder:
                mp3_jobs.append((src, self.public / name, lm["gain_db"]))
        # cleanup delta of the main sample: core `clean delta stems` (stem sum minus cleaned stem sum)
        proj = main["proj"]
        try:
            d = api.clean_delta(str(proj), "stems")
        except api.MankoError as e:
            out["delta"] = {"file": None, "status": "not_generated", "reason": e.message}
            return out
        df = self._file(proj, d.get("delta"))
        if df is None:
            out["delta"] = {"file": None, "status": "not_generated", "reason": "no delta file"}
            return out
        made_by = "core clean delta stems: unprocessed stem sum minus the cleaned stem sum (unity gain)"
        m = measure(df, self.mcache)
        out["delta"] = {"file": "audio/delta.mp3" if self.encoder else None, "of": item["id"],
                        "definition": "only what the cleanup stage removed (input minus output), main sample",
                        "stems": list(d.get("cleaned") or []), "made_by": made_by,
                        "lossless": {"format": m["info"], "sha256": _sha256(df)}, "measured": m["measured"]}
        if self.encoder:
            mp3_jobs.append((df, self.public / "audio/delta.mp3", None))
        return out

    def _verify_only(self, main_s: dict | None, items: list[dict]) -> dict:
        """Verification-only profiles (SPEC 15.2): the main variant's rendered masters judged against
        each profile by the core (``verify`` with profiles: P-03, S-01, S-02; no re-render, project unchanged)."""
        from mankomix.core import api
        profiles = list(self.sample_set.get("verification_only_profiles") or [])
        table: dict[str, Any] = {"profiles": profiles, "of": None, "rows": [], "method": None}
        main_item = next((i for i in items if i.get("role") == "main"), None)
        if main_s is None or main_item is None or not main_item.get("masters") or not profiles:
            table["status"] = "not_generated"
            table["reason"] = "the main sample was not built or not rendered"
            return table
        proj, vid = str(self._proj(main_s)), main_item["project_variant"]
        before = api.project_get(proj)["value"]
        vr = api.verify(proj, vid, profiles=profiles)
        after = api.project_get(proj)["value"]
        for pid in profiles:
            row = (vr.get("profiles") or {}).get(pid) or {}
            table["rows"].append({
                "profile": pid, "passed": row.get("overall") == "pass", "overall": row.get("overall"),
                "failed": row.get("failed") or [],
                "outputs": [{"delivery": (o.get("rendered_for") or {}).get("delivery"), "overall": o.get("overall"),
                             "failed": o.get("failed") or [],
                             "codecs": sorted(((o.get("checks") or {}).get("S-02") or {}).get("codecs") or {})}
                            for o in row.get("outputs") or []],
            })
        f = self._file(Path(proj), vr.get("path"))
        if f is not None:
            dest = self.public / "reports" / main_item["id"] / "verify_against.json"
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, dest)
        table.update({"of": main_item["id"], "status": "ok", "passed": vr.get("passed"),
                      "checks": vr.get("checks"), "project_unchanged": before == after,
                      "report": f"reports/{main_item['id']}/verify_against.json" if f is not None else None,
                      "method": "core verify with verification-only profiles: the main variant's rendered "
                                "masters (every delivery) judged against each profile's P-03 loudness window, "
                                "S-01 ceiling and S-02 codec round trip, without re-rendering"})
        return table

    def _mp3_records(self, items: list[dict], audio: dict) -> list[dict]:
        recs = [i["listening_copy"] for i in items if i.get("listening_copy") and i["listening_copy"].get("file")]
        recs += [v for v in audio.values() if isinstance(v, dict) and v.get("file")]
        return recs

    # ------------------------------------------------------------------

    def _commands(self, input_records: list[dict], audio: dict) -> dict:
        src = PLACEHOLDER[self.kind]
        sources = [src] if self.kind == "export" else [f"{src}/{r['file']}" for r in input_records]
        per = {}
        for s in self.variants:
            vnn = f"v{int(s['n']):02d}"
            p = f"{WORK_PLACEHOLDER}/{vnn}/song.mmx"
            init, run = self._run_args(s, sources, p, f"{WORK_PLACEHOLDER}/{vnn}/out")
            cmds = [_cmdline(init), _cmdline(run), _cmdline(["listen", "--project", p]),
                    _cmdline(["gate", "--project", p])]
            per[vnn] = cmds
        builder = ["python", "-I", GENERATOR, "--source-kind", self.kind]
        return {
            "placeholders": {src: f"the sample folder, given from outside via {ENV_DIR[self.kind]} (never recorded)",
                             WORK_PLACEHOLDER: f"the build folder (default tmp/sample_build/{self.kind}, gitignored)"},
            "one_shot": " ".join(builder) + (" --variants " + ",".join(str(s["n"]) for s in self.variants)
                                             if len(self.variants) != len(self.sample_set.get("variants") or []) else ""),
            "per_variant": per,
            "main_delta": [_cmdline(["clean", "delta", "stems", "--project",
                                     f"{WORK_PLACEHOLDER}/{(audio.get('delta') or {}).get('of') or 'v01'}/song.mmx"])],
            "verification_only_profiles": [_cmdline(
                ["verify", "--project", f"{WORK_PLACEHOLDER}/v01/song.mmx"]
                + [x for pid in self.sample_set.get("verification_only_profiles") or [] for x in ("--against-profile", pid)])],
            "notes": ["Every command runs from the repository root. Masters, reports and verification come from "
                      "run; before/after/delta files and the level-match gain from listen; the translation gate "
                      "from gate; measurements from measure <file>.",
                      "The MP3 listening copies are made by an external ffmpeg process (libmp3lame, 320 kbps CBR, "
                      "options under listening_copies.encoder)."],
        }

    def _manifest(self, engine: str, sel: dict, input_records: list[dict], items: list[dict], audio: dict,
                  verify_only: dict, before_shas: dict, consistent: bool) -> dict:
        n_all = len(self.sample_set.get("variants") or [])
        return {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "kind": "official_sample_manifest",
            "generator": {"name": GENERATOR, "engine_version": engine,
                          "note": "Every audio file comes from the tool's own commands; nothing is hand-made "
                                  "(SPEC 15.2). Sample folders and absolute paths are never recorded."},
            "title": self.title,
            "terms": TERMS,
            "genre": self.genre,
            "genre_note": "declared, not inferred from audio (D-053)",
            "references": [],
            "references_note": "no references are registered: generic targets and the hiphop genre prior (D-039, "
                               "D-053); each Mix Report states this (report.states.no_references_note)",
            "intensity": self.intensity,
            "sample_set": "samples/sample_set.json",
            "variants_built": [i["id"] for i in items],
            "complete": len(items) == n_all,
            "source": {
                "kind": "conformed_set" if self.kind == "conformed" else "suno_studio_multitrack_export",
                "canonical": self.kind == "conformed",
                "folder": PLACEHOLDER[self.kind],
                "passed_as_is": sel["pass_folder_as_is"],
                "inputs": input_records,
                "excluded": sel["excluded"],
                "selection_note": ("the download folder is the run input exactly as downloaded (no rename, no "
                                   "conversion)" if self.kind == "export" else
                                   "the 12 stems and the conformed full mix are selected by name; every other audio "
                                   "file of the folder is excluded explicitly (listed under excluded). Importing the "
                                   "folder itself would skip other/no_vocals (derived_sum) but take 0_fullmix as the "
                                   "full mix, so the 13 selected files are given to run as an explicit file list "
                                   "(imported as one set, unchanged)"),
            },
            "listening_copies": {
                "format": "mp3", "bitrate_kbps": MP3_BITRATE_KBPS, "masters": False,
                "note": "MP3 files are listening copies made from the masters, NOT masters (SPEC 5.3, 15.3). The "
                        "lossless masters are Release attachments.",
                "committed": False,
                "commit_policy": "audio is not committed until the owner approves the M9 public audit (D-061)",
                "encoder": self.encoder.info if self.encoder else None,
                "generated": self.encoder is not None,
            },
            "release_assets": {"staging": "tmp/release_assets/ (gitignored)",
                               "content": "lossless masters in their delivery formats, only of variants that "
                                          "passed verification"},
            "audio": audio,
            "before_consistency": {"identical_in_every_project": consistent,
                                   "sha256": sorted(set(before_shas.values()))},
            "variants": items,
            "verification_only_profiles": verify_only,
            "summary": {
                "verified": [i["id"] for i in items if (i.get("verification") or {}).get("passed")],
                "failed_verification": [i["id"] for i in items if (i.get("verification") or {}).get("passed") is False],
                "stopped": [{"id": i["id"], "at": i["run"]["stopped_at"]} for i in items
                            if i["run"].get("status") == "stopped"],
                "send_backs": [{"id": i["id"], **(i["send_back"] or {})} for i in items if i.get("send_back")],
                "errors": list(self.errors),
            },
            "regeneration": self._commands(input_records, audio),
        }

    def _write_manifest(self, manifest: dict) -> None:
        roots = _local_roots([self.source, self.work, self.public, self.release])
        text = json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        leaks = find_leaks(text, roots)
        for f in sorted((self.public / "reports").rglob("*")) if (self.public / "reports").is_dir() else []:
            if f.is_file():
                leaks += [f"{f.name}: {x}" for x in find_leaks(f.read_text(encoding="utf-8"), roots)]
        if leaks:
            raise BuildError("refusing to write: local paths in the outputs: " + "; ".join(sorted(set(leaks))[:10]))
        (self.public / "manifest.json").write_text(text, encoding="utf-8", newline="\n")


def _cmdline(argv: list[str]) -> str:
    def q(a: str) -> str:
        if re.fullmatch(r"[A-Za-z0-9_./:=,+-]+", a):
            return a
        if a.startswith("$") and re.fullmatch(r"\$[A-Za-z_]+[A-Za-z0-9_./-]*", a):
            return f'"{a}"'   # placeholder: the shell expands it, the quotes keep spaces in folder names
        return "'" + a.replace("'", "'\"'\"'") + "'"
    return "python -m mankomix.cli " + " ".join(q(a) for a in argv)


def strip_timings(manifest: dict) -> dict:
    """The manifest without run-dependent timings (for determinism checks)."""
    m = copy.deepcopy(manifest)
    m.pop("timings", None)
    return m


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

def _select_variants(sample_set: dict, spec: str | None) -> list[dict]:
    allv = [v for v in sample_set.get("variants") or [] if isinstance(v, dict)]
    if not spec:
        return allv
    want = []
    for part in spec.split(","):
        part = part.strip().lower().lstrip("v")
        if not part:
            continue
        if not part.isdigit():
            raise BuildError(f"--variants takes sample numbers like 1,8,10 (got '{part}')")
        want.append(int(part))
    chosen = [v for v in allv if int(v["n"]) in want]
    unknown = sorted(set(want) - {int(v["n"]) for v in chosen})
    if unknown:
        raise BuildError(f"unknown sample numbers: {unknown}")
    return chosen


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
    ap = argparse.ArgumentParser(prog="build_samples.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--source-kind", choices=("conformed", "export"), default="conformed",
                    help="conformed set (canonical, default) or the as-downloaded export set")
    ap.add_argument("--source", help="sample folder (default: $MANKOMIX_SAMPLE_DIR / $MANKOMIX_SAMPLE_EXPORT_DIR)")
    ap.add_argument("--variants", help="subset of sample numbers, e.g. 1,8 (default: all of the sample set)")
    ap.add_argument("--sample-set", default=str(DEFAULT_SAMPLE_SET), help="sample set definition")
    ap.add_argument("--work", help="build folder (default tmp/sample_build/<kind>)")
    ap.add_argument("--public", help="listening set folder (default samples/public; export: <work>/public)")
    ap.add_argument("--release", help="lossless master staging (default tmp/release_assets; export: <work>/release_assets)")
    ap.add_argument("--jobs", type=int, default=1, help="variants run in parallel (default 1)")
    ap.add_argument("--mix-max-iter", dest="mix_max_iter", type=int, help="passed to run (default: run's)")
    ap.add_argument("--max-iter", dest="max_iter", type=int, help="passed to run (default: run's)")
    ap.add_argument("--title", help="song title (default: the sample set's)")
    ap.add_argument("--no-mp3", dest="no_mp3", action="store_true", help="skip the MP3 listening copies")
    ap.add_argument("--ffmpeg", help="ffmpeg executable (default: on PATH)")
    ap.add_argument("--resume", action="store_true", help="reuse finished runs with identical arguments and inputs")
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    try:
        sample_set = json.loads(Path(a.sample_set).read_text(encoding="utf-8"))
        variants = _select_variants(sample_set, a.variants)
        src_value = a.source or os.environ.get(ENV_DIR[a.source_kind], "").strip()
        if not src_value:
            raise BuildError(f"no sample folder: set {ENV_DIR[a.source_kind]} or pass --source")
        source = Path(src_value).expanduser().resolve()
        work = Path(a.work).resolve() if a.work else REPO / "tmp" / "sample_build" / a.source_kind
        if a.public:
            public = Path(a.public).resolve()
        else:
            public = REPO / "samples" / "public" if a.source_kind == "conformed" else work / "public"
        if a.release:
            release = Path(a.release).resolve()
        else:
            release = REPO / "tmp" / "release_assets" if a.source_kind == "conformed" else work / "release_assets"
        encoder = None
        if not a.no_mp3:
            exe = find_ffmpeg(a.ffmpeg)
            if exe is None:
                print("warning: ffmpeg not found; MP3 listening copies are skipped", file=sys.stderr)
            else:
                encoder = Mp3Encoder(exe)
    except (BuildError, OSError, ValueError) as e:
        print(f"error: {e}" if isinstance(e, BuildError) else f"error: {type(e).__name__}", file=sys.stderr)
        return 2
    b = Builder(a, sample_set, variants, source, work, public, release, encoder,
                log=lambda m: print(m, file=sys.stderr, flush=True))
    try:
        m = b.build()
    except BuildError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1 if not str(e).startswith("the conform set") else 2
    rows = []
    for i in m["variants"]:
        mm = (i["masters"] or [{}])[0].get("measured") or {}
        rows.append({"id": i["id"], "objective": i["objective"], "profile": i["profile"],
                     "lufs_i": mm.get("lufs_i"), "true_peak_dbtp": mm.get("true_peak_dbtp"),
                     "verify": (i.get("verification") or {}).get("overall"),
                     "gate": (i.get("translation_gate") or {}).get("status"),
                     "run": i["run"]["status"], "wall_s": (m["timings"].get(i["id"]) or {}).get("run_wall_s")})
    print(json.dumps({"manifest": _display(public / "manifest.json"), "variants": rows,
                      "verification_only": [(r["profile"], r["overall"]) for r in
                                            m["verification_only_profiles"].get("rows") or []],
                      "errors": m["summary"]["errors"]}, ensure_ascii=False, indent=1))
    return 1 if m["summary"]["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
