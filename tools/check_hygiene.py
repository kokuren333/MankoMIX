#!/usr/bin/env python3
"""Repository hygiene check (docs/SPEC.md section 16.4).

Scans the files that git tracks or would track (respecting .gitignore) and
fails if any of them contains an absolute filesystem path, a personal e-mail
address, or something that looks like an access token. Also fails if a
forbidden directory is tracked, if any commit was made with a non-noreply
identity, or if any commit message carries a Co-Authored-By trailer.

Usage:
    python -I tools/check_hygiene.py

Exit code 0 means clean; 1 means findings were printed.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

FORBIDDEN_DIRS = ("_handoff/", "_private/")

# An e-mail domain suffix that is always acceptable (GitHub noreply addresses)
# plus reserved documentation domains.
ALLOWED_EMAIL_SUFFIXES = (
    "users.noreply.github.com",
    "noreply.github.com",
    "noreply.anthropic.com",
    "example.com",
    "example.org",
    "example.invalid",
)

PATTERNS = {
    "windows absolute path": re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/](?![\\/])[^\s\"'`)]*"),
    "user home path": re.compile(r"(?:/Users/|/home/|\\Users\\)[A-Za-z0-9._-]+"),
    "e-mail address": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"),
    "token-like string": re.compile(
        r"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|xox[abprs]-[A-Za-z0-9-]{10,})"
    ),
}

BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".flac", ".mp3", ".opus", ".wav", ".pdf", ".woff", ".woff2"}


def candidate_files(root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def check_commit_identities(root: Path) -> list[str]:
    """Every commit must use a noreply identity and carry no co-author trailer."""
    result = subprocess.run(
        ["git", "log", "--format=%h%x1f%ae%x1f%ce%x1f%B%x1e"],
        cwd=root,
        capture_output=True,
    )
    if result.returncode != 0:  # no commits yet
        return []
    problems: list[str] = []
    for record in result.stdout.decode("utf-8", errors="replace").split(chr(30)):
        record = record.strip()
        if not record:
            continue
        short, author, committer, body = (record.split(chr(31)) + ["", "", ""])[:4]
        for role, mail in (("author", author), ("committer", committer)):
            if not mail.lower().endswith("users.noreply.github.com"):
                problems.append(f"commit {short}: {role} e-mail is not a noreply address")
        if "co-authored-by:" in body.lower():
            problems.append(f"commit {short}: message contains a Co-Authored-By trailer")
    return problems


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    findings: list[str] = []

    for rel in candidate_files(root):
        if rel.startswith(FORBIDDEN_DIRS):
            findings.append(f"{rel}: forbidden directory is tracked")
            continue
        path = root / rel
        if path.suffix.lower() in BINARY_SUFFIXES or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            findings.append(f"{rel}: not valid UTF-8 text (unexpected binary?)")
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for label, pattern in PATTERNS.items():
                for match in pattern.finditer(line):
                    value = match.group(0)
                    if label == "e-mail address" and value.lower().endswith(ALLOWED_EMAIL_SUFFIXES):
                        continue
                    findings.append(f"{rel}:{lineno}: {label}: {value}")

    findings.extend(check_commit_identities(root))

    if findings:
        print("Hygiene check FAILED:")
        for item in findings:
            print("  " + item)
        return 1
    print("Hygiene check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
