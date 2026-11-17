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
| `verify [VARIANT] [--against-profile P ...]` | `verify` | 検証（不合格・未完了は終了コード 1）。`--against-profile` は検証専用プロファイル（§15.2）: 既にレンダリングしたマスターを、そのプロファイルの P-03 / S-01（条件付き天井を含む）/ S-02 で判定する。再レンダリングせず正本も変えない。結果は `reports/verify_<variant>__against.json` |
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
| `clean delta ASSET` | `clean_delta` | 除去分の音声（入力 − 出力）を `renders/delta/<asset>.wav` に書き出す。素材 id、トラック id、`fullmix`。`stems` はステム全体の除去分（無加工のステム合算 − 整音後のステム合算）を `renders/delta/stem_sum_delta.wav` に書き、`listen` のステム経路の delta になる |
| `mix plan [--variant V] [--objective O] [--max-iter N] [--full-length] [--apply]` | `mix_plan` | ミックス段の計画（固定順: 静的バランス、編曲の提案、減算 EQ、ダイナミクス、加算 EQ、空間、ミックスバス。各段の後で測定）。`--variant` はバリアントの `track_overrides` として保存 |
| `mix apply PROPOSAL [--edits JSON]` | `mix_apply` | ミックスの提案を承認して適用（`mix.applied` / `decisions` / `evaluation`） |
| `plan propose --stage clean\|mix\|master` / `plan apply` / `plan reject` | `plan_propose` / `plan_apply` / `plan_reject` | 全段で共通の提案・承認・却下（clean は `--target` / `--overrides`） |
| `stem list` | `stem_list` | トラック、クリップ、未使用の素材、R-22 の注記 |
| `stem add FILE [--role R]` / `stem replace TRACK (FILE \| --asset ID) [--drop-chain]` / `stem remove TRACK` | `stem_add` / `stem_replace` / `stem_remove` | ステムの追加・差し替え（取り込み検査、テンポ・キーの整合は報告のみ、D-048）・削除（素材は残り `unused`） |
| `stem split CLIP AT` / `stem mute TRACK START END` / `stem move CLIP POS` / `stem range-replace TRACK START END ASSET [--source-start S]` / `stem role TRACK ROLE [--lead\|--no-lead]` | `stem_split` / `stem_mute` / `stem_move` / `stem_range_replace` / `stem_role` | クリップの分割、区間の無効化、再配置、区間の差し替え、役割と主役。時間はサンプル数か秒（`1.5s`） |
| `stem export [--track T ...] [--raw] [--out-dir D] [--subtype FLOAT\|PCM_24\|PCM_16] [--variant V]` | `stem_export` | 処理後（または編集後のクリップだけ）のステムの書き出しとマニフェスト |
| `run SOURCES... [--objective O] [--profile P ...] [--delivery D ...] [--variants JSON] [--out DIR] [--genre G] [--title T] [--separate] [--variant-mix] [--mix-max-iter N] [--max-iter N]` | `run` | 一括実行（プランナーだけ）。取り込み → 解析 → 整音 → ミックス（ステムがある場合。2mix だけならフルミックス経路）→ バリアントごとのマスタリング → レンダリング → 検証 → Mix Report（ja + en）。`--out` にマスター、マニフェスト、レポート、`run_summary.json` を置く。プロジェクトは既定で `--out` の隣の `<名前>.mmx`。段ゲートに落ちたら段・規則・測定値・是正案つきで止まり終了コード 1（整音 S-07、ミックス S-03/S-04、マスタリングの差し戻し R-14 / R-15 / S-08。マスタリングのプレビューでの S-nn 不合格は報告して検証へ委ね、OF-5 不合格は `unresolved` に記録して続行）。検証不合格も終了コード 1（そのバリアントのマスターは納品せず、レポートと検証結果は置く）。入力の誤りは 2 |

`--profile` と `--delivery` は繰り返せる（全プロファイルに全納品形式）。`--variants '[{"objective": "bass_heavy:0.7", "profile": "club"}]'` で組み合わせを直接指定できる。最初の目的関数のバリアントは `var_<profile>`、それ以外は `var_<objective>_<profile>`。

指揮レイヤー（`director/`。コア API を経由しない。`direction`／`kb` 群の全体は [docs/DIRECTION_FORMAT.md](../docs/DIRECTION_FORMAT.md) §0）のうち、リファレンス（原液）と kb の検索のコマンド。今回は CLI だけで、MCP には出していない:

| コマンド | 内容 |
|---|---|
| `direction ref study --work SLUG [--master AUDIO] [--stems DIR] [--sections JSON] [--roles JSON] [--separate] [--kb ROOT]` | 持ち込まれたリファレンスのマスター／ステムをメモリ上で測り、`<kb>/references/works/<slug>/refstudy.md` を書く（音声は残さない）。work カードの雛形が無ければ作る。`--kb` の既定は `_private/kb`（第三者作品は非公開） |
| `direction ref compare --work SLUG [--variant V] --out MD [--kb ROOT]` | 対照表 refsheet（参照／こちら／差／比較条件。目標・推奨の列は無い）。`--out` はプロジェクトの外。読み取りのみ |
| `direction ref credit --person SLUG [--kb ROOT]` | 技術者カードの集計部（中央値・四分位範囲・n）の再生成 |
| `direction ref list [--kb ROOT]` | 作品・技術者の一覧と refstudy の鮮度 |
| `direction dossier ... [--ref WORK_ID ...] [--ref-kb ROOT]` | 曲資料 §10.3 に指定した作品の ID・題・refstudy のハッシュを載せる |
| `kb search [--kind K ...] [--genre G ...] [--text T] [--root ROOT]` / `kb show ID [--root ROOT]` | kb のカードの検索と表示（読み取りのみ。`--root` の既定は `kb`） |
| `direction edit scan --track TRK --op edit_trim\|edit_gate [--params JSON\|@FILE] [--section ID\|JSON]` | 編集 op が切る区間・拒否する区間（safeguard EG-1〜EG-5）・除くエネルギーを、整音前の原素材で調べて JSON で返す。何も書かない（2026-11-15 追補 2） |
| `direction edit revert --direction DIR_ID [--move MID]` | 指揮書の編集段で無音化した区間とフェードを、台帳 `directions/dir_<id>.edits.json` から戻す（ジャーナル 1 エントリ。同じトラックに適用中の編集の手が他にあると `--move` は拒否され、指揮書全体か `checkout` で戻す） |
| `direction stems observe --project P [--variant V] SPEC` | 観察量 1 つまたは配列（JSON 文字列か `@file`）を現在のトラック信号で測り、`direction_stem_observations` の JSON を返す |
| `direction stems relate --project P [--variant V] [--section ID\|JSON] [--top N]` | 聞こえる全トラックの dry 信号のマスキング、帯域別の値、上位の相手、帯域の担当を `direction_stem_relate` の JSON で返す。区間は ID か `{t0_s, t1_s}`。`--top` は既定 3、整数 1〜8（範囲外は入力エラー） |
| `direction stems purity --project P [--track TRK]...` | 整音後・チェーン前・フェーダー前の共有成分、残響、幅、ダイナミクス、由来等のフラグと取り込み時の和の整合を `direction_stem_purity` の JSON で返す。`--track` 省略時は聞こえる全トラック |
| `direction stems relate ... --axes` | `relate` の JSON の末尾に `axes` を足す。トラックの組ごとの帯域の重なり（`band_overlap`）・鳴り始めの一致（`co_onset_ratio`）・同時に鳴る割合（`co_active_ratio`）・同じオクターブ帯の割合（`same_octave_time`、補助）・左右の距離（`image_distance`）、情報用の基準（コード内の定数）を超えた軸の一覧と 4 軸とも超えた組。付けないときの出力は従来と同じ |
| `direction stems stages --project P [--variant V] --band LO,HI [--section ID\|JSON] [--direction MD]` | 1 つの帯域のエネルギーを、各トラックの整音後・チェーン前（`pre_chain_db`）とチェーン・フェーダー後（`dry_db`）、dry の和と打ち消しの差（`cancellation_db`）、ミックスバス（`mix_db`）、描画済みマスター（`master_db`。無ければ `null`）とラウドネスをそろえた差で `direction_stem_stages` の JSON に並べる。`--direction` を付けると R-06 の基準を超える EQ のブーストの一覧（`large_boosts`。読む材料で、拒否も警告もしない）を足す |
| `direction stems placement --project P [--variant V] [--direction MD]` | 床の提案の区間ごと・聞こえるトラックごとの活動率、活動中のレベル、活動エネルギーの割合、6 帯域の割合、占有周波数、鳴り始め、持続、左右を `direction_stem_placement` の JSON で返す。`--direction` を付けると `frame.section_roles` を書かれたまま `declared_roles` に写す（役割は決めない）。無音のセルは `null` |
| `direction listen pack --project P --floor FLOOR [--variant V] (--section ID\|JSON \| --excerpt T0,T1)... --out DIR [--match integrated\|section\|lead] [--kb ROOT]...` | 抜粋ごとに結果・床・無処理のステム和（`raw_gain_only`）の 3 本を、音量合わせ（大きい方を下げる）と名前を隠したファイル名で `--out` に書き出す（24 bit WAV、鍵 `key/key.json`、回答用紙 `sheet.md`、`answers.template.json`）。標準出力は `kind`・`files`・`key_path` だけで対応を出さない。`--out` がプロジェクト・床・kb（`--kb` で足した物を含む）の中、または空でないときは入力エラー |
| `direction listen record --project P --direction DIR_ID --from ANSWERS` | 埋めた回答 1 回分を `directions/dir_<id>.listening.json` に足す（outcome は書き換えない）。等級 `grade`（`trial`／`adoption`）は記録された条件から機械が付け、回答に書くと拒否。outcome が無いと入力エラー |
| `direction stems phrases --project P --track TRK [--min-gap-ms N]` | 1 本のトラックの dry 信号の鳴っている所をフレーズに分け（隙間が `--min-gap-ms` より短ければつなぐ。既定 250）、各フレーズの時刻・全帯域レベル・中央値との差・先頭／末尾 150 ms のレベル・1〜4 kHz での他の全トラックの和との差（`margin_db`）と、差の小さい 100 ms 窓（最大 32 件）を `direction_stem_phrases` の JSON で返す。ゲインの推奨値は出さない |
| `direction wiring --project P [--variant V] [--direction MD] [--format json\|mermaid]` | プロジェクトの現状から、トラック・バス・マスターの経路、センド（量と `pre_fader`）、ダッキングの引き金→相手（深さ・手前・戻り・全帯域）、各節の処理の並び（残響の低域・高域の切りなど）を `direction_wiring` の JSON か mermaid の文字列で返す。`--direction` を付けるとまだ適用していない手を `planned: true` で重ねる。導出であって宣言ではない。音声を描画せず、何も書かない。入力エラーは終了コード 2 |

`direction stems` の下見 6 コマンド（`observe`／`relate`〔`--axes` を含む〕／`purity`／`stages`／`placement`／`phrases`）は、どれもプロジェクトに何も書かない。適用済みの整音キャッシュが無い・古い場合は描画せず入力エラー（終了コード 1）になり、先に `clean apply`／`render` を実行する旨を返す。引数が数として読めないとき（`relate` の `--top`、`stages` の `--band`、`phrases` の `--min-gap-ms`）だけは終了コード 2。`direction wiring` は下見群と違い、`direction validate`／`check` と同じく入力エラーが終了コード 2 で、音声を読まないので整音キャッシュは要らない。整音未適用・無効・スキップのトラックは元の素材を読む。共通の `--project`・`--format json|text` 等は他の direction コマンドと同様に使える。下見の実施や順序は必須ではない。マスキングの値は粗いモデル値で、0 に近いほど良いわけではない。帯域の担当（`band_owners`）は P-22 の担当の規則を満たしたトラックだけで、その帯域で鳴っているトラックの一覧ではない。共有成分は漏れの量そのものではなく、残響も粗い推定である。音が良くなることは実証していない。

`direction stems stages`／`placement` と `relate --axes` も上の 3 コマンドと同じく、プロジェクトに何も書かず、整音キャッシュが無い・古いときは描画せずに入力エラー（終了コード 1。`stages` の `--band` が数として読めないときは 2）になる。指揮書の観察量では `target: "mix"`（ミックスバス出力。レベルマッチなし）と `view: side`（`(L−R)/2`。`band_energy`／`crest`／`loudness` だけ）も書ける。下見を見たか・どの順で見たかは検査しない。値は状態の記述で、良し悪し・役割・譲らせ方を言わない。音が良くなることは実証していない。詳しくは [docs/DIRECTION_FORMAT.md](../docs/DIRECTION_FORMAT.md) §9.6〜§9.9。

`direction validate` は、主張・期待・安全弁に台帳指標（`P-nn`）の量を書くと、`--project` の有無に依らず警告 `unmeasured_quantity` を量ごとに 1 件出す（`direction check` は結果を測り直さず、標準の流れでは `not_measured` になるため。`ok` と終了コードは変わらない。詳しくは [docs/DIRECTION_FORMAT.md](../docs/DIRECTION_FORMAT.md) §8.6）。

`direction listen` の 2 コマンドは任意で、validate／check／`kb lint` は聴取記録の有無を見ない（聴いたか・何回聴いたかを検査しない）。`pack` はプロジェクトと kb に何も書かず、`record` は聴取記録だけを書く。どちらも CLI だけで、MCP には出していない。等級の条件と聴取記録の形は [docs/DIRECTION_FORMAT.md](../docs/DIRECTION_FORMAT.md) §9.2。指揮書の任意欄 `frame`・`scene.room`・`triage`（§9.3〜§9.5）はコマンドを足さず、使わない指揮書の出力は従来と同じ。音が良くなることは実証していない。

`direction check` に足したフラグ（どれも付けたときだけ outcome に判定外のブロックを足し、付けないときの outcome は従来と同じ。`--translation` と同じ扱いで、主張・ガード・`summary`・`--calibrate` は読まない）: `direction check --edit-list`（時間で動く手〔区間つき `gain`、`gain_curve` の各区間、`duck`、編集 op〕の床と結果の dry のレベル、`duck` の帯域の下がり幅〔床 − 結果。下がると正〕を並べる `edit_list`。512 行を超えると手ごとの要約）、`direction check --contour`（レベルマッチ後のマスターの区間ごとの短時間ラウドネスの平均・側成分比・明るさ・低域・傾き、区間の落差、床の空白に残った量を並べる `contour`）。指揮書の任意の op `gain_curve`（時刻の区間ごとのゲイン。量は ±6 dB、ランプ 5〜200 ms、区間 1〜256 件の固定の範囲）はコマンドを足さない。`stems phrases` は他の `direction stems` と同じく何も書かず、整音キャッシュが無い・古いときは入力エラー（終了コード 1。`--min-gap-ms` が数として読めないときは 2）。使ったか・どの順かは検査しない。音が良くなることは実証していない。詳しくは [docs/DIRECTION_FORMAT.md](../docs/DIRECTION_FORMAT.md) §9.10〜§9.13。

追補 2 で既存のコマンドに足したフラグ（どれも付けたときだけ働き、付けないときの出力は従来と同じ。使わなくても不利にならない）: `direction ref study --add transient`（refstudy にトランジェント輪郭の節）、`direction ref compare --add transient|guide`（refsheet に輪郭の対照・汎用ガイドからの形の偏差の節）、`direction check --translation`（outcome に判定外の `translation` ブロック）、`kb search --source-type T ... --curriculum CUR_ID`。詳しくは [docs/DIRECTION_FORMAT.md](../docs/DIRECTION_FORMAT.md) §6.1・§7。

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

ツール実装の追補（direction層はCLI専用。MCPの計画名と公開済みツールは別）。下見は採用・適用を行わず、`--out` があるコマンドも省略時はJSONだけを返す。詳しくは [DIRECTION_FORMAT](../docs/DIRECTION_FORMAT.md) §9.15〜§9.20。

<!-- tool-cli:begin -->
| コマンド | 内容 |
|---|---|
| `direction suggest eq --target TRK [--against ID] [--refsheet MD\|--ref-kb ID...]` | EQ候補・測定根拠・confidence。適用しない |
| `direction ref matcheq --target ID --ref AUDIO_OR_WORK [--smooth-oct N] [--max-db N] [--band-hz LO HI] [--points N]` | 参照との平滑した差の曲線とfir_eq候補。書き込みなし |
| `direction suggest lowend [--target ID] (--refsheet MD\|--ref-kb ID...) [--max-db N]` | 低域の分布と候補。target省略時はマスター前のミックスバス |
| `direction ref balance [--audio FILE] (--refsheet MD\|--ref-kb ID...\|--ref FILE...) [--bands 4\|third\|sixth] [--normalize lufs\|mid_band] [--over-time S]` | 参照とこちらの帯域分布・偏差・時系列。目標や合否は出さない |
| `direction suggest align --tracks IDS [--reference ID] [--max-ms N] [--mode delay\|delay_polarity\|phase] [--preset drums]` | 遅れ・極性・位相の測定とtime_align候補。tracksはカンマ区切り |
| `direction query align_time --target TRK --guide TRK [--section ID\|JSON] [--anchors JSON] [--tightness N]` | ガイドに対する単調な時間写像・処理前後の測定とedit_align_time候補。適用しない |
| `direction extract midi --target TRK --kind drums\|mono [--bpm N] [--quantize NOTE] [--bend on\|off] [--out FILE]` | 打点／単音の音符列。明示outだけSMFも書く |
| `direction pitch notes --target TRK [--section ID\|JSON] [--lo-hz N] [--hi-hz N] [--a4 N]` | 音符ID・時刻・音高・confidence。GUI音符表示はOQ-3で保留 |
| `direction query onsets [--target ID] [--kind percussive\|soft] [--band full\|low\|mid\|high] [--threshold N] [--min-interval-ms N] [--grid-note NOTE --bpm N] [--against ID]` | 打点ID・強さ・数・グリッドや相手との差。targetの既定master |
| `direction query mono [--target ID] [--section ID\|JSON] [--by-track] [--worst N]` | 帯域・時間ごとの符号付きモノ合算差。by-trackはmasterのstem_mix経路で各トラックを外した比較 |
| `direction query limiter_headroom` | drive0〜12 dBの仮描画によるLUFS・GR・TP等。低域残差比は音楽の調波THDではない。正本を変えない |
| `direction query meters [--target ID] [--what ITEMS...] [--step-ms N] [--max-points N] [--points N] [--octave 3\|6\|12]` | メータの数値。点数を超えると実効刻みと間引きを表示しピーク最大値を保持。GUIはOQ-3で保留 |
| `direction query breaths --target TRK [--sensitivity N] [--min-ms N] [--max-ms N]` | ブレス候補ID・特徴・スコア。較正は合成素材のみで、実録音の検出率を保証しない |
| `direction suggest ambience --target TRK [--find-quiet] [--region T0,T1] [--points N] [--smooth-oct N]` | 静かな候補区間の列挙、明示したノイズ区間の測定とnoise_bed候補。書き込みなし |
| `direction preview codec [--audio FILE] [--codec ITEMS...] [--bitrate-kbps N...] [--normalize-lufs N...] [--section ID\|JSON\|--excerpt T0,T1] [--match on\|off] [--out DIR]` | 符号化往復の測定。音声指定ならプロジェクトなしでも使用可能。明示outだけ試聴ファイルを書く |
<!-- tool-cli:end -->

上表は共通の `--project`・`--format` 等も使える。下見はプロジェクト・kb・指揮書台帳を変更しない。必要な整音cacheがない・古いときは描画で補修せず入力エラーにする。入力エラーは終了コード2。`preview codec` と `extract midi` はout省略ならファイルを書かず、指定時も明示出力だけを書く。下見を実施したか、読んだか、候補を採用したかは検査しない。使わない場合、既存コマンドの出力は従来とバイト同一。

独立したファイル間の空間変換（プロジェクト不要、MCPには出さない）:

<!-- tool-spatial:begin -->
| コマンド | 内容 |
|---|---|
| `spatial ambi encode --in FILE --out FILE.wav [--order 1\|2\|3] [--azimuth DEG] [--elevation DEG]` | mono/stereo点音源をACN/SN3Dへ。次数既定1、方位・仰角既定0。stereo入力は算術平均 |
| `spatial ambi rotate --in FILE --out FILE.wav [--yaw DEG] [--pitch DEG] [--roll DEG]` | 右手系の能動回転roll→pitch→yaw。角度既定0 |
| `spatial ambi decode --in FILE --out FILE.wav --to stereo\|binaural [--angle DEG] [--hrtf ID]` | stereoは左右±angleのカーディオイド対（既定90度）、binauralは登録HRTFを使う |
| `spatial ambi convert --in FILE --out FILE.wav --from fuma\|ambix --to fuma\|ambix` | 1次の形式間変換 |
| `spatial ambi info --in FILE` | 次数・各成分のRMS/peak。音声だけでは並び・正規化を特定できないのでunknownと仮定を区別 |
<!-- tool-spatial:end -->

座標はx前/y左/z上、正方位は左。info以外は明示されたfloat64 WAVだけを書く。sr・フレーム数を保ち、プロジェクトのミックスグラフには入れない。使わない場合、既存コマンドの結果は従来とバイト同一。変換を使ったか・次数をどう選んだかは検査しない。
