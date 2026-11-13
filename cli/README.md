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
| `profile list --detail` / `profile deliveries` | `profile_list(full=True)` / `delivery_list` | プロファイルの完全な定義、納品形式（コンテナ、レート、ビット深度、ディザ） |
| `objective list --detail` | `objective_list(full=True)` | 目的関数の完全な定義（項、制約の強調） |
| `plan apply PROPOSAL [--edits JSON]` | `plan_apply` | `--edits '{"<処理 id>": {"<パラメータ>": 値}}'` で提案のパラメータを編集してから適用（既存のパラメータのみ） |
| `plan list [--variant V] [--stage S] [--status pending\|applied\|rejected]` / `plan show ID` | `proposal_list` / `proposal_get` | 保存済みの提案（プランナーとエージェント、全状態、新しい順）。提案者（`author`）と状態つき |
| `verify [VARIANT] --last` | `verification_get` | 直前の検証結果を再実行せずに表示（制約、プロファイル、コーデック、ノイズ戻りの行。正本が変わっていれば `stale`） |
| `variant list` | `variant_list` | バリアント（目的関数 × 媒体）、出口、レンダリング済みか |
| `listen [VARIANT]` | `audio_set` | 試聴セット: 処理前（フルミックス、またはステムの静的合算）、処理後、除去分、レベルマッチのゲイン（大きい方を下げる） |
| `analysis [VARIANT]` | `analysis_view` | 解析の表示用データ: ラウドネスの時系列、LTAS、帯域別相関、ステムの配置、診断、前後の指標（先に `analyze`） |
| `model list` / `model show ID` | `model_list` / `model_show` | モデルレジストリ（公式カタログと BYOW）、ライセンスと根拠、ローカルの状態 |
| `model pull ID [--allow-candidate] [--force]` | `model_pull` | 固定された公式配布元から取得し sha256 を照合。`verified` 以外は `--allow-candidate` が要る |
| `model register PATH --id ID --license-weights L [--usage-restrictions U] [--evidence-url URL] [--stems a,b] [--runtime JSON] [--replace]` | `model_register` | 手持ちのウェイトの登録（BYOW）。ハッシュを取るだけで、コピー・配布はしない |
| `model verify ID` / `model remove ID` | `model_verify` / `model_remove` | ウェイトの再ハッシュ照合 / 取得済みウェイトの削除（BYOW は登録の解除のみ） |
| `separate [--model M] [--source ASSET] [--mode preview\|full] [--stems a,b] [--device auto\|cpu\|cuda] [--excerpt-s N] [--add-tracks\|--no-add-tracks]` | `separate` | ステム分離（§6.2）。モデルは別プロセスで実行し、ここでは取得しない。`preview` は最も大きい区間だけ、`full` は全尺でトラックも追加（操作はバランスに限定、R-22）。`--records` で分離の記録の一覧（`separation_list`） |
| `serve [--root DIR] [--host 127.0.0.1] [--port 8765] [--static gui/dist] [--allow-remote]` | — | GUI 用のローカルサーバー（`core/server/`。HTTP と Server-Sent Events）。`--project` で開くプロジェクトを指定。既定は 127.0.0.1 だけで待ち受け、それ以外のアドレスは `--allow-remote` がないと拒否する。起動時に `{"serving": ...}` を 1 行出力 |
| `mcp [--root DIR]` | — | MCP サーバー（標準入出力） |

`doctor` の `models` は、公式（verified）／候補／BYOW の件数と、ウェイトが手元にあるモデル（`downloaded`、`byow_available`）を返す。

段の処理、リミックス操作、一括実行（§6.4、§6.5、§9.3、§7.1）:

| コマンド | コア API | 内容 |
|---|---|---|
| `clean plan [--target T ...] [--overrides JSON] [--apply]` | `clean_plan` | 整音の計画。ステムごと（フルミックス経路では 2mix）に診断し、何も検出しなかった素材は理由つきで `skipped`。`--overrides '{"spectral_reduction": "light"}'`（全対象、または素材・トラック id ごと）。`cache/proposals/cln_*.json` に保存 |
| `clean apply PROPOSAL` | `clean_apply` | 整音の提案を承認して適用（整音済み音声、除去分、記録、ノイズ基準。トラックごとの計画を正本へ） |
| `clean delta ASSET` | `clean_delta` | 除去分の音声（入力 − 出力）を `renders/delta/<asset>.wav` に書き出す。素材 id、トラック id、`fullmix` |
| `mix plan [--variant V] [--objective O] [--max-iter N] [--full-length] [--apply]` | `mix_plan` | ミックス段の計画（固定順: 静的バランス、編曲の提案、減算 EQ、ダイナミクス、加算 EQ、空間、ミックスバス。各段の後で測定）。`--variant` はバリアントの `track_overrides` として保存 |
| `mix apply PROPOSAL [--edits JSON]` | `mix_apply` | ミックスの提案を承認して適用（`mix.applied` / `decisions` / `evaluation`） |
| `plan propose --stage clean\|mix\|master` / `plan apply` / `plan reject` | `plan_propose` / `plan_apply` / `plan_reject` | 全段で共通の提案・承認・却下（clean は `--target` / `--overrides`） |
| `stem list` | `stem_list` | トラック、クリップ、未使用の素材、R-22 の注記 |
| `stem add FILE [--role R]` / `stem replace TRACK (FILE \| --asset ID) [--drop-chain]` / `stem remove TRACK` | `stem_add` / `stem_replace` / `stem_remove` | ステムの追加・差し替え（取り込み検査、テンポ・キーの整合は報告のみ、D-048）・削除（素材は残り `unused`） |
| `stem split CLIP AT` / `stem mute TRACK START END` / `stem move CLIP POS` / `stem range-replace TRACK START END ASSET [--source-start S]` / `stem role TRACK ROLE [--lead\|--no-lead]` | `stem_split` / `stem_mute` / `stem_move` / `stem_range_replace` / `stem_role` | クリップの分割、区間の無効化、再配置、区間の差し替え、役割と主役。時間はサンプル数か秒（`1.5s`） |
| `stem export [--track T ...] [--raw] [--out-dir D] [--subtype FLOAT\|PCM_24\|PCM_16] [--variant V]` | `stem_export` | 処理後（または編集後のクリップだけ）のステムの書き出しとマニフェスト |
| `run SOURCES... [--objective O] [--profile P ...] [--delivery D ...] [--variants JSON] [--out DIR] [--genre G] [--title T] [--separate] [--variant-mix] [--mix-max-iter N] [--max-iter N]` | `run` | 一括実行（プランナーだけ）。取り込み → 解析 → 整音 → ミックス（ステムがある場合。2mix だけならフルミックス経路）→ バリアントごとのマスタリング → レンダリング → 検証 → Mix Report（ja + en）。`--out` にマスター、マニフェスト、レポート、`run_summary.json` を置く。プロジェクトは既定で `--out` の隣の `<名前>.mmx`。段ゲートに落ちたら理由つきで止まり（整音 S-07、ミックス S-03/S-04。マスタリングのプレビューでの S-nn 不合格は報告して検証へ委ねる。OF-5 不合格は `unresolved` に記録）、検証不合格は終了コード 1（そのバリアントのマスターは納品しない） |

`--profile` と `--delivery` は繰り返せる（全プロファイルに全納品形式）。`--variants '[{"objective": "bass_heavy:0.7", "profile": "club"}]'` で組み合わせを直接指定できる。最初の目的関数のバリアントは `var_<profile>`、それ以外は `var_<objective>_<profile>`。

`STUB_GROUPS` の仕組み（未実装のグループを登録して `not implemented yet (milestone Mx)` で終了コード 2 を返す）は、後続のグループのために残している。現時点で該当するグループはない。

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
mankomix model list
mankomix -p song.mmx separate --mode preview
mankomix -p song.mmx clean plan --apply
mankomix -p song.mmx mix plan
mankomix -p song.mmx mix apply mxp_0123456789ab
mankomix -p song.mmx stem mute trk_vocals 12.5s 14s
mankomix run ./stems --objective comfort --profile spotify --delivery distributor_44k16 --out ./out
mankomix run ./stems --objective bass_heavy:0.7 --profile club --out ./out
mankomix serve --project song.mmx
python -m mankomix.cli doctor
```
