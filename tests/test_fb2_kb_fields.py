"""X-14: optional context fields only check shape; existing kb contracts stay unchanged."""

from pathlib import Path

import pytest

from mankomix.director import kb
from tests.test_upgrade2_kb import _w, research_card, theory_card, work_card


REPO_KB = Path(__file__).resolve().parent.parent / "kb"
CARD_PATHS = {
    "work": "references/works/mysong/work.md",
    "theory": "theory/KT-0001.md",
    "research": "research/KR-0001.md",
}
CARD_FACTORIES = {"work": work_card, "theory": theory_card, "research": research_card}


def _lint_card(root, kind="work", extra=""):
    _w(root / CARD_PATHS[kind], CARD_FACTORIES[kind](extra=extra))
    kb.write_index(root)
    return kb.lint(root)


def test_public_kb_without_new_fields_is_unchanged():
    index = (REPO_KB / "INDEX.md").read_bytes()
    assert all("stance" not in c["meta"] and "aim_note" not in c["meta"]
               for c in kb.load_cards(REPO_KB))
    assert kb.lint(REPO_KB) == {
        "ok": True, "files": 70, "cards": 59, "scope": "public", "errors": [],
    }
    assert kb.build_index(REPO_KB).encode("utf-8") == index
    assert (REPO_KB / "INDEX.md").read_bytes() == index


@pytest.mark.parametrize("kind", CARD_FACTORIES)
def test_missing_context_fields_preserve_lint_result(tmp_path, kind):
    assert _lint_card(tmp_path / "kb", kind) == {
        "ok": True, "files": 2, "cards": 1, "scope": "public", "errors": [],
    }


@pytest.mark.parametrize("kind", CARD_FACTORIES)
@pytest.mark.parametrize("value", [
    "{}", '{ who: "" }', '{ music: "歌もの" }', '{ era: "2020 年代" }',
    '{ who: "実務者", music: "歌もの", era: "2020 年代" }',
])
def test_valid_stance_and_unchanged_index(tmp_path, kind, value):
    root = tmp_path / "kb"
    before = _lint_card(root, kind)
    index = (root / "INDEX.md").read_bytes()
    assert _lint_card(root, kind, f"stance: {value}\n") == before
    assert (root / "INDEX.md").read_bytes() == index


@pytest.mark.parametrize("kind", CARD_FACTORIES)
@pytest.mark.parametrize("value", ["null", "[]", "text", "42", "true", "", "[{}]"])
def test_stance_must_be_map(tmp_path, kind, value):
    result = _lint_card(tmp_path / "kb", kind, f"stance: {value}\n")
    assert not result["ok"]
    assert [e["code"] for e in result["errors"]] == ["bad_stance"]


@pytest.mark.parametrize("key", ["who", "music", "era"])
@pytest.mark.parametrize("value", ["null", "42", "1.5", "true", "false", "[]", "{}"])
def test_stance_children_must_be_strings(tmp_path, key, value):
    result = _lint_card(tmp_path / "kb", extra=f"stance: {{ {key}: {value} }}\n")
    assert [e["code"] for e in result["errors"]] == ["bad_stance"]
    assert f"stance.{key}" in result["errors"][0]["message"]


def test_only_stance_children_reject_unknown_keys(tmp_path):
    root = tmp_path / "kb"
    assert _lint_card(root, extra="future_context: { anything: [1] }\n")["ok"]
    result = _lint_card(root, extra='stance: { who: "実務者", unknown: "文" }\n')
    assert [e["code"] for e in result["errors"]] == ["bad_stance"]
    assert "unknown" in result["errors"][0]["message"]


@pytest.mark.parametrize("value", ['""', '"歌を前に置く"', '"2020"'])
def test_work_aim_note_is_optional_string(tmp_path, value):
    result = _lint_card(tmp_path / "kb", extra=f"aim_note: {value}\n")
    assert result["ok"], result["errors"]


@pytest.mark.parametrize("value", ["null", "42", "1.5", "true", "false", "[]", "{}", ""])
def test_work_aim_note_rejects_non_strings(tmp_path, value):
    result = _lint_card(tmp_path / "kb", extra=f"aim_note: {value}\n")
    assert [e["code"] for e in result["errors"]] == ["bad_aim_note"]


def test_aim_note_on_other_kinds_keeps_unknown_key_behavior(tmp_path):
    assert _lint_card(tmp_path / "kb", "theory", "aim_note: []\n")["ok"]


@pytest.mark.parametrize("fields", [
    'release: { title: "", year: null }\ngenre: []\n',
    'release: { year: [] }\ngenre: { unrestricted: true }\n',
])
def test_existing_release_and_genre_are_not_restricted(tmp_path, fields):
    root = tmp_path / "kb"
    before = _lint_card(root, extra=fields)
    assert before["ok"], before["errors"]
    assert _lint_card(root, extra=fields + 'stance: {}\naim_note: ""\n') == before
