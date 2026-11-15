"""The experience store ``kb/``: front matter, index and lint (minimal version).

``kb/`` holds Markdown cards with a small front matter block (see
``kb/README.md``). This module is deterministic and read-only except for
``write_index``, which writes ``kb/INDEX.md``. The core never imports it.

Front matter is a restricted YAML subset parsed here without a YAML
dependency: one ``key: value`` per line, values are scalars (bare or quoted),
``null``, flow lists ``[a, b]`` or flow maps ``{ k: [a], k2: v }``. Text after
``#`` outside quotes is a comment.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

INDEX_NAME = "INDEX.md"
REFSTUDY_NAME = "refstudy.md"
# no front matter (rules / machine-generated): README, INDEX, the song dossier, the reference study
# (kb/references/works/<slug>/refstudy.md) and comparison sheets (refsheet*.md, wherever they are kept)
EXEMPT_NAMES = {"README.md", INDEX_NAME, "dossier.md", REFSTUDY_NAME}
_REFSHEET_RE = re.compile(r"^refsheet[^/\\]*\.md$")

# Order of the kinds in kb/INDEX.md. New kinds (work, engineer, theory) are inserted without changing the
# relative order of the existing ones.
KINDS = ("song", "work", "engineer", "lesson", "move", "research", "theory", "outcome", "direction", "analysis",
         "research-log")
# The kinds the index header always lists (the kinds of the first kb version). The new kinds appear in the
# header only once a card of that kind exists, so an index without such cards stays byte-identical.
_LEGACY_KINDS = ("song", "lesson", "move", "research", "outcome", "direction", "analysis", "research-log")
STATUSES = ("draft", "active", "stale", "disputed", "superseded", "retracted")
EVIDENCE = ("replicated", "measured", "literature", "practice", "tip", "hunch")
VISIBILITY = ("public", "private")
REQUIRED = ("id", "kind", "title", "created", "status", "visibility")
EVIDENCE_REQUIRED_KINDS = ("research", "move", "lesson")
BACKED_EVIDENCE = ("replicated", "measured")
ID_PREFIX = {"research": "KR-", "move": "KM-", "lesson": "KL-", "theory": "KT-"}

# new kinds (update proposal: reference works, credited engineers, theory cards)
SLUG_RE = r"[a-z0-9][a-z0-9_-]*"
SLUG_ID_PREFIX = {"work": "work_", "engineer": "eng_"}
RIGHTS = ("own", "third_party")
WORK_CREDIT_ROLES = ("mix", "master", "produce", "arrange", "record")
THEORY_DOMAINS = ("rudiments", "harmony", "philosophy", "practice")
THEORY_TRADITIONS = ("common", "berklee-style", "genneki", "field")
THEORY_EVIDENCE = ("literature", "practice")
# required fields on top of REQUIRED. engineer: the credited works (ids) and where the credits come from.
KIND_REQUIRED = {
    "work": ("rights", "credits_source", "materials"),
    "engineer": ("works", "credits_source"),
    "theory": ("evidence", "domain", "tradition", "paraphrase", "sources_note"),
}
# fields a draft work card (the template written by 'direction ref study') may leave empty; the key itself
# must still be present
DRAFT_MAY_BE_EMPTY = {"work": ("credits_source", "materials"), "engineer": ("works", "credits_source")}

# --- publication stops (UD-1, conservative side) ---------------------------------------------------------
# (a) every root: these rights may never be combined with visibility: public. Relax by editing this one line.
PUBLIC_FORBIDDEN_RIGHTS = ("third_party",)
# (b) the repository's public kb (a root that is not inside a '_private' folder): work cards must be
# rights: own, and engineer cards may only refer to such works (UD-4).
PUBLIC_KB_RIGHTS = ("own",)
PRIVATE_DIR_NAME = "_private"

# --- theory cards: limits against copying (design 2.1 / 3.3) ---------------------------------------------
THEORY_BODY_MAX_CHARS = 1200       # characters of the body, whitespace not counted
THEORY_QUOTE_MAX_CHARS = 80        # longest run allowed inside one pair of quotation marks
_QUOTE_PAIRS = (("「", "」"), ("『", "』"), ("“", "”"), ("‘", "’"), ("〝", "〟"),
                ("＂", "＂"), ('"', '"'), ("«", "»"))
_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(|<img\b", re.IGNORECASE)
_BLOCKQUOTE_RE = re.compile(r"^\s{0,3}>")

# --- materials: hashes only, never file names or paths -----------------------------------------------------
_MATERIAL_FORBIDDEN_KEYS = ("path", "paths", "file", "files", "filename", "filenames", "file_name", "name",
                            "names", "url", "uri", "location", "dir", "directory", "folder", "source_file")
_MATERIAL_HASH_KEYS = ("sha256", "sha256_set")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_FILE_NAME_RE = re.compile(r"[\w\-]\.[A-Za-z][A-Za-z0-9]{1,4}(?![A-Za-z0-9])")
_PATH_RE = re.compile(r"\\|^\.{1,2}/|^~|/[^/\s]*/|[^/\s]+/[^/\s]*\.[A-Za-z]")

# --- granularity of machine-generated reference documents (refstudy.md, refsheet*.md) ---------------------
# The design allows time down to sections and frequency down to band aggregates; frame series, spectrograms
# and waveform samples are refused. The limits are set so that the documents of the design (1.2 / 1.3) pass
# with margin and a frame or bin series does not:
# - REF_TABLE_MAX_ROWS: the largest legitimate table is the ERB long-term spectrum of core.reference
#   (ltas_erb, step 1 ERB from 20 Hz: about 40 bands at 44.1/48 kHz, about 44 at 96 kHz) or a per-stem table
#   (a stem set is a few dozen files at most). A frame list of a 3-minute song at the 0.1 s short-term hop is
#   1800 rows, at 1 s still 180; a linear FFT spectrum is thousands of bins.
# - REF_TABLE_MAX_COLS: the widest legitimate table is a per-section or per-stem table with one column per
#   quantity (loudness, p50/p95/max, crest, 6 band ratios, side ratio, correlation, ... about 16).
# - REF_EVEN_SERIES_ROWS: a table whose first column is an evenly spaced numeric series of at least this many
#   rows is a frame (time) or bin (linear frequency) series. Sections and ERB band centres are not evenly
#   spaced.
#   Checked on the first (key) column and on columns whose header names a time or frequency axis
#   (_AXIS_HEADER_RE); value columns may legitimately be evenly spaced.
# - REF_LINE_MAX_NUMBERS / REF_NUMERIC_LINES_MAX: numbers outside tables (code blocks, inline lists): one line
#   may carry a band vector (about 44 values), and a run of numeric lines outside tables is a dump.
REF_TABLE_MAX_ROWS = 64
REF_TABLE_MAX_COLS = 24
REF_EVEN_SERIES_ROWS = 16
REF_LINE_MAX_NUMBERS = 64
REF_NUMERIC_LINES_MAX = 32
_AXIS_HEADER_RE = re.compile(r"時刻|時間|秒|周波数|フレーム|\b(?:s|sec|ms|time|t|hz|khz|freq|frequency|bin|frame)\b",
                             re.IGNORECASE)
_NUM_RE = re.compile(r"(?<![A-Za-z0-9_.])[-+−]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?(?![A-Za-z0-9_])")

# forbidden content (v2 e.2: no absolute paths, no audio references)
_ABS_PATTERNS = [
    ("absolute path (drive letter)", re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]")),
    ("absolute path (user home)", re.compile(r"(?:/Users/|/home/|\\Users\\)")),
    ("absolute path (file URL)", re.compile(r"file:/", re.IGNORECASE)),
]
_AUDIO_RE = re.compile(r"\.(?:wav|wave|mp3|flac|aiff?|m4a|aac|ogg|opus|wma|alac)\b", re.IGNORECASE)
_LINK_RE = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")

SUMMARY_MAX = 80


# ---------------------------------------------------------------------------
# front matter
# ---------------------------------------------------------------------------

class FrontMatterError(ValueError):
    pass


def _strip_comment(line: str) -> str:
    out, quote = [], None
    for ch in line:
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            out.append(ch)
        elif ch == "#":
            break
        else:
            out.append(ch)
    return "".join(out).rstrip()


class _Flow:
    """Tiny parser for flow-style values: [a, b], {k: v}, quoted and bare scalars."""

    def __init__(self, text: str):
        self.s = text
        self.i = 0

    def ws(self):
        while self.i < len(self.s) and self.s[self.i] in " \t":
            self.i += 1

    def parse(self) -> Any:
        self.ws()
        v = self.value(top=True)
        self.ws()
        if self.i != len(self.s):
            raise FrontMatterError(f"unexpected text: {self.s[self.i:]!r}")
        return v

    def value(self, top: bool = False) -> Any:
        self.ws()
        if self.i >= len(self.s):
            return None
        c = self.s[self.i]
        if c == "[":
            return self.seq()
        if c == "{":
            return self.map()
        if c in ("'", '"'):
            return self.quoted()
        return self.bare(top)

    def seq(self) -> list:
        self.i += 1
        out: list = []
        self.ws()
        if self.i < len(self.s) and self.s[self.i] == "]":
            self.i += 1
            return out
        while True:
            out.append(self.value())
            self.ws()
            if self.i >= len(self.s):
                raise FrontMatterError("unterminated list")
            if self.s[self.i] == ",":
                self.i += 1
                continue
            if self.s[self.i] == "]":
                self.i += 1
                return out
            raise FrontMatterError(f"bad list near {self.s[self.i:]!r}")

    def map(self) -> dict:
        self.i += 1
        out: dict = {}
        self.ws()
        if self.i < len(self.s) and self.s[self.i] == "}":
            self.i += 1
            return out
        while True:
            self.ws()
            j = self.s.find(":", self.i)
            if j < 0:
                raise FrontMatterError("map entry without ':'")
            key = self.s[self.i:j].strip().strip("'\"")
            self.i = j + 1
            out[key] = self.value()
            self.ws()
            if self.i >= len(self.s):
                raise FrontMatterError("unterminated map")
            if self.s[self.i] == ",":
                self.i += 1
                continue
            if self.s[self.i] == "}":
                self.i += 1
                return out
            raise FrontMatterError(f"bad map near {self.s[self.i:]!r}")

    def quoted(self) -> str:
        q = self.s[self.i]
        j = self.s.find(q, self.i + 1)
        if j < 0:
            raise FrontMatterError("unterminated quote")
        v = self.s[self.i + 1:j]
        self.i = j + 1
        return v

    def bare(self, top: bool) -> Any:
        stop = "" if top else ",]}"
        j = self.i
        while j < len(self.s) and self.s[j] not in stop:
            j += 1
        tok = self.s[self.i:j].strip()
        self.i = j
        if tok in ("null", "~", ""):
            return None
        if tok == "true":
            return True
        if tok == "false":
            return False
        if re.fullmatch(r"-?\d+", tok):
            return int(tok)
        if re.fullmatch(r"-?\d+\.\d+", tok):
            return float(tok)
        return tok


def parse_front_matter(text: str) -> tuple[dict | None, str]:
    """Return (front matter dict or None when absent, body). Raises FrontMatterError when malformed."""
    t = text.lstrip("\ufeff")
    lines = t.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, t
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        raise FrontMatterError("front matter is not closed with '---'") from None
    meta: dict = {}
    for n, raw in enumerate(lines[1:end], start=2):
        line = _strip_comment(raw)
        if not line.strip():
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:(.*)$", line)
        if not m:
            raise FrontMatterError(f"line {n}: expected 'key: value'")
        key, rest = m.group(1), m.group(2).strip()
        if key in meta:
            raise FrontMatterError(f"line {n}: duplicate key '{key}'")
        meta[key] = _Flow(rest).parse()
    body = "\n".join(lines[end + 1:])
    return meta, body


# ---------------------------------------------------------------------------
# cards
# ---------------------------------------------------------------------------

def _rel(root: Path, p: Path) -> str:
    return p.relative_to(root).as_posix()


def is_exempt(name: str) -> bool:
    """True for files without front matter: rules, the index and machine-generated documents."""
    return name in EXEMPT_NAMES or bool(_REFSHEET_RE.match(name))


def is_reference_document(name: str) -> bool:
    """Machine-generated reference documents whose granularity is limited (refstudy.md, refsheet*.md)."""
    return name == REFSTUDY_NAME or bool(_REFSHEET_RE.match(name))


def markdown_files(root: Path) -> list[Path]:
    return sorted((p for p in root.rglob("*.md") if p.is_file()), key=lambda p: _rel(root, p))


def section_text(body: str, heading: str) -> str:
    """Text of the first '## <heading>' section (heading match is a prefix match)."""
    lines = body.splitlines()
    out, on = [], False
    for ln in lines:
        if re.match(r"^#{1,6}\s", ln):
            if on:
                break
            title = re.sub(r"^#{1,6}\s+", "", ln).strip()
            on = title.startswith(heading)
            continue
        if on:
            out.append(ln)
    return "\n".join(out).strip()


def summary(body: str, limit: int = SUMMARY_MAX) -> str:
    text = section_text(body, "主張") or ""
    if not text:
        for para in re.split(r"\n\s*\n", body):
            p = para.strip()
            if p and not p.startswith("#") and not p.startswith("|"):
                text = p
                break
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)       # links -> their text
    text = re.sub(r"[*`_]", "", text)
    text = re.sub(r"^\s*[-*]\s+", "", text, flags=re.MULTILINE)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def load_cards(root: str | Path) -> list[dict]:
    """Cards with a front matter (exempt files and files with errors are skipped)."""
    root = Path(root)
    cards = []
    if not root.is_dir():
        return cards
    for p in markdown_files(root):
        if is_exempt(p.name):
            continue
        text = p.read_text(encoding="utf-8")
        try:
            meta, body = parse_front_matter(text)
        except FrontMatterError:
            continue
        if not meta:
            continue
        cards.append({"path": _rel(root, p), "meta": meta, "body": body, "summary": summary(body)})
    return cards


def format_applies(applies: Any) -> str:
    if not applies:
        return "—"
    if isinstance(applies, dict):
        parts = []
        for k in sorted(applies):
            v = applies[k]
            vs = ",".join(str(x) for x in v) if isinstance(v, list) else str(v)
            parts.append(f"{k}={vs}")
        return "; ".join(parts)
    return str(applies)


def _cell(v: Any) -> str:
    s = "—" if v in (None, "") else str(v)
    return s.replace("|", "\\|").replace("\n", " ")


def _kind_rank(kind: Any) -> int:
    return KINDS.index(kind) if kind in KINDS else len(KINDS)


def _card_order(c: dict) -> tuple:
    return (_kind_rank(c["meta"].get("kind")), str(c["meta"].get("id")), c["path"])


def sorted_cards(root: str | Path) -> list[dict]:
    """Cards in index order: kind (KINDS) -> id -> path."""
    return sorted(load_cards(root), key=_card_order)


def build_index(root: str | Path) -> str:
    root = Path(root)
    cards = sorted_cards(root)
    present = {c["meta"].get("kind") for c in cards}
    shown = [k for k in KINDS if k in _LEGACY_KINDS or k in present]
    out = [
        "# kb 索引",
        "",
        "<!-- 機械生成（mankomix kb index）。手で編集しない。 -->",
        "",
        f"{len(cards)} 件。並び順: 種類（{' > '.join(shown)}）→ ID。",
        "",
        "| ID | kind | 題 | 適用条件 | 等級 | 状態 | 要旨 |",
        "|---|---|---|---|---|---|---|",
    ]
    for c in cards:
        m = c["meta"]
        link = f"[{_cell(m.get('id'))}]({c['path']})"
        out.append("| " + " | ".join([
            link, _cell(m.get("kind")), _cell(m.get("title")), _cell(format_applies(m.get("applies_to"))),
            _cell(m.get("evidence")), _cell(m.get("status")), _cell(c["summary"]),
        ]) + " |")
    return "\n".join(out) + "\n"


def write_index(root: str | Path) -> dict:
    root = Path(root)
    if not root.is_dir():
        raise FileNotFoundError(f"kb root not found: {root.name}")
    text = build_index(root)
    path = root / INDEX_NAME
    old = path.read_text(encoding="utf-8") if path.is_file() else None
    changed = old != text
    if changed:
        path.write_bytes(text.encode("utf-8"))
    return {"index": INDEX_NAME, "entries": len(load_cards(root)), "changed": changed}


# ---------------------------------------------------------------------------
# lint
# ---------------------------------------------------------------------------

def _is_external(target: str) -> bool:
    return bool(re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target)) or target.startswith("#")


def _resolve(root: Path, base: Path, target: str) -> Path | None:
    path = target.split("#", 1)[0]
    if not path:
        return base
    if path.startswith("/") or path.startswith("\\"):
        return None
    p = (base.parent / path).resolve()
    try:
        p.relative_to(root.resolve())
    except ValueError:
        # links may point outside kb/ into the repository (e.g. ../docs/...); allowed if they exist
        pass
    return p


def is_private_root(root: str | Path) -> bool:
    """A kb root inside a '_private' folder (the non-committed kb, e.g. _private/kb/).

    Every other root is treated as the repository's public kb, so the stricter publication stop (b) applies
    to it. Judged on the resolved path, so 'kb', './kb' and an absolute path behave the same.
    """
    return PRIVATE_DIR_NAME in Path(root).resolve().parts


def _empty(v: Any) -> bool:
    return v is None or v == "" or v == [] or v == {}


def _as_list(v: Any) -> list:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _publication_errors(meta: dict, public_kb: bool, work_rights: dict[str, Any],
                        referenced_works: list[str]) -> list[tuple[str, str]]:
    """Publication stops (UD-1). (a) everywhere; (b) only in the public kb."""
    out = []
    kind, rights = meta.get("kind"), meta.get("rights")
    # (a) one rule, every root
    if rights in PUBLIC_FORBIDDEN_RIGHTS and meta.get("visibility") == "public":
        out.append(("public_third_party", f"rights: {rights} may not be visibility: public"))
    if not public_kb:
        return out
    # (b) the repository's public kb holds own works only (UD-1), and engineers of such works only (UD-4)
    if kind == "work" and rights not in PUBLIC_KB_RIGHTS:
        out.append(("public_kb_rights", f"the public kb holds work cards with rights: "
                                        f"{' / '.join(PUBLIC_KB_RIGHTS)} only (found {rights}); keep it in "
                                        f"_private/kb/"))
    if kind == "engineer":
        for w in referenced_works:
            if w not in work_rights:
                out.append(("public_kb_rights", f"engineer card refers to {w}, which is not a work card of this "
                                                f"kb (its rights cannot be confirmed)"))
            elif work_rights[w] not in PUBLIC_KB_RIGHTS:
                out.append(("public_kb_rights", f"engineer card refers to {w} (rights: {work_rights[w]}); the "
                                                f"public kb lists credits of own works only"))
    return out


def _location_errors(kind: str, cid: str, rel: str) -> list[tuple[str, str]]:
    """New kinds live at a fixed place whose name matches the id."""
    if kind == "work":
        m = re.fullmatch(r"work_(" + SLUG_RE + ")", cid)
        if not m:
            return [("bad_id", "id of a work card must look like work_<slug> (lowercase letters, digits, - _)")]
        want = f"references/works/{m.group(1)}/work.md"
    elif kind == "engineer":
        m = re.fullmatch(r"eng_(" + SLUG_RE + ")", cid)
        if not m:
            return [("bad_id", "id of an engineer card must look like eng_<slug> (lowercase letters, digits, - _)")]
        want = f"references/engineers/{m.group(1)}.md"
    elif kind == "theory":
        want = f"theory/{cid}.md"
    else:
        return []
    return [] if rel == want else [("bad_location", f"a {kind} card with id {cid} belongs at {want}")]


def _required_errors(meta: dict) -> list[tuple[str, str]]:
    kind = meta.get("kind")
    out = []
    lenient = DRAFT_MAY_BE_EMPTY.get(kind, ()) if meta.get("status") == "draft" else ()
    for k in KIND_REQUIRED.get(kind, ()):
        if k not in meta or (_empty(meta.get(k)) and k not in lenient):
            out.append(("missing_field", f"required field '{k}' is missing for kind '{kind}'"))
    if kind == "work":
        if meta.get("rights") is not None and meta.get("rights") not in RIGHTS:
            out.append(("bad_value", f"rights '{meta.get('rights')}' is not one of {', '.join(RIGHTS)}"))
        credits = meta.get("credits")
        if credits is not None:
            if not isinstance(credits, list) or not all(isinstance(c, dict) for c in credits):
                out.append(("bad_value", "credits must be a flow list of maps: [{ role: mix, person: eng_x, "
                                         "name: \"...\" }]"))
            else:
                for c in credits:
                    if c.get("role") not in WORK_CREDIT_ROLES:
                        out.append(("bad_value", f"credit role '{c.get('role')}' is not one of "
                                                 f"{', '.join(WORK_CREDIT_ROLES)}"))
                    person = c.get("person")
                    if person not in (None, "") and not re.fullmatch(r"eng_" + SLUG_RE, str(person)):
                        out.append(("bad_value", f"credit person '{person}' must be an engineer id eng_<slug>"))
    elif kind == "engineer":
        works = meta.get("works")
        if works is not None and not isinstance(works, list):
            out.append(("bad_value", "works must be a flow list of work ids: [work_a, work_b]"))
        for w in _as_list(works):
            if not re.fullmatch(r"work_" + SLUG_RE, str(w)):
                out.append(("bad_value", f"works entry '{w}' is not a work id work_<slug>"))
    elif kind == "theory":
        if meta.get("paraphrase") is not True and "paraphrase" in meta:
            out.append(("bad_value", "paraphrase must be true (the card is written in your own words)"))
        for key, allowed in (("domain", THEORY_DOMAINS), ("tradition", THEORY_TRADITIONS),
                             ("evidence", THEORY_EVIDENCE)):
            v = meta.get(key)
            if v is not None and v not in allowed:
                out.append(("bad_value", f"{key} '{v}' of a theory card is not one of {', '.join(allowed)}"))
    return out


def _material_errors(materials: Any) -> list[tuple[str, str]]:
    """work 'materials': hashes and plain facts only; no file name, no path (design 1.5 / 3.3)."""
    out = []
    if materials is None:
        return out
    if not isinstance(materials, list):
        return [("bad_materials", "materials must be a flow list of maps")]
    for i, item in enumerate(materials, start=1):
        if not isinstance(item, dict):
            out.append(("bad_materials", f"materials[{i}] must be a map"))
            continue
        for k, v in item.items():
            if str(k).lower() in _MATERIAL_FORBIDDEN_KEYS:
                out.append(("material_file_name", f"materials[{i}]: key '{k}' is not allowed (hashes only, no "
                                                  f"file names or paths)"))
                continue
            for s in (x for x in _as_list(v) if isinstance(x, str)):
                if _FILE_NAME_RE.search(s) or _PATH_RE.search(s):
                    out.append(("material_file_name", f"materials[{i}].{k}: looks like a file name or path "
                                                      f"(hashes only)"))
        hashes = [k for k in _MATERIAL_HASH_KEYS if k in item]
        if not hashes:
            out.append(("bad_materials", f"materials[{i}] needs a sha256 (or sha256_set for a stem set)"))
        for k in hashes:
            if not _HEX64_RE.match(str(item[k])):
                out.append(("bad_materials", f"materials[{i}].{k} must be 64 lowercase hex digits"))
    return out


def _theory_body_errors(body: str) -> list[tuple[str, str]]:
    """Limits against copying text into theory cards (design 2.1 / 3.3)."""
    out = []
    n = len(re.sub(r"\s", "", body))
    if n > THEORY_BODY_MAX_CHARS:
        out.append(("theory_too_long", f"body is {n} characters (limit {THEORY_BODY_MAX_CHARS}, whitespace not "
                                       f"counted)"))
    for ln, line in enumerate(body.splitlines(), start=1):
        if _IMAGE_RE.search(line):
            out.append(("theory_image", f"body line {ln}: embedded image"))
        if _BLOCKQUOTE_RE.match(line):
            out.append(("theory_blockquote", f"body line {ln}: quotation block ('>')"))
    for op, cl in _QUOTE_PAIRS:
        rx = re.compile(re.escape(op) + r"([^" + re.escape(cl) + (re.escape(op) if op != cl else "") + r"]*)"
                        + re.escape(cl))
        for m in rx.finditer(body):
            inner = len(m.group(1).replace("\n", ""))
            if inner > THEORY_QUOTE_MAX_CHARS:
                line = body.count("\n", 0, m.start()) + 1
                out.append(("theory_long_quote", f"body line {line}: {inner} characters inside {op}{cl} (limit "
                                                 f"{THEORY_QUOTE_MAX_CHARS})"))
    return out


def _numbers(s: str) -> list[float]:
    return [float(x.replace("−", "-")) for x in _NUM_RE.findall(s)]


def _evenly_spaced(vals: list[float]) -> bool:
    if len(vals) < REF_EVEN_SERIES_ROWS:
        return False
    d = [b - a for a, b in zip(vals, vals[1:])]
    step = d[0]
    if step == 0:
        return False
    return all(abs(x - step) <= 1e-6 * max(1.0, abs(step)) for x in d)


def granularity_errors(text: str) -> list[tuple[str, str]]:
    """Refuse frame series, spectrograms and waveform numbers in refstudy / refsheet (see REF_* limits)."""
    out = []
    lines = text.splitlines()
    i, run, run_start = 0, 0, 0
    while i < len(lines):
        line = lines[i]
        if line.lstrip().startswith("|"):
            start = i
            block = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                block.append(lines[i])
                i += 1
            run = 0
            cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in block]
            data = [c for c in cells if not all(re.fullmatch(r":?-{2,}:?", x or "-") for x in c)]
            header, rows = (data[0], data[1:]) if data else ([], [])
            if len(rows) > REF_TABLE_MAX_ROWS:
                out.append(("too_fine", f"line {start + 1}: table has {len(rows)} rows (limit {REF_TABLE_MAX_ROWS}"
                                        f"; time down to sections, frequency down to bands)"))
            width = max([len(header)] + [len(r) for r in rows])
            if width > REF_TABLE_MAX_COLS:
                out.append(("too_fine", f"line {start + 1}: table has {width} columns (limit {REF_TABLE_MAX_COLS})"))
            for col in range(width):
                name = header[col] if col < len(header) else ""
                if col > 0 and not _AXIS_HEADER_RE.search(name):
                    continue                  # value columns may happen to be evenly spaced
                vals = []
                for r in rows:
                    cell = r[col] if col < len(r) else ""
                    m = re.fullmatch(r"([-+−]?\d+(?:\.\d+)?)\s*[A-Za-z%]*", cell)
                    if m:
                        vals.append(float(m.group(1).replace("−", "-")))
                if _evenly_spaced(vals):
                    out.append(("too_fine", f"line {start + 1}: column {col + 1} is an evenly spaced series of "
                                            f"{len(vals)} values (a frame or bin series)"))
                    break
            continue
        nums = _numbers(line)
        if len(nums) > REF_LINE_MAX_NUMBERS:
            out.append(("too_fine", f"line {i + 1}: {len(nums)} numbers on one line (limit {REF_LINE_MAX_NUMBERS})"))
        words = len(line.split())
        if len(nums) >= 3 and len(nums) * 2 >= words:
            if run == 0:
                run_start = i
            run += 1
            if run == REF_NUMERIC_LINES_MAX + 1:
                out.append(("too_fine", f"line {run_start + 1}: more than {REF_NUMERIC_LINES_MAX} consecutive "
                                        f"lines of numbers outside a table"))
        else:
            run = 0
        i += 1
    return out


def _work_refs(meta: dict, body: str, path: Path, root: Path) -> list[str]:
    """Work ids an engineer card refers to: 'works', work ids in the text, links to works/<slug>/work.md."""
    refs = [str(w) for w in _as_list(meta.get("works"))]
    refs += re.findall(r"(?<![A-Za-z0-9_])work_" + SLUG_RE, body)
    for m in _LINK_RE.finditer(body):
        target = m.group(2)
        if _is_external(target):
            continue
        q = _resolve(root, path, target)
        if q is not None and q.name == "work.md" and q.parent.parent.name == "works":
            refs.append("work_" + q.parent.name)
    return sorted(set(refs))


def lint(root: str | Path, *, public: bool | None = None) -> dict:
    """Check every Markdown file of a kb root.

    ``public`` selects the publication stop (b) (public kb: own works only). None decides from the root:
    a root inside a '_private' folder is private, any other root is the public kb (is_private_root).
    """
    root = Path(root)
    errors: list[dict] = []

    def err(path: str, code: str, msg: str):
        errors.append({"file": path, "code": code, "message": msg})

    if not root.is_dir():
        return {"ok": False, "files": 0, "cards": 0, "errors": [{"file": ".", "code": "no_root",
                                                                  "message": "kb root not found"}]}
    files = markdown_files(root)
    public_kb = (not is_private_root(root)) if public is None else bool(public)
    work_rights = {str(c["meta"].get("id")): c["meta"].get("rights") for c in load_cards(root)
                   if c["meta"].get("kind") == "work"}
    ids: dict[str, str] = {}
    n_cards = 0
    for p in files:
        rel = _rel(root, p)
        text = p.read_text(encoding="utf-8")
        # forbidden content anywhere in the file
        for n, line in enumerate(text.splitlines(), start=1):
            for label, rx in _ABS_PATTERNS:
                if rx.search(line):
                    err(rel, "absolute_path", f"line {n}: {label}")
            if _AUDIO_RE.search(line):
                err(rel, "audio_reference", f"line {n}: reference to an audio file extension")
        # relative links
        for n, line in enumerate(text.splitlines(), start=1):
            for m in _LINK_RE.finditer(line):
                target = m.group(2)
                if _is_external(target):
                    continue
                q = _resolve(root, p, target)
                if q is None:
                    err(rel, "absolute_link", f"line {n}: link must be relative: {target}")
                elif not q.exists():
                    err(rel, "broken_link", f"line {n}: link target not found: {target}")
        # machine-generated reference documents: section / band granularity only
        if is_reference_document(p.name):
            for code, msg in granularity_errors(text):
                err(rel, code, msg)
        if is_exempt(p.name):
            continue
        try:
            meta, body = parse_front_matter(text)
        except FrontMatterError as e:
            err(rel, "front_matter", str(e))
            continue
        if meta is None:
            err(rel, "front_matter", "missing front matter")
            continue
        n_cards += 1
        for k in REQUIRED:
            if meta.get(k) in (None, ""):
                err(rel, "missing_field", f"required field '{k}' is missing")
        kind = meta.get("kind")
        if kind is not None and kind not in KINDS:
            err(rel, "bad_value", f"kind '{kind}' is not one of {', '.join(KINDS)}")
        status = meta.get("status")
        if status is not None and status not in STATUSES:
            err(rel, "bad_value", f"status '{status}' is not one of {', '.join(STATUSES)}")
        vis = meta.get("visibility")
        if vis is not None and vis not in VISIBILITY:
            err(rel, "bad_value", f"visibility '{vis}' is not one of {', '.join(VISIBILITY)}")
        ev = meta.get("evidence")
        if kind in EVIDENCE_REQUIRED_KINDS and ev in (None, ""):
            err(rel, "missing_field", f"evidence is required for kind '{kind}'")
        if ev is not None and ev not in EVIDENCE:
            err(rel, "bad_value", f"evidence '{ev}' is not one of {', '.join(EVIDENCE)}")
        if created := meta.get("created"):
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(created)):
                err(rel, "bad_value", "created must be YYYY-MM-DD")
        cid = meta.get("id")
        if cid:
            cid = str(cid)
            pref = ID_PREFIX.get(kind)
            if pref and not re.fullmatch(re.escape(pref) + r"\d{4}", cid):
                err(rel, "bad_id", f"id of a {kind} card must look like {pref}nnnn")
            if cid in ids:
                err(rel, "duplicate_id", f"id {cid} is also used by {ids[cid]}")
            else:
                ids[cid] = rel
            for code, msg in _location_errors(kind, cid, rel):
                err(rel, code, msg)
        # new kinds: required fields and values, materials, copying limits, publication stops
        for code, msg in _required_errors(meta):
            err(rel, code, msg)
        if kind == "work":
            for code, msg in _material_errors(meta.get("materials")):
                err(rel, code, msg)
        if kind == "theory":
            for code, msg in _theory_body_errors(body):
                err(rel, code, msg)
        refs = _work_refs(meta, body, p, root) if kind == "engineer" else []
        for code, msg in _publication_errors(meta, public_kb, work_rights, refs):
            err(rel, code, msg)
        if ev in BACKED_EVIDENCE:
            backing = meta.get("backing")
            if isinstance(backing, str):
                backing = [backing]
            if not backing:
                err(rel, "missing_backing", f"evidence '{ev}' needs at least one 'backing' link")
            else:
                for b in backing:
                    b = str(b)
                    if _is_external(b) or b.startswith("/") or b.startswith("\\"):
                        err(rel, "bad_backing", f"backing must be a relative link inside kb: {b}")
                        continue
                    path = b.split("#", 1)[0]
                    cand = [(root / path), (p.parent / path)]
                    if not any(c.is_file() for c in cand):
                        err(rel, "bad_backing", f"backing target not found: {b}")
    # index freshness
    idx = root / INDEX_NAME
    if not idx.is_file():
        err(INDEX_NAME, "index_missing", "INDEX.md is missing (run: mankomix kb index)")
    elif idx.read_text(encoding="utf-8") != build_index(root):
        err(INDEX_NAME, "index_stale", "INDEX.md is not up to date (run: mankomix kb index)")
    errors.sort(key=lambda e: (e["file"], e["code"], e["message"]))
    return {"ok": not errors, "files": len(files), "cards": n_cards, "scope": "public" if public_kb else "private",
            "errors": errors}


# ---------------------------------------------------------------------------
# search / show
# ---------------------------------------------------------------------------

def _genres(meta: dict) -> list[str]:
    out = [str(g) for g in _as_list(meta.get("genre"))]
    applies = meta.get("applies_to")
    if isinstance(applies, dict):
        out += [str(g) for g in _as_list(applies.get("genre"))]
    return out


def _entry(c: dict) -> dict:
    m = c["meta"]
    return {"id": m.get("id"), "kind": m.get("kind"), "title": m.get("title"), "path": c["path"],
            "status": m.get("status"), "evidence": m.get("evidence"), "visibility": m.get("visibility"),
            "applies_to": format_applies(m.get("applies_to")), "summary": c["summary"]}


def search(root: str | Path, *, kind: str | list[str] | None = None, genre: str | list[str] | None = None,
           text: str | None = None) -> dict:
    """Cards matching every given filter, in index order.

    kind: card kind(s). genre: matches the card's 'genre' list or applies_to.genre (case-insensitive).
    text: case-insensitive substring of the id, title or body.
    """
    root = Path(root)
    kinds = [str(k) for k in _as_list(kind)]
    genres = [str(g).lower() for g in _as_list(genre)]
    needle = text.casefold() if text else None
    hits = []
    for c in sorted_cards(root):
        m = c["meta"]
        if kinds and m.get("kind") not in kinds:
            continue
        if genres and not ({g.lower() for g in _genres(m)} & set(genres)):
            continue
        if needle is not None:
            hay = "\n".join([str(m.get("id") or ""), str(m.get("title") or ""), c["body"]]).casefold()
            if needle not in hay:
                continue
        hits.append(_entry(c))
    return {"kind": "kb_search", "filters": {"kind": kinds, "genre": genres, "text": text},
            "count": len(hits), "cards": hits}


def show(root: str | Path, card_id: str) -> dict | None:
    """The card with this id (front matter and body), or None. With duplicate ids the first in index order."""
    matches = [c for c in sorted_cards(root) if str(c["meta"].get("id")) == str(card_id)]
    if not matches:
        return None
    c = matches[0]
    out = {"kind": "kb_card", "id": c["meta"].get("id"), "path": c["path"], "front_matter": c["meta"],
           "body": c["body"]}
    if len(matches) > 1:
        out["duplicates"] = [x["path"] for x in matches[1:]]
    return out
