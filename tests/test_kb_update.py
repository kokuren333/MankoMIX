"""kb update (reference works, credited engineers, theory cards): schema, lint, index order, search / show.

Fast and self-contained (tmp_path kbs only; the repository kb/ is read, never written).
"""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from mankomix.cli.main import main as cli_main
from mankomix.director import kb

REPO = Path(__file__).resolve().parent.parent
REPO_KB = REPO / "kb"
HEX = "0123456789abcdef" * 4


def _w(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _codes(root: Path, **kw) -> set[str]:
    kb.write_index(root)
    return {e["code"] for e in kb.lint(root, **kw)["errors"]}


def _errors(root: Path, **kw) -> list[dict]:
    kb.write_index(root)
    return kb.lint(root, **kw)["errors"]


def work_card(slug="mysong", rights="own", visibility="public", status="active", materials=None,
              credits_source='"利用者提供（盤のクレジット表記）"', extra="") -> str:
    if materials is None:
        materials = (f'[{{ type: master, lossy: false, format: "44.1k/16", sha256: "{HEX}", '
                     f'obtained: "利用者申告（自作・公式配布）" }}, {{ type: stems, count: 12, sha256_set: "{HEX}", '
                     f'obtained: "利用者申告" }}]')
    return f"""---
id: work_{slug}
kind: work
title: 自作曲 {slug}
created: 2026-11-15
status: {status}
visibility: {visibility}
artist: "kokuren"
release: {{ title: "manko-shugi", year: 2026 }}
credits: [{{ role: mix, person: eng_taro, name: "Taro" }}, {{ role: master, person: eng_taro, name: "Taro" }}]
credits_source: {credits_source}
genre: [hiphop]
rights: {rights}
materials: {materials}
study: {{ sha256: "{HEX}", engine: {{ version: "0.1" }} }}
evidence: measured
backing: [refstudy.md]
{extra}---

## 何の作品か

自作のヒップホップ曲。

## 測定の要点

LUFS-I は refstudy の値を書き写す。
"""


def engineer_card(slug="taro", works="[work_mysong]", visibility="public", body="") -> str:
    return f"""---
id: eng_{slug}
kind: engineer
title: 技術者 {slug}
created: 2026-11-15
status: active
visibility: {visibility}
works: {works}
credits_source: "公表クレジット（利用者提供）"
---

## クレジットされた作品

{body or "- work_mysong"}
"""


def theory_card(cid="KT-0001", body=None, **over) -> str:
    fm = {"evidence": "literature", "domain": "rudiments", "tradition": "common", "paraphrase": "true",
          "sources_note": '"広く共有された理論の要約。特定の書籍・教材の文面、譜例、図表を写していない"'}
    fm.update(over)
    lines = "".join(f"{k}: {v}\n" for k, v in fm.items() if v is not None)
    if body is None:
        body = "## 要点\n\n音程は二音の距離。協和の度合いで濁りの原因を分ける。\n\n## 指揮での使いどころ\n\n低域の濁り。\n"
    return f"""---
id: {cid}
kind: theory
title: 音程と協和
created: 2026-11-15
status: active
visibility: public
{lines}---

{body}"""


REFSTUDY = """# refstudy — work_mysong

## 全体

| 量 | 値 |
|---|---|
| LUFS-I | -9.1 |
| トゥルーピーク | -0.8 dBTP |
| PLR | 8.3 dB |

## 区間

| 区間 | 開始 s | 終了 s | LUFS | p95 | クレスト dB | サブ | ロー | ローミッド | ミッド | プレゼンス | エア | 側／中央 | 相関 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| intro | 0.0 | 12.4 | -14.2 | -12.0 | 13.1 | 0.08 | 0.21 | 0.22 | 0.30 | 0.12 | 0.07 | 0.31 | 0.82 |
| verse | 12.4 | 45.9 | -10.1 | -9.0 | 10.2 | 0.10 | 0.24 | 0.20 | 0.29 | 0.11 | 0.06 | 0.28 | 0.85 |
| hook | 45.9 | 70.3 | -8.7 | -8.1 | 9.0 | 0.11 | 0.25 | 0.19 | 0.28 | 0.11 | 0.06 | 0.33 | 0.80 |
| outro | 70.3 | 88.0 | -13.0 | -11.5 | 12.0 | 0.09 | 0.22 | 0.21 | 0.30 | 0.12 | 0.06 | 0.30 | 0.83 |
"""


def _erb_table() -> str:
    # 42 ERB band centres (not evenly spaced): band aggregates are allowed
    rows = ["| 帯域中心 Hz | dB |", "|---|---|"]
    f = 26.0
    for i in range(42):
        rows.append(f"| {f:.1f} | {-30 - i * 0.5:.1f} |")
        f *= 1.17
    return "\n".join(rows) + "\n"


def good_kb(root: Path, theory_id: str = "KT-0001") -> Path:
    _w(root / "references/works/mysong/work.md", work_card())
    _w(root / "references/works/mysong/refstudy.md", REFSTUDY + "\n## LTAS\n\n" + _erb_table())
    _w(root / "references/engineers/taro.md", engineer_card())
    _w(root / f"theory/{theory_id}.md", theory_card(theory_id))
    return root


# ---------------------------------------------------------------------------
# schema and required fields
# ---------------------------------------------------------------------------

def test_new_kinds_lint_ok_and_flow_front_matter_parses(tmp_path):
    root = good_kb(tmp_path / "kb")
    res = kb.lint(root) if kb.write_index(root) else None
    assert res["ok"], res["errors"]
    assert res["scope"] == "public" and res["cards"] == 3
    meta, _ = kb.parse_front_matter(work_card())
    assert meta["credits"][0] == {"role": "mix", "person": "eng_taro", "name": "Taro"}
    assert meta["materials"][0]["sha256"] == HEX and meta["materials"][0]["lossy"] is False
    assert meta["release"] == {"title": "manko-shugi", "year": 2026}
    assert kb.parse_front_matter(theory_card())[0]["paraphrase"] is True


def test_refstudy_and_refsheet_are_exempt_from_front_matter(tmp_path):
    root = good_kb(tmp_path / "kb")
    _w(root / "songs/s/2026-11-15_p1-x/refsheet.md", REFSTUDY)
    _w(root / "songs/s/2026-11-15_p1-x/refsheet_work_mysong.md", REFSTUDY)
    errs = _errors(root)
    assert not errs, errs
    idx = (root / "INDEX.md").read_text(encoding="utf-8")
    assert "refstudy" not in idx and "refsheet" not in idx
    assert kb.is_exempt("refsheet-v2.md") and kb.is_exempt("refstudy.md") and not kb.is_exempt("work.md")


@pytest.mark.parametrize("kind,text,field", [
    ("work", work_card().replace("rights: own\n", ""), "rights"),
    ("work", work_card().replace('credits_source: "利用者提供（盤のクレジット表記）"\n', ""), "credits_source"),
    ("work", work_card(credits_source='""'), "credits_source"),
    ("work", work_card(materials="[]"), "materials"),
    ("engineer", engineer_card(works="[]"), "works"),
    ("engineer", engineer_card().replace('credits_source: "公表クレジット（利用者提供）"\n', ""), "credits_source"),
    ("theory", theory_card(paraphrase=None), "paraphrase"),
    ("theory", theory_card(sources_note=None), "sources_note"),
    ("theory", theory_card(domain=None), "domain"),
    ("theory", theory_card(tradition=None), "tradition"),
    ("theory", theory_card(evidence=None), "evidence"),
])
def test_new_kinds_required_fields(tmp_path, kind, text, field):
    root = good_kb(tmp_path / "kb")
    target = {"work": "references/works/mysong/work.md", "engineer": "references/engineers/taro.md",
              "theory": "theory/KT-0001.md"}[kind]
    _w(root / target, text)
    msgs = [e["message"] for e in _errors(root) if e["code"] == "missing_field" and e["file"] == target]
    assert any(f"'{field}'" in m for m in msgs), msgs


def test_draft_work_template_may_leave_metadata_empty(tmp_path):
    root = good_kb(tmp_path / "kb")
    _w(root / "references/works/mysong/work.md",
       work_card(status="draft", credits_source='""', materials="[]", visibility="private"))
    assert _errors(root) == []
    # the key itself must still be present
    _w(root / "references/works/mysong/work.md",
       work_card(status="draft", visibility="private").replace("credits_source: ", "x_credits_source: "))
    assert "missing_field" in _codes(root)


@pytest.mark.parametrize("target,text,needle", [
    ("references/works/mysong/work.md", work_card(rights="borrowed"), "rights 'borrowed'"),
    ("references/works/mysong/work.md",
     work_card().replace("role: master", "role: mastering"), "credit role 'mastering'"),
    ("references/engineers/taro.md", engineer_card(works="[mysong]"), "works entry 'mysong'"),
    ("theory/KT-0001.md", theory_card(paraphrase="false"), "paraphrase must be true"),
    ("theory/KT-0001.md", theory_card(domain="acoustics"), "domain 'acoustics'"),
    ("theory/KT-0001.md", theory_card(tradition="jazz"), "tradition 'jazz'"),
    ("theory/KT-0001.md", theory_card(evidence="measured"), "evidence 'measured'"),
])
def test_new_kinds_enumerations(tmp_path, target, text, needle):
    root = good_kb(tmp_path / "kb")
    _w(root / target, text)
    errs = [e for e in _errors(root) if e["file"] == target and e["code"] == "bad_value"]
    assert any(needle in e["message"] for e in errs), errs


def test_new_kinds_ids_and_locations(tmp_path):
    root = good_kb(tmp_path / "kb")
    _w(root / "theory/KT-0002.md", theory_card(cid="KT-2"))
    _w(root / "theory/misplaced.md", theory_card(cid="KT-0003"))
    _w(root / "references/works/other/work.md", work_card(slug="Bad Slug"))
    _w(root / "references/engineers/hanako.md", engineer_card(slug="taro2"))
    errs = _errors(root)
    by_file = {}
    for e in errs:
        by_file.setdefault(e["file"], set()).add(e["code"])
    assert "bad_id" in by_file["theory/KT-0002.md"]
    assert "bad_location" in by_file["theory/misplaced.md"]
    assert "bad_id" in by_file["references/works/other/work.md"]
    assert "bad_location" in by_file["references/engineers/hanako.md"]


# ---------------------------------------------------------------------------
# materials: hashes only
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("materials,code", [
    (f'[{{ type: master, sha256: "{HEX}", file: "master_final" }}]', "material_file_name"),
    (f'[{{ type: master, sha256: "{HEX}", path: "masters" }}]', "material_file_name"),
    (f'[{{ type: master, sha256: "{HEX}", obtained: "master_final.wav" }}]', "audio_reference"),
    (f'[{{ type: master, sha256: "{HEX}", obtained: "master_final.wav" }}]', "material_file_name"),
    (f'[{{ type: stems, sha256_set: "{HEX}", obtained: "stems/kick.txt" }}]', "material_file_name"),
    (f'[{{ type: master, sha256: "{HEX}", obtained: "C:' + '/music/x" }}]', "absolute_path"),
    ('[{ type: master, obtained: "購入盤" }]', "bad_materials"),
    ('[{ type: master, sha256: "abc" }]', "bad_materials"),
    ('"master_final"', "bad_materials"),
])
def test_materials_hash_only(tmp_path, materials, code):
    root = good_kb(tmp_path / "kb")
    _w(root / "references/works/mysong/work.md", work_card(materials=materials))
    assert code in _codes(root)


def test_audio_and_absolute_paths_are_refused_in_new_directories(tmp_path):
    root = good_kb(tmp_path / "kb")
    _w(root / "references/works/mysong/refstudy.md", REFSTUDY + "\n元: track01.flac\n")
    _w(root / "theory/KT-0001.md", theory_card(body="## 要点\n\n" + "/ho" + "me/user/notes を参照。\n"))
    errs = _errors(root)
    assert {"file": "references/works/mysong/refstudy.md", "code": "audio_reference"} in \
        [{"file": e["file"], "code": e["code"]} for e in errs]
    assert any(e["file"] == "theory/KT-0001.md" and e["code"] == "absolute_path" for e in errs)


# ---------------------------------------------------------------------------
# publication stops (UD-1 / UD-4)
# ---------------------------------------------------------------------------

def test_publication_stop_a_applies_to_every_root(tmp_path):
    for root in (tmp_path / "kb", tmp_path / "_private" / "kb"):
        good_kb(root)
        _w(root / "references/works/mysong/work.md", work_card(rights="third_party", visibility="public"))
        assert "public_third_party" in _codes(root), root
    # a theory or any other card carrying rights: third_party + public is refused too (one rule)
    root = tmp_path / "_private" / "kb"
    _w(root / "references/works/mysong/work.md", work_card(rights="third_party", visibility="private"))
    _w(root / "theory/KT-0001.md", theory_card(rights="third_party"))
    errs = _errors(root)
    assert [e["file"] for e in errs if e["code"] == "public_third_party"] == ["theory/KT-0001.md"]
    assert kb.PUBLIC_FORBIDDEN_RIGHTS == ("third_party",)


def test_publication_stop_b_public_kb_holds_own_works_only(tmp_path):
    pub = good_kb(tmp_path / "kb")
    _w(pub / "references/works/mysong/work.md", work_card(rights="third_party", visibility="private"))
    errs = _errors(pub)
    files = {(e["file"], e["code"]) for e in errs}
    assert ("references/works/mysong/work.md", "public_kb_rights") in files
    # the engineer card of that work is refused too (UD-4)
    assert ("references/engineers/taro.md", "public_kb_rights") in files
    assert kb.lint(pub)["scope"] == "public"

    priv = good_kb(tmp_path / "_private" / "kb")
    _w(priv / "references/works/mysong/work.md", work_card(rights="third_party", visibility="private"))
    _w(priv / "references/engineers/taro.md", engineer_card(visibility="private"))
    res = (kb.write_index(priv), kb.lint(priv))[1]
    assert res["ok"], res["errors"]
    assert res["scope"] == "private" and kb.is_private_root(priv) and not kb.is_private_root(pub)
    # the scope can be forced either way
    assert "public_kb_rights" in _codes(priv, public=True)
    assert "public_kb_rights" not in _codes(pub, public=False)


def test_publication_stop_b_engineer_references(tmp_path):
    pub = good_kb(tmp_path / "kb")
    _w(pub / "references/works/theirs/work.md", work_card(slug="theirs", rights="own"))
    _w(pub / "references/works/theirs/refstudy.md", REFSTUDY)
    assert _errors(pub) == []
    # an unknown work cannot be confirmed as own
    _w(pub / "references/engineers/taro.md", engineer_card(works="[work_mysong, work_unknown]"))
    msgs = [e["message"] for e in _errors(pub) if e["code"] == "public_kb_rights"]
    assert any("work_unknown" in m for m in msgs) and not any("work_mysong" in m for m in msgs)
    # references in the body (id or link) count as well
    _w(pub / "references/works/theirs/work.md", work_card(slug="theirs", rights="third_party",
                                                          visibility="private"))
    _w(pub / "references/engineers/taro.md",
       engineer_card(body="- [他作品](../works/theirs/work.md)"))
    msgs = [e["message"] for e in _errors(pub) if e["code"] == "public_kb_rights"
            and e["file"] == "references/engineers/taro.md"]
    assert any("work_theirs" in m for m in msgs)


# ---------------------------------------------------------------------------
# theory cards: limits against copying
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("body,code", [
    ("## 要点\n\n" + "あ" * 1201 + "\n", "theory_too_long"),
    ("## 要点\n\n![図](fig.svg)\n", "theory_image"),
    ("## 要点\n\n<img src=\"x.svg\">\n", "theory_image"),
    ("## 要点\n\n> 引用された一文\n", "theory_blockquote"),
    ("## 要点\n\n「" + "い" * 81 + "」\n", "theory_long_quote"),
    ("## 要点\n\n『" + "う" * 81 + "』\n", "theory_long_quote"),
    ("## 要点\n\n\u201c" + "e" * 81 + "\u201d\n", "theory_long_quote"),
    ("## 要点\n\n\"" + "f" * 81 + "\"\n", "theory_long_quote"),
    ("## 要点\n\n「" + "お" * 50 + "\n" + "お" * 40 + "」\n", "theory_long_quote"),
])
def test_theory_copy_limits(tmp_path, body, code):
    root = good_kb(tmp_path / "kb")
    _w(root / "theory/KT-0001.md", theory_card(body=body))
    assert code in _codes(root)


def test_theory_within_limits_passes(tmp_path):
    root = good_kb(tmp_path / "kb")
    body = ("## 要点\n\n" + "あ" * 1100 + "\n\n" + " " * 300 + "\n「" + "い" * 80 + "」と「短い」。\n")
    _w(root / "theory/KT-0001.md", theory_card(body=body))
    assert _errors(root) == []
    # the copying limits are for theory cards only
    _w(root / "lessons/KL-0001.md", """---
id: KL-0001
kind: lesson
title: l
created: 2026-11-15
status: active
visibility: public
evidence: tip
---

> 引用ブロックは lesson では検査しない
""")
    assert _errors(root) == []


# ---------------------------------------------------------------------------
# granularity of refstudy / refsheet
# ---------------------------------------------------------------------------

def _frames_table(n: int, step: float = 0.1) -> str:
    rows = ["| 時刻 s | LUFS |", "|---|---|"]
    rows += [f"| {i * step:.1f} | {-12 - (i % 7) * 0.3:.1f} |" for i in range(n)]
    return "\n".join(rows) + "\n"


@pytest.mark.parametrize("extra", [
    _frames_table(20),                                                       # evenly spaced frame times
    "\n".join(["| 帯域 | dB |", "|---|---|"] + [f"| b{i} | -{i}.5 |" for i in range(65)]) + "\n",  # too many rows
    "| " + " | ".join(f"c{i}" for i in range(25)) + " |\n|" + "---|" * 25 + "\n| " +
    " | ".join("1" for _ in range(25)) + " |\n",                           # too many columns
    "\n".join(["| Hz | dB |", "|---|---|"] + [f"| {i * 10.7666:.4f} | -40 |" for i in range(1, 30)]) + "\n",
    "```\n" + ", ".join(f"{(i % 13) * 0.01:.3f}" for i in range(80)) + "\n```\n",   # waveform samples
    "```\n" + "\n".join(f"{i} -12.{i % 9} 0.{i % 7}" for i in range(40)) + "\n```\n",  # numeric dump
])
def test_reference_documents_refuse_fine_grained_data(tmp_path, extra):
    root = good_kb(tmp_path / "kb")
    for rel in ("references/works/mysong/refstudy.md", "songs/s/p1/refsheet.md"):
        _w(root / rel, REFSTUDY + "\n## 付録\n\n" + extra)
    errs = _errors(root)
    files = {e["file"] for e in errs if e["code"] == "too_fine"}
    assert files == {"references/works/mysong/refstudy.md", "songs/s/p1/refsheet.md"}, errs


def test_reference_documents_section_and_band_level_pass(tmp_path):
    root = good_kb(tmp_path / "kb")
    stems = ["| ステム | 役割 | LUFS 差 | 側／中央 |", "|---|---|---|---|"]
    stems += [f"| s{i:02d} | other | -{i}.0 | 0.{i} |" for i in range(1, 25)]
    _w(root / "references/works/mysong/refstudy.md",
       REFSTUDY + "\n## LTAS\n\n" + _erb_table() + "\n## ステム\n\n" + "\n".join(stems) + "\n")
    _w(root / "songs/s/p1/refsheet.md", REFSTUDY)
    assert _errors(root) == []
    # other documents are not limited (the existing dossier keeps its tables)
    _w(root / "songs/s/dossier.md", "# dossier\n\n" + _frames_table(80))
    assert _errors(root) == []


# ---------------------------------------------------------------------------
# index order
# ---------------------------------------------------------------------------

def test_index_order_inserts_new_kinds(tmp_path):
    root = good_kb(tmp_path / "kb")
    shutil.copytree(REPO_KB / "songs", root / "songs")
    shutil.copytree(REPO_KB / "lessons", root / "lessons")
    shutil.copytree(REPO_KB / "moves", root / "moves")
    order = [c["meta"]["kind"] for c in kb.sorted_cards(root)]
    seen = list(dict.fromkeys(order))
    assert seen == [k for k in kb.KINDS if k in seen]
    assert seen.index("song") < seen.index("work") < seen.index("engineer") < seen.index("lesson") \
        < seen.index("move") < seen.index("theory") < seen.index("outcome")
    idx = kb.build_index(root)
    assert "並び順: 種類（song > work > engineer > lesson > move > research > theory > outcome > direction > " \
           "analysis > research-log）→ ID。" in idx


def test_existing_kinds_keep_their_relative_order_and_rows(tmp_path):
    legacy = ("song", "lesson", "move", "research", "outcome", "direction", "analysis", "research-log")
    assert [k for k in kb.KINDS if k in legacy] == list(legacy)
    repo_rows = [ln for ln in (REPO_KB / "INDEX.md").read_text(encoding="utf-8").splitlines()
                 if ln.startswith("| [")]
    root = tmp_path / "kb"
    shutil.copytree(REPO_KB, root)
    # the repository kb carries real theory cards: use an ID it does not have, so the test card adds a row
    assert not (root / "theory/KT-9001.md").exists()
    good_kb(root, theory_id="KT-9001")
    rows = [ln for ln in kb.build_index(root).splitlines() if ln.startswith("| [")]
    kept = [ln for ln in rows if ln in repo_rows]
    assert kept == repo_rows                          # same text, same relative order
    assert len(rows) == len(repo_rows) + 3
    assert any("KT-9001" in ln for ln in rows if ln not in repo_rows)


def test_repository_kb_lints_ok_and_index_is_unchanged():
    res = kb.lint(REPO_KB)
    assert res["ok"], res["errors"]
    assert kb.build_index(REPO_KB) == (REPO_KB / "INDEX.md").read_text(encoding="utf-8")
    # The design order (§2.2) itself, pinned independently of the heading.
    # upgrade 2 (§6.3 b) inserts 'curriculum' right after 'theory'
    assert kb.KINDS == ("song", "work", "engineer", "lesson", "move", "research", "theory", "curriculum",
                        "outcome", "direction", "analysis", "research-log")
    legacy = ("song", "lesson", "move", "research", "outcome", "direction", "analysis", "research-log")
    assert [k for k in kb.KINDS if k in legacy] == list(legacy)
    # Heading = legacy kinds + the new kinds actually present in the repository kb, in design order.
    present = {c["meta"].get("kind") for c in kb.load_cards(REPO_KB)}
    shown = [k for k in kb.KINDS if k in legacy or k in present]
    assert f"並び順: 種類（{' > '.join(shown)}）→ ID。" in kb.build_index(REPO_KB)


# ---------------------------------------------------------------------------
# search / show
# ---------------------------------------------------------------------------

def _search_kb(tmp_path) -> Path:
    root = good_kb(tmp_path / "kb")
    _w(root / "theory/KT-0002.md", theory_card(cid="KT-0002", domain="harmony", tradition="berklee-style",
                                               body="## 要点\n\nダイアトニックの機能。\n"))
    shutil.copytree(REPO_KB / "lessons", root / "lessons")
    shutil.copytree(REPO_KB / "songs", root / "songs")
    kb.write_index(root)
    return root


def test_search_filters_and_order(tmp_path):
    root = _search_kb(tmp_path)
    allc = kb.search(root)
    assert [c["id"] for c in allc["cards"]] == [c["meta"]["id"] for c in kb.sorted_cards(root)]
    th = kb.search(root, kind="theory")
    assert [c["id"] for c in th["cards"]] == ["KT-0001", "KT-0002"] and th["count"] == 2
    assert [c["id"] for c in kb.search(root, kind=["work", "engineer"])["cards"]] == ["work_mysong", "eng_taro"]
    assert [c["id"] for c in kb.search(root, kind="theory", text="ダイアトニック")["cards"]] == ["KT-0002"]
    assert [c["id"] for c in kb.search(root, text="kt-0001")["cards"]] == ["KT-0001"]
    hip = [c["id"] for c in kb.search(root, genre="HipHop")["cards"]]
    assert "work_mysong" in hip and "KL-0001" in hip and "KT-0001" not in hip
    assert kb.search(root, kind="theory", genre="hiphop")["cards"] == []
    entry = th["cards"][0]
    assert set(entry) == {"id", "kind", "title", "path", "status", "evidence", "visibility", "applies_to",
                          "summary"}


def test_show_returns_front_matter_and_body(tmp_path):
    root = _search_kb(tmp_path)
    w = kb.show(root, "work_mysong")
    assert w["path"] == "references/works/mysong/work.md"
    assert w["front_matter"]["rights"] == "own" and "何の作品か" in w["body"]
    t = kb.show(root, "KT-0002")
    assert t["front_matter"]["domain"] == "harmony" and "ダイアトニック" in t["body"]
    assert kb.show(root, "KL-0001")["front_matter"]["kind"] == "lesson"
    assert kb.show(root, "KT-9999") is None


def test_cli_search_and_show(tmp_path, capsys):
    root = _search_kb(tmp_path)
    assert cli_main(["kb", "search", "--kind", "theory", "--root", str(root)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert [c["id"] for c in out["cards"]] == ["KT-0001", "KT-0002"]
    assert cli_main(["kb", "search", "--kind", "work", "--genre", "hiphop", "--text", "自作", "--root",
                     str(root)]) == 0
    assert [c["id"] for c in json.loads(capsys.readouterr().out)["cards"]] == ["work_mysong"]
    assert cli_main(["kb", "show", "KT-0001", "--root", str(root)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["id"] == "KT-0001" and out["front_matter"]["paraphrase"] is True and "要点" in out["body"]
    assert cli_main(["kb", "show", "nope", "--root", str(root)]) == 2
    assert json.loads(capsys.readouterr().out)["error"] == "input_error"
    assert cli_main(["kb", "search", "--root", str(tmp_path / "missing")]) == 2
    capsys.readouterr()
    # deterministic: same bytes twice
    cli_main(["kb", "search", "--root", str(root)])
    a = capsys.readouterr().out
    cli_main(["kb", "search", "--root", str(root)])
    assert capsys.readouterr().out == a


def test_cli_lint_reports_publication_stop(tmp_path, capsys):
    root = good_kb(tmp_path / "kb")
    _w(root / "references/works/mysong/work.md", work_card(rights="third_party", visibility="private"))
    kb.write_index(root)
    assert cli_main(["kb", "lint", "--root", str(root)]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["scope"] == "public" and any(e["code"] == "public_kb_rights" for e in out["errors"])


# ---------------------------------------------------------------------------
# optional name block list (tools/check_hygiene.py)
# ---------------------------------------------------------------------------

def _hygiene():
    spec = importlib.util.spec_from_file_location("check_hygiene", REPO / "tools" / "check_hygiene.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_blocklist_absent_means_no_check(tmp_path):
    h = _hygiene()
    assert h.load_blocklist(tmp_path) == []
    assert h.blocked_names("docs/a.md", "anything", []) == []


def test_blocklist_matches_without_printing_the_word(tmp_path):
    h = _hygiene()
    _w(tmp_path / "_private" / "blocklist.txt", "# comment\n\nSecretName\n")
    bl = h.load_blocklist(tmp_path)
    assert bl == [(3, "secretname")]
    found = h.blocked_names("kb/secretname-notes.md", "ok\nmet secretNAME today\n", bl)
    assert found == ["kb/secretname-notes.md: blocked name in the path (blocklist line 3)",
                     "kb/secretname-notes.md:2: blocked name (blocklist line 3)"]
    assert all("ecret" not in f.split(":", 1)[1].replace("secretname-notes", "") for f in found)
