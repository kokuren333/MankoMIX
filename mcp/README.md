# mcp — MCP サーバー

AI エージェント向けの MCP サーバー。コア API（`core/api.py`）を 1 対 1 で包み、CLI と同じ粒度のツールを公開する（`docs/SPEC.md` §10.3）。外部ライブラリ（MCP SDK）には依存しない。

- 通信: 標準入出力の JSON-RPC 2.0（1 行 1 メッセージ、UTF-8）。標準出力にはプロトコルのメッセージだけを書き、ログは標準エラーへ（`MANKOMIX_MCP_LOG=INFO` などで詳しくできる）
- 対応メソッド: `initialize` / `notifications/initialized` / `ping` / `tools/list` / `tools/call`
- 対応プロトコル版: `2025-11-25` / `2025-06-18` / `2025-03-26` / `2024-11-05`（クライアントの版が対応範囲ならそのまま返し、そうでなければ最新を返す）
- 外部サービスの MCP（Suno など）には依存しない

## 起動

```
mankomix mcp --root <作業フォルダ>
python -m mankomix.mcp --root <作業フォルダ>
```

`--root` を省くとカレントフォルダが作業フォルダになる。

## MCP クライアントへの登録

多くのクライアント（Claude Desktop、Claude Code、Cursor など）は次の形の JSON 設定を受け付ける。`<作業フォルダ>` を楽曲プロジェクトを置くフォルダに置き換える。

```json
{
  "mcpServers": {
    "mankomix": {
      "command": "mankomix",
      "args": ["mcp", "--root", "<作業フォルダ>"]
    }
  }
}
```

`mankomix` コマンドがインストールされていない（ソースのチェックアウトから使う）場合は、`"command": "python"`、`"args": ["-m", "mankomix.mcp", "--root", "<作業フォルダ>"]` とし、環境変数 `PYTHONPATH` にリポジトリのフォルダを渡す（`"env": {"PYTHONPATH": "<リポジトリ>"}`）。

## 共通のふるまい

| 項目 | 内容 |
|---|---|
| 作業フォルダの制限 | パス引数はすべて作業フォルダ基準で解決し、外に出るもの（`..`、外の絶対パス、ドライブ相対パス、外を指すシンボリックリンクやジャンクション）は `path_outside_workspace` で拒否する。結果に絶対パスは含めない |
| `project` 引数 | 作業フォルダ内のプロジェクトフォルダ。省略時は `.`（作業フォルダ自体） |
| 要約と詳細 | 応答は要約が既定（件数、主要な測定値、ID）。`detail: "full"` で API の結果をそのまま返す |
| ジョブ | 時間のかかるツール（`analyze_run`、`separate_run`、`model_pull`、`render_preview`、`export_run` など）は `async: true` でジョブ ID を返す。`job_status` / `job_result` / `job_list` で問い合わせる。同じプロジェクトで同時に動くジョブは 1 つまで（`project_busy`） |
| 操作者 | プロジェクトを変更するツールは、履歴に actor `agent` を記録する（引数では変えられない） |
| エラー | ツールの失敗は `isError: true` の結果で返す（`{"error", "message", "details"}`。CLI と同じコード）。未知のメソッドや不正なパラメータは JSON-RPC のエラー |

結果は `content[0].text`（JSON 文字列）と `structuredContent`（同じオブジェクト）の両方で返す。

## ツール

| ツール | API 関数 | CLI | 内容 |
|---|---|---|---|
| `doctor` | `doctor` | `doctor` | 依存、FFmpeg のビルド構成、符号化器、GPU、モデル |
| `project_init` | `init_project` | `init` | プロジェクトの作成 |
| `project_open` | `status` | `status` | プロジェクトの要約 |
| `project_get` | `project_get` | `get` | project.json 全体、または JSON pointer の位置の値 |
| `project_set` | `set_value` | `set` | JSON pointer で 1 値を変更 |
| `project_patch` | `patch` | `patch` | RFC 6902 パッチ |
| `project_validate` | `validate_project` | `validate` | 正本の検証 |
| `import_files` | `import_files` | `import` | ファイル入力アダプタでの取り込みと取り込み検査 |
| `analyze_run` | `analyze` | `analyze` | 全素材とステム合算の測定（ジョブ可） |
| `measure_audio` | `measure_audio` | `measure` | 任意の音声の測定 |
| `compare_audio` | `compare_audio` | `compare` | レベルマッチ比較 |
| `objective_list` / `objective_get` | `objective_list` / `objective_show` | `objective list` / `show` | 目的関数 |
| `objective_set` / `objective_validate` | `objective_set` / `objective_validate` | `objective set` / `validate` | 目的関数の指定（混合、強度、公開パラメータ、主役）と、定義ファイルや指定の検証（制約の緩和は不可） |
| `reference_add` / `reference_list` / `reference_remove` | `reference_add` / `reference_list` / `reference_remove` | `reference add` / `list` / `remove` | リファレンス曲。測定ベクトルだけを保存し、音声はプロジェクトに含めない（ジョブ可） |
| `plan_propose` / `plan_apply` / `plan_reject` | `plan_propose` / `plan_apply` / `plan_reject` | `plan propose` / `apply` / `reject` | 段の計画の提案（`cache/proposals/<id>.json`、ジョブ可）、承認して適用、却下して別案（R-31。却下は履歴に記録） |
| `plan_run` | `planner_run` | `plan run` | プランナーのループ（測定 → プレビュー → 評価 → 反復）。`apply: true` で適用（ジョブ可） |
| `gate_check` | `gate_check` | `gate` | トランスレーション・ゲート（OF-5）。`incomplete` は合格扱いにしない |
| `profile_list` / `profile_get` | `profile_list` / `profile_show` | `profile list` / `show` | 媒体プロファイルと納品形式 |
| `history_list` / `history_undo` / `history_checkout` | `history` / `undo` / `checkout` | `history` / `undo` / `checkout` | 操作履歴 |
| `knowledge_lookup` | `knowledge_lookup` | `knowledge` | `knowledge/*.json` の検索（判断規則 R-01〜R-33、知覚語彙、帯域、ジャンル prior、閾値）。id、ラベル、注記の自由語検索 |
| `plan_list` / `plan_get` | `proposal_list` / `proposal_get` | `plan list` / `show` | 保存済みの提案（全状態、新しい順、提案者つき）。`plan_apply` の `edits` で適用前にパラメータを編集できる |
| `variant_list` | `variant_list` | `variant list` | バリアント、出口、レンダリング済みか |
| `analysis_get` | `analysis_view` | `analysis` | 解析の表示用データ（ラウドネスの時系列、LTAS、帯域別相関、ステムの配置、診断、前後の指標。ジョブ可） |
| `audio_get` | `audio_set` | `listen` | 試聴セット（処理前／処理後／除去分のプロジェクト相対パスと、レベルマッチのゲイン。ジョブ可） |
| `verify_get` | `verification_get` | `verify --last` | 直前の検証結果（再実行しない） |
| `delivery_list` | `delivery_list` | `profile deliveries` | 納品形式。`profile_list` / `objective_list` は `full: true` で完全な定義 |
| `model_list` / `model_get` | `model_list` / `model_show` | `model list` / `show` | モデルレジストリ（公式と BYOW）、ライセンスと根拠、ローカルの状態 |
| `model_pull` | `model_pull` | `model pull` | 固定された公式配布元から取得し sha256 を照合（ジョブ可）。`verified` 以外は `allow_candidate` |
| `model_register` / `model_verify` / `model_remove` | 同名 | `model register` / `verify` / `remove` | BYOW の登録（`path` は作業フォルダ内）、再ハッシュ照合、削除 |
| `separate_run` / `separate_list` | `separate` / `separation_list` | `separate` / `separate --records` | ステム分離（ジョブ可。`source` は素材 ID）と分離の記録。ウェイトは取得しない（S-10） |
| `job_status` / `job_result` / `job_list` | — | — | ジョブの問い合わせ（サーバー側の機能） |

`plan_propose` / `plan_run` で作った提案には `author: "agent"` が記録され、GUI では承認待ちのエージェント提案として表示される（D-035）。

段の処理、リミックス操作、一括実行:

| ツール | コア API | CLI | 内容 |
|---|---|---|---|
| `clean_plan` / `clean_apply` / `clean_delta` | `clean_plan` / `clean_apply` / `clean_delta` | `clean plan` / `apply` / `delta` | 整音の計画（`targets`、`overrides`、`apply`）、承認して適用、除去分の書き出し（ジョブ可） |
| `mix_plan` / `mix_apply` | `mix_plan` / `mix_apply` | `mix plan` / `apply` | ミックス段の計画（固定順、段ごとの測定、`variant` でバリアントの差分）と適用（`edits` 可。ジョブ可） |
| `plan_propose` / `plan_apply` | 同名 | `plan propose --stage` / `plan apply` | `stage: "clean" \| "mix" \| "master"` で段ごとの提案と適用（§10.3） |
| `stems_list` / `stems_add` / `stems_replace` / `stems_remove` | `stem_list` / `stem_add` / `stem_replace` / `stem_remove` | `stem list` / `add` / `replace` / `remove` | リミックス操作（§9.3）。`stems_replace` は `source`（作業フォルダ内のファイル）か `asset`（既存の素材 id） |
| `stems_edit` | `stem_edit` | `stem split` / `mute` / `move` / `role` / `range-replace` / `remove` | `op` で分割・区間の無効化・再配置・役割・区間の差し替え・削除。時間はサンプル数か `1.5s` |
| `stems_export` | `stem_export` | `stem export` | ステムの書き出し（`out_dir` はプロジェクト相対。ジョブ可） |
| `pipeline_run` | `run` | `run` | 一括実行（取り込みから検証と Mix Report まで、プランナーだけ）。段ごとの状態とゲート、検証結果、納品物を返す。`exit_code` 1 は段ゲートか検証の不合格。`project` を省くと `out` の隣の `<名前>.mmx`（作業フォルダ内）。ジョブ可 |

`render_spectrogram` は表に登録済みで、対応する関数が `core/api.py` に入ると自動で公開される。`render_preview` / `export_run` / `verify_run` / `report_get` / `master_plan` / `master_apply` は `render` / `export` / `verify` / `report` / `master_plan` / `master_apply` を包む。`verify_run` の `profiles` は検証専用プロファイル（§15.2、再レンダリングなし）、`clean_delta` の `asset: "stems"` はステム全体の除去分。

`project_get` と `knowledge_lookup` もコア API（`api.project_get`、`api.knowledge_lookup`、実体は `core/knowledge.py`）を包む。判断規則の索引（R-01〜R-33）は `knowledge/rules.json` のデータで、`knowledge_lookup` の `kind: "rule"` として引ける。

## ツールの追加

`tools.py` の `SPECS` に 1 行足す。入力スキーマは API 関数のシグネチャから作られる（`project_path` → `project`、パス名の引数 → 作業フォルダ内で解決、`actor` → 常に `agent`、`detail` → 要約／詳細）。要約関数（`summary=`）を省くと、小さい結果はそのまま、大きい結果は浅く切り詰めて返す。

```python
ToolSpec("verify_run", ("verify_run", "verify"), "Run verification of the rendered outputs."),
```

## ファイル

| ファイル | 内容 |
|---|---|
| `server.py` | JSON-RPC の受け渡しと標準入出力のループ |
| `tools.py` | ツール表、API シグネチャからのスキーマ生成、要約 |
| `jobs.py` | バックグラウンドジョブ（プロジェクトごとに 1 つ） |
| `workspace.py` | 作業フォルダの制限と結果の絶対パス除去 |
| `knowledge.py` | 旧い import 経路の互換（実体は `core/knowledge.py`） |
