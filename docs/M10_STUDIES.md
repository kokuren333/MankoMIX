# MankoMIX M10 調査（較正と拡張）

- 版: 0.1（調査） / 作成: 2026-11-14
- 位置づけ: SPEC §17 の M10 行の 8 項目について、現状のコード、選択肢、推奨、工数の見積もり、必要な決定をまとめた調査文書である。**本書は決定ではない**。決定が要る事項は「決定候補 M10-Pnn」として §9 に列挙した。`docs/REQUIREMENTS_NOTES.md` には記録していない（採否はオーナーと統括が判断し、採用したものに D-ID を振る）
- 試作: §3 の ISO 532-1（Zwicker 法）を `core/analysis/iso532_1.py` に試作し、`tests/test_iso532_1.py` で検証した。測定ベクトル（§4.2）、目的関数、プランナーには**つないでいない**
- 工数は、このリポジトリの実装を担うエージェント（または開発者）1 名の作業日（人日）で見積もった。聴感評価そのものの時間（人が聴く時間）は別に書く
- 出典の URL は §10 にまとめ、本文では [Sn] で参照する。ライセンスの一次資料の確認は `docs/PUBLICATION_AUDIT.md`（M9 の公開監査）に委ね、重複して調べ直していない

## 0. 要約

| 項目 | 推奨 | 工数 | 主な決定候補 |
|---|---|---|---|
| (a) 聴感評価による較正 | 公式サンプルの抜粋を使い、**一対比較（強制選択）を主、ABX を閾値の検出、MUSHRA 型を目的関数ごとの尺度確認**に使う。評価結果は音声なしのデータ（`calibration/`）として残し、重みは「事前重みへの正則化つきの制約付き回帰」で更新し、交差検証で改善したときだけ版を上げる | 道具 4〜6 人日、評価は 1 人 1 回 45 分 × 3〜5 名 × 2〜3 回 | M10-P01〜P03 |
| (b) 残りの目的関数 | SPEC の 7 つは全て `objectives/catalog.json` にある。`low_fatigue` は暫定のまま据え置き、昇格条件を決める。新しい目的関数の組み込みは較正の後。測定器が要るもの（歌詞の明瞭さの専用指標）だけ別に決定する | 1〜3 人日 | M10-P04、P05 |
| (c) ISO 532 系 | ISO 532-1 は numpy / scipy で実装可能で、試作は規格の参照値に 2.2 % 以内で一致した。まず**検証用（Mix Report の参考値、P-11 と P-20 の照合）に留め**、目的関数の項にはしない。SPL の校正規約を先に決める。ISO 532-2 は定常音なら安価に実装可能、532-3 は重いので見送り | 532-1 の配線 2〜3 人日、532-2 の実装 4〜6 人日 | M10-P06〜P08 |
| (d) プラグイン化 | 「本体で決めたチェーンを DAW で再生する**チェーンプレイヤー**」に限定し、CLAP で実装、clap-wrapper で VST3 / AU を作る。最大の作業は、参照実装（numpy）にしかないプロセッサの C++ 移植 | 25〜40 人日 | M10-P09、P10 |
| (e) アルバムモード | 曲のプロジェクトを参照する**アルバムの正本**を別に持ち、曲どうしをリファレンス集合として使い回す（既存の `core/reference.py` の仕組み）。ラウドネスは「曲間の相対差を保つアルバムゲイン」を既定にする | 8〜12 人日 | M10-P11 |
| (f) タイムストレッチ | signalsmith-stretch（MIT）を `dsp/native` に取り込む案を第一候補、FFmpeg の `atempo`（LGPL、外部プロセス）を手軽な代替とする。**conform（D-054）では使わず**、リミックス操作の明示的な指定だけで使う | 4〜7 人日 | M10-P12、P13 |
| (g) リファレンス統計の同梱 | 市販曲の統計の同梱は引き続き見送る。代わりに「統計ファイルの形式と作成ツール」を整え、オーナー自身の楽曲から作った統計を**例として**同梱することを検討する | 2〜4 人日 | M10-P14 |
| (h) 外部サービスの入力アダプタ | Suno に公式 API はなく、公式 MCP（ベータ）がある。**エージェント仲介（エージェントが Suno MCP で取得 → 本体の `import`）を標準**とし、コアにアダプタを足さない。足す場合は別パッケージの entry point にする | 0.5〜1 人日（仲介）、3〜5 人日（アダプタ） | M10-P15、P16 |

---

## 1. (a) 聴感評価による重みと閾値の較正

### 1.1 現状

- 重みは `objectives/catalog.json` の各項の `weight`（合計 1.0）にあり、SPEC §4.4 の初期案と同じ値である。`status: "draft"`
- 目標範囲・ペナルティの尺度・強度の上限は `knowledge/objective_metrics.json`、ステム文脈の指標の定数は `knowledge/masking_model.json`、2mix の知覚指標の閾値は `knowledge/thresholds_m3.json`、マスタリングと検証の閾値は `knowledge/thresholds.json`、整音は `knowledge/cleanup_policy.json` にある。各値は `confidence`（`initial` / `practice` / `standard`）または `evidence` を持つ
- 評価に使った定義の版は、目的関数の評価結果の `definitions` に**正準化 JSON のハッシュ**として残る（`core/objectives.py`。対象は `catalog`、`objective_metrics`、`genre_priors`）。`masking_model`、`thresholds_m3`、`thresholds`、`cleanup_policy` のハッシュは残っていない（§1.4 の 6 で補う提案）
- 聴き比べの道具: GUI の試聴画面（`gui/src/screens/ListenScreen.tsx`、`gui/src/audio/gains.ts`）がレベルマッチの切り替えつき A/B を持つ。ブラインド（提示順のランダム化、回答の記録）はない
- 公式サンプルは 1 曲（ヒップホップ、`samples/sample_set.json`）で、11 種のバリアントの定義がある。音声は D-061 により履歴に入れない

### 1.2 「暫定」「初期値」と書かれた重みと閾値の一覧

SPEC が暫定・初期値・較正対象と明記した項目と、その実体の置き場所。個々の数値は各ファイルの `confidence: "initial"` / `"practice"` で機械的に列挙できる（`cleanup_policy.json` だけで initial が 94 個ある）ので、ここでは較正の単位（まとめて動かす組）で示す。

| 項目 | SPEC | ファイルとキー | ラベル |
|---|---|---|---|
| 目的関数の重み（OF-0〜OF-4、OF-6） | §4.4「重みは初期案」 | `objectives/catalog.json` の `objectives[].terms[].weight` | 初期案 |
| `low_fatigue` 自体 | §4.4「暫定」 | 同 `objectives[id=low_fatigue].provisional` | 暫定 |
| 目標範囲・尺度・強度の上限 | §4.1、§4.7 | `knowledge/objective_metrics.json` の `metrics.*`（`base`、`limit`、`scale`）、`intensity`、`genre.emphasis_factor`、`reference.*`（単一リファレンスの IQR 既定幅など） | [モデル] / [慣行] |
| トランスレーション・ゲートの閾値 | §4.5 | 同 `gate.small_speaker`、`gate.mono_fold`、`gate.low_level`、`gate.pitch` | [慣行] / [モデル] |
| S-03 の持続判定 | §4.3「持続判定の時間は初期値」 | `knowledge/thresholds.json` の `s03_low_band_phase.window_s`、`max_persistence_s` | [慣行] |
| S-04 のモノ損失の上限 | §4.3「上限は初期値（較正対象）」 | 同 `s04_mono_loss.low_band_max_db`（1.5）、`lead_clarity_max_db`（3.0） | initial |
| S-07 の残差上限 | §4.3「初期値 −80 dBFS」 | `knowledge/cleanup_policy.json` の `s07.residual_limit_dbfs` | initial |
| S-08 の許容幅 | §4.3「許容幅は初期値」 | 同 `s08.shimmer_index_tol_db`（1.5）、`noise_floor_tol_db`（2.0）、`noise_floor_hf_tol_db`、`above_ceiling_tol_db`。計画側の余裕は `knowledge/thresholds.json` の `s08_planning.plan_margin_db` | initial |
| 整音の帯域ポリシーと低減量 | §6.4.1「初期値は較正対象」 | `knowledge/cleanup_policy.json` の `crossover`、`bands`、`passes`、`strength`、`detector`、`protection`、`completion`、`p21`、`oversuppression` | initial |
| P-18 の警告と差し戻し | §6.6.3（[慣行]） | `knowledge/thresholds.json` の `p18_limiter_dependency` | practice |
| マスター EQ の上限 | §6.6.3 | 同 `master_eq` | practice |
| P-20 の縮小の警告 | §6.6.3 | 同 `contrast.p20_shrink_warn_lu`、`knowledge/thresholds_m3.json` の `p20_contrast` | initial / [モデル] |
| 汎用 prior | §4.6 の 3 | `knowledge/thresholds.json` の `generic_tonal_prior`、`knowledge/thresholds_m3.json` の `p01_generic_prior` | practice |
| P-11、P-17、P-19 の範囲 | §4.2 | `knowledge/thresholds_m3.json` の `p11_harshness`、`p17_sibilance`、`p19_smoothness` | [モデル] |
| P-01 の等ラウドネス重みの phon | §4.1 | 同 `erb.phon`（80） | [モデル] |
| マスキングのモデル定数と各指標 | §4.2 | `knowledge/masking_model.json` の `spreading`、`masking`、`penalties`、`p08`〜`p22`、`importance_defaults` | [モデル] / [慣行] |
| ジャンル prior の P-10 目標帯 | §4.10「暫定」 | `knowledge/genre_priors.json` の `genres[].p10_target_db`（`provisional: true`） | 暫定 |
| 語彙辞書の帯域 | §6.8.1、§18 | `knowledge/vocabulary.json` の `bands[].range_hz` | 目安 |
| 媒体プロファイルの許容幅 | §5.2「`window_lufs_i` などの許容幅は初期値」 | `profiles/media_profiles.json` の `profiles[].loudness.window_lufs_i` | 初期値 |
| 歌ものの既定チェーンの数値 | §6.5.4「[慣行] の初期値」 | `knowledge/mix_rules.json` | [慣行] |

聴感評価で直接動かせるのは、上のうち**重み、目標範囲の幅、知覚的な閾値**（S-04、S-08、P-11、P-17、P-20、P-18、整音の強度）である。S-07 の残差上限は「聞こえるか」ではなく「低域が変わっていないか」の検査なので、聴感でなく測定で決める。媒体プロファイルの許容幅は配信側の仕様なので、聴感評価の対象外とする。

### 1.3 選択肢

| 方式 | 何が分かるか | 長所 | 短所 | 主な用途 |
|---|---|---|---|---|
| ABX（二重盲検、X が A と B のどちらか）[S1] | 差が**聞き分けられるか** | 判定が客観的。二項検定で有意性が出る | 好みは分からない。疲れやすい | 閾値（S-08 の許容幅、整音の強度、マスター EQ の最小量）の検出限 |
| 一対比較・強制選択（A と B のどちらが「観点 X で」良いか） | **選好の順序** | 1 試行が短く、素人の評価者でも安定する。Bradley–Terry モデル [S2] で効用の尺度に直せる | 組み合わせ数が刺激数の 2 乗で増える | 重みの推定（主） |
| MUSHRA 型（ITU-R BS.1534 [S3]。隠れ基準とアンカーを含む多刺激の 0〜100 評価） | 刺激間の**差の大きさ** | 一度に多くの刺激を比べられる。評価者の選別規則が規格にある | 中程度の差に向く。「基準」がない比較（目的関数の違い）では隠れ基準の意味が弱い | 目的関数ごとの強度の尺度（`intensity` 0〜1）の確認 |
| 単一刺激の絶対評価（ACR 型） | 絶対的な好み | 簡単 | 評価者間・日内のぶれが大きい。少人数では使えない | 採らない |
| ITU-R BS.1116 [S4]（小さな劣化の検出） | 微小な劣化の大きさ | 厳密 | 訓練された評価者と統制された環境が要る | 採らない（ABX で代える） |

### 1.4 推奨する手順（オーナーが実施できる形）

**1. 刺激の準備（本体のコマンドで自動生成し、手作業で作らない）**

- 素材: 公式サンプルの conform 済みセット。D-039 によりリファレンスは登録しない
- バリアント: §15.2 の 11 種に加え、較正する目的関数ごとに次を作る
  - 強度の段階: `intensity` = 0、0.25、0.5、0.75、1.0
  - 重みの摂動: 目的関数の各項について、その項の重みを +0.15 して残りを比例で縮めた版（項の数 k なら k 本）。これにより「どの項を重くした仕上げが好まれるか」が分かる
  - 閾値の段階（ABX 用）: 検出限を測りたい量を等間隔に 5〜7 段（例: S-08 なら高域ブースト量を 0、0.5、1.0、1.5、2.0、3.0 dB）
- 抜粋: `core/analysis/music.py` のセクション推定から、静かな部分・盛り上がる部分・その中間を含む **12〜15 秒 × 4 か所**。前後 50 ms のフェード
- レベルマッチ: 抜粋ごとに統合ラウドネスを −23 LUFS（`knowledge/thresholds_m3.json` の `level_match.target_lufs`）にそろえる。大きい方を下げる（R-01）。True Peak の天井を超える場合は全刺激を同じ量だけ下げる
- 刺激の目録（manifest）: 正本のハッシュ、バリアントの定義、レンダリングのハッシュ、抜粋の区間、レベルマッチのゲイン。音声そのものは保存せず、目録から再生成する（D-061）

**2. 課題と試行数**

| 課題 | 1 回の構成 | 試行数の根拠 |
|---|---|---|
| T1: ABX（閾値） | 1 つの量につき、5〜7 段 × 各 16 試行 | 16 試行で 12 回以上正解なら片側二項検定で p < 0.05。75 % 正解の点を検出限とする（心理測定関数をロジスティックで当てはめる） |
| T2: 一対比較（重み） | 1 つの目的関数につき刺激 6 本（強度 0.5 の基準、重みの摂動 4〜5 本）、全 15 対 × 提示順を入れ替えて 2 回 = 30 試行 × 抜粋 4 = **120 試行** | 推定する重みが 5〜7 個なので、1 評価者あたり 1 パラメータに 15〜20 試行以上。評価者 3〜5 名で 360〜600 試行 |
| T3: MUSHRA 型（強度の尺度） | 1 画面に強度 5 段 + 隠れ基準（処理前の単純合算、レベルマッチ済み）+ アンカー（2〜5 kHz を +6 dB のシェルフ、または 3.5 kHz のローパス）= 7 本、抜粋 4 | BS.1534 の評価者の事後選別: 隠れ基準を 90 未満と評価した試行が 15 % を超える評価者を除く |

- 1 回は 45 分以内とし、15 分ごとに休憩を挟む。1 日 2 回まで。開始時に再生系と音量を固定し、記録する（§6.8 の試聴条件）
- **一度に問う観点は 1 つ**（§16.5）。観点は目的関数の「一言で」（`summary`）をそのまま使う（例: `comfort` なら「偏りがなく、疲れにくく、要素が聞き分けられる」のはどちらか）
- 提示順は、評価セッションごとの乱数の種から決め、種を記録する（再現できるように）
- 評価者はオーナーとオーナーが声を掛けた協力者（D-039）。仮名 ID だけを記録し、氏名やメールアドレスを書かない（D-020）

**3. 評価から重みへの写像**

- 各刺激 i について、目的関数の評価（`core/objectives.py`）が出す項ごとのペナルティ p_ik を記録する（レベルマッチ後の値）
- 一対比較の結果を、Bradley–Terry 型のロジスティック回帰で当てはめる:
  `P(A が B より好まれる) = σ( β · Σ_k w_k · (p_Bk − p_Ak) )`
  制約は w_k ≥ 0、Σ w_k = 1。β は評価者の一貫性（尺度）として別に推定する
- **事前重みへの正則化**: 損失に `λ · Σ_k (w_k − w_k^prior)^2` を足す（w^prior は現行の重み）。λ は交差検証で選ぶ
- **1 回の更新の上限**: 各重みの変化は ±0.10 まで。上限に当たった項は Mix Report の「較正の注記」に出す
- **採用の条件**: 抜粋を 1 つずつ外す交差検証で、新しい重みの的中率（どちらが好まれるかの予測）が現行の重みより改善し、かつ 60 % を超えたときだけ新しい版として採用する。改善しなければ版を上げず、評価データだけを残す
- 閾値（T1）: 検出限を、ペナルティが 0 の範囲（`ok_max` や `base`）の端に写す。「聞き分けられない差は罰しない」。安全不変条件（S-nn）の値は**厳しくする方向にだけ**動かせる（§4.9「制約を目的関数側へ降格しない」と同じ考え方）
- 強度（T3）: 強度 0〜1 に対する評価の平均が単調で、0.5 付近で中間になることを確認する。単調でない目的関数は、`objective_metrics.json` の `limit` を見直す対象として記録する
- 公式サンプルは 1 曲で、ジャンルも 1 つしかない。**1 曲の評価で汎用の重みを動かすと過学習になる**ので、公式サンプルだけの結果は `genre: hiphop` のジャンル prior（`emphasis` と目標帯）の更新にのみ使い、カタログの重み自体は、オーナーの手元の複数曲（非公開。音声も測定値もリポジトリに入れない。結果の重みだけを入れる）を加えた評価がそろってから動かす

**4. 記録（データとして残す。音声は残さない）**

```
calibration/                         （新設の提案。M10-P01）
  README.md                          手順と形式の説明
  sessions/<YYYYMMDD>_<listener>_<n>.jsonl
                                     1 行 1 試行: session_id、listener（仮名）、task（abx/pair/mushra）、
                                     attribute、stimuli（manifest の ID）、presented_order、seed、
                                     response、response_time_ms、playback（system、level の申告）
  manifests/<manifest_id>.json       刺激の目録（正本のハッシュ、バリアントと摂動、抜粋区間、
                                     レベルマッチのゲイン、レンダリングのハッシュ、各刺激の p_ik）
  fits/<objective>_<version>.json    当てはめの結果（使ったセッション、λ、交差検証の的中率、
                                     旧重み、新重み、上限に当たった項）
```

- 採用した重みは `objectives/catalog.json` の新しい版として書き、各目的関数に `calibration: {version, fit, sessions, date}` を持たせる。Mix Report は使った版を記録する（§4.9。現行のハッシュに加え、人が読める版番号を出す）
- 定義のハッシュに `masking_model`、`thresholds_m3`、`thresholds`、`cleanup_policy` も加える（較正で動かした値がどの評価に効いたかを追えるように）
- 評価データの JSON Schema（`schemas/listening_session.schema.json` など）は、`schemas/` を編集している作業と調整して別途追加する

**5. 道具（実装が要るもの）**

- `mankomix calibrate prepare|fit`（CLI と MCP の新コマンド。刺激の生成と当てはめ）
- 評価の実施は GUI の試聴画面にブラインドモード（提示順のランダム化、A/B/X のラベル、回答の記録、JSONL の書き出し）を足すのが最も手軽。Pages のデモには載せない（評価データが外に出ないように）

### 1.5 工数

| 作業 | 工数 |
|---|---|
| 刺激生成（摂動バリアント、抜粋、レベルマッチ、目録） | 1.5〜2 人日 |
| GUI のブラインドモードと記録 | 1.5〜2 人日 |
| 当てはめ（制約付きロジスティック回帰、交差検証、心理測定関数）と `catalog.json` の版上げ | 1〜2 人日 |
| 評価の実施 | 1 回 45 分 × 評価者 3〜5 名 × 2〜3 回（目的関数 6 つを一巡するのに 4〜6 回） |

### 1.6 決定候補

- **M10-P01**: 評価の手順（§1.4）と記録の置き場所（`calibration/`）・形式を採用する
- **M10-P02**: 重みの更新規則（事前重みへの正則化、1 回 ±0.10 の上限、交差検証で改善したときだけ版を上げる、安全不変条件は厳しくする方向のみ）
- **M10-P03**: 評価データの公開範囲（仮名、評価者の同意、手元の非公開曲は結果の重みだけを公開する）

---

## 2. (b) 残りの目的関数

### 2.1 現状

- SPEC §4.4 の 7 つ（`comfort`、`bass_heavy`、`vocal_forward`、`clarity`、`club_impact`、`translation`、`low_fatigue`）は**全て** `objectives/catalog.json` にあり、評価器（`core/objectives.py`）は全ての変種（`P-03:lra_density`、`P-05:width_restraint`、`P-07:playable_band`、`P-11:two_sided` など）を実装済みである
- `low_fatigue` は `provisional: true` を持ち、使うと Mix Report に「根拠が弱い」旨の注記が出る（`provisional_objective`）
- ブリーフ（D-006）が例示した意図のうち「歌詞の明瞭さ」は `clarity` に、「ループ再生での疲れにくさ」は `low_fatigue` に対応づけ済み
- ユーザー定義の目的関数は同じ形式で追加できる（§4.8）。既存の代理指標の重み付けだけで表せる意図は、コードなしで足せる

### 2.2 選択肢

| 対象 | 選択肢 | 評価 |
|---|---|---|
| `low_fatigue` | (1) 暫定のまま据え置く (2) 長時間聴取の評価で昇格させる (3) 外す | 聴覚疲労の定量研究が弱い（§8.1）ことは変わっていない。10 分以上のループ聴取での比較は、評価者の負担が大きく、少人数では有意差が出にくい。**(1) を推奨**。昇格の条件を「一対比較（T2）で、`low_fatigue` 版が `comfort` 版より『長く聴いても疲れにくい』と 60 % 以上選ばれ、それが 2 曲以上で再現すること」と決めておく |
| 歌詞の明瞭さの専用指標 | (1) 現行の `clarity`（P-02、P-11 両側、P-12、P-15、P-05）のまま (2) 明瞭度指数（ANSI S3.5 の SII のような、帯域ごとの SN 比の重み付き和）を、ボーカルのステムと伴奏の合算に当てる新しい代理指標を足す | (2) は新しい測定器であり、§4.2 の「新しい目的関数は新しい重み付けであって新しい測定器ではない」の例外になる。ステムがある場合だけ計算でき、2mix では使えない。**較正の後に判断**（P-02 の対ボーカル版と強く相関するなら足さない） |
| 新しい意図（例: 「温かい」「広がり」「スマートフォン優先」「BGM・ループ向け」「ローファイ」） | (1) 組み込みに足す (2) ユーザー定義の例として文書に置く | 語彙辞書（§6.8.1）は「語彙を評価軸にしない」と定めている。「温かい」「広がり」を目的関数にすると語彙と軸が混ざる。**(2) を推奨**。「スマートフォン優先」は媒体プロファイルの `playback_assumptions` とトランスレーション・ゲートの厳しさで表せる。「BGM・ループ向け」でループの継ぎ目を評価するには新しい測定（末尾と先頭の連続性）が要る |

### 2.3 推奨

1. 組み込みの目的関数は増やさない。較正（§1）で既存 6 つの重みを先に固める
2. `low_fatigue` は暫定のまま、昇格条件を決定として記録する
3. 新しい測定器が要る候補（歌詞の明瞭度指数、ループの継ぎ目）は、個別に決定を取ってから P-23 以降を振る

工数: 昇格条件と例の文書化 1 人日。明瞭度指数を足す場合は追加で 3〜4 人日（ステム文脈の解析 `core/analysis/stems.py` への追加と、目的関数の項の定義）。

### 2.4 決定候補

- **M10-P04**: `low_fatigue` を暫定のまま維持し、昇格条件を上記のとおり定める
- **M10-P05**: 組み込みの目的関数は較正まで増やさない。新しい測定器を伴う候補（明瞭度指数など）は個別の決定で P-23 以降を振る

---

## 3. (c) 精密な知覚指標（ISO 532 系）

### 3.1 現状

- 周波数の評価は ERB 帯域と ISO 226:2003 の等ラウドネス重み（80 phon）で行う（`core/analysis/erb.py`、P-01）
- マスキング（P-02）は Bark 領域の 2 傾斜の拡散関数（Terhardt 型）で、絶対レベルの仮定として `knowledge/masking_model.json` の `analysis.full_scale_spl_db`（96）を持つ
- 絶対的なラウドネス（sone）は計算していない。Mix Report の「+10 dB でおよそ 2 倍」（§6.8）は dB 差からの換算（`core/report.py` の `_sone`）である
- SPEC §4.2 は ISO 532 系とシャープネス、ラフネス、変動強度を「将来の測定器拡張の候補」としている

### 3.2 規格の概要

| 規格 | 方法 | 入力 | 等ラウドネスの基礎 | 備考 |
|---|---|---|---|---|
| ISO 532-1:2017 [S5] | Zwicker 法。定常音（1/3 オクターブのレベルからも可）と時間変化音 | モノラル | ISO 226:1987（DIN 45631 との連続性のため） | 2022 年に確認・現行。第 2 版の改訂が進行中 [S6]。電子付属物（C のプログラム、試験信号、結果）は ISO の顧客ライセンスの下にあり、寛容ライセンスではない [S7] |
| ISO 532-2:2017 [S8] | Moore–Glasberg 法。定常音 | モノラル／両耳（ダミーヘッド、ヘッドホンを含む） | ISO 226:2003 と整合 | 情報としてのソースコードが付属（同じく ISO の条件）。改訂の CD が進行中 |
| ISO 532-3:2023 [S9] | Moore–Glasberg–Schlittenlacher 法。定常音と時間変化音（短期・長期ラウドネス） | 同上 | ISO 226:2003 | 5 秒を超える信号の単一の総合値は範囲外 |

- 寛容ライセンスの参照実装: ISO 532-1 は MoSQITo（Apache-2.0）[S10] がある。532-2 / 532-3 は見つからなかった（ケンブリッジ大学の配布はライセンスの記載なし、deeuu/loudness は GPL-3.0 で参照不可）
- シャープネスは DIN 45692:2009 が ISO 532-1 の比ラウドネスから定義する（重み関数を掛けた比ラウドネスの重心）。532-1 があれば追加の実装は小さい

### 3.3 試作（`core/analysis/iso532_1.py`）

- 公開関数: `loudness_zwicker(x, sr, field="free"|"diffuse", *, calibration_db_spl, method="stationary"|"time_varying", skip_s=0.2, return_specific=False)`、`loudness_from_third_octave_levels(levels_db, field)`、`third_octave_levels(...)`、`loudness_level_phon(N)`、`pascal_per_unit(cal)`
- 返り値（定常）: `N_sone`、`LN_phon`、`specific_loudness`（0.1〜24 Bark の 240 点、sone/Bark）、`core_loudness`、`third_octave_levels_db`、`calibration`、`warnings`、多チャンネル時の `per_channel`。時間変化: `N_sone_series`（2 ms ごと）、`N_max_sone`、`N5_sone`、`N10_sone`、`LN_phon`（N5 から）
- **校正は必須の引数**: `calibration_db_spl` = 「フルスケールの正弦波（ピーク 1.0）の dB SPL」。ISO 532-1 の WAV は 100 dB の規約である。省略すると `TypeError`
- 出所: 定数表と手順は、ISO 532-1 がそのまま採用している Zwicker ほか（1991）の BASIC プログラムの公刊論文 [S11] に従い、表の転記は MoSQITo（Apache-2.0）と照合した。コードは独自に書いた。ISO の C プログラムは使っていない（[S7] の条件のため）
- 1/3 オクターブのフィルタは**独自設計**（IEC 61260-1 の 10 進の帯域端で 6 次バターワース）であり、ISO 532-1 付属書 A の係数表を写していない。差は帯域中心の利得で 0.01 dB 未満、−3 dB 帯域幅で約 2 % 広い

検証結果（`python -m pytest tests/test_iso532_1.py -q` → 18 passed）:

| 試験信号（出典） | 参照値 | 試作 | 差 |
|---|---|---|---|
| 1 kHz、40 dB、自由音場（sone の定義） | 1 sone | 1.017 | +1.7 % |
| ISO 532-1 付属書 B.2 試験信号 1（1/3 オクターブのレベル入力） | 83.296 | 83.30 | 一致（同じ手順と表） |
| 付属書 B.3 試験信号 2（250 Hz、80 dB） | 14.655 | 14.723 | +0.5 % |
| 付属書 B.3 試験信号 3（1 kHz、60 dB） | 4.019 | 4.099（44.1 kHz 入力でも 4.101） | +2.0 % |
| 付属書 B.3 試験信号 4（4 kHz、40 dB） | 1.549 | 1.582 | +2.1 % |
| 付属書 B.4 試験信号 10〜12（1 kHz、70 dB のトーンパルス、時間変化法の Nmax） | 4.2998 / 5.9746 / 8.0772 | 4.152 / 6.050 / 8.240 | −3.4 % / +1.3 % / +2.0 % |

- 参照値は規格の電子付属物の結果ファイルの値で、MoSQITo のテストと検証スクリプトが引用しているものを使った。ISO の音声とデータはリポジトリに置かず、試験信号はテストの中で合成した（トーンパルスの包絡は 5 ms の二乗余弦の立ち上がり・立ち下がりで近似）
- 調査の過程で、MoSQITo が再配布している ISO の WAV（試験信号 3、5、11）にも試作を当てた（リポジトリ外、検証のためだけ）: 4.101（参照 4.019）、ピンクノイズ 10.559（参照 10.498）、トーンパルス 50 ms の Nmax 6.091（参照 5.975）。いずれも ISO 532-1 自身の適合の許容幅 5 % の内側
- 残る差の主因はフィルタの裾の形（独自設計）である。−3 dB 帯域幅を ISO の応答に合わせると 1.4 % 程度まで縮むが、係数表の再現にはしない方針を取った

計算の費用（Windows、1 コア、numpy / scipy）:

| 処理 | 実測 |
|---|---|
| 定常法、3 分、ステレオ | 約 17 秒（大半は 28 帯域のフィルタ） |
| 時間変化法、10 秒、モノラル（全帯域が鳴るノイズ） | 約 10 秒（非線形減衰の逐次計算が支配的。3 分ステレオで約 6 分） |

時間変化法を楽曲全体に日常的に掛けるには、非線形減衰と傾斜の計算を `dsp/native`（C++）に移す必要がある（50〜100 倍の高速化が見込める）。

### 3.4 どの代理指標を置き換え・検証できるか

| 代理指標 | ISO 532 で何ができるか | 推奨 |
|---|---|---|
| P-01 LTAS 帯域偏差 | 「80 phon の等ラウドネス重みを掛けた ERB の dB 偏差」の代わりに、比ラウドネス N'(z) どうしの偏差を測れる。レベル依存の重みが自然に入る | 置き換えない。リファレンスとの比較はレベルマッチ後の相対値なので、現行で足りる。**検証**（両者の順位相関）に使う |
| P-02 マスキング | Moore–Glasberg の部分ラウドネス（Glasberg & Moore 2005 [S12]）は「伴奏の中での主役のラウドネス」を直接与える。現行の拡散関数よりも根拠が強い | 中期の候補（532-2 系の実装が前提）。P-02 の対ボーカル版の検証から始める |
| P-10 主役帯域レベル差 | dB 差の代わりに、主役と伴奏のラウドネス（sone）の比 | P-02 と同じ扱い |
| P-11 ハーシュネス | シャープネス（DIN 45692、532-1 の N'(z) から計算）を併記し、P-11 との相関を確かめる | **検証用に最初に配線する**候補 |
| P-20 セクション間コントラスト | セクションごとの N5（sone）の比。Short-term LUFS の差より知覚に近い | 検証用に併記 |
| OF-5 の「小音量相当」 | 校正を −20 dB 動かして N'(z) の主役と伴奏の関係を見れば、等ラウドネス補正の近似でなく直接計算になる | 中期の候補 |
| Mix Report の「sone 比」 | dB 差からの換算でなく、処理前後の実際の N を出せる | 検証用に併記 |

### 3.5 SPL の校正（決定が要る）

デジタル音声には絶対音圧がない。ISO 532 の値は「どの音量で聴くか」の仮定に依存する。決め方の案:

- 正本の `listening_assumption.level`（既定 `"moderate"`）を校正値に写す表を `knowledge/` に持つ。例: 「媒体プロファイルの目標ラウドネス（例 −14 LUFS）に正規化された番組が、`moderate` なら 75 dB SPL（A 特性ではなく、統合ラウドネスと同じ量の SPL 換算）で鳴る」とし、`calibration_db_spl = L_listen − T_LUFS + 3.01`（フルスケールの正弦波は −3.01 LUFS）とする
- `masking_model.json` の `full_scale_spl_db`（96）とも同じ規約にそろえる
- 値は [慣行] の初期値で、Mix Report に必ず併記する

### 3.6 推奨と工数

1. **ISO 532-1 は検証用として配線する**（Mix Report の参考値、P-11 とシャープネス、P-20 と N5 の照合）。目的関数の項には入れない（較正前に項を増やすと §1 の推定が難しくなる）: 2〜3 人日
2. 校正規約（§3.5）を先に決める: 0.5 人日
3. 時間変化法は、楽曲全体に使うならネイティブ核に移す: 3〜4 人日
4. ISO 532-2（定常、両耳）は、P-02 / P-10 の検証の必要が出たら実装する。FFT のスペクトルから励起パターン（0.1 Cam 刻み）を作る構成で、numpy で数秒以内に収まる見込み。参照値は ISO の付属物でなく公刊論文（Moore, Glasberg & Baer 1997 [S13]、Glasberg & Moore 2006 など）の表から取る: 4〜6 人日
5. ISO 532-3 は計算が重く（多重解像度の FFT を 1 ms ごと）、総合値の定義も範囲外なので、v1 の後も見送る
6. ラフネス・変動強度は、規格化された手順が ECMA-418-2（Sottek の聴覚モデル）系で別体系になるので、今回の範囲外とする

### 3.7 決定候補

- **M10-P06**: ISO 532-1 の位置づけ（測定ベクトルに入れず、検証と Mix Report の参考値に留める。入れる場合は P-23 以降の ID と [規格] のラベルの扱い）。あわせて、定数表の出所（Zwicker ほか 1991、DIN 45631）を公開監査（`docs/PUBLICATION_AUDIT.md`）の対象に加える
- **M10-P07**: SPL の校正規約（`listening_assumption.level` から `calibration_db_spl` への写像、`masking_model.json` の 96 dB との統一）
- **M10-P08**: 時間変化法をネイティブ核に移すか（移す場合、C ABI に解析用の関数を足すことになり、§14.2 の「核は DSP だけ」との関係を整理する）

---

## 4. (d) プラグイン化の実現可能性（アーキテクチャ側）

ライセンスの一次資料は `docs/PUBLICATION_AUDIT.md` §3 にあり、D-063 で「VST3 SDK 3.8 以降は MIT。CLAP（MIT）を第一候補、LV2（ISC）と AudioUnitSDK（Apache-2.0）も候補、JUCE と VST2・ASIO・AAX の SDK は使わない」と確定している。本節はそれを前提に、構造の対応だけを扱う。

### 4.1 現状

- ネイティブ核（`dsp/native`）は C ABI（`mmx_create` / `mmx_set_param` / `mmx_process` / `mmx_latency` / `mmx_reset`）を持ち、planar の double をその場で処理する。処理中のメモリ確保・ロック・入出力をしない。ブロック長によらずビット一致（テスト済み）。プラグイン SDK のヘッダに依存しない（§14.2 の約束どおり）
- ただし**核に実装されているのは Airwindows 由来の 4 つ（`aw.*`）と、ダイナミクス系の平滑化の補助関数だけ**である。`eq`、`filter`、`dynamic_eq`、`compressor` のゲイン計算以外の部分、`deesser`、`saturator`、`stereo`、`clipper`、`limiter`、`reverb`、`delay`、`gain`、`pan` は参照実装（numpy、`dsp/reference/`）にしかない
- 各プロセッサは `dsp/processors.py` で `realtime`（`block_ok`、`latency_samples`、`allocates`、`latency_rule`）と `offline_only` を宣言済み。`resample` だけが `offline_only: true`。レイテンシの規則は、線形位相 EQ（FIR の半分）、`stereo` の帯域分割 FIR、オーバーサンプリングの多相 FIR、`limiter` の先読み、`aw.clip_only2` の 1 サンプル
- チェーンの共有契約: 正本のトラック・バス・マスター（`variants[].master.chain`）の `chain` が、プロセッサ型・パラメータ ID・値の JSON（§9.2、§14.2）

### 4.2 対応づけ

| 本体の要素 | プラグインでの姿 | 実時間に載るか |
|---|---|---|
| トラック／バス／マスターの `chain` | プラグイン 1 インスタンス = 1 つのチェーン。状態はチェーンの JSON そのもの | 載る（下の例外を除く） |
| パラメータ ID（`gain_db`、`freq_hz` …） | ホストに見せるパラメータ。ID は「ステップ番号 + パラメータ ID」から安定に決める（CLAP の `clap_id` は 32 bit の整数なので、対応表を状態に持つ） | 載る |
| `limiter` の先読み、線形位相 EQ、帯域分割 FIR、オーバーサンプリング | 宣言済みのレイテンシをホストに報告し、ホストが補償する | 載る |
| `reverb` | 現行はレンダリングしたインパルス応答の FFT 畳み込み（`allocates: true`）。分割畳み込みに作り直し、確保を初期化時に寄せる | 作り直せば載る |
| `delay`、`dynamic_eq`、`deesser`、`compressor`、`saturator`、`clipper`、`stereo`、`gain`、`pan`、`aw.*` | そのまま | 載る |
| サイドチェイン（ダッキング） | ホストのサイドチェイン入力（CLAP の追加の音声ポート）が要る | 載る（ホスト依存） |
| `loudness_gain`（マスタリング第 5 段） | 本体が曲全体の統合ラウドネスから決めた**固定値**として持つ。プラグイン内で再計算しない | 値の決定は載らない |
| `resample`、`dither`、書き出し | ホストの役割。プラグインに入れない | 入れない |
| 整音（`cleanup.*`） | STFT ベースで、曲全体の診断と検出に依存する。オフライン専用と宣言する | **載らない**（本体で処理した音声を DAW に戻す） |
| 解析、目的関数の評価、プランナー、トランスレーション・ゲート、検証 | コンパニオン（本体）側（§14.2） | **載らない** |
| 自動化（ブレークポイント） | v1 の正本はゲインのみ（§9.2）。ホストの自動化に写す | 載る |

- 状態（プリセット）の形の案: `{"format": "mankomix-chain", "schema_version": 1, "engine_min_version", "chain": [...], "param_map": {clap_id: [step, param_id]}, "source": {"project_sha256", "variant", "target": "track:trk_vocals"}, "sample_rate_rendered"}`。本体に `mankomix export-chain`（チェーンを書き出すコマンド）を足し、プラグインがそれを読む
- 再現性: 本体のレンダリングは double、ホストの入出力は多くが float32 で、ホストの補償や自動化の解像度も違う。**オフラインのレンダリングとのビット一致は約束できない**。「許容誤差内の一致」（§16.3 の環境をまたぐ場合と同じ扱い）とし、テストで誤差を測る
- サンプルレート: パラメータは物理単位なので移せるが、FIR とインパルス応答はレートごとに作り直す（初期化時）

### 4.3 形式とフレームワーク

| 形式 | 道具 | 判断 |
|---|---|---|
| CLAP | CLAP（MIT）、clap-helpers（MIT） | **第一候補**（D-063）。Bitwig、REAPER、FL Studio、Studio One などが対応 [S14] |
| VST3、AUv2 | clap-wrapper（MIT）で CLAP から生成。VST3 SDK 3.8 以降（MIT）、AudioUnitSDK（Apache-2.0） | CLAP で書いてラッパーで出す。AAX と ASIO を有効にするビルド設定は使わない（`docs/PUBLICATION_AUDIT.md` §3.2） |
| LV2 | LV2（ISC）。DPF（ISC）でも可 | Linux の需要があれば。clap-wrapper は LV2 を出さないので別のシェルが要る |
| （不採用） | JUCE（AGPLv3 / 商用）、nih-plug の VST3 バインディング（GPLv3）、VST2 のヘッダ、AAX SDK | ライセンスで除外（nih-plug 本体は ISC だが VST3 部分が GPL） |

- GUI は最初は持たない（ホストの汎用パラメータ表示で足りる）。チェーンの決定は本体の GUI で行う
- 配布: macOS は署名と公証（notarization）が要り、Apple Developer Program の費用がかかる。Windows も未署名の DLL は警告が出る。費用を払うかは別の判断

### 4.4 工数

| 作業 | 工数 |
|---|---|
| 参照実装にしかないプロセッサの C++ 移植（12 種）と、参照実装との許容誤差テスト | 15〜25 人日 |
| `reverb` の分割畳み込み化 | 3〜5 人日 |
| CLAP のシェル（状態の読み書き、パラメータ表、レイテンシ報告） | 3〜5 人日 |
| clap-wrapper による VST3 / AUv2、3 OS のビルドと CI | 3〜5 人日 |
| `export-chain` コマンドと状態の形式 | 1〜2 人日 |

合計 25〜40 人日。最大の作業はプラグイン固有の部分ではなく C++ への移植であり、移植は `native` バックエンドの高速化（§3.3 の時間変化ラウドネスや、プランナーの反復の高速化）にも効く。

### 4.5 決定候補

- **M10-P09**: プラグインの範囲を「チェーンプレイヤー」に限る（解析・評価・整音は持たない）。状態の形式（`mankomix-chain`）とパラメータ ID の写像を定める
- **M10-P10**: プロセッサを C++ に移植したとき、どちらを正とするか（参照実装を正として C++ を許容誤差内で一致させるか、C++ を正にして参照実装をテスト用にするか）。再現性の約束（§9.6）とレンダリング記録のバックエンドの版に影響する

---

## 5. (e) アルバムモード

### 5.1 現状

- v1 は 1 プロジェクト 1 曲（D-047）。`tidal` は 1 曲をアルバムとみなして扱う（§5.2）
- 複数の出口（プロファイル × 納品形式）とバリアントは 1 曲の中で持てる（§5.4、§9.4）
- リファレンスの仕組み（`core/reference.py`）は、他の音声から測定ベクトルだけを取り、中央値と四分位範囲の分布を P-01 などの目標に使える

### 5.2 要件の整理

1. **ラウドネスの関係**: アルバム単位で正規化する再生系（Tidal など）では、曲間の音量差がそのまま聞こえる。バラードを盛り上がる曲と同じ統合ラウドネスにそろえると、アルバムとしての起伏が消える。逆に、曲ごとに正規化する再生系では差は消える
2. **トーンの一貫性**: 曲ごとに別々に仕上げると、LTAS の傾き（明るさ）や低域量（P-07）がばらつく
3. **アルバム単位のレポート**: 曲ごとの値の表、アルバム全体の統合ラウドネス（全曲を連結した番組として BS.1770 で測る）、PLR、ばらつきの指標、正規化の方式ごとに聴き手にどう聞こえるか
4. （後回し）曲間の無音・クロスフェード、CD の DDP やトラックのインデックス

### 5.3 選択肢

| 案 | 内容 | 評価 |
|---|---|---|
| A: 1 プロジェクトに複数曲を入れる | `project.json` に曲の配列を持つ | 正本の形式の変更が大きく、既存の全コマンドと GUI に波及する。採らない |
| B: アルバムの正本を別に持つ | `<name>.mmxalbum/album.json` が、曲のプロジェクト（`.mmx`）を相対パスと正本のハッシュで参照する。曲側は今のまま | **推奨**。曲のプロジェクトは単独でも仕上がり、アルバムは「曲を束ねて整える層」になる |
| C: レポートだけ作る | 既存の曲のマスターを並べて測るだけ | 最初の一歩として B の中で実装する |

### 5.4 推奨する設計（案 B）

- `album.json` の骨子: `tracks: [{project: "songs/01.mmx", project_sha256, variant, order, role: "single"|"album_track", loudness_offset_lu: null}]`、`policy: {loudness: "preserve_relative", tonal: "album_reference", target_profile}`、`report` の版
- **ラウドネスの既定（`preserve_relative`）**: 各曲を単独で仕上げた後、アルバムで最も大きい曲をプロファイルの目標に合わせ、他の曲は単独の仕上げでの相対差（統合ラウドネスの差、または Short-term 最大の差）を保つようにゲインだけを下げる。下げるだけなので、リミッターの深さ（P-18）は増えない。ユーザーが `loudness_offset_lu` で曲ごとの差を明示できる
- 代替の方針: `match_integrated`（全曲を同じ統合ラウドネスに。曲ごとの正規化と同じ聞こえ方）
- **トーンの一貫性（`album_reference`）**: アルバムの他の曲の測定ベクトルを、その曲のリファレンス集合として使う（既存の `reference_distribution` をそのまま使える）。目的関数の評価で P-01、P-07 の目標に入り、外れた曲だけ是正の提案が出る。曲の個性を消さないよう、この項の重みは小さくし、是正は「提案」に留める（R-31）
- **アルバムのレポート**: 曲ごとの表（統合ラウドネス、TP、PLR、LRA、P-07、LTAS の傾き）、アルバム全体の値、ばらつき（曲間の中央値からの偏差）、正規化の方式（曲単位／アルバム単位）ごとの「聞こえ方」の説明
- 曲側を変えずに済むように、アルバムの調整は曲のプロジェクトの**新しいバリアント**として書き戻す（`variants[]` に `album:<id>` を足す）。操作履歴（journal）に残る

### 5.5 工数

| 作業 | 工数 |
|---|---|
| アルバムの正本、スキーマ、読み込み | 2〜3 人日 |
| アルバムの測定とレポート（案 C 相当） | 2〜3 人日 |
| ラウドネスの方針と、曲側へのバリアントの書き戻し | 2〜3 人日 |
| トーンの一貫性（リファレンスの流用）と CLI / MCP | 2〜3 人日 |

合計 8〜12 人日。GUI のアルバム画面は別に 3〜5 人日。

### 5.6 決定候補

- **M10-P11**: アルバムの正本を別形式（案 B）とし、ラウドネスの既定を `preserve_relative`、トーンは他の曲をリファレンス集合として使う。アルバムの調整は曲のバリアントとして書き戻す（D-047 の「v1 は 1 曲」の後継の決定）

---

## 6. (f) タイムストレッチの実装調査

### 6.1 現状

- タイムストレッチとピッチシフトは v1 の範囲外（D-048）。リミックスで足した素材のテンポとキーは `core/remix.py` の `diagnose_consistency` が比べ、ずれと「必要な伸縮率」（`stretch_needed_pct`）を**報告するだけ**で、伸縮しない（`time_stretch: false`）
- 尺の違う素材は、先頭そろえ・末尾は無音で扱い、差が大きければ差し戻す（D-054、`core/ingest/checks.py` の `conform_policy`。「自動で伸縮しない」）
- `ffmpeg` バックエンドは LGPL 構成の機能だけを使い、rubberband を使わない（`dsp/README.md`）

### 6.2 寛容ライセンスの候補

| 実装 | ライセンス | 形態 | 評価 |
|---|---|---|---|
| signalsmith-stretch [S15] | **MIT** | C++11 のヘッダのみ。ストリーミング API、レイテンシを報告 | 音質の評判がよく、多オクターブのピッチシフトも可能。伸縮は 0.75〜1.5 倍で最良と作者が書いている。**決定性は文書化されていない**（乱数は使わない設計に見えるが、FFT のバックエンドで値が変わりうる）ので、取り込み時にビット一致のテストを足す。`dsp/native` に `third_party/` として取り込める |
| FFmpeg `atempo` | **LGPL**（libavfilter の `af_atempo.c`。WSOLA）[S16] | 外部プロセス（既存の `ffmpeg` バックエンド） | 追加の依存がなく手軽。0.5〜100 倍。音楽では過渡音が崩れやすいが、1〜2 % 程度の小さな補正なら実用になる。ピッチはそのまま。FFmpeg の `rubberband` フィルタは GPL のライブラリが要るので使わない |
| 自前の numpy 実装（位相ボコーダ＋位相ロック、または WSOLA） | 本体と同じ Apache-2.0 | `reference` バックエンド | ライセンスは最も清潔で決定的。音質は signalsmith に及ばない見込み |
| stftPitchShift [S17] | MIT | C++ / Python | ピッチ（とフォルマント）だけで、伸縮はない |
| Bungee [S18] | **MPL-2.0** | C++ | ファイル単位の弱いコピーレフト。本体の方針（§13）は GPL / AGPL を禁止し LGPL を外部プロセスに隔離するが、MPL の扱いは決めていない。採るなら方針の決定が要る |
| SoundTouch | LGPL-2.1 | C++ | 同一プロセスに入れられない（§13.1）。外部プロセスにするなら FFmpeg の `atempo` で足りる |
| Rubber Band | GPL / 商用 | — | **除外**（D-015） |
| zplane élastique | 商用のみ | — | 除外 |
| librosa の位相ボコーダ | ISC | Python | コアで librosa を import しない（D-057）ので使わない |

### 6.3 どこに差し込むか

- **新しい抽象プロセッサ `time_stretch`**（`ratio`、`pitch_semitones`、`algorithm`、`algorithm_version`）を、トラックのチェーンではなく**クリップの性質**として持つ（`tracks[].clips[].stretch`）。尺が変わる処理なので、チェーン（長さを変えない。S-09）には入れない
- 実行はクリップの組み立て（`core/mixrender.py` のクリップをタイムラインに置く段）の前。結果は素材のハッシュとパラメータでキャッシュする。`offline_only: true`（§14.2 の宣言）
- 使えるのは**リミックス操作の明示的な指定だけ**: `diagnose_consistency` は今の報告に加えて、伸縮率とピッチの差を「提案」として出す（R-31）。人間かエージェントが採用したときだけ `clip.stretch` が正本に入り、操作履歴と Mix Report に残る
- **conform（D-054）では使わない**: 書き出しのレンダリングの尺の違いは、テンポの違いではなく末尾の切り落としや別レンダリングの混在であり、伸縮で合わせると誤った素材を黙って通す。D-054 の差し戻しは維持する
- ごく小さなずれ（例えば 0.1 % 以下）の補正には、ピッチも一緒に動く「バリスピード」（多相フィルタによるリサンプル。0.1 % で約 1.7 セント）が最も無害で決定的。これも明示の指定だけで使う
- 伸縮した素材には P-12（トランジェント保持）を当て、悪化を Mix Report に出す

### 6.4 推奨と工数

1. 第一候補は **signalsmith-stretch を `dsp/native` に取り込む**: ライセンス表示（`third_party/signalsmith-stretch/`）、C ABI の関数、ctypes の結線、決定性とブロック長非依存のテスト、OS をまたいだ許容誤差の測定で 4〜6 人日
2. 早く使える代替として **FFmpeg の `atempo`** を `ffmpeg` バックエンドに足す: 1〜2 人日。ピッチシフトは提供しない
3. 自前の numpy 実装は、参照実装として決定性の基準が要るときに作る: 3〜4 人日

### 6.5 決定候補

- **M10-P12**: `time_stretch` をクリップの性質として導入し（D-048 の改訂）、リミックス操作の明示の指定だけで使う。conform（D-054）では使わない。アルゴリズムは signalsmith-stretch（MIT、ネイティブ核）を既定、FFmpeg の `atempo`（LGPL、外部プロセス）を代替とする
- **M10-P13**: MPL-2.0 などのファイル単位の弱いコピーレフトの扱い（同一プロセスに入れてよいか）を、§13 の依存方針に明記する

---

## 7. (g) リファレンス統計の同梱の再検討

### 7.1 現状

- v1 は市販曲から得た統計を同梱しない（D-039）。リファレンスは利用者がプロジェクトごとに登録し、音声は保存せず測定ベクトルだけを `analysis/ref_<id>.json` に置く（`core/reference.py`）
- リファレンスがないときは汎用 prior（`knowledge/thresholds.json` の `generic_tonal_prior`、`knowledge/thresholds_m3.json` の `p01_generic_prior`）を使い、その旨を Mix Report に書く
- ジャンル prior の P-10 目標帯は「暫定」（`knowledge/genre_priors.json`）

### 7.2 権利の整理

- 米国では、事実は（単独でも編集物の一部でも）著作物にならない（Feist v. Rural, 1991 [S19]）。自分で測った数値の統計は、それだけでは著作物ではない。ただし他人の「選択と配列」を写すと問題になりうる
- EU では、データベースの作成者に、相当な投資を条件とする独自の権利（sui generis）がある（指令 96/9/EC の第 7 条、保護期間 15 年 [S20]）。**他人が公表した統計の表を大量に写すと侵害になりうる**。自分で測った統計にはこの危険はない
- 市販曲を測るには音源の入手が要る。ストリーミングから取り出すことはサービスの規約に反しうる（購入したファイルを測る必要がある）
- 選曲そのもの（「このジャンルの基準はこの曲たち」）が、曲名を出せば第三者の名前を使った表示になり、出さなければ検証できない
- 公開されている、寛容ライセンスのジャンル別ラウドネス・LTAS の統計のデータセットは見つからなかった（Pestana ほか 2013 [S21] は論文のみでデータの配布なし。iZotope などの公開値はライセンスの記載なし）

### 7.3 選択肢

| 案 | 内容 | 評価 |
|---|---|---|
| A: 現状維持 | 同梱しない | 安全。汎用 prior の幅が広く、ジャンルに合わせた評価ができない |
| B: オーナーが市販曲を測った統計を同梱 | 購入音源から測り、集計値（中央値と四分位範囲）だけを置く | 法的な危険は小さいが、選曲の説明責任と検証不能性が残る。公開監査の負担が大きい |
| C: CC ライセンスのコーパスから作る | 楽曲ごとに CC ライセンスが付いた公開データセット（候補: FMA、MTG-Jamendo。**ライセンス条件は未確認**） | ライセンスが曲ごとに異なり、非商用条件の曲も混ざる。統計は事実でも、データセット側の利用条件を確認する必要がある。ジャンルの分布が商用の J-POP やアニソンと違う |
| D: オーナー自身の楽曲から作る | 権利者自身の曲の統計 | 権利は清潔。1 アーティストの偏りがあるので「ジャンルの基準」でなく「例」として示す |
| E: 形式と作成ツールだけを用意する | 利用者が手元のライブラリから集合を作り、共有する仕組み | 同梱の問題を避けつつ、ジャンル別の評価を利用者が得られる |

### 7.4 推奨と工数

- **E を実装し、D を「例」として同梱を検討する**。B は引き続き見送る（D-039 の理由は今も有効）。C はデータセットのライセンスを一次資料で確認してから再検討する
- 統計ファイルの形式: `knowledge/reference_sets/<id>.json` に `{id, label, genre, n_tracks, stats: {P-01: {centres_hz, median_db, iqr_db}, P-07: …, P-03: …}, provenance: {source: "user"|"owner_catalog"|"corpus", license, measured_with: analyzer_version, level_match_lufs, created}}`。曲ごとのベクトルは置かず、集計値だけを置く。最小の曲数（例えば 8 曲）を下回る集合は作れないようにする
- 作成ツール: `mankomix reference-set build <folder> --genre …`（音声は読むだけで複製しない）
- 工数: 形式とツール 2〜3 人日、オーナーの曲からの例の作成と監査 1 人日

### 7.5 決定候補

- **M10-P14**: リファレンス集合の形式（`knowledge/reference_sets/`、集計値のみ、最小曲数、出所の必須項目）を定め、オーナー自身の楽曲から作った集合を「例」として同梱することを認める（D-039 の改訂）。市販曲の統計の同梱は引き続き行わない

---

## 8. (h) 外部サービスの入力アダプタ

### 8.1 現状

- 入力アダプタの契約は `core/adapters/base.py` の `SourceAdapter`（`probe(src)`、`fetch(src, project, mode, provenance)`）と登録表（`register_adapter`、`get_adapter`）。v1 の実装は `FileAdapter`（`core/adapters/file.py`）だけ（D-007）
- Suno Studio の書き出しセットは、名前のパターンと役割の対応表（`knowledge/ingest_patterns.json`）で検出し、出所（`provenance`: `source`、`service`、`input_kind`、`detected_by`、`declared_by_user`）を正本に残す
- コアは外部サービスに依存しない（A-10、D-007）

### 8.2 Suno の現状（2026-11 時点）

- **公式の公開 API はない**。2026-07 に開発者向け API を一部の提携先と検討中と報じられたが、時期は未定 [S22]
- **公式の Suno MCP（ベータ）がある**（`https://api.suno.com/mcp`、Suno アカウントでのサインイン、全プランで利用可、生成はクレジットを消費）[S23]。Studio のマルチトラック（ステム）書き出しを MCP から取得できるかは**確認できていない**
- 規約（2026-09-03 発効）[S24]: スクレイピングやロボットによる取得を禁止。有料プランの出力は権利が利用者に譲渡されるが、著作権の存在は保証しない。無料プランの出力は非商用。公式サンプルの権利の前提は D-062 にある
- したがって、非公式の API やブラウザの自動操作でダウンロードするアダプタは作らない

### 8.3 選択肢

| 案 | 内容 | 評価 |
|---|---|---|
| A: エージェント仲介 | エージェントが Suno MCP（または利用者の手作業）でファイルを手元のフォルダに取得し、本体の `import` にそのフォルダと `provenance` を渡す | コードの追加がほぼない。コアは依存しない。認証は Suno MCP 側で完結し、本体は資格情報に触れない。**推奨** |
| B: 別パッケージのアダプタ | `mankomix-adapter-suno` を別配布し、entry point（`mankomix.adapters`）で登録する。中で MCP のクライアントとして Suno MCP を呼ぶ | 外部依存（MCP クライアント、認証フロー）を本体から切り離せる。Suno MCP の仕様変更に追従する保守が要る |
| C: 本体にアダプタを入れる | `core/adapters/suno.py` | D-007、A-10 に反する。採らない |

### 8.4 インターフェースの骨子（案 B を作る場合）

外部サービスのアダプタは「取得（acquire）」と「取り込み（ファイルアダプタへの委譲）」を分ける。取り込みの規則（無加工、内容ハッシュ、検査）は全てファイルアダプタのものを使い、二重に実装しない。

```python
class ExternalSourceAdapter(SourceAdapter):
    """取得だけを担い、取り込みは FileAdapter に委ねる外部サービスのアダプタ。"""

    id = ""                 # 例: "suno_mcp"
    service = ""            # provenance.service に入る値。例: "suno"

    def probe(self, src) -> dict:
        """src（サービス上の項目 ID や共有 URL）が扱えるか、何が取れるか（ステムの有無、
        フルミックスの有無、形式、尺）を返す。何も書かない。"""

    def acquire(self, src, staging_dir, *, credentials) -> dict:
        """素材を staging_dir（プロジェクトの外の一時フォルダ）へダウンロードし、
        取得記録 {files: [{name, sha256, bytes}], service_item_id, retrieved_at,
        retrieval_method, terms_url} を返す。ファイルは受け取ったまま（A-12）。
        credentials は呼び出し側が渡す（環境変数や OS の資格情報ストア）。
        正本にもログにも書かない（D-020）。"""

    def fetch(self, src, project, *, mode="copy", provenance=None, **kw) -> dict:
        staging = make_staging_dir()
        rec = self.acquire(src, staging, credentials=kw.get("credentials"))
        prov = {"source": "ai_generated", "service": self.service,
                "retrieval": {k: rec[k] for k in ("service_item_id", "retrieved_at",
                                                  "retrieval_method", "terms_url")},
                **(provenance or {})}
        result = get_adapter("file").fetch(staging, project, mode="copy", provenance=prov)
        verify_hashes(rec["files"], result)      # 取得と取り込みで内容ハッシュが一致すること
        return {**result, "acquire": rec}
```

- 登録は entry point（`[project.entry-points."mankomix.adapters"]`）から読み、`available_adapters()` に出す。本体はアダプタのパッケージを import しない限り何も読み込まない
- `provenance` に足す項目: `retrieval.service_item_id`、`retrieved_at`、`retrieval_method`（`"suno_mcp"` / `"manual_download"`）、`terms_url`、利用者の申告として `plan_at_generation`（有料プランか。D-062 の C-1 に対応）
- 再取得で内容ハッシュが変わったら警告する（サービス側の再レンダリングの検出）
- 案 A の場合も、上の `provenance` の項目だけは `import --provenance` で渡せるようにすると、取得の経路が正本に残る

### 8.5 推奨と工数

- **案 A を標準の手順とし**、`provenance` の項目を足し、エージェント向けの手順（Suno MCP で取得 → `mankomix import`）を文書化する: 0.5〜1 人日
- 案 B は、Suno MCP がステムの取得に対応していると確認でき、需要が出てから作る: 3〜5 人日（entry point の登録の仕組み 1 人日を含む）

### 8.6 決定候補

- **M10-P15**: 外部サービスからの入力はエージェント仲介を標準とし、本体にサービス固有のアダプタを入れない。アダプタを作る場合は別パッケージで entry point から登録する（D-007 の具体化）
- **M10-P16**: `provenance` の項目の拡張（取得の経路、サービス上の ID、取得日時、規約の URL、生成時のプランの申告）。スキーマ（`schemas/`）の変更を伴う

---

## 9. 決定候補の一覧

採用時に `docs/REQUIREMENTS_NOTES.md` で D-ID を振る。番号はこの文書の中だけのもの。

| 候補 | 内容 | 関係する既存の決定・節 |
|---|---|---|
| M10-P01 | 聴感評価の手順と記録（`calibration/`、セッションの JSONL、刺激の目録、当てはめの結果）の採用 | §4.9、§16.5、D-039 |
| M10-P02 | 重みの更新規則（事前重みへの正則化、1 回 ±0.10 の上限、交差検証での改善を条件、S-nn は厳しくする方向のみ、1 曲だけの結果はジャンル prior にだけ反映） | §4.9 |
| M10-P03 | 評価データの公開範囲（仮名 ID、評価者の同意、非公開曲は結果の重みだけ） | D-020、D-039 |
| M10-P04 | `low_fatigue` を暫定のまま維持し、昇格の条件を定める | §4.4、U-006 |
| M10-P05 | 組み込みの目的関数を較正まで増やさない。新しい測定器を伴う候補は個別の決定で P-23 以降を振る | §4.2、§4.8 |
| M10-P06 | ISO 532-1 を検証と参考値に留める（測定ベクトルの項にしない）。定数表の出所を公開監査の対象にする | §4.2、§13.4 |
| M10-P07 | SPL の校正規約（`listening_assumption.level` → `calibration_db_spl`、`masking_model.json` の 96 dB との統一） | §4.2、§9.2 |
| M10-P08 | 時間変化ラウドネスをネイティブ核に移すか（核に解析用の関数を置くことの整理） | §14.2、D-034 |
| M10-P09 | プラグインの範囲（チェーンプレイヤー）、状態の形式、パラメータ ID の写像 | §14、D-049、D-063 |
| M10-P10 | C++ に移植したプロセッサと参照実装のどちらを正とするか | §3.2、§9.6、§16.3 |
| M10-P11 | アルバムの正本（別形式）、ラウドネスの既定（`preserve_relative`）、トーンの一貫性（曲どうしをリファレンスに）、曲のバリアントへの書き戻し | D-047、§5.2 |
| M10-P12 | `time_stretch` をクリップの性質として導入（明示の指定だけ、conform では使わない）。signalsmith-stretch を既定、FFmpeg `atempo` を代替 | D-048、D-054、§9.3 |
| M10-P13 | MPL-2.0 などファイル単位の弱いコピーレフトの扱い | §13、D-015 |
| M10-P14 | リファレンス集合の形式と、オーナー自身の楽曲の集合を例として同梱すること（市販曲の統計は引き続き同梱しない） | D-039、§4.6 |
| M10-P15 | 外部サービスの入力はエージェント仲介を標準とし、アダプタは別パッケージ（entry point） | D-007、A-10 |
| M10-P16 | `provenance` の項目の拡張（取得の経路、サービス上の ID、取得日時、規約、プランの申告） | §6.1、D-062 |

---

## 10. 出典

- [S1] D. Clark, "High-Resolution Subjective Testing Using a Double-Blind Comparator", J. Audio Eng. Soc., 1982（初出は AES 第 69 回コンベンション、1981） — https://www.aes.org/e-lib/browse.cfm?elib=3839
- [S2] R. A. Bradley, M. E. Terry, "Rank Analysis of Incomplete Block Designs: I. The Method of Paired Comparisons", Biometrika 39(3/4), 1952 — https://doi.org/10.2307/2334029
- [S3] ITU-R BS.1534-3, "Method for the subjective assessment of intermediate quality level of audio systems"（MUSHRA） — https://www.itu.int/rec/R-REC-BS.1534
- [S4] ITU-R BS.1116-3, "Methods for the subjective assessment of small impairments in audio systems" — https://www.itu.int/rec/R-REC-BS.1116
- [S5] ISO 532-1:2017, Acoustics — Methods for calculating loudness — Part 1: Zwicker method — https://www.iso.org/standard/63077.html
- [S6] ISO/CD 532-1（第 2 版の改訂） — https://www.iso.org/standard/90809.html
- [S7] ISO 532-1 の電子付属物（"ISO 532-1 - Program etc.zip"）と利用条件 — https://standards.iso.org/iso/532/-1/ 、https://www.iso.org/terms-conditions-licence-agreement.html#Customer-Licence
- [S8] ISO 532-2:2017, Part 2: Moore-Glasberg method — https://www.iso.org/standard/63078.html
- [S9] ISO 532-3:2023, Part 3: Moore-Glasberg-Schlittenlacher method — https://www.iso.org/standard/69856.html
- [S10] MoSQITo（Apache-2.0）。ISO 532-1 の実装、テスト、検証スクリプト — https://github.com/Eomys/MoSQITo 、https://github.com/Eomys/MoSQITo/blob/master/tests/sq_metrics/loudness/test_loudness_zwst.py 、https://github.com/Eomys/MoSQITo/blob/master/validations/sq_metrics/loudness_zwst/validation_loudness_zwst.py
- [S11] E. Zwicker, H. Fastl, U. Widmann, K. Kurakata, S. Kuwano, S. Namba, "Program for calculating loudness according to DIN 45631 (ISO 532B)", J. Acoust. Soc. Jpn. (E) 12(1), 39–42, 1991 — https://www.jstage.jst.go.jp/article/ast1980/12/1/12_1_39/_article
- [S12] B. R. Glasberg, B. C. J. Moore, "Development and Evaluation of a Model for Predicting the Audibility of Time-Varying Sounds in the Presence of Background Sounds", J. Audio Eng. Soc. 53(10), 906–918, 2005 — https://www.aes.org/e-lib/browse.cfm?elib=13391
- [S13] B. C. J. Moore, B. R. Glasberg, T. Baer, "A Model for the Prediction of Thresholds, Loudness, and Partial Loudness", J. Audio Eng. Soc. 45(4), 224–240, 1997 — https://www.aes.org/e-lib/browse.cfm?elib=10272
- [S14] CLAP の対応ホストの一覧 — https://cleveraudio.org/hosts-and-plugins/ （最新は https://clapdb.tech ）。CLAP 本体 https://github.com/free-audio/clap 、clap-wrapper https://github.com/free-audio/clap-wrapper 。ライセンスの判定は `docs/PUBLICATION_AUDIT.md` §3
- [S15] signalsmith-stretch（MIT） — https://github.com/Signalsmith-Audio/signalsmith-stretch
- [S16] FFmpeg `libavfilter/af_atempo.c`（LGPL、WSOLA） — https://github.com/FFmpeg/FFmpeg/blob/master/libavfilter/af_atempo.c 。`rubberband` フィルタは `--enable-librubberband`（GPL のライブラリ）が要る — https://github.com/FFmpeg/FFmpeg/blob/master/configure
- [S17] stftPitchShift（MIT） — https://github.com/jurihock/stftPitchShift
- [S18] Bungee（MPL-2.0） — https://github.com/bungee-audio-stretch/bungee 。SoundTouch（LGPL-2.1） https://codeberg.org/soundtouch/soundtouch 。Rubber Band（GPL / 商用） https://breakfastquay.com/rubberband/
- [S19] Feist Publications, Inc. v. Rural Telephone Service Co., 499 U.S. 340 (1991) — https://www.law.cornell.edu/supremecourt/text/499/340
- [S20] Directive 96/9/EC（データベースの法的保護。第 7 条、第 10 条） — https://eur-lex.europa.eu/eli/dir/1996/9/oj/eng
- [S21] P. D. Pestana, Z. Ma, J. D. Reiss, A. Barbosa, D. A. A. Black, "Spectral Characteristics of Popular Commercial Recordings 1950–2010", AES 135th Convention, Paper 8960, 2013 — https://www.aes.org/e-lib/browse.cfm?elib=17010
- [S22] Music Business Worldwide, Suno の開発者向け API の検討（2026-07） — https://www.musicbusinessworldwide.com/suno-explores-developer-api-seeking-apps-that-unlock-experiences-generative-music-makes-possible-for-the-first-time/
- [S23] Suno ヘルプ（Suno MCP、ベータ） — https://help.suno.com/en/articles/14486145 、https://help.suno.com/en/articles/14551425
- [S24] Suno 利用規約（2026-08-10 改訂、2026-09-03 発効） — https://suno.com/terms 。公式サンプルへの当てはめは `docs/PUBLICATION_AUDIT.md` §1 と D-062
