"""File input adapter (docs/SPEC.md 6.1.1-6.1.3).

Takes a folder (stems with an optional full mix), a single file (2mix) or a
list of files, exactly as downloaded (A-12): no conversion, resampling,
normalising, renaming or reordering. Files are copied byte for byte into the
project's assets/ folder (sha256 verified before and after) or linked in place
(the real location is stored outside the project file, SPEC 9.1).
"""

from __future__ import annotations

import re
import shutil
import unicodedata
from pathlib import Path
from typing import Any, Iterable

from .. import audio_io
from ..errors import InputError
from ..ingest import naming
from ..ingest.checks import length_at_rate, resolve_timebase, run_checks
from .base import SourceAdapter, register_adapter

# Default stem importance (SPEC 4.11): lead > rhythm core > low end > harmony > pads/fx.
DEFAULT_IMPORTANCE = {
    "vocals": 1.0,
    "drums": 0.8, "percussion": 0.8,
    "bass": 0.7,
    "guitar": 0.5, "keyboard": 0.5, "synth": 0.5, "strings": 0.5, "brass": 0.5,
    "woodwinds": 0.5, "backing_vocals": 0.5,
    "fx": 0.3, "other": 0.3,
}

_SUBTYPE_TAG = {"FLOAT": "f32", "DOUBLE": "f64", "PCM_16": "pcm16", "PCM_24": "pcm24",
                "PCM_32": "pcm32", "PCM_S8": "pcm8", "PCM_U8": "pcm8"}
_CONTAINER_TAG = {"wavex": "wav", "rf64": "wav", "aif": "aiff"}
_IGNORED_PREFIXES = ("._", ".")


def format_tag(container: str, subtype: str, lossy: bool) -> str:
    """'wav_f32', 'wav_pcm24', 'flac_pcm16', ... (lossy files: container only)."""
    c = (container or "unknown").lower()
    c = _CONTAINER_TAG.get(c, c)
    if lossy:
        return c
    s = (subtype or "unknown").upper()
    return f"{c}_{_SUBTYPE_TAG.get(s, s.lower())}"


def slugify(text: str) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")


def _unique(base: str, taken: set[str]) -> str:
    if base not in taken:
        return base
    i = 2
    while f"{base}_{i}" in taken:
        i += 1
    return f"{base}_{i}"


def _unique_filename(name: str, taken: set[str]) -> str:
    """Keep the original name when free; otherwise add a numeric suffix."""
    if name.casefold() not in taken:
        return name
    p = Path(name)
    i = 2
    while f"{p.stem}_{i}{p.suffix}".casefold() in taken:
        i += 1
    return f"{p.stem}_{i}{p.suffix}"


def _sha256(path: Path) -> str:
    from ..hashing import sha256_file  # contract: core/hashing.py
    return sha256_file(path)


@register_adapter
class FileAdapter(SourceAdapter):
    id = "file"

    # ------------------------------------------------------------------ scan
    def _scan(self, src: Any) -> dict:
        """Resolve src into audio files. Only the given folder level is read."""
        ignored: list[dict] = []
        single = False
        if isinstance(src, (str, Path)):
            p = Path(src)
            if p.is_dir():
                candidates = sorted(p.iterdir(), key=lambda q: q.name)
            elif p.is_file():
                candidates, single = [p], True
            else:
                raise InputError(f"input not found: {p.name}")
        elif isinstance(src, Iterable):
            candidates = [Path(s) for s in src]
            for c in candidates:
                if not c.is_file():
                    raise InputError(f"input file not found: {c.name}")
        else:
            raise InputError("src must be a folder, a file or a list of files")
        files: list[Path] = []
        for c in candidates:
            if c.is_dir():
                ignored.append({"name": c.name, "reason": "subfolder (not searched)"})
            elif c.name.startswith(_IGNORED_PREFIXES):
                ignored.append({"name": c.name, "reason": "hidden or system file"})
            elif not audio_io.is_audio_file(c):
                ignored.append({"name": c.name, "reason": "not an audio file"})
            else:
                files.append(c)
        if not files:
            raise InputError("no audio files found in the input", details={"ignored": ignored})
        if single and len(files) != 1:
            single = False
        return {"files": files, "ignored": ignored, "single": single}

    def _classify(self, src: Any) -> tuple[dict, dict]:
        scan = self._scan(src)
        names = [f.name for f in scan["files"]]
        cls = naming.classify(names, single_file=scan["single"])
        by_name: dict[str, list[Path]] = {}
        for f in scan["files"]:
            by_name.setdefault(f.name, []).append(f)
        for e in cls["entries"]:
            e["_path"] = by_name[e["original_name"]].pop(0)
        return scan, cls

    # ----------------------------------------------------------------- probe
    def probe(self, src: Any) -> dict:
        """Describe what would be imported. Reads names only; writes nothing."""
        scan, cls = self._classify(src)
        files = [{"original_name": e["original_name"], "role": e["role"], "role_source": e["role_source"],
                  "role_note": e.get("role_note", ""), "number": e["number"],
                  "derived_sum": e["derived_sum"]} for e in cls["entries"]]
        return {
            "adapter": self.id,
            "kind": cls["kind"],
            "input_kind": cls["input_kind"],
            "detected_by": cls["detected_by"],
            "pattern_set": cls["pattern_set"],
            "service": (cls["provenance_hint"] or {}).get("service"),
            "title": cls["title"],
            "files": files,
            "ignored": scan["ignored"],
            "warnings": list(cls["warnings"]),
        }

    # ----------------------------------------------------------------- fetch
    def fetch(self, src: Any, project: Any, *, mode: str = "copy", provenance: dict | None = None,
              actor: str = "human", reason: str | None = None, roles: dict[str, str] | None = None,
              include_derived: bool = False, **_: Any) -> dict:
        """Import src into project as-is and return the import record.

        mode="copy": byte-for-byte copy into assets/ (sha256 verified).
        mode="link": no copy; the asset is recorded as linked and its real
        location is stored with config.set_linked_location (outside the project).
        roles: optional {original_name: role} declared by the user.
        """
        if mode not in ("copy", "link"):
            raise InputError(f"unknown import mode: {mode!r} (use 'copy' or 'link')")
        scan, cls = self._classify(src)
        data = project.data
        root = Path(project.root)
        assets: list[dict] = data.setdefault("assets", [])
        tracks: list[dict] = data.setdefault("tracks", [])
        vocab = set(naming.load_knowledge("ingest_patterns").get("role_vocabulary", []))
        warnings = list(cls["warnings"])

        known_sha = {a["sha256"]: a["id"] for a in assets}
        asset_ids = {a["id"] for a in assets}
        track_ids = {t["id"] for t in tracks}
        clip_ids = {c["id"] for t in tracks for c in t.get("clips", [])}
        taken_paths = {Path(a["path"]).name.casefold() for a in assets}
        assets_dir = root / "assets"
        if mode == "copy":
            assets_dir.mkdir(parents=True, exist_ok=True)
            taken_paths |= {p.name.casefold() for p in assets_dir.iterdir()}

        files_rec: list[dict] = []
        skipped: list[dict] = []
        new_assets: list[dict] = []
        written: list[Path] = []
        try:
            for e in cls["entries"]:
                path: Path = e["_path"]
                name = e["original_name"]
                role, role_source = e["role"], e["role_source"]
                if e["derived_sum"] and not include_derived:
                    skipped.append({"original_name": name, "reason": "derived_sum"})
                    continue
                if roles and name in roles:
                    role, role_source = roles[name], naming.RS_USER
                    e["role_note"] = naming.NOTE_USER
                    if role not in vocab:
                        raise InputError(f"unknown role {role!r} for {name}", details={"vocabulary": sorted(vocab)})
                sha = _sha256(path)
                if sha in known_sha:
                    skipped.append({"original_name": name, "reason": "duplicate", "sha256": sha,
                                    "duplicate_of": known_sha[sha]})
                    warnings.append(f"'{name}' has the same content as {known_sha[sha]}; not imported again")
                    continue
                ai = audio_io.info(path)
                stored = _unique_filename(name, taken_paths)
                taken_paths.add(stored.casefold())
                if stored != name:
                    warnings.append(f"'{name}' stored as '{stored}' (name already used in the project)")
                if mode == "copy":
                    dest = assets_dir / stored
                    shutil.copyfile(path, dest)
                    written.append(dest)
                    after = _sha256(dest)
                    if after != sha:
                        raise InputError(f"copy verification failed for {name}: sha256 differs",
                                         details={"before": sha, "after": after})
                    rel = f"assets/{stored}"
                else:
                    from ..config import set_linked_location  # contract: core/config.py
                    set_linked_location(sha, str(path.resolve()))
                    rel = f"linked/{stored}"
                is_fullmix = role == "fullmix"
                slug = "fullmix" if is_fullmix else (
                    role if role != "other" else (slugify(e.get("part_name") or Path(name).stem) or "other"))
                aid = _unique(f"ast_{slug}", asset_ids)
                asset_ids.add(aid)
                asset = {
                    "id": aid, "path": rel, "original_name": name, "sha256": sha,
                    "format": format_tag(ai.container, ai.subtype, ai.lossy),
                    "container": ai.container, "subtype": ai.subtype, "lossy": bool(ai.lossy),
                    "channels": ai.channels, "sample_rate": ai.sample_rate,
                    "length_samples": ai.frames, "duration_s": round(ai.duration_s, 6),
                    "role": role, "role_source": role_source, "role_note": e.get("role_note", ""),
                    "origin": "reference_fullmix" if is_fullmix else "native_stem",
                    "linked": mode == "link",
                }
                known_sha[sha] = aid
                new_assets.append(asset)
                files_rec.append({"original_name": name, "sha256": sha, "asset": aid})
        except Exception:
            for w in written:  # leave no half-imported copies behind
                try:
                    w.unlink()
                except OSError:
                    pass
            raise

        assets.extend(new_assets)
        all_assets = assets
        tb = resolve_timebase(all_assets) if all_assets else None
        pr = tb["sample_rate"] if tb else None

        # Full mix: registered as a reference, never as a track (SPEC 6.1.3).
        new_fullmix = [a for a in new_assets if a["role"] == "fullmix"]
        if new_fullmix:
            if data.get("fullmix_asset") and data["fullmix_asset"] in {a["id"] for a in assets}:
                warnings.append("project already has a full mix (" + data["fullmix_asset"] + "); "
                                + ", ".join(a["id"] for a in new_fullmix) + " kept as extra asset(s)")
            else:
                data["fullmix_asset"] = new_fullmix[0]["id"]
                for extra in new_fullmix[1:]:
                    warnings.append(f"{extra['id']} is an extra full-mix candidate (asset only)")
        else:
            data.setdefault("fullmix_asset", None)

        new_tracks = []
        for a in new_assets:
            if a["role"] == "fullmix":
                continue
            slug = a["id"][len("ast_"):]
            tid = _unique(f"trk_{slug}", track_ids)
            track_ids.add(tid)
            cid = _unique(f"clp_{slug}", clip_ids)
            clip_ids.add(cid)
            length = (a["length_samples"] if pr is None else
                      length_at_rate(a["length_samples"], a["sample_rate"], pr))
            track = {
                "id": tid, "kind": "audio", "role": a["role"], "is_lead": False,
                "importance": {"value": DEFAULT_IMPORTANCE.get(a["role"], 0.3), "source": "default",
                               "by_section": {}},
                "clips": [{"id": cid, "asset": a["id"], "source_start": 0, "length": length,
                           "timeline_start": 0, "gain_db": 0.0, "fade_in": 0, "fade_out": 0,
                           "muted": False}],
                "cleanup": {"enabled": True, "plan": "auto", "overrides": {}},
                "chain": [], "gain_db": 0.0, "pan": {"position": 0.0, "width": 1.0},
                "sends": [], "output": "bus_mix",
            }
            tracks.append(track)
            new_tracks.append(track)

        # Lead: the single "vocals" track, as an estimate, unless one is already set.
        objective = data.get("objective") if isinstance(data.get("objective"), dict) else None
        lead_estimate = None
        if not any(t.get("is_lead") for t in tracks) and not (objective or {}).get("lead_stem"):
            vocal_tracks = [t for t in tracks if t.get("role") == "vocals"]
            if len(vocal_tracks) == 1:
                vocal_tracks[0]["is_lead"] = True
                if objective is not None:
                    objective["lead_stem"] = vocal_tracks[0]["id"]
                lead_estimate = {"track": vocal_tracks[0]["id"],
                                 "basis": "only track with role 'vocals' (estimate)"}
            elif len(vocal_tracks) > 1:
                warnings.append("several 'vocals' tracks: lead stem not inferred")

        # Buses: make sure the default output exists.
        buses = data.setdefault("buses", [])
        if not any(b.get("id") == "bus_mix" for b in buses):
            buses.append({"id": "bus_mix", "kind": "mix", "chain": []})

        # Provenance.
        hint = cls["provenance_hint"] or {}
        prov_new = {
            "source": hint.get("source"), "service": hint.get("service"),
            "input_kind": cls["input_kind"], "detected_by": cls["detected_by"],
            "declared_by_user": False,
            "notes": "detected from file name pattern (estimate)" if cls["detected_by"] else "",
        }
        if provenance:
            prov_new.update({k: v for k, v in provenance.items() if k != "declared_by_user"})
            prov_new["declared_by_user"] = True
        existing = data.get("provenance")
        if provenance or not existing or not existing.get("input_kind"):
            data["provenance"] = prov_new

        # Timebase (conform policy; nothing is converted here, D-054).
        if tb:
            timebase = data.setdefault("timebase", {})
            timebase["sample_rate"] = tb["sample_rate"]
            timebase["length_samples"] = tb["length_samples"]
            timebase["conform_policy"] = tb["conform_policy"]

        # Ingest record.
        ingest = data.get("ingest")
        if not isinstance(ingest, dict) or not ingest:
            ingest = {"adapter": self.id, "input_kind": cls["input_kind"], "detected_by": cls["detected_by"],
                      "files": [], "skipped": [], "checks": [], "conform": {}}
            data["ingest"] = ingest
        ingest.setdefault("files", []).extend(files_rec)
        # Re-importing the same folder must not pile up identical skip records.
        known_skips = {(s.get("original_name"), s.get("reason"), s.get("sha256"))
                       for s in ingest.setdefault("skipped", [])}
        for s in skipped:
            key = (s.get("original_name"), s.get("reason"), s.get("sha256"))
            if key not in known_skips:
                known_skips.add(key)
                ingest["skipped"].append(s)
        if lead_estimate:
            ingest["lead_estimate"] = lead_estimate
        checks = run_checks(project) if all_assets else []
        ingest["checks"] = checks
        if tb:
            rates: dict[str, int] = {}
            for a in all_assets:
                rates[str(a["sample_rate"])] = rates.get(str(a["sample_rate"]), 0) + 1
            ingest["conform"] = {"sample_rate": tb["sample_rate"], "length_samples": tb["length_samples"],
                                 "rates": rates, "policy": tb["conform_policy"]}

        n_reject = sum(1 for c in checks if c["level"] == "reject")
        n_warn = sum(1 for c in checks if c["level"] == "warning")
        project.save(actor=actor, op="import",
                     reason=reason or (f"import {len(new_assets)} file(s) as {cls['input_kind']} "
                                       f"({mode}); checks: {n_reject} reject, {n_warn} warning"))

        return {
            "adapter": self.id, "mode": mode, "kind": cls["kind"], "input_kind": cls["input_kind"],
            "detected_by": cls["detected_by"], "pattern_set": cls["pattern_set"],
            "files": files_rec, "skipped": skipped, "ignored": scan["ignored"],
            "assets_added": [a["id"] for a in new_assets], "tracks_added": [t["id"] for t in new_tracks],
            "fullmix_asset": data.get("fullmix_asset"), "lead_estimate": lead_estimate,
            "provenance": data.get("provenance"), "conform": ingest.get("conform", {}),
            "checks": checks, "warnings": warnings,
            "rejects": [c for c in checks if c["level"] == "reject"],
        }

