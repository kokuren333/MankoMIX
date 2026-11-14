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
EXEMPT_NAMES = {"README.md", INDEX_NAME, "dossier.md"}   # no front matter (rules / machine-generated)

KINDS = ("song", "lesson", "move", "research", "outcome", "direction", "analysis", "research-log")
STATUSES = ("draft", "active", "stale", "disputed", "superseded", "retracted")
EVIDENCE = ("replicated", "measured", "literature", "practice", "tip", "hunch")
VISIBILITY = ("public", "private")
REQUIRED = ("id", "kind", "title", "created", "status", "visibility")
EVIDENCE_REQUIRED_KINDS = ("research", "move", "lesson")
BACKED_EVIDENCE = ("replicated", "measured")
ID_PREFIX = {"research": "KR-", "move": "KM-", "lesson": "KL-"}

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
        if p.name in EXEMPT_NAMES:
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


def build_index(root: str | Path) -> str:
    root = Path(root)
    cards = sorted(load_cards(root), key=lambda c: (_kind_rank(c["meta"].get("kind")), str(c["meta"].get("id")),
                                                     c["path"]))
    out = [
        "# kb 索引",
        "",
        "<!-- 機械生成（mankomix kb index）。手で編集しない。 -->",
        "",
        f"{len(cards)} 件。並び順: 種類（{' > '.join(KINDS)}）→ ID。",
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


def lint(root: str | Path) -> dict:
    root = Path(root)
    errors: list[dict] = []

    def err(path: str, code: str, msg: str):
        errors.append({"file": path, "code": code, "message": msg})

    if not root.is_dir():
        return {"ok": False, "files": 0, "cards": 0, "errors": [{"file": ".", "code": "no_root",
                                                                  "message": "kb root not found"}]}
    files = markdown_files(root)
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
        if p.name in EXEMPT_NAMES:
            continue
        try:
            meta, _ = parse_front_matter(text)
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
    return {"ok": not errors, "files": len(files), "cards": n_cards, "errors": errors}
