# cli — コマンドラインインターフェース

コア API（`core/api.py`）を 1 対 1 で包む `mankomix` コマンド（短縮名 `mmx`）。コマンド体系は `docs/SPEC.md` §10.2。

- 既定の出力は機械可読な JSON（標準出力、UTF-8）。`--format text` で短い要約
- 出力に絶対パスを含めない（プロジェクト相対パスかファイル名だけ）
- 終了コード: 0 成功 / 1 検証不合格 / 2 入力エラー / 3 環境エラー。エラーも JSON（`{"error", "message", "details"}`）で返す
- MCP と GUI サーバーも同じ `core/api.py` の関数を呼ぶ。片方にしかない機能を作らない

共通オプション（コマンドの前後どちらでも可）: `--project/-p PATH`（既定: `project.json` があればカレントフォルダ）、`--actor human|agent|planner`、`--format json|text`、`--debug`。

| コマンド | API 関数 | 内容 |
|---|---|---|
| `doctor [--strict-lgpl]` | `doctor` | 依存、FFmpeg の版とビルド構成（lgpl / gpl / nonfree）、往復検査用の符号化器、ffprobe、GPU、モデルの状態 |
| `init [PATH] [--title T] [--genre G]` | `init_project` | プロジェクトの作成 |
| `import SRC... [--mode copy\|link] [--provenance JSON]` | `import_files` | ファイル入力アダプタで無加工取り込み＋取り込み検査 |
| `status` | `status` | 素材と役割、トラック、フルミックス、検査件数、解析キャッシュ、直近の履歴 |
| `validate` | `validate_project` | 正本の検証（エラーがあれば終了コード 2） |
| `analyze [--force]` | `analyze` | 全素材と静的ステム合算の測定。`analysis/` に保存し、ハッシュと解析器の版でキャッシュ |
| `measure FILE` | `measure_audio` | 任意の音声の測定 |
| `compare A B` | `compare_audio` | レベルマッチ比較 |
| `set POINTER VALUE_JSON [--reason R]` | `set_value` | JSON pointer で 1 値を変更 |
| `patch OPS [--reason R]` | `patch` | RFC 6902 パッチ（インライン、`@file`、`-` で標準入力） |
| `history [--limit N] [--detail]` / `undo` / `checkout SEQ` | `history` / `undo` / `checkout` | 操作履歴 |
| `profile list` / `profile show ID` | `profile_list` / `profile_show` | 媒体プロファイルと納品形式 |
| `objective list` / `objective show ID` | `objective_list` / `objective_show` | 目的関数 |

後続マイルストーンのコマンド（`stem` `separate` `clean` `mix` `master` `render` `export` `verify` `report` `run` `model` `reference` `serve` `mcp`、`objective set/validate`）は登録済みで、現時点では `not implemented yet (milestone Mx)` を返して終了コード 2 で終わる。

```
mankomix init song.mmx --title "Example Song" --genre jpop
mankomix -p song.mmx import "./Suno export"
mankomix -p song.mmx analyze
mankomix -p song.mmx status --format text
python -m mankomix.cli doctor
```
