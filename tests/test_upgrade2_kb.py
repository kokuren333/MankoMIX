"""Upgrade 2, bundle W-1 (kb): work 'sources', 'observed_media', the evidence grade observed_media, source_type,
curriculum bundles, the 'curriculum' reference field, kb search --source-type / --curriculum, the dossier
§10.2 bundle line, and the public-kb stop on work ids in any file (T-22).

Every new field is optional: a card or kb without it lints, indexes and renders exactly as before, and no
direction check reads a curriculum (U-17 / U-28). Fast and self-contained (tmp_path kbs only; the repository
kb/ is read, never written).
"""

from __future__ import annotations

import ast
import copy
import json
import re
from pathlib import Path

import pytest

from mankomix.cli.main import main as cli_main
from mankomix.director import direction as D
from mankomix.director import dossier as DS
from mankomix.director import kb
from tests.test_direction_update import _block, _check_out, _project, _write_doc

REPO = Path(__file__).resolve().parent.parent
REPO_KB = REPO / "kb"
HEX = "0123456789abcdef" * 4
OLD_EVIDENCE = ("replicated", "measured", "literature", "practice", "tip", "hunch")


def _w(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _errors(root: Path, **kw) -> list[dict]:
    kb.write_index(root)
    return kb.lint(root, **kw)["errors"]


def _codes(root: Path, **kw) -> set[str]:
    return {e["code"] for e in _errors(root, **kw)}


def work_card(slug="mysong", rights="own", visibility="public", extra="", body="") -> str:
    return f"""---
id: work_{slug}
kind: work
title: 自作曲 {slug}
created: 2026-11-15
status: active
visibility: {visibility}
credits_source: "利用者提供"
rights: {rights}
materials: [{{ type: stems, count: 4, sha256_set: "{HEX}", obtained: "利用者申告" }}]
{extra}---

## 何の作品か

自作の曲。
{body}"""


def engineer_card(slug="taro", works="[work_mysong]", extra="", body="") -> str:
    return f"""---
id: eng_{slug}
kind: engineer
title: 技術者 {slug}
created: 2026-11-15
status: active
visibility: public
works: {works}
credits_source: "盤のクレジット表記"
{extra}---

## 担当作品

一覧は front matter。
{body}"""


def research_card(cid="KR-0001", evidence="practice", extra="", body="## 主張\n\n要点。\n") -> str:
    return f"""---
id: {cid}
kind: research
title: 調査 {cid}
created: 2026-11-15
status: active
visibility: public
evidence: {evidence}
{extra}---

{body}"""


def lesson_card(cid: str, evidence: str) -> str:
    return (f"---\nid: {cid}\nkind: lesson\ntitle: 教訓 {cid}\ncreated: 2026-11-15\nstatus: active\n"
            f"visibility: public\nevidence: {evidence}\n---\n\n## 主張\n\n{cid} の主張。\n")


def theory_card(cid="KT-0001", title="低い音の高さ", extra="", body=None) -> str:
    body = body if body is not None else "## 要点\n\n自分の言葉で書いた要点。\n"
    return f"""---
id: {cid}
kind: theory
title: {title}
created: 2026-11-15
status: active
visibility: public
evidence: practice
domain: rudiments
tradition: common
paraphrase: true
sources_note: "自分の言葉で要約"
{extra}---

{body}"""


ITEMS = ('[{ order: 2, level: core, topic: "倍音と音色", cards: [KT-0002] }, '
         '{ order: 1, level: intro, topic: "低い音の高さと周波数", cards: [KT-0001, KT-0009] }, '
         '{ order: 3, level: advanced, topic: "まとめ", cards: [] }]')
CUR_BODY = ("## 目的\n\n低域の語彙をそろえる。\n\n## 範囲と水準\n\n入門から応用。\n\n"
            "## 読み方の注意\n\n順序は学ぶ順で、作業の手順ではない。\n")


def curriculum_card(slug="low-end", status="active", items=ITEMS, extra="", body=CUR_BODY, cid=None) -> str:
    return f"""---
id: {cid or 'cur_' + slug}
kind: curriculum
title: 低域の基礎
created: 2026-11-15
status: {status}
visibility: public
specified_by: "同梱の例"
paraphrase: true
sources_note: "自前カードの並べ直し"
items: {items}
{extra}---

{body}"""


GOOD_SOURCES = ('sources: [{ kind: official_stems, where: "制作に使ったサービスの書き出し機能（本人のアカウント）", '
                'rights_note: "本人の制作物。サービスの利用条件に従う", noted: 2026-11-15 }, '
                '{ kind: breakdown_media, where: "制作過程を見せる解説の動画", rights_note: "視聴のみ", '
                'url: "https://example.org/watch" }]\n')
GOOD_OBSERVED = ('observed_media: [{ part: "低域（キックとベース）", order: 1, '
                 'note: "先に打楽器の長さを決め、その後で低音の長さを合わせていた", source: 2 }]\n')


def _work_kb(tmp_path: Path, extra: str = "", body: str = "", rights: str = "own") -> Path:
    root = tmp_path / "kb"
    _w(root / "references" / "works" / "mysong" / "work.md", work_card(rights=rights, extra=extra, body=body))
    return root


# ---------------------------------------------------------------------------
# §4.5 work 'sources'
# ---------------------------------------------------------------------------

def test_repository_kb_is_unchanged_by_the_new_rules():
    """§4.5-1 / §6.5-1 / §14 T-22: the current public kb stays ok and its index unchanged."""
    res = kb.lint(REPO_KB)
    assert res["ok"], res["errors"]
    assert res["scope"] == "public"
    assert kb.build_index(REPO_KB) == (REPO_KB / "INDEX.md").read_text(encoding="utf-8")
    assert set(res) == {"ok", "files", "cards", "scope", "errors"}     # no new 'recommended'/'unused' keys


def test_work_without_sources_lints_as_before(tmp_path):
    root = _work_kb(tmp_path)
    assert _errors(root) == []


def test_good_sources_pass(tmp_path):
    root = _work_kb(tmp_path, extra=GOOD_SOURCES)
    assert _errors(root) == []
    meta = kb.load_cards(root)[0]["meta"]
    assert meta["sources"][0]["kind"] == "official_stems" and meta["sources"][0]["noted"] == "2026-11-15"


@pytest.mark.parametrize("sources,code", [
    ('sources: [{ kind: torrent, where: "どこか", rights_note: "不明" }]', "bad_sources"),
    ('sources: [{ kind: official_stems, rights_note: "本人の制作物" }]', "bad_sources"),
    ('sources: [{ kind: official_stems, where: "書き出し機能" }]', "bad_sources"),
    ('sources: [{ kind: official_stems, where: "", rights_note: "x" }]', "bad_sources"),
    ('sources: [{ kind: official_stems, where: "書き出し機能", rights_note: "x", owner: "me" }]', "bad_sources"),
    ('sources: [{ kind: official_stems, where: "stems_final.zip", rights_note: "x" }]', "source_file_name"),
    ('sources: [{ kind: official_stems, where: "downloads/stems/", rights_note: "x" }]', "source_file_name"),
    ('sources: [{ kind: official_stems, where: "書き出し機能", rights_note: "x", url: "ftp://example.org" }]',
     "bad_sources"),
    ('sources: [{ kind: official_stems, where: "書き出し機能", rights_note: "x", url: [a, b] }]', "bad_sources"),
    ('sources: [{ kind: official_stems, where: "書き出し機能", rights_note: "x", noted: "昨日" }]', "bad_sources"),
    ('sources: { kind: official_stems }', "bad_sources"),
    ('sources: [official_stems]', "bad_sources"),
])
def test_bad_sources_are_refused(tmp_path, sources, code):
    root = _work_kb(tmp_path, extra=sources + "\n")
    assert code in _codes(root)


def test_long_where_is_refused(tmp_path):
    root = _work_kb(tmp_path, extra=f'sources: [{{ kind: contest_stems, where: "{"あ" * 201}", rights_note: "x" }}]\n')
    assert "bad_sources" in _codes(root)


def test_sources_on_other_kinds_are_not_read(tmp_path):
    """The field belongs to work cards; elsewhere it is simply not looked at (no new rule)."""
    root = tmp_path / "kb"
    _w(root / "research" / "KR-0001.md", research_card(extra="sources: [whatever]\n"))
    assert _errors(root) == []


def test_third_party_work_with_sources_is_still_refused_in_the_public_kb(tmp_path):
    root = _work_kb(tmp_path, extra=GOOD_SOURCES, rights="third_party")
    codes = _codes(root)
    assert "public_kb_rights" in codes and "public_third_party" in codes
    # the same card is fine in a private root with visibility: private
    priv = tmp_path / "_private" / "kb"
    _w(priv / "references" / "works" / "mysong" / "work.md",
       work_card(rights="third_party", visibility="private", extra=GOOD_SOURCES))
    assert _errors(priv) == []


NETWORK_MODULES = ("urllib", "requests", "http.client", "socket", "http")


def test_director_has_no_network_imports():
    """§4.5-4: no tool fetches anything (U-3); 'sources' and its url are a record only."""
    found = []
    for py in sorted((REPO / "director").rglob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for n in names:
                if n == "http" or any(n == m or n.startswith(m + ".") for m in NETWORK_MODULES):
                    found.append(f"{py.name}: {n}")
    assert found == []


# ---------------------------------------------------------------------------
# §5.6 evidence grade observed_media and the 'observed_media' field
# ---------------------------------------------------------------------------

def test_evidence_order():
    assert kb.EVIDENCE == ("replicated", "measured", "literature", "practice", "observed_media", "tip", "hunch")
    assert tuple(e for e in kb.EVIDENCE if e in OLD_EVIDENCE) == OLD_EVIDENCE
    assert "observed_media" not in kb.BACKED_EVIDENCE
    assert kb.THEORY_EVIDENCE == ("literature", "practice")


def _s101_ids(md: str) -> list[str]:
    start = md.index("### 10.1 経験")
    sec = md[start:md.index("### 10.2", start)]
    return [ln.split("**")[1] for ln in sec.splitlines() if ln.startswith("- **")]


def test_dossier_experience_order_is_unchanged(tmp_path):
    """§5.6-2: the §10.1 order of the existing grades is the old one; observed_media sits between practice
    and tip without moving the others."""
    proj = _project(tmp_path / "p", low_amp=0.2)
    root = tmp_path / "kb"
    # ids deliberately against the grade order so that the sort is visible
    grades = list(reversed(OLD_EVIDENCE))
    for i, ev in enumerate(grades, start=1):
        _w(root / "lessons" / f"KL-{i:04d}.md", lesson_card(f"KL-{i:04d}", ev))
    md = DS.build_dossier(proj, kb_root=root, section_audio=False, ref_kb_root=tmp_path / "none")["markdown"]
    before = _s101_ids(md)
    want = [f"KL-{grades.index(ev) + 1:04d}" for ev in OLD_EVIDENCE]
    assert before == want
    assert "replicated > measured > literature > practice > tip > hunch" in md     # header text unchanged
    # an observed_media card
    _w(root / "research" / "KR-0001.md", research_card(evidence="observed_media"))
    md2 = DS.build_dossier(proj, kb_root=root, section_audio=False, ref_kb_root=tmp_path / "none")["markdown"]
    after = _s101_ids(md2)
    assert [x for x in after if x != "KR-0001"] == before
    assert after.index("KR-0001") == OLD_EVIDENCE.index("tip")


def test_cards_without_observed_media_lint_as_before(tmp_path):
    root = _work_kb(tmp_path)
    _w(root / "references" / "engineers" / "taro.md", engineer_card())
    assert _errors(root) == []


def test_good_observed_media_passes(tmp_path):
    body = "\n## 観察\n\n1. 低域の長さを先に決めていた（自分の言葉で）。\n"
    root = _work_kb(tmp_path, extra=GOOD_SOURCES + GOOD_OBSERVED, body=body)
    _w(root / "references" / "engineers" / "taro.md",
       engineer_card(extra='observed_media: [{ part: "声", note: "声の帯域を最後に整えていた" }]\n'))
    assert _errors(root) == []


@pytest.mark.parametrize("observed,code", [
    # 21 characters inside a pair of quotation marks
    ('observed_media: [{ part: "声", note: "「' + "あ" * 21 + '」と話していた" }]', "observed_quote"),
    ('observed_media: [{ part: "声", note: "見えた", speaker: "x" }]', "bad_observed"),
    ('observed_media: [{ part: "声", note: "見えた", source: 1 }]', "bad_observed"),     # 1 = official_stems
    ('observed_media: [{ part: "声", note: "見えた", source: 3 }]', "bad_observed"),     # out of range
    ('observed_media: [{ part: "声", note: "見えた", order: 0 }]', "bad_observed"),
    ('observed_media: [{ part: "声" }]', "bad_observed"),
    ('observed_media: [{ note: "見えた" }]', "bad_observed"),
    (f'observed_media: [{{ part: "{"あ" * 61}", note: "見えた" }}]', "bad_observed"),
    ('observed_media: "見えた"', "bad_observed"),
])
def test_bad_observed_media_is_refused(tmp_path, observed, code):
    root = _work_kb(tmp_path, extra=GOOD_SOURCES + observed + "\n")
    assert code in _codes(root)


def test_twenty_character_quote_passes(tmp_path):
    root = _work_kb(tmp_path, extra=GOOD_SOURCES + 'observed_media: [{ part: "声", note: "「' + "あ" * 20
                    + '」という順に見えた" }]\n')
    assert _errors(root) == []


def test_observed_section_with_a_quotation_block_is_refused(tmp_path):
    body = "\n## 観察\n\n> 逐語の書き起こし\n"
    root = _work_kb(tmp_path, extra=GOOD_OBSERVED.replace(", source: 2", ""), body=body)
    assert "observed_quote" in _codes(root)
    # without observed_media the section is not looked at (no new rule for cards that do not use the field)
    root2 = _work_kb(tmp_path / "b", body=body)
    assert _errors(root2) == []


def test_engineer_observed_media_may_not_point_to_sources(tmp_path):
    root = _work_kb(tmp_path)
    _w(root / "references" / "engineers" / "taro.md",
       engineer_card(extra='observed_media: [{ part: "声", note: "見えた", source: 1 }]\n'))
    assert "bad_observed" in _codes(root)


def test_observed_media_research_card_needs_no_backing(tmp_path):
    root = tmp_path / "kb"
    _w(root / "research" / "KR-0001.md", research_card(evidence="observed_media"))
    for i, k in enumerate(("move", "lesson"), start=1):
        pref = {"move": "KM", "lesson": "KL"}[k]
        _w(root / f"{k}s" / f"{pref}-0001.md",
           research_card(cid=f"{pref}-0001", evidence="observed_media").replace("kind: research", f"kind: {k}"))
    assert _errors(root) == []
    _w(root / "theory" / "KT-0001.md", theory_card().replace("evidence: practice", "evidence: observed_media"))
    assert "bad_value" in _codes(root)       # THEORY_EVIDENCE unchanged


# ---------------------------------------------------------------------------
# §6.5 source_type, curriculum bundles, the 'curriculum' reference field
# ---------------------------------------------------------------------------

def test_source_type_values(tmp_path):
    assert kb.SOURCE_TYPES == ("paper", "pro", "amateur", "internal", "curriculum")
    root = tmp_path / "kb"
    _w(root / "research" / "KR-0001.md", research_card(extra="source_type: pro\n"))
    assert _errors(root) == []
    _w(root / "research" / "KR-0002.md", research_card(cid="KR-0002", extra="source_type: blog\n"))
    assert [e["code"] for e in _errors(root)] == ["bad_value"]


def test_kb_without_bundles_has_the_old_index_heading(tmp_path):
    root = tmp_path / "kb"
    _w(root / "theory" / "KT-0001.md", theory_card())
    assert "curriculum" not in kb.build_index(root)
    _w(root / "curricula" / "low-end.md", curriculum_card())
    idx = kb.build_index(root)
    assert "theory > curriculum > outcome" in idx and "[cur_low-end](curricula/low-end.md)" in idx


def test_good_curriculum_passes(tmp_path):
    root = tmp_path / "kb"
    _w(root / "curricula" / "low-end.md", curriculum_card())
    assert _errors(root) == []


def test_draft_curriculum_may_have_empty_items(tmp_path):
    root = tmp_path / "kb"
    _w(root / "curricula" / "low-end.md", curriculum_card(status="draft", items="[]"))
    assert _errors(root) == []
    _w(root / "curricula" / "low-end.md", curriculum_card(status="active", items="[]"))
    assert "missing_field" in _codes(root)


@pytest.mark.parametrize("items,code", [
    ('[{ order: 1, level: intro, topic: "a" }, { order: 1, level: core, topic: "b" }]', "bad_curriculum"),
    ('[{ order: 1, level: expert, topic: "a" }]', "bad_curriculum"),
    ('[{ order: 0, level: intro, topic: "a" }]', "bad_curriculum"),
    ('[{ order: 1, level: intro }]', "bad_curriculum"),
    (f'[{{ order: 1, level: intro, topic: "{"あ" * 81}" }}]', "bad_curriculum"),
    ('[{ order: 1, level: intro, topic: "a", cards: [KT-1] }]', "bad_curriculum"),
    ('[{ order: 1, level: intro, topic: "a", cards: KT-0001 }]', "bad_curriculum"),
    ('[{ order: 1, level: intro, topic: "a", note: "x" }]', "bad_curriculum"),
    ('{ order: 1 }', "bad_curriculum"),
    ('[{ order: 1, level: intro, topic: "a", title: "x" }]', "curriculum_material_name"),
    ('[{ order: 1, level: intro, topic: "a", author: "x" }]', "curriculum_material_name"),
    ('[{ order: 1, level: intro, topic: "a", isbn: "x" }]', "curriculum_material_name"),
    ('[{ order: 1, level: intro, topic: "a", url: "x" }]', "curriculum_material_name"),
])
def test_bad_curriculum_items_are_refused(tmp_path, items, code):
    root = tmp_path / "kb"
    _w(root / "curricula" / "low-end.md", curriculum_card(items=items))
    assert code in _codes(root)


def test_curriculum_id_and_location(tmp_path):
    root = tmp_path / "kb"
    _w(root / "curricula" / "other.md", curriculum_card(slug="low-end"))
    assert "bad_location" in _codes(root)
    root2 = tmp_path / "kb2"
    _w(root2 / "curricula" / "low-end.md", curriculum_card(cid="CUR-0001"))
    assert "bad_id" in _codes(root2)


def test_curriculum_required_fields_and_copy_limits(tmp_path):
    root = tmp_path / "kb"
    _w(root / "curricula" / "low-end.md", curriculum_card().replace("paraphrase: true\n", ""))
    assert "missing_field" in _codes(root)
    _w(root / "curricula" / "low-end.md", curriculum_card().replace("paraphrase: true", "paraphrase: false"))
    assert "bad_value" in _codes(root)
    _w(root / "curricula" / "low-end.md", curriculum_card(body=CUR_BODY + "\n> 教材の一節\n"))
    assert "theory_blockquote" in _codes(root)
    _w(root / "curricula" / "low-end.md", curriculum_card(body=CUR_BODY + "\n" + "あ" * 1201 + "\n"))
    assert "theory_too_long" in _codes(root)


def test_curriculum_sourced_card_needs_paraphrase_and_no_quotes(tmp_path):
    root = tmp_path / "kb"
    _w(root / "research" / "KR-0001.md", research_card(extra="source_type: curriculum\n"))
    assert "missing_field" in _codes(root)
    _w(root / "research" / "KR-0001.md", research_card(extra="source_type: curriculum\nparaphrase: true\n"))
    assert _errors(root) == []
    _w(root / "research" / "KR-0001.md", research_card(
        extra="source_type: curriculum\nparaphrase: true\n", body="## 主張\n\n> 教材の一節\n"))
    assert "theory_blockquote" in _codes(root)
    _w(root / "research" / "KR-0001.md", research_card(
        extra="source_type: curriculum\nparaphrase: true\n", body="## 主張\n\n「" + "あ" * 81 + "」\n"))
    assert "theory_long_quote" in _codes(root)
    # no length limit outside theory cards
    _w(root / "research" / "KR-0001.md", research_card(
        extra="source_type: curriculum\nparaphrase: true\n", body="## 主張\n\n" + "あ" * 1500 + "\n"))
    assert _errors(root) == []
    # a card that is not curriculum-sourced keeps its old rules (quotation blocks allowed)
    _w(root / "research" / "KR-0001.md", research_card(body="## 主張\n\n> 文献の一節\n"))
    assert _errors(root) == []


@pytest.mark.parametrize("ref,ok", [
    ("{ id: cur_low-end, order: 3, level: core }", True),
    ("{ id: cur_low-end }", True),
    ("{ id: low-end, order: 3 }", False),
    ("{ id: cur_low-end, order: 0 }", False),
    ("{ id: cur_low-end, level: expert }", False),
    ("{ id: cur_low-end, title: x }", False),
    ("cur_low-end", False),
])
def test_curriculum_reference_field(tmp_path, ref, ok):
    root = tmp_path / "kb"
    _w(root / "theory" / "KT-0001.md", theory_card(extra=f"source_type: curriculum\ncurriculum: {ref}\n"))
    codes = _codes(root)
    assert (codes == set()) if ok else ("bad_curriculum_ref" in codes)


# --- search ------------------------------------------------------------------------------------------------

def _search_kb(tmp_path: Path) -> Path:
    root = tmp_path / "kb"
    _w(root / "theory" / "KT-0001.md", theory_card("KT-0001", "低い音の高さ"))
    _w(root / "theory" / "KT-0002.md", theory_card("KT-0002", "倍音"))
    _w(root / "theory" / "KT-0003.md", theory_card("KT-0003", "束に無いカード"))
    _w(root / "theory" / "KT-0004.md", theory_card(
        "KT-0004", "蒸留カード", extra="source_type: curriculum\ncurriculum: { id: cur_low-end, order: 2, level: core }\n"))
    _w(root / "research" / "KR-0001.md", research_card(extra="source_type: pro\n"))
    _w(root / "curricula" / "low-end.md", curriculum_card())
    kb.write_index(root)
    assert kb.lint(root)["ok"], kb.lint(root)["errors"]
    return root


def test_search_by_curriculum_returns_the_bundle_order(tmp_path):
    root = _search_kb(tmp_path)
    res = kb.search(root, curriculum="cur_low-end")
    assert [(c["id"], c["curriculum_order"], c["curriculum_level"]) for c in res["cards"]] == [
        ("KT-0001", 1, "intro"), ("KT-0002", 2, "core"), ("KT-0004", 2, "core")]
    assert res["not_in_this_kb"] == ["KT-0009"]
    assert res["filters"]["curriculum"] == "cur_low-end"
    assert kb.search(root, curriculum="cur_none")["count"] == 0
    # combined with another filter
    assert [c["id"] for c in kb.search(root, curriculum="cur_low-end", text="倍音")["cards"]] == ["KT-0002"]


def test_search_by_source_type(tmp_path):
    root = _search_kb(tmp_path)
    assert [c["id"] for c in kb.search(root, source_type="curriculum")["cards"]] == ["KT-0004"]
    assert [c["id"] for c in kb.search(root, source_type=["pro", "curriculum"])["cards"]] == ["KR-0001", "KT-0004"]


def test_search_without_new_filters_is_unchanged(tmp_path):
    root = _search_kb(tmp_path)
    res = kb.search(root, kind="theory")
    assert set(res) == {"kind", "filters", "count", "cards"}
    assert res["filters"] == {"kind": ["theory"], "genre": [], "text": None}
    assert all("curriculum_order" not in c for c in res["cards"])
    assert [c["id"] for c in res["cards"]] == ["KT-0001", "KT-0002", "KT-0003", "KT-0004"]


def test_cli_search_flags(tmp_path, capsys):
    root = _search_kb(tmp_path)
    assert cli_main(["kb", "search", "--curriculum", "cur_low-end", "--root", str(root)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert [c["id"] for c in out["cards"]] == ["KT-0001", "KT-0002", "KT-0004"]
    assert cli_main(["kb", "search", "--source-type", "pro", "--source-type", "curriculum",
                     "--root", str(root)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert [c["id"] for c in out["cards"]] == ["KR-0001", "KT-0004"]


# --- dossier §10.2 -----------------------------------------------------------------------------------------

def _shelf(md: str) -> list[str]:
    start = md.index("### 10.2 理論の棚")
    sec = md[start:md.index("### 10.3", start)]
    return [ln for ln in sec.splitlines() if ln.startswith("- ")]


def test_dossier_bundle_line(tmp_path):
    proj = _project(tmp_path / "p", low_amp=0.2)
    root = tmp_path / "kb"
    _w(root / "theory" / "KT-0001.md", theory_card())
    none = tmp_path / "none"
    md0 = DS.build_dossier(proj, kb_root=root, section_audio=False, ref_kb_root=none)["markdown"]
    assert _shelf(md0) == ["- KT-0001 低い音の高さ"]
    _w(root / "curricula" / "draft-one.md", curriculum_card(slug="draft-one", status="draft", items="[]"))
    md1 = DS.build_dossier(proj, kb_root=root, section_audio=False, ref_kb_root=none)["markdown"]
    assert md1 == md0                                  # a draft bundle is not listed
    _w(root / "curricula" / "low-end.md", curriculum_card())
    md2 = DS.build_dossier(proj, kb_root=root, section_audio=False, ref_kb_root=none)["markdown"]
    assert _shelf(md2) == ["- KT-0001 低い音の高さ", "- カリキュラム: cur_low-end 低域の基礎（3 項）"]
    assert len(md2.splitlines()) == len(md0.splitlines()) + 1
    assert DS.DOSSIER_VERSION == 2
    # without theory cards the bundle line still follows the shelf line
    root2 = tmp_path / "kb2"
    _w(root2 / "curricula" / "low-end.md", curriculum_card())
    md3 = DS.build_dossier(proj, kb_root=root2, section_audio=False, ref_kb_root=none)["markdown"]
    assert _shelf(md3) == ["- 理論カードなし", "- カリキュラム: cur_low-end 低域の基礎（3 項）"]


# --- the curriculum is never a procedure (§6.5-6) ----------------------------------------------------------

def _masked(obj, did: str, tag: str) -> str:
    """JSON of a result with the ids derived from the document (dir_ / mxp_ hashes) and the tmp folder tag
    masked: they differ by design because the documents differ in sources.cards."""
    text = json.dumps(obj, sort_keys=True, ensure_ascii=False)
    text = re.sub(r"mxp_[0-9a-f]{12}", "mxp_<id>", text.replace(did, "<dir>"))
    return text.replace(f"_{tag}", "_<tag>")


def test_direction_results_do_not_depend_on_curriculum_cards(tmp_path, monkeypatch):
    """validate / proposal / check give the same verdicts whether sources.cards is empty or lists every card
    of a bundle, and none of them reads the kb (so a bundle in the kb cannot change them)."""
    proj = _project(tmp_path / "p", low_amp=0.2)
    empty = _block()
    full = copy.deepcopy(empty)
    full["sources"]["cards"] = ["cur_low-end", "KT-0001", "KT-0002", "KT-0004", "KT-0005", "KT-0012", "KT-0013"]

    def boom(*a, **k):
        raise AssertionError("the direction checks must not read the kb")

    for name in ("load_cards", "sorted_cards", "search", "show", "lint", "build_index"):
        monkeypatch.setattr(kb, name, boom)
    results = {}
    for tag, b in (("empty", empty), ("full", full)):
        doc = D.parse_document(_write_doc(tmp_path / f"d_{tag}", b))
        v = D.validate(doc, proj)
        assert v["ok"], v["errors"]
        prop, record, notes = D.build_proposal(D._Project(proj), doc)
        out, _ = _check_out(tmp_path, b, tag)
        results[tag] = {"validate": _masked(v, doc["id"], tag),
                        "proposal": _masked({"prop": prop, "record": record, "notes": notes}, doc["id"], tag),
                        "check": _masked(out, doc["id"], tag)}
    assert results["empty"]["validate"] == results["full"]["validate"]
    assert results["empty"]["proposal"] == results["full"]["proposal"]
    assert results["empty"]["check"] == results["full"]["check"]


# ---------------------------------------------------------------------------
# §14 T-22: the public kb names own works only, in every file
# ---------------------------------------------------------------------------

def _case_kb(root: Path, note: str) -> Path:
    _w(root / "references" / "works" / "mysong" / "work.md", work_card())
    _w(root / "songs" / "s" / "2026-11-15_p1-x" / "analysis.md",
       "---\nid: an_x\nkind: analysis\ntitle: 分析\ncreated: 2026-11-15\nstatus: draft\nvisibility: public\n---\n\n"
       + note + "\n")
    return root


def test_public_kb_refuses_unknown_or_third_party_work_ids_in_any_file(tmp_path):
    ok = _case_kb(tmp_path / "ok" / "kb", "比べた作品は work_mysong。")
    assert _errors(ok) == []
    unknown = _case_kb(tmp_path / "u" / "kb", "比べた作品は work_other-song。")
    errs = _errors(unknown)
    assert [(e["file"], e["code"]) for e in errs] == [("songs/s/2026-11-15_p1-x/analysis.md", "public_kb_rights")]
    assert "work_other-song" in errs[0]["message"]
    # machine-generated documents (refsheet, dossier) are covered as well
    third = tmp_path / "t" / "kb"
    _case_kb(third, "x")
    _w(third / "references" / "works" / "other" / "work.md", work_card(slug="other", rights="third_party"))
    _w(third / "songs" / "s" / "2026-11-15_p1-x" / "refsheet.md", "# 対照表\n\n参照: work_other\n")
    _w(third / "songs" / "s" / "dossier.md", "# 曲資料\n\n- work_other\n")
    errs = [e for e in _errors(third) if e["code"] == "public_kb_rights"]
    assert {e["file"] for e in errs} >= {"songs/s/2026-11-15_p1-x/refsheet.md", "songs/s/dossier.md"}


def test_readme_and_index_are_not_scanned(tmp_path):
    root = _case_kb(tmp_path / "kb", "x")
    _w(root / "README.md", "例: work_<slug>、work_example-song\n")
    assert _errors(root) == []


def test_private_root_is_not_scanned(tmp_path):
    priv = _case_kb(tmp_path / "_private" / "kb", "比べた作品は work_other-song。")
    assert kb.lint(priv)["scope"] == "private"
    assert _errors(priv) == []
    # the same tree judged as public is stopped
    assert "public_kb_rights" in _codes(priv, public=True)
