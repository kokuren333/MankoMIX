"""Name-based detection of export sets and stem roles (docs/SPEC.md 6.1.3).

Everything here works on file names only and is an estimate; the result says
so. Patterns live in knowledge/ingest_patterns.json so other services and DAWs
can be added as data.
"""

from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import PurePath

# role_source values (schema enum: filename_pattern, filename_keyword, user, default).
# The finer reason is kept in role_note so estimates stay visible.
RS_PATTERN = "filename_pattern"   # part name found in a pattern set's role_map
RS_KEYWORD = "filename_keyword"   # generic keyword rule
RS_USER = "user"                  # declared by the caller
RS_DEFAULT = "default"            # nothing usable in the name; role defaulted

NOTE_PATTERN = "role from the part name in the file name pattern (estimate)"
NOTE_PATTERN_UNKNOWN = "part name not in the role vocabulary; role set to 'other' (estimate)"
NOTE_KEYWORD = "role from a keyword in the file name (estimate)"
NOTE_UNKNOWN = "no keyword matched; role set to 'other' (estimate)"
NOTE_SINGLE = "single file input treated as the full mix"
NOTE_DERIVED = "looks like a sum of other stems (derived file)"
NOTE_USER = "role declared by the user"


def is_unknown_role(entry: dict) -> bool:
    """True when the role could not be inferred from the name."""
    return entry.get("role") == "other" and entry.get("role_source") == RS_DEFAULT


def load_knowledge(name: str) -> dict:
    """Load knowledge/<name>.json via core.config when present, else directly."""
    return _load_knowledge_cached(name)


@lru_cache(maxsize=None)
def _load_knowledge_cached(name: str) -> dict:
    try:
        from ..config import load_knowledge as _cfg_load  # type: ignore[import-not-found]
    except ImportError:
        _cfg_load = None
    if _cfg_load is not None:
        try:
            data = _cfg_load(name)
            if isinstance(data, dict):
                return data
        except Exception:  # fall back to the bundled file
            pass
    from mankomix import repo_data_root
    path = repo_data_root() / "knowledge" / f"{name}.json"
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def stem_of(name: str) -> str:
    """File name without its (last) extension, NFC-normalised."""
    return nfc(PurePath(name).stem)


def normalize(text: str) -> str:
    """Casefolded, separators collapsed: 'Backing_Vocals' -> 'backing vocals'."""
    t = nfc(text).casefold()
    t = re.sub(r"[\s_\-.]+", " ", t)
    return t.strip()


def _compile(regex: str) -> re.Pattern:
    return re.compile(regex, re.IGNORECASE)


def keyword_role(stem: str, patterns: dict | None = None) -> tuple[str, str]:
    """Role from the generic keyword rules -> (role, role_source)."""
    patterns = patterns or load_knowledge("ingest_patterns")
    norm = normalize(stem)
    for rule in patterns.get("generic_keyword_rules", {}).get("rules", []):
        if _compile(rule["regex"]).search(norm):
            return rule["role"], RS_KEYWORD
    return "other", RS_DEFAULT


def _derived_rule(stem: str, patterns: dict) -> dict | None:
    norm = normalize(stem)
    for rule in patterns.get("derived_sum_patterns", {}).get("rules", []):
        if _compile(rule["regex"]).search(norm):
            return rule
    return None


def _derived_condition_holds(rule: dict, other_roles: list[str]) -> bool:
    if rule.get("condition", "always") == "always":
        return True
    if rule.get("condition") == "overlaps_roles":
        overlap = set(rule.get("roles", [])) & set(other_roles)
        return len(overlap) >= int(rule.get("min_overlap", 1))
    return False


def _natural_key(name: str):
    return [int(t) if t.isdigit() else t.casefold() for t in re.split(r"(\d+)", name)]


def _try_pattern_set(pset: dict, names: list[str], patterns: dict) -> dict | None:
    """Return a classification if every (non-derived) name fits the set."""
    stem_re = _compile(pset["stem_regex"])
    full_re = _compile(pset["fullmix_regex"])
    role_map = {normalize(k): v for k, v in pset.get("role_map", {}).items()}
    req = pset.get("requires", {})
    entries, unmatched, numbers = [], [], []
    title = None
    for name in names:
        stem = stem_of(name)
        m_full = full_re.match(stem)
        if m_full:
            title = m_full.groupdict().get("title")
            entries.append({"original_name": name, "role": "fullmix", "role_source": RS_PATTERN,
                            "role_note": "number 0 with the song title: bundled full mix (estimate)",
                            "number": 0, "derived_sum": False})
            continue
        m = stem_re.match(stem)
        if m:
            number = int(m.group("number"))
            part = m.group("part")
            role = role_map.get(normalize(part))
            source, note = RS_PATTERN, NOTE_PATTERN
            if role is None:
                role, source, note = pset.get("unknown_part_role", "other"), RS_DEFAULT, NOTE_PATTERN_UNKNOWN
            numbers.append(number)
            entries.append({"original_name": name, "role": role, "role_source": source, "role_note": note,
                            "number": number, "part_name": part, "derived_sum": False})
            continue
        unmatched.append(name)
    fullmix_n = sum(1 for e in entries if e["role"] == "fullmix" and e["number"] == 0)
    stems_n = len(entries) - fullmix_n
    if "fullmix_count" in req and fullmix_n != int(req["fullmix_count"]):
        return None
    if stems_n < int(req.get("min_stems", 1)):
        return None
    if req.get("unique_numbers", True) and len(set(numbers)) != len(numbers):
        return None
    # Unmatched files are only tolerated when they are derived sums.
    stem_roles = [e["role"] for e in entries if e["role"] != "fullmix"]
    derived = []
    for name in unmatched:
        rule = _derived_rule(stem_of(name), patterns)
        if rule is None or not _derived_condition_holds(rule, stem_roles):
            if req.get("all_audio_files_match", True):
                return None
            entries.append(_keyword_entry(name, patterns))
            continue
        derived.append({"original_name": name, "role": "other", "role_source": RS_KEYWORD,
                        "role_note": NOTE_DERIVED, "number": None, "derived_sum": True})
    entries.sort(key=lambda e: (e["number"] is None, e["number"] or 0, _natural_key(e["original_name"])))
    return {"entries": entries + derived, "title": title}


def classify(names: list[str], *, single_file: bool = False, patterns: dict | None = None) -> dict:
    """Classify a set of audio file names.

    Returns {kind, input_kind, detected_by, pattern_set, provenance_hint,
    title, entries:[{original_name, role, role_source, number, derived_sum}],
    warnings}.
    """
    patterns = patterns or load_knowledge("ingest_patterns")
    warnings: list[str] = []
    if single_file:
        if len(names) != 1:
            raise ValueError("single_file classification needs exactly one name")
        return {"kind": "single_mix", "input_kind": "single_mix", "detected_by": None,
                "pattern_set": None, "provenance_hint": None, "title": None, "warnings": warnings,
                "entries": [{"original_name": names[0], "role": "fullmix", "role_source": RS_DEFAULT,
                             "role_note": NOTE_SINGLE, "number": None, "derived_sum": False}]}

    # Files that are sums of other stems regardless of context.
    always_derived = []
    rest = []
    for name in names:
        rule = _derived_rule(stem_of(name), patterns)
        if rule is not None and rule.get("condition", "always") == "always":
            always_derived.append(name)
        else:
            rest.append(name)
    derived_entries = [{"original_name": n, "role": "other", "role_source": RS_KEYWORD,
                        "role_note": NOTE_DERIVED, "number": None, "derived_sum": True}
                       for n in always_derived]

    for pset in patterns.get("pattern_sets", []):
        res = _try_pattern_set(pset, rest, patterns)
        if res is not None:
            entries = res["entries"] + derived_entries
            _warn_derived(entries, warnings)
            return {"kind": pset["input_kind"], "input_kind": pset["input_kind"],
                    "detected_by": "filename_pattern", "pattern_set": pset["id"],
                    "provenance_hint": dict(pset.get("provenance", {})), "title": res["title"],
                    "entries": entries, "warnings": warnings}

    # Generic folder: keyword roles.
    entries = [_keyword_entry(name, patterns) for name in sorted(rest, key=_natural_key)]
    # Conditional derived sums ('other' next to many harmony stems).
    for e in entries:
        rule = _derived_rule(stem_of(e["original_name"]), patterns)
        if rule is None:
            continue
        others = [x["role"] for x in entries if x is not e]
        if _derived_condition_holds(rule, others):
            e["derived_sum"], e["role_note"] = True, NOTE_DERIVED
    entries += derived_entries
    _warn_derived(entries, warnings)

    usable = [e for e in entries if not e["derived_sum"]]
    stems = [e for e in usable if e["role"] != "fullmix"]
    kind = "stem_folder"
    if len(usable) == 1 and usable[0]["role"] in ("fullmix", "other"):
        usable[0].update(role="fullmix", role_source=RS_DEFAULT, role_note=NOTE_SINGLE)
        kind = "single_mix"
    elif not stems and usable:
        kind = "single_mix"
    fullmixes = [e for e in usable if e["role"] == "fullmix"]
    if len(fullmixes) > 1:
        warnings.append("several full-mix candidates: " + ", ".join(e["original_name"] for e in fullmixes)
                        + f"; '{fullmixes[0]['original_name']}' is used as the full mix")
    return {"kind": kind, "input_kind": kind, "detected_by": None, "pattern_set": None,
            "provenance_hint": None, "title": None, "entries": entries, "warnings": warnings}


def _keyword_entry(name: str, patterns: dict) -> dict:
    role, src = keyword_role(stem_of(name), patterns)
    return {"original_name": name, "role": role, "role_source": src,
            "role_note": NOTE_KEYWORD if src == RS_KEYWORD else NOTE_UNKNOWN,
            "number": None, "derived_sum": False}


def _warn_derived(entries: list[dict], warnings: list[str]) -> None:
    for e in entries:
        if e["derived_sum"]:
            warnings.append(f"'{e['original_name']}' looks like a sum of other stems (derived file); "
                            "skipped so the same sound is not added twice (D-037)")
