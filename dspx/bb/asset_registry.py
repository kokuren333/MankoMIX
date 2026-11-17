"""BB-08/24: reusable pinned catalogues and local BYO registrations.

AssetRegistry(name, catalog_path, metadata, generate=None, validate=None) supplies
catalog(), local(), resolve(id), register_file(...), remove(id), load(id).
Only local settings contain file paths; public records contain IDs and hashes.
Files are hashed on every load and are never copied or downloaded.
"""
from __future__ import annotations
import copy
import hashlib
import json
import os
import re
from pathlib import Path
from mankomix.core import config
from mankomix.dsp.errors import ParamError


def sha256(data):
    return hashlib.sha256(data).hexdigest()


class AssetRegistry:
    def __init__(self, name, catalog_path, metadata, *, generate=None, validate=None):
        if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
            raise ValueError("invalid registry name")
        self.name, self.catalog_path = name, Path(catalog_path)
        self.metadata, self.generate, self.validate = metadata, generate, validate

    @property
    def local_path(self):
        return config.settings_dir() / ("byo_" + self.name + ".json")

    def check(self, doc, *, local=False):
        if not isinstance(doc, dict) or doc.get("schema_version") != 1 or not isinstance(doc.get(self.name), list):
            raise ParamError("invalid asset registry document")
        ids = set()
        for e in doc[self.name]:
            if not isinstance(e, dict):
                raise ParamError("asset entry must be an object")
            key = e.get("id")
            if not isinstance(key, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_.-]*", key) or key in ids:
                raise ParamError("invalid or duplicate asset id")
            ids.add(key)
            if not isinstance(e.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", e["sha256"]):
                raise ParamError("asset requires pinned sha256")
            lic = e.get("license")
            if not isinstance(lic, dict) or not isinstance(lic.get("spdx"), str) or not lic["spdx"].strip():
                raise ParamError("asset license.spdx is required (use unknown when necessary)")
            if not isinstance(lic.get("evidence"), list) or not lic["evidence"] or not isinstance(lic.get("checked_on"), str) or not lic["checked_on"]:
                raise ParamError("asset license evidence and checked_on are required")
            if any(not isinstance(item, dict) or not item.get("kind") or not any(
                    isinstance(item.get(k), str) and item[k] for k in ("note", "url", "path"))
                   for item in lic["evidence"]):
                raise ParamError("asset license evidence must identify its basis")
            if not local and (lic["spdx"].lower() in ("unknown", "??") or lic.get("usage_restrictions") != "none"):
                raise ParamError("official asset licenses must be known and unrestricted")
            if e.get("tier") != ("byo" if local else "official"):
                raise ParamError("BYO assets belong only in local settings")
            if local:
                if not isinstance(e.get("path"), str) or not Path(e["path"]).is_absolute():
                    raise ParamError("local asset requires its absolute source path")
            elif "path" in e:
                raise ParamError("official catalogues cannot contain local source paths")
            else:
                origin = e.get("origin")
                primary_cc0 = lic["spdx"] == "CC0-1.0" and any(
                    isinstance(item, dict) and item.get("kind") in ("license_file", "author_statement")
                    for item in lic["evidence"])
                if not isinstance(origin, dict) or (origin.get("type") != "synthetic" and not primary_cc0):
                    raise ParamError("official assets require original synthesis or primary CC0 evidence")
            if self.validate:
                self.validate(e)
        return doc

    def _read(self, path, *, local=False):
        if local and not path.is_file():
            return {"schema_version": 1, self.name: []}
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ParamError("asset registry is unreadable") from exc
        return self.check(doc, local=local)

    def catalog(self):
        return self._read(self.catalog_path)

    def local(self):
        return self._read(self.local_path, local=True)

    def _save(self, doc):
        self.check(doc, local=True)
        p = self.local_path
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=2)+"\n", encoding="utf-8", newline="\n")
        os.replace(tmp, p)

    def _find(self, id):
        for e in self.catalog()[self.name] + self.local()[self.name]:
            if e["id"] == id:
                return e
        raise LookupError(id)

    def resolve(self, id):
        e = copy.deepcopy(self._find(id))
        e.pop("path", None)
        return e

    def register_file(self, path, *, id, license_spdx, evidence=None, checked_on="unknown",
                      usage_restrictions="unknown", replace=False, **attributes):
        if not isinstance(license_spdx, str) or not license_spdx.strip():
            raise ParamError("license_spdx is required (use unknown when necessary)")
        if any(e["id"] == id for e in self.catalog()[self.name]):
            raise ParamError("official IDs cannot be replaced by BYO assets")
        p = Path(path)
        try:
            data = p.read_bytes()
        except OSError as exc:
            raise ParamError("asset file is missing or unreadable") from exc
        meta = self.metadata(data)
        e = dict(attributes, **meta, id=id, sha256=sha256(data), path=str(p.resolve()), tier="byo",
                 origin={"type": "measured", "note": "user supplied; never copied or redistributed"},
                 license={"spdx": license_spdx.strip(), "usage_restrictions": usage_restrictions,
                          "evidence": evidence or [{"kind": "user_declaration", "note": "declared by user"}],
                          "checked_on": checked_on})
        doc = self.local()
        existing = any(r["id"] == id for r in doc[self.name])
        if existing and not replace:
            raise ParamError("asset already registered; pass replace=True")
        doc[self.name] = sorted([r for r in doc[self.name] if r["id"] != id] + [e], key=lambda r: r["id"])
        self._save(doc)
        return {"entry": self.resolve(id), "warnings": self.warnings(e), "replaced": existing}

    def warnings(self, e):
        if e["tier"] != "byo":
            return []
        out = ["BYO asset: license declared by the user; not checked; never redistributed"]
        if e["license"]["spdx"].lower() in ("unknown", "??"):
            out.append("BYO asset license is unknown; recorded for the Mix Report")
        if e["license"].get("usage_restrictions", "unknown") != "none":
            out.append("BYO asset usage restrictions: " + str(e["license"].get("usage_restrictions", "unknown")))
        return out

    def remove(self, id):
        doc = self.local()
        if not any(e["id"] == id for e in doc[self.name]):
            raise ParamError("only local registrations can be removed")
        doc[self.name] = [e for e in doc[self.name] if e["id"] != id]
        self._save(doc)
        return {"id": id, "removed": "registration"}

    def load(self, id):
        try:
            e = self._find(id)
        except LookupError:
            raise ParamError("unregistered asset: " + str(id)) from None
        try:
            data = Path(e["path"]).read_bytes() if e["tier"] == "byo" else self.generate(e)
        except (OSError, TypeError, ValueError) as exc:
            raise ParamError("asset source is unavailable") from exc
        if sha256(data) != e["sha256"]:
            raise ParamError("asset sha256 mismatch: " + id)
        meta = self.metadata(data)
        if any(e.get(k) != v for k, v in meta.items()):
            raise ParamError("asset metadata does not match pinned data")
        return data, self.resolve(id), self.warnings(e)
