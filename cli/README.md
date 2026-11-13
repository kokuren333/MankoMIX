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
| `init [PATH] [--title T] [--genre G] [--project-id ID]` | `init_project` | プロジェクトの作成 |
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
| `objective set SPEC [--variant V]` | `objective_set` | 目的関数の指定。`comfort`、`bass_heavy:0.7`（強度）、`comfort:0.6+bass_heavy:0.4`（混合）、JSON（`{"blend", "intensity", "overrides", "lead_stem"}`、`@file`、`-`）。制約（S-nn）は緩和できない |
| `objective validate DEF` | `objective_validate` | 目的関数の定義（`.json`、インライン JSON、`@file`、`-`）または指定の検証。未知の指標 ID、重みの合計、宣言のないパラメータ、制約の緩和を検出し、エラーがあれば終了コード 2 |
| `reference add FILE [--label L]` / `reference list` / `reference remove ID` | `reference_add` / `reference_list` / `reference_remove` | リファレンス曲。測定ベクトルだけを `analysis/ref_<id>.json` に保存し、音声はコピーしない（§4.6、D-039） |
| `route` | `route` | マスタリング経路の選択（R-21） |
| `master plan --profile P [--delivery D] [--objective O] [--apply]` / `master apply PROPOSAL` | `master_plan` / `master_apply` | マスタリング段の計画（プランナーのループなし）と適用 |
| `plan propose [--stage master] [--profile P] [--delivery D] [--objective O] [--variant V] [--max-iter N]` | `plan_propose` | 段の計画の提案。プランナーがレベルマッチ後のプレビューで目的関数に沿って小さな手を試し、最良の候補を提案する。`cache/proposals/<id>.json` に保存し、適用はしない（R-31） |
| `plan apply PROPOSAL` | `plan_apply` | 提案を承認して適用。バリアントにチェーン、目的関数の評価（score と指標別の内訳、制約、ゲート）、6 要素の判断を保存する |
| `plan reject ID --reason R` | `plan_reject` | 提案を却下して別案を求める。履歴（op `plan_reject`）と提案ファイルに記録し、却下した提案は適用できない |
| `plan run [--profile P] [--objective O] [--max-iter N] [--apply]` | `planner_run` | プランナーのループ（§7.2）。反復の記録、収束の理由、未解決事項を返す。操作者は既定で `planner` |
| `render [VARIANT] [--output P:D]` / `export [VARIANT]` | `render` / `export` | 出口ごとのレンダリングとマニフェスト |
| `verify [VARIANT]` | `verify` | 検証（不合格・未完了は終了コード 1） |
| `gate [VARIANT]` | `gate_check` | トランスレーション・ゲート（OF-5）。`incomplete`（ステムがないと評価できない検査など）は合格扱いにせず終了コード 1 |
| `report [VARIANT] [--lang ja\|en\|both] [--no-write]` | `report` | Mix Report（JSON と Markdown）。5 章に指標別の内訳、6 章に制約とゲート |
| `get [POINTER]` | `project_get` | project.json 全体、または JSON pointer の位置の値 |
| `knowledge [QUERY...] [--id ID] [--kind K] [--source S]` | `knowledge_lookup` | 判断規則（R-01〜R-33）、知覚語彙、帯域、ジャンル prior、閾値の検索 |
| `mcp [--root DIR]` | — | MCP サーバー（標準入出力） |

後続マイルストーンのコマンド（`stem` `separate` `clean` `mix` `run` `model` `serve`）は登録済みで、現時点では `not implemented yet (milestone Mx)` を返して終了コード 2 で終わる。

```
mankomix init song.mmx --title "Example Song" --genre jpop
mankomix -p song.mmx import "./Suno export"
mankomix -p song.mmx analyze
mankomix -p song.mmx status --format text
mankomix -p song.mmx objective set comfort:0.6+bass_heavy:0.4
mankomix -p song.mmx plan propose --profile spotify
mankomix -p song.mmx plan apply mpl_0123456789ab
mankomix -p song.mmx render var_spotify
mankomix -p song.mmx report var_spotify --lang ja
python -m mankomix.cli doctor
```
