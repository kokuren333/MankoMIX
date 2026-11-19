#!/usr/bin/env python3
"""Build the GitHub Pages demo dataset from a MankoMIX project (docs/SPEC.md 11.4, 15.2, 15.3).

Every number in the dataset comes from the core through ``core/api.py`` (the same calls the
local GUI server makes); nothing is hand-written or invented. Variants of the sample set that
the project has not rendered (or not analysed / verified) are listed as unavailable, never
fabricated. Audio is written only with ``--mp3``: MP3 320 kbps listening copies of the
rendered masters, encoded by an external ffmpeg process with libmp3lame. They are listening
copies, not masters (SPEC 5.3, 15.3).

When a variant's mix carries director-layer moves, the variant is labelled by its direction
(read from the direction document stored inside the project); the objective x profile stays
recorded as the floor the direction was applied on top of, never as the headline.

Usage:
    python -I tools/build_demo_data.py --project <song.mmx> [--out tmp/demo_data]
        [--variants-from samples/sample_set.json | --project-variants] [--slot N=PROJECT ...]
        [--floor N=PROJECT ...] [--official-manifest manifest.json] [--mp3] [--ffmpeg PATH]

The default output folder is ``tmp/demo_data`` (gitignored). Writing into ``gui/public/demo``
replaces the committed placeholder. Audio there is not committed until the owner approves the M9
public audit (D-061), and after that only at release milestones (SPEC 15.3).
Layout: gui/DEMO_DATA.md. Exit code 0 on success, 1 when the build fails, 2 on usage errors.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))   # -I drops the script folder; the package lives at the repo root

GENERATOR = "tools/build_demo_data.py"
DEFAULT_OUT = REPO / "tmp" / "demo_data"
DEFAULT_SAMPLE_SET = REPO / "samples" / "sample_set.json"
MP3_BITRATE_KBPS = 320
MP3_RATES = (32000, 44100, 48000)
FFMPEG_TIMEOUT_S = 600

# Canonical definition files copied verbatim (same list as gui/scripts/sync-definitions.mjs).
DEFINITIONS = (
    ("objectives/catalog.json", "definitions/objectives.json"),
    ("profiles/media_profiles.json", "definitions/media_profiles.json"),
    ("profiles/delivery_formats.json", "definitions/delivery_formats.json"),
    ("registry/models.json", "definitions/models.json"),
)
# Everything the builder owns inside --out (removed before a rebuild; other files are left alone).
MANAGED = ("index.json", "project.json", "history.json", "definitions", "variants", "audio")
STAGE_ORDER = {"cleanup": 0, "mix": 1, "master": 2}

# Anything that looks like a local absolute location or a personal address must not be written.
_FORBIDDEN = {
    "windows absolute path": re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]"),
    "UNC path": re.compile(r"\\\\[^\\\s]+\\"),
    "posix absolute path": re.compile(
        r"(?:^|[\s\"'(=,;])/(?:Users|home|mnt|media|Volumes|private|tmp|var|opt|root|srv|usr|etc)/"),
    "file URL": re.compile(r"file:/", re.IGNORECASE),
    "e-mail address": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"),
}


class BuildError(Exception):
    """A build failure with a message that never contains an absolute path."""


def _label(ja: str, en: str) -> dict:
    return {"ja": ja, "en": en}


def _display(p: Path) -> str:
    """A path for messages: relative to the current folder when it lies inside it, else the bare name.

    A relative path that climbs out of the current folder ("../../tmp/...") would still spell out
    the absolute location, so it is never shown."""
    try:
        rel = Path(os.path.relpath(p)).as_posix()
    except ValueError:
        return p.name
    return p.name if rel == ".." or rel.startswith("../") else rel


# ---------------------------------------------------------------------------
# Hygiene
# ---------------------------------------------------------------------------

def _local_roots(project_root: Path) -> list[str]:
    roots = {project_root, REPO, Path.home(), Path.cwd(), Path(tempfile.gettempdir())}
    out = set()
    for r in roots:
        try:
            s = str(r.resolve())
        except OSError:
            continue
        if len(s) > 3:
            out.add(s.lower())
            out.add(s.replace("\\", "/").lower())
    return sorted(out, key=len, reverse=True)


def find_leaks(obj: Any, roots: list[str], where: str = "") -> list[str]:
    """JSON pointers of strings that carry an absolute path, a local root or an e-mail address."""
    found: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            found += find_leaks(k, roots, f"{where}/{k}[key]") if isinstance(k, str) else []
            found += find_leaks(v, roots, f"{where}/{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            found += find_leaks(v, roots, f"{where}/{i}")
    elif isinstance(obj, str):
        low = obj.lower()
        if any(r in low for r in roots):
            found.append(f"{where or '/'}: local folder")
        for what, pat in _FORBIDDEN.items():
            if pat.search(obj):
                found.append(f"{where or '/'}: {what}")
    return found


def _logical_asset_path(path: Any) -> Any:
    """Asset paths are project-relative; anything else becomes the logical 'linked/<name>'."""
    if not isinstance(path, str):
        return path
    p = path.replace("\\", "/")
    if p.startswith("/") or re.match(r"^[A-Za-z]:/", p) or p.startswith("~") or ".." in p.split("/"):
        return "linked/" + p.rstrip("/").rsplit("/", 1)[-1]
    return p


def sanitise_project(data: dict) -> dict:
    data = json.loads(json.dumps(data))
    for a in data.get("assets") or []:
        if isinstance(a, dict) and "path" in a:
            a["path"] = _logical_asset_path(a["path"])
    for r in data.get("references") or []:
        if isinstance(r, dict) and "path" in r:
            r["path"] = _logical_asset_path(r["path"])
    return data


# ---------------------------------------------------------------------------
# Listening copies (external ffmpeg + libmp3lame)
# ---------------------------------------------------------------------------

class Mp3Encoder:
    def __init__(self, exe: str):
        self.exe = exe
        from mankomix.core import api
        ver = subprocess.run([exe, "-hide_banner", "-version"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=30, stdin=subprocess.DEVNULL)
        enc = subprocess.run([exe, "-hide_banner", "-encoders"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=30, stdin=subprocess.DEVNULL)
        if not re.search(r"^\s*A\S*\s+libmp3lame\s", enc.stdout or "", re.MULTILINE):
            raise BuildError("ffmpeg has no libmp3lame encoder; MP3 listening copies cannot be made")
        build = api.parse_ffmpeg_build(ver.stdout or "")
        self.info = {"tool": "ffmpeg", "version": build.get("version"), "build": build.get("build"),
                     "license": build.get("license"), "codec": "libmp3lame",
                     "bitrate_kbps": MP3_BITRATE_KBPS, "mode": "CBR",
                     "options": ["-c:a", "libmp3lame", "-b:a", f"{MP3_BITRATE_KBPS}k", "-map_metadata", "-1",
                                 "-id3v2_version", "0", "-write_id3v1", "0", "-fflags", "+bitexact",
                                 "-flags:a", "+bitexact"]}

    @staticmethod
    def _rate(src: Path) -> int:
        import soundfile as sf
        sr = int(sf.info(str(src)).samplerate)
        if sr in MP3_RATES:
            return sr
        return 44100 if sr % 44100 == 0 else 48000

    def encode(self, src: Path, dst: Path, gain_db: float | None = None) -> None:
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(f".{dst.stem}.{os.getpid()}.tmp.mp3")
        cmd = [self.exe, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
               "-map", "0:a:0", "-vn"]
        if gain_db is not None and gain_db != 0.0:
            cmd += ["-af", f"volume={gain_db:.2f}dB"]
        cmd += ["-ar", str(self._rate(src))] + self.info["options"] + [str(tmp)]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                 timeout=FFMPEG_TIMEOUT_S, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError) as e:
            raise BuildError(f"ffmpeg failed on {src.name}: {type(e).__name__}") from None
        if res.returncode != 0 or not tmp.is_file():
            tmp.unlink(missing_ok=True)
            raise BuildError(f"ffmpeg failed on {src.name} (exit {res.returncode})")
        os.replace(tmp, dst)


def find_ffmpeg(explicit: str | None) -> str | None:
    if explicit:
        return explicit if Path(explicit).is_file() else shutil.which(explicit)
    return shutil.which("ffmpeg")


# ---------------------------------------------------------------------------
# Variant selection (sample set numbering)
# ---------------------------------------------------------------------------

def _single_objective(v: dict) -> str | None:
    blend = ((v.get("objective") or {}).get("blend") or [])
    ids = [b.get("id") for b in blend if isinstance(b, dict) and float(b.get("weight") or 0) > 0]
    return ids[0] if len(ids) == 1 else None


def _intensity_ok(v: dict, want: Any) -> bool:
    got = v.get("intensity")
    if want is None or got is None:
        return True
    return math.isclose(float(got), float(want), abs_tol=1e-6)


def plan_entries(sample_set: dict | None, project_variants: list[dict], profiles: dict[str, dict],
                 warn) -> list[dict]:
    """The demo variants: the sample set in order (or the project's own variants), each with the
    matching project variant id or None."""
    entries: list[dict] = []
    if sample_set is None:
        for i, v in enumerate(project_variants, start=1):
            entries.append({"n": i, "objective": (v.get("objectives") or [None])[0], "profile": v.get("profile"),
                            "role": "main" if i == 1 else None, "deliveries": v.get("deliveries") or [],
                            "intensity": v.get("intensity"), "delta": i == 1, "level_matched_pair_file": i == 1,
                            "project_variant": v})
        return entries
    default_intensity = sample_set.get("intensity")
    used: set[str] = set()
    for s in sample_set.get("variants") or []:
        cands = [v for v in project_variants
                 if v.get("id") not in used and v.get("profile") == s.get("profile")
                 and _single_objective(v) == s.get("objective")]
        good = [v for v in cands if _intensity_ok(v, default_intensity)]
        if cands and not good:
            warn(f"#{s.get('n')}: project variant(s) {', '.join(sorted(v['id'] for v in cands))} have a "
                 f"different intensity than the sample set ({default_intensity}); not used")
        good.sort(key=lambda v: (not v.get("rendered"), str(v.get("id"))))
        if len(good) > 1:
            warn(f"#{s.get('n')}: several project variants match; using {good[0]['id']}")
        match = good[0] if good else None
        if match is not None:
            used.add(match["id"])
        planned = s.get("deliveries") or [d for d in [(profiles.get(s.get("profile")) or {}).get("default_delivery")] if d]
        entries.append({"n": s.get("n"), "objective": s.get("objective"), "profile": s.get("profile"),
                        "role": s.get("role"), "deliveries": (match or {}).get("deliveries") or planned,
                        "intensity": (match or {}).get("intensity", default_intensity) if match else default_intensity,
                        "delta": bool(s.get("delta")), "level_matched_pair_file": bool(s.get("level_matched_pair_file")),
                        "project_variant": match})
    for v in project_variants:
        if v.get("id") not in used:
            warn(f"project variant {v.get('id')} is not part of the sample set; not included")
    return entries


def project_path(value: str) -> Path:
    path = Path(value)
    return (path.parent if path.name == "project.json" else path).resolve()


def parse_assignments(values: list[str], option: str) -> dict[int, Path]:
    """Parse numbered project assignments; shared by future numbered input options."""
    assignments = {}
    for value in values:
        number, sep, path = value.partition("=")
        if not sep or not number.isdecimal() or int(number) < 1 or not path.strip():
            raise BuildError(f"{option} expects N=<project> with N >= 1")
        n = int(number)
        if n in assignments:
            raise BuildError(f"{option}: duplicate assignment for #{n}")
        assignments[n] = project_path(path)
        if not (assignments[n] / "project.json").is_file():
            raise BuildError(f"{option} #{n}: not a MankoMIX project (no project.json)")
    return assignments


def assign_slots(entries: list[dict], slots: dict[int, Path], variants, option="--slot") -> None:
    """Resolve overrides independently of the default project's variant ids and used set."""
    by_n = {e["n"]: e for e in entries}
    for n, project in slots.items():
        if n not in by_n:
            raise BuildError(f"{option} #{n}: no such slot")
        e = by_n[n]
        matches = [v for v in variants(project)
                   if v.get("profile") == e["profile"] and _single_objective(v) == e["objective"]
                   and (e["intensity"] is None or v.get("intensity") is not None)
                   and _intensity_ok(v, e["intensity"])]
        if len(matches) != 1:
            raise BuildError(f"{option} #{n}: expected exactly 1 variant matching "
                             f"{e['objective']} x {e['profile']} x {e['intensity']}; found {len(matches)}")
        e["project_variant"] = matches[0]
        e["deliveries"] = matches[0].get("deliveries") or e["deliveries"]


def _sha256(path: Path) -> str:
    try:
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()
    except OSError:
        raise BuildError("cannot read before source for sha256 comparison") from None


# ---------------------------------------------------------------------------
# Direction (director layer) metadata
# ---------------------------------------------------------------------------

def direction_ids(props: list[dict]) -> list[str]:
    """Direction ids applied in a proposal list, in first-use order.

    Director-layer steps carry a ``move_ref`` of the form "<direction id>/<move>"
    (their processor is owned by "director"); template steps never do.
    """
    ids: list[str] = []
    for p in props:
        for st in p.get("steps") or []:
            proc = (st or {}).get("processor") or {}
            ref = proc.get("move_ref") or ""
            if isinstance(ref, str) and "/" in ref:
                did = ref.split("/", 1)[0]
                if did and did not in ids:
                    ids.append(did)
    return ids


def _frontmatter(text: str) -> dict[str, str]:
    """The scalar frontmatter block of a Markdown document (direction documents)."""
    if not text.startswith("---"):
        return {}
    out: dict[str, str] = {}
    for line in text.splitlines()[1:]:
        if line.strip() == "---":
            break
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$", line)
        if m:
            v = m.group(2).strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            out[m.group(1)] = v
    return out


def _direction_meta(project_root: Path, did: str) -> dict | None:
    """Frontmatter of the direction document the project itself stores
    (<project>/directions/<id>.md), or None when it is not there. Only the
    id / pattern / request / title scalars are taken; the document stays behind."""
    p = project_root / "directions" / f"{did}.md"
    if not p.is_file():
        return None
    try:
        fm = _frontmatter(p.read_text(encoding="utf-8"))
    except OSError:
        return None
    if fm.get("id") != did:
        return None
    meta: dict[str, Any] = {"id": did}
    for key in ("pattern", "request", "title"):
        if fm.get(key):
            meta[key] = fm[key]
    return meta


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def _proposal_key(p: dict) -> tuple:
    return (STAGE_ORDER.get(str(p.get("stage")), 9), str(p.get("created_at") or ""), str(p.get("id") or ""))


def _labels(items: list[dict]) -> dict[str, dict]:
    out = {}
    for it in items:
        lab = it.get("label")
        if isinstance(lab, dict):
            out[it.get("id")] = {"ja": lab.get("ja") or lab.get("en") or it.get("id"),
                                 "en": lab.get("en") or lab.get("ja") or it.get("id")}
        else:
            out[it.get("id")] = {"ja": lab or it.get("id"), "en": lab or it.get("id")}
    return out


def three_way_gains(after: dict, floor: dict) -> dict[str, float]:
    """Combine the directed and floor pairs arithmetically, without measuring audio."""
    differences = {"before": 0.0}
    for side, pair in (("after", after), ("floor", floor)):
        gain, target = pair.get("match_gain_db"), pair.get("match_target")
        if not isinstance(gain, (int, float)) or not math.isfinite(gain) or gain > 0 or \
                target not in ("before", "after"):
            raise BuildError(f"{side}: invalid core level-match pair")
        differences[side] = gain if target == "before" else -gain
    lowest = min(differences.values())
    return {side: round(lowest - differences[side], 2) for side in ("before", "floor", "after")}


class Builder:
    def __init__(self, project: Path, out: Path, sample_set_path: Path | None, encoder: Mp3Encoder | None,
                 warn=None, *, slots: dict[int, Path] | None = None,
                 floors: dict[int, Path] | None = None, official_manifest: Path | None = None):
        from mankomix.core import api
        self.api = api
        self.project = project
        self.out = out
        self.sample_set_path = sample_set_path
        self.encoder = encoder
        self.slots = slots or {}
        self.floors = floors or {}
        self.official = None
        if official_manifest is not None:
            try:
                self.official = json.loads(official_manifest.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                raise BuildError(f"cannot read official manifest: {e}") from None
        self.expected_mp3: dict[str, str] = {}
        self.warn = warn or (lambda msg: print(f"warning: {msg}", file=sys.stderr))
        self.files: dict[str, Any] = {}           # demo-relative path -> JSON object
        self.audio_jobs: dict[str, tuple] = {}    # demo-relative path -> (source Path, gain or None)

    # -- core calls --

    def _try(self, what: str, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs), None
        except self.api.NotGenerated:
            return None, what
        except self.api.MankoError as e:
            self.warn(f"{what}: {e.message}")
            return None, what

    def _source(self, rel: str | None, project: Path | None = None) -> Path | None:
        """A project-relative file from the core as a readable file inside the project (or None)."""
        if not rel or rel.startswith(("external/", "linked/")):
            return None
        project = project or self.project
        p = (project / rel).resolve()
        try:
            p.relative_to(project)
        except ValueError:
            return None
        return p if p.is_file() else None

    def _audio(self, dst: str, rel: str | None, gain_db: float | None = None,
               *, project: Path | None = None) -> str | None:
        if self.encoder is None:
            return None
        src = self._source(rel, project)
        if src is None:
            if rel:
                self.warn(f"{rel}: not readable inside the project (linked asset?); no listening copy")
            return None
        prev = self.audio_jobs.get(dst)
        if prev is not None and prev != (src, gain_db):
            if (dst in {"audio/before.mp3", "audio/delta.mp3", "audio/fullmix_reference.mp3",
                        "audio/before_level_matched.mp3"}
                    and prev[1] == gain_db and _sha256(prev[0]) == _sha256(src)):
                return dst
            raise BuildError(f"two different sources for {dst}")
        self.audio_jobs[dst] = (src, gain_db)
        return dst

    def build(self) -> dict:
        api = self.api
        proj = str(self.project)
        project_data = api.project_get(proj)["value"]
        hist = api.history(proj, limit=None)
        catalogue = api.objective_list(full=True)
        profiles_full = api.profile_list(full=True)
        obj_labels = _labels(catalogue.get("objectives") or [])
        prof_by_id = {p.get("id"): p for p in profiles_full.get("profiles") or []}
        prof_labels = _labels(profiles_full.get("profiles") or [])
        project_variants = api.variant_list(proj)["variants"]

        sample_set = None
        if self.sample_set_path is not None:
            try:
                sample_set = json.loads(self.sample_set_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                raise BuildError(f"cannot read the sample set {self.sample_set_path.name}: {e}") from None
        entries = plan_entries(sample_set, project_variants, prof_by_id, self.warn)
        variant_cache = {self.project: project_variants}

        def variants(project):
            if project not in variant_cache:
                variant_cache[project] = api.variant_list(str(project))["variants"]
            return variant_cache[project]

        assign_slots(entries, self.slots, variants)
        floor_entries = [dict(e) for e in entries]
        assign_slots(floor_entries, self.floors, variants, "--floor")
        floor_by_n = {e["n"]: e for e in floor_entries if e["n"] in self.floors}
        contexts = {}
        for project in set(self.slots.values()):
            data = api.project_get(str(project))["value"]
            history = api.history(str(project), limit=None)
            history_entries = [dict(x, summary=x.get("reason") or x.get("op"))
                               for x in history.get("entries") or []]
            content_hash = next((x.get("after_hash") for x in reversed(history_entries)
                                 if x.get("after_hash")), None)
            contexts[project] = (data, {"entries": history_entries},
                                 {"project_id": data.get("id"), "content_hash": content_hash})

        # Preserve the legacy layout without overrides; multi-project builds share by content.
        befores: dict[str, str] = {}      # before identity -> demo audio path
        before_hash = None
        variants_index = []
        for e in entries:
            project = self.slots.get(e["n"], self.project)
            proj = str(project)
            vid = f"v{int(e['n']):02d}"
            pv = e["project_variant"]
            item = {"id": vid, "n": e["n"], "objective": e["objective"], "profile": e["profile"],
                    "role": e["role"], "deliveries": list(e["deliveries"]), "intensity": e["intensity"],
                    "label": {lang: f"{(obj_labels.get(e['objective']) or {}).get(lang, e['objective'])} × "
                                    f"{(prof_labels.get(e['profile']) or {}).get(lang, e['profile'])}"
                              for lang in ("ja", "en")},
                    "dir": f"variants/{vid}/", "project_variant": pv.get("id") if pv else None,
                    "available": False}
            variants_index.append(item)
            if e["n"] in self.slots:
                item["source"] = contexts[project][2]
            if e["n"] in self.floors and (pv is None or not pv.get("rendered")):
                raise BuildError(f"--floor #{e['n']}: directed slot must be available")
            if pv is None:
                item["unavailable_reason"] = "not_in_project"
                continue
            if not pv.get("rendered"):
                item["unavailable_reason"] = "not_rendered"
                continue
            # Only rendered slots share audio; audio_set may write derived project files.
            # Keep the comparison even when no listening copies are requested.
            slot_audio = None
            if self.slots:
                slot_audio = api.audio_set(proj, pv["id"])
                before = self._source((slot_audio.get("files") or {}).get("before"), project)
                if before is None:
                    raise BuildError(f"#{e['n']}: before source is not readable for sha256 comparison")
                digest = _sha256(before)
                if before_hash is not None and before_hash != digest:
                    raise BuildError(f"#{e['n']}: before source sha256 differs from other slots")
                before_hash = digest
            pid = pv["id"]
            analysis, m1 = self._try("analysis", api.analysis_view, proj, pid)
            verification, m2 = self._try("verification", api.verification_get, proj, pid)
            audio, m3 = (slot_audio, None) if slot_audio is not None else self._try("audio", api.audio_set, proj, pid)
            rep_ja, m4 = self._try("report", lambda: api.report(proj, pid, lang="ja", write=False)["report"])
            rep_en, m5 = self._try("report", lambda: api.report(proj, pid, lang="en", write=False)["report"])
            missing = sorted({m for m in (m1, m2, m3, m4, m5) if m})
            if missing:
                if e["n"] in self.floors:
                    raise BuildError(f"--floor #{e['n']}: directed slot is incomplete")
                item["unavailable_reason"] = "incomplete"
                item["missing"] = missing
                continue
            props = [p for p in api.proposal_list(proj)["proposals"]
                     if p.get("variant") == pid or (p.get("variant") is None and p.get("stage") in ("cleanup", "mix"))]
            props.sort(key=_proposal_key)
            dids = direction_ids(props)
            if dids:
                meta = _direction_meta(project, dids[0]) or {"id": dids[0]}
                item["direction"] = meta
                req = meta.get("request") or meta.get("title")
                if req:
                    # The headline is the direction; the objective x profile is its floor.
                    pat = f" {meta['pattern']}" if meta.get("pattern") else ""
                    item["label"] = {
                        "ja": f"指揮書{pat}「{req}」 × "
                              f"{(prof_labels.get(e['profile']) or {}).get('ja', e['profile'])}"
                              f"（土台: {(obj_labels.get(e['objective']) or {}).get('ja', e['objective'])}）",
                        "en": f"Direction{pat} \"{req}\" × "
                              f"{(prof_labels.get(e['profile']) or {}).get('en', e['profile'])}"
                              f" (floor: {(obj_labels.get(e['objective']) or {}).get('en', e['objective'])})",
                    }
            item["available"] = True
            d = item["dir"]
            self.files[d + "analysis.json"] = analysis
            self.files[d + "plan.json"] = {"proposals": props}
            self.files[d + "verify.json"] = verification
            self.files[d + "report.ja.json"] = rep_ja
            self.files[d + "report.en.json"] = rep_en
            self.files[d + "audio.json"] = self._audio_json(vid, e, audio, befores, project)
            if self.official is not None:
                self._official_audio(vid, audio, verification, project, bool(dids))
            if e["n"] in self.floors:
                self._floor(vid, floor_by_n[e["n"]], self.floors[e["n"]],
                            project, audio, dids, item)
            if e["n"] in self.slots:
                item["project"] = d + "project.json"
                item["history"] = d + "history.json"
                self.files[item["project"]] = sanitise_project(contexts[project][0])
                self.files[item["history"]] = contexts[project][1]

        if self.official is not None:
            published = (sample_set or {}).get("published")
            if published is None:
                raise BuildError("official mode requires sample_set published metadata")
            by_n = {v["n"]: v for v in variants_index}
            for n in published.get("verified") or []:
                if n not in by_n or not by_n[n]["available"]:
                    raise BuildError(f"published.verified #{n} is unavailable")
            for stopped in published.get("stopped") or []:
                n = stopped["n"]
                if n not in by_n or by_n[n]["available"]:
                    raise BuildError(f"published.stopped #{n} is available or missing")
                by_n[n].update(stopped={k: stopped[k] for k in ("at", "rule")},
                               unavailable_reason="not_rendered")

        title = project_data.get("title") or (sample_set or {}).get("title") or "MankoMIX"
        entries_h = [dict(x, summary=x.get("reason") or x.get("op")) for x in hist.get("entries") or []]
        last_hash = next((x.get("after_hash") for x in reversed(entries_h) if x.get("after_hash")), None)
        index = {
            "schema_version": 1,
            "synthetic": False,
            "generator": {"name": GENERATOR, "version": self._engine_version(),
                          "note": "Built from the core (core/api.py); not hand-written (SPEC 11.4)."},
            "title": _label(str(title), str(title)),
            "notice": _label(
                "事前に計算した結果です。音声は試聴用の MP3 で、マスターではありません。" if self.encoder else
                "事前に計算した結果です。このデータには音声を含みません。",
                "Precomputed results. Audio files are MP3 listening copies, not masters." if self.encoder else
                "Precomputed results. This dataset contains no audio."),
            "project": "project.json",
            "history": "history.json",
            "definitions": {"objectives": "definitions/objectives.json",
                            "profiles": "definitions/media_profiles.json",
                            "deliveries": "definitions/delivery_formats.json",
                            "models": "definitions/models.json"},
            "intensity": (sample_set or {}).get("intensity", 0.5),
            "variants": variants_index,
            "verification_only_profiles": list((sample_set or {}).get("verification_only_profiles") or []),
            "source": {"project_id": project_data.get("id"), "content_hash": last_hash,
                       "sample_set": self._logical(self.sample_set_path) if self.sample_set_path else None},
            "audio": ({"included": True, "format": "mp3", "listening_copies": True, "masters": False,
                       "encoder": self.encoder.info,
                       "files": sorted(self.audio_jobs)} if self.encoder else
                      {"included": False, "format": None, "listening_copies": True, "masters": False,
                       "encoder": None, "files": []}),
        }
        self.files["index.json"] = index
        self.files["project.json"] = sanitise_project(project_data)
        self.files["history.json"] = {"entries": entries_h}

        roots = _local_roots(self.project)
        for project in self.slots.values():
            roots.extend(_local_roots(project))
        for project in self.floors.values():
            roots.extend(_local_roots(project))
        leaks = [f"{name}{p}" for name, obj in sorted(self.files.items()) for p in find_leaks(obj, roots)]
        if leaks:
            raise BuildError("refusing to write: absolute paths or addresses in the dataset:\n  "
                             + "\n  ".join(leaks[:20]))
        self._write()
        result = {"out": _display(self.out),
                "available": [v["id"] for v in variants_index if v["available"]],
                "unavailable": {v["id"]: v.get("unavailable_reason") for v in variants_index if not v["available"]},
                "audio_files": len(self.audio_jobs), "json_files": len(self.files) + len(DEFINITIONS)}
        if self.official is not None:
            result["mp3_sha256_verification"] = "passed" if self.encoder else "skipped (JSON-only: no MP3 files)"
        return result

    def _manifest_variant(self, vid: str) -> dict:
        matches = [v for v in self.official.get("variants", []) if v.get("id") == vid]
        if len(matches) != 1:
            raise BuildError(f"official manifest: expected one variant {vid}")
        return matches[0]

    @staticmethod
    def _check_match(audio: dict, expected: dict | None, label: str) -> None:
        if not expected or audio.get("match_gain_db") != expected.get("gain_db") or \
                audio.get("match_target") != expected.get("lowered_side", expected.get("target")):
            raise BuildError(f"{label}: level_match mismatch")

    def _expect(self, dst: str, digest: str | None) -> None:
        if not digest:
            raise BuildError(f"official manifest: missing MP3 sha256 for {dst}")
        if dst in self.expected_mp3 and self.expected_mp3[dst] != digest:
            raise BuildError(f"official manifest: conflicting MP3 sha256 for {dst}")
        self.expected_mp3[dst] = digest

    def _master(self, project: Path, verification: dict, delivery: str | None) -> str:
        matches = [o.get("file") for o in verification.get("outputs") or []
                   if o.get("delivery") == delivery and o.get("file")]
        if not delivery or len(matches) != 1 or self._source(matches[0], project) is None:
            raise BuildError(f"official manifest: delivery master {delivery!r} is not readable")
        return matches[0]

    def _listening_values(self, vid: str, audio: dict, record: dict, project: Path,
                          master: str, label: str) -> dict:
        """Measure the encoding source and verify its published provenance (PM gate 2)."""
        from tools.build_samples import level_match, proxies

        delivery = (record.get("listening_copy") or {}).get("of_master")
        rows = [m for m in record.get("masters") or [] if m.get("delivery") == delivery]
        if len(rows) != 1:
            raise BuildError(f"{label}: expected one of_master in manifest masters")
        source = self._source(master, project)
        if source is None or _sha256(source) != rows[0].get("sha256"):
            raise BuildError(f"{label}: master sha256 mismatch")
        before = self._source((audio.get("files") or {}).get("before"), project)
        if before is None:
            raise BuildError(f"{label}: before source is not readable")

        def measured(path):
            p = proxies(self.api.measure_audio(str(path))["vector"])
            return {k: p[k] for k in ("lufs_i", "true_peak_dbtp")}

        b, a = measured(before), measured(source)
        core_before = (audio.get("measurements") or {}).get("before") or {}
        if b != {k: core_before.get(k) for k in b}:
            raise BuildError(f"{label}: before measurements mismatch")
        expected = rows[0].get("measured") or {}
        if a != {k: expected.get(k) for k in a}:
            raise BuildError(f"{label}: after LUFS/TP mismatch")
        lm = level_match(b["lufs_i"], a["lufs_i"])
        pair = {"match_gain_db": lm["gain_db"], "match_target": lm["target"]}
        self._check_match(pair, record.get("level_match"), label)
        self._check_match(audio, (record.get("level_match") or {}).get("core_audio_set"),
                          f"{label} core_audio_set")
        if vid != "v08" and (pair["match_gain_db"], pair["match_target"]) != \
                (audio.get("match_gain_db"), audio.get("match_target")):
            raise BuildError(f"{label}: listening/core pair differs outside v08; PM review required")
        return {**pair, "measurements": a, "after_master": delivery,
                "core_audio_set": {"gain_db": audio.get("match_gain_db"),
                                   "target": audio.get("match_target"),
                                   "measurements": audio.get("measurements") or {}}}

    def _official_audio(self, vid: str, audio: dict, verification: dict,
                        project: Path, directed: bool) -> None:
        record = self._manifest_variant(vid)
        main = self.official.get("main_sample") or {}
        is_main = directed and main.get("of") == vid
        uses_listening_values = not is_main and vid in {f"v{n:02d}" for n in range(2, 9)}
        if is_main:
            self._check_match(audio, main.get("level_match"), vid)
        elif not uses_listening_values:
            self._check_match(audio, record.get("level_match"), vid)
        data = self.files[f"variants/{vid}/audio.json"]
        files = data["files"]
        if not is_main:
            listening = record.get("listening_copy") or {}
            master = self._master(project, verification, listening.get("of_master"))
            if uses_listening_values:
                values = self._listening_values(vid, audio, record, project, master, vid)
                data.update({k: v for k, v in values.items() if k != "measurements"})
                data["measurements"] = {**data["measurements"], "after": values["measurements"]}
            dst = f"variants/{vid}/after.mp3"
            self.audio_jobs.pop(dst, None)
            files["after"] = self._audio(dst, master, project=project)
            data["source_files"]["after"] = master
            matched = files.get("after_level_matched")
            if matched:
                self.audio_jobs.pop(matched, None)
                files["after_level_matched"] = self._audio(matched, master, data["match_gain_db"], project=project)
        if self.encoder is None:
            return
        for key, dst in files.items():
            if dst is None:
                continue
            if key == "after":
                digest = ((main.get("mp3") or {}).get("main") or {}).get("sha256") if is_main else \
                    (record.get("listening_copy") or {}).get("mp3_sha256")
            elif key in ("after_level_matched", "before_level_matched"):
                digest = ((main.get("mp3") or {}).get("level_matched") or {}).get("sha256") if is_main else \
                    ((self.official.get("audio") or {}).get("level_matched_pair") or {}).get("mp3_sha256")
            else:
                digest = ((self.official.get("audio") or {}).get(key) or {}).get("mp3_sha256")
            self._expect(dst, digest)

    def _floor(self, vid: str, entry: dict, project: Path, directed_project: Path,
               directed_audio: dict, dids: list[str], item: dict) -> None:
        pv = entry["project_variant"]
        if not dids:
            raise BuildError(f"--floor {vid}: slot has no direction_ids")
        props = self.api.proposal_list(str(project))["proposals"]
        if direction_ids(props):
            raise BuildError(f"--floor {vid}: floor must have no direction_ids")
        if not pv.get("rendered"):
            raise BuildError(f"--floor {vid}: floor is not rendered")
        verification, missing = self._try("verification", self.api.verification_get, str(project), pv["id"])
        if missing:
            raise BuildError(f"--floor {vid}: floor is not verified")
        audio = self.api.audio_set(str(project), pv["id"])
        src = audio.get("files") or {}
        before = self._source(src.get("before"), project)
        directed_before = self._source((directed_audio.get("files") or {}).get("before"), directed_project)
        if before is None or directed_before is None or _sha256(before) != _sha256(directed_before):
            raise BuildError(f"--floor {vid}: before source sha256 differs or is unreadable")
        if self._source(src.get("after"), project) is None:
            raise BuildError(f"--floor {vid}: floor master is not readable")
        data = self.api.project_get(str(project))["value"]
        hist = self.api.history(str(project), limit=None).get("entries") or []
        content_hash = next((h.get("after_hash") for h in reversed(hist) if h.get("after_hash")), None)
        measurements = (audio.get("measurements") or {}).get("after") or {}
        floor = {"project_variant": audio.get("variant"), "project_id": data.get("id"),
                 "content_hash": content_hash, "objective": entry["objective"], "profile": entry["profile"],
                 "measurements": measurements, "match_gain_db": audio.get("match_gain_db"),
                 "match_target": "floor" if audio.get("match_target") == "after" else audio.get("match_target"),
                 "source_files": {k: v for k, v in sorted(src.items()) if v}}
        master = src.get("after")
        floor_pair = audio
        if self.official is not None:
            record = self._manifest_variant(vid)
            master = self._master(project, verification, (record.get("listening_copy") or {}).get("of_master"))
            if vid == "v01":
                values = self._listening_values(vid, audio, record, project, master, f"{vid} floor")
                floor_pair = values
                floor.update(values)
                floor["match_target"] = "floor" if values["match_target"] == "after" else values["match_target"]
                floor["source_files"] = {**floor["source_files"], "after": master}
                measurements = values["measurements"]
            else:
                self._check_match(audio, record.get("level_match"), f"{vid} floor")
        dst = f"variants/{vid}/floor.mp3"
        aj = self.files[f"variants/{vid}/audio.json"]
        aj["files"]["floor"] = self._audio(dst, master, project=project)
        if self.official is not None and self.encoder:
            self._expect(dst, (record.get("listening_copy") or {}).get("mp3_sha256"))
        aj["floor"] = floor
        aj["measurements"] = {**aj["measurements"], "floor": measurements}
        aj["level_match_gains_db"] = three_way_gains(directed_audio, floor_pair)
        item["floor"] = {k: floor[k] for k in ("objective", "profile", "project_id")}

    def _audio_json(self, vid: str, e: dict, audio: dict, befores: dict[str, str],
                    project: Path | None = None) -> dict:
        src = audio.get("files") or {}
        gain = audio.get("match_gain_db")
        target = audio.get("match_target")
        files: dict[str, Any] = {"before": None, "after": None, "delta": None,
                                 "before_level_matched": None, "fullmix_reference": None}
        b_rel = src.get("before")
        if b_rel:
            key = _sha256(self._source(b_rel, project)) if self.slots else b_rel
            dst = befores.get(key) or ("audio/before.mp3" if not befores else f"audio/before_{vid}.mp3")
            files["before"] = self._audio(dst, b_rel, project=project)
            if files["before"]:
                befores[key] = dst
        files["after"] = self._audio(f"variants/{vid}/after.mp3", src.get("after"), project=project)
        if e["delta"]:
            files["delta"] = self._audio("audio/delta.mp3", src.get("delta"), project=project)
        if src.get("fullmix_reference"):
            files["fullmix_reference"] = self._audio("audio/fullmix_reference.mp3", src.get("fullmix_reference"), project=project)
        if e["level_matched_pair_file"] and isinstance(gain, (int, float)):
            # SPEC 15.3: only the main pair gets a level-matched file; the louder side is lowered.
            if target == "before":
                files["before_level_matched"] = self._audio("audio/before_level_matched.mp3", b_rel, float(gain), project=project)
            elif target == "after":
                files["after_level_matched"] = self._audio(f"variants/{vid}/after_level_matched.mp3",
                                                           src.get("after"), float(gain), project=project)
        note = audio.get("note")
        if self.encoder is None:
            note = _label("音声を含まないデータ（JSON のみ）。", "JSON-only dataset: no audio files.")
        return {"variant": vid, "project_variant": audio.get("variant"), "before_kind": audio.get("before_kind"),
                "files": files, "match_gain_db": gain, "match_target": target,
                "measurements": audio.get("measurements") or {}, "note": note,
                "source_files": {k: v for k, v in sorted(src.items()) if v},
                "listening_copies": {"format": "mp3", "bitrate_kbps": MP3_BITRATE_KBPS, "masters": False}
                if self.encoder else None}

    @staticmethod
    def _engine_version() -> str:
        import mankomix
        return str(getattr(mankomix, "ENGINE_VERSION", getattr(mankomix, "__version__", "unknown")))

    @staticmethod
    def _logical(p: Path) -> str:
        try:
            return p.resolve().relative_to(REPO).as_posix()
        except ValueError:
            return p.name

    def _write(self) -> None:
        out = self.out
        out.mkdir(parents=True, exist_ok=True)
        for name in MANAGED:
            t = out / name
            if t.is_dir():
                shutil.rmtree(t)
            elif t.exists():
                t.unlink()
        for src, dst in DEFINITIONS:
            (out / dst).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO / src, out / dst)
        for rel, obj in sorted(self.files.items()):
            p = out / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            text = json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True, allow_nan=False) + "\n"
            p.write_text(text, encoding="utf-8", newline="\n")
        for rel, (src, gain) in sorted(self.audio_jobs.items()):
            self.encoder.encode(src, out / rel, gain)
            if self.official is not None:
                if rel not in self.expected_mp3 or _sha256(out / rel) != self.expected_mp3[rel]:
                    raise BuildError(f"official MP3 sha256 mismatch: {rel}")


def _check_out(out: Path) -> None:
    if out.exists() and not out.is_dir():
        raise BuildError(f"--out is not a folder: {out.name}")
    if out.is_dir() and any(out.iterdir()) and not (out / "index.json").is_file():
        raise BuildError(f"--out {out.name} is not empty and holds no demo dataset (no index.json); "
                         "choose an empty folder")


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(prog="build_demo_data.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--project", required=True, help="project folder (or its project.json)")
    ap.add_argument("--out", default=None, help="output folder (default: tmp/demo_data, gitignored)")
    ap.add_argument("--slot", action="append", default=[], metavar="N=PROJECT",
                    help="build slot N from this project (repeatable; exactly one matching variant required)")
    ap.add_argument("--floor", action="append", default=[], metavar="N=PROJECT",
                    help="attach an undirected, rendered and verified floor to slot N")
    ap.add_argument("--official-manifest", type=Path, help="strict official sample validation manifest")
    grp = ap.add_mutually_exclusive_group()
    grp.add_argument("--variants-from", default=None,
                     help="sample set manifest giving the variant list and numbering (default: samples/sample_set.json)")
    grp.add_argument("--project-variants", action="store_true",
                     help="list the project's own variants instead of a sample set")
    ap.add_argument("--mp3", action="store_true", help="write MP3 320 kbps listening copies (needs ffmpeg + libmp3lame)")
    ap.add_argument("--ffmpeg", default=None, help="ffmpeg executable (default: ffmpeg on PATH)")
    args = ap.parse_args(argv)

    project = project_path(args.project)
    if not (project / "project.json").is_file():
        print(f"error: not a MankoMIX project (no project.json): {project.name}", file=sys.stderr)
        return 2
    out = Path(args.out).resolve() if args.out else DEFAULT_OUT
    sample_set = None if args.project_variants else Path(args.variants_from or DEFAULT_SAMPLE_SET).resolve()
    if sample_set is not None and not sample_set.is_file():
        print(f"error: sample set not found: {sample_set.name}", file=sys.stderr)
        return 2
    try:
        slots = parse_assignments(args.slot, "--slot")
        floors = parse_assignments(args.floor, "--floor")
        _check_out(out)
        encoder = None
        if args.mp3:
            exe = find_ffmpeg(args.ffmpeg)
            if not exe:
                raise BuildError("--mp3 needs ffmpeg (with libmp3lame) on PATH or --ffmpeg")
            encoder = Mp3Encoder(exe)
        from mankomix.core.errors import MankoError
        try:
            result = Builder(project, out, sample_set, encoder, slots=slots, floors=floors,
                             official_manifest=args.official_manifest).build()
        except MankoError as e:
            raise BuildError(f"{e.code if hasattr(e, 'code') else 'error'}: {e.message}") from None
    except BuildError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
