# spec/10 修復／クリーンアップ（19 件）

カタログ §10。共通規約は `spec/01_dynamics.md` §0。表面の分け方は `spec/08_pitch_time.md` §0.1。タグは 2 代目 PM が付けた。**Audacity（GPL）の Noise Reduction／Click Removal、iZotope の特許・実装は読まない。**

## 0. カテゴリ共通

- 特記の無い型：`stages: ["track","bus"]`、`master_slot: None`、**`offline_only: True`**（検出に前後の文脈を使う。全長を受け取って処理する。CT-2 は「途中からの描画＝全長描画の該当部分と一致」に読み替える）、TV の一覧には**載せない**（修復は「主役に掛ける時間変化」の警告の趣旨と違う。OD-6 の既定の範囲外なので、載せるかどうかは OD-6 で決める。既定は載せない）
- **床の整音段（既存の自動の診断・処理）は変えない。** 本カテゴリの型は指揮書と手書きチェーンからだけ使う（PM_PLAN OD-17）
- 全型が持つ共通パラメータ **RP ブロック**：

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `amount` | f | 0..1 | 0〜1 | 型ごと（0＝ビット一致の素通し。経路を通さない） |
| `delta` | b | — | — | false（true＝「取り除いた分」だけを出す。聴いて確かめるため） |
| `start_s`・`end_s` | f | s | 0〜36000 | 0／0（両方 0＝全体。書けばその区間だけ処理し、外はビット一致。境目 10 ms 交差） |

- **記録（全型）**：検出した事象の数と一覧（時刻・長さ・強さ。最大 2000 件、超えたら件数と上位だけ）、取り除いたエネルギー（dB、全体比と帯域別）、処理前後の積分ラウドネスとピーク。**「直った」とは書かない**（取り除いた量だけ）
- 取りすぎの害が大きい。既定値は全部「弱め」に置く。指揮書の `removed_energy_rel_db`（既存の適用記録の項目）と同じ読み方ができるようにする

**共通テスト（RP）**：(RP1) `amount=0` でビット一致 (RP2) `delta` 出力＋通常出力＝（遅延補償した）入力、ヌル ≤ −120 dBFS (RP3) 区間指定の外がビット一致 (RP4) **無害性**：傷の無い合成素材（正弦の和、ピンクノイズ、合成母音、打楽器的バースト列の 4 種）に既定値で掛けて、取り除いたエネルギーが −60 dB 以下（各件で緩める型はそこに書く） (RP5) 記録の事象一覧と実際に変わった区間が一致 (RP6) 2 回描画一致

**部品**：BB-06（STFT）、BB-20（雑音の推定と抑圧ゲイン）、BB-21（自己回帰モデルの補間）、BB-22（発音点の検出）。

カテゴリの正典（最初に読む）：Godsill & Rayner『Digital Audio Restoration』（Springer 1998。クリック・クラックル・ヒス・補間の章。本カテゴリの決定論の型の大半の正）／Vaseghi『Advanced Digital Signal Processing and Noise Reduction』（Wiley）／Loizou『Speech Enhancement: Theory and Practice』（CRC。スペクトル減算・ウィーナー・MMSE・雑音推定）

---

## T10-01 定常ノイズリダクション

`denoise`｜B（カタログ：「決定論で書ける」）｜W3｜M｜Codex

RP（`amount` 既定 1）に加えて：

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `profile` | e | — | `region`／`auto` | `auto` |
| `profile_start_s`・`profile_end_s` | f | s | 0〜36000（長さ 0.2 s 以上） | 0／0（`region` のとき必須：雑音だけの区間） |
| `reduction_db` | f | dB | 0〜40 | 12（各ビンの最大の減衰） |
| `sensitivity` | f | dB | −12〜12 | 0（雑音の推定値に足す余裕。正＝多く取る） |
| `method` | e | — | `wiener`／`log_mmse`／`subtract` | `log_mmse` |
| `time_smooth_ms` | f | ms | 0〜500 | 80（ゲインの時間平滑。ミュージカルノイズ対策） |
| `freq_smooth_oct` | f | oct | 0〜1 | 0.1 |
| `transient_protect` | f | 0..1 | 0〜1 | 0.5（発音の頭でゲインを開ける度合い） |
| `window` | e | — | 1024／2048／4096 | 2048 |
| `lo_hz`・`hi_hz` | f | Hz | 20〜20000／20〜24000 | 20／20000 |

- アルゴリズム：`region`＝指定区間のパワースペクトルの平均と分散を雑音の型紙にする。`auto`＝最小統計法（各ビンの過去 1.5 s の最小値を追い、偏りを補正）で雑音床を推定。事前 SNR は決定指向法（前フレームの推定との加重）、ゲインは `method` の式、下限 −`reduction_db`、時間・周波数で平滑。位相は触らない
- 正典：Ephraim & Malah「Speech Enhancement Using a Minimum Mean-Square Error Log-Spectral Amplitude Estimator」IEEE Trans. ASSP 1985／Martin「Noise Power Spectral Density Estimation Based on Optimal Smoothing and Minimum Statistics」IEEE Trans. SAP 2001／Cappé 1994（決定指向法がミュージカルノイズを抑える理由）／Boll「Suppression of Acoustic Noise in Speech Using Spectral Subtraction」IEEE Trans. ASSP 1979
- 記録：推定した雑音床（1/3 oct、dBFS）、型紙の出どころ（区間か自動か）
- テスト（RP。RP4 は `auto` で −45 dB 以下に緩める：ピンクノイズ素材は「雑音」と区別できないので RP4 の対象から外し、その旨を docs に書く）：(1) 合成母音＋白色雑音（SNR 10 dB）、`region`：雑音だけの区間の残留が −`reduction_db` ±2 dB、母音区間の調波のレベル変化 ≤ 1 dB (2) セグメント SNR の改善 ≥ 6 dB（数値を記録） (3) ミュージカルノイズの指標：雑音だけの区間の残留の、時間−周波数の尖度が入力の雑音の 1.5 倍以下（`time_smooth_ms=80`）、平滑 0 では超える (4) `auto`：定常雑音 20 s で推定した雑音床が真値 ±2 dB (5) 発音の頭 10 ms のエネルギー損失 ≤ 1 dB（`transient_protect=0.5`） (6) spec/02 の S4
- 依存：BB-06、BB-20

## T10-02 適応型／AI ノイズリダクション

`denoise_ml`｜C（カタログ：「学習系が本質」）｜W5｜M｜Codex｜`stages: ["track"]`

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `model` | as | `models` レジストリ（BB-16。種別 `denoise`） | 登録済み ID | （必須） |
| `reduction_db` | f | dB | 0〜60 | 18（モデルの出力と原音の配分の上限：出力＝原音−(1−10^(−r/20))·(原音−モデル出力) 相当） |
| `fallback` | e | — | `denoise`／`error` | `denoise`（T10-01 の `auto`。走ったことを記録と Mix Report に出す） |
| RP ブロック | | | | `amount` 1 |

- PM_PLAN §5 の 6 条件。推論は ONNX Runtime・CPU・1 スレッド。モデルの sr（多くは 48 kHz か 16 kHz）へ既存 `resample` で往復。チャンク長・重なり・窓を固定
- 候補（**調査レッグが一次でライセンスを確かめる。PM は記憶で挙げている**）：DeepFilterNet（コード MIT／Apache-2.0 と記憶。48 kHz・全帯域）、RNNoise（BSD-3 と記憶。48 kHz・会話向け・古い）、DTLN（MIT と記憶。16 kHz）。採否の基準：(a) コードと重みの両方が再配布可（`official` にする場合）(b) ONNX で動く (c) 48 kHz 全帯域 (d) 同一環境でビット一致
- **留保（`caveats` に固定で書く）**：候補は全部**会話音声で学習**されている。歌・楽器・ミックスに掛けると音楽成分を雑音として削る。用途は「語り・台詞・ボーカルの素録り」に限る、と記録と docs に書く
- テスト（C-6）：モデル無し＝入出力の形、チャンク継ぎ目（継ぎ目の位置を変えて結果が同じ）、`fallback` が走って記録に出る、未登録・ハッシュ不一致の明示エラー、RP1〜3。モデルあり＝2 回描画一致、既知入力の出力ハッシュ、T10-01 (1)(2) と同じ測定を記録（合否にしない）
- 依存：BB-16、T10-01

### 実装時の確定（統括の判断 D-29・D-30）

`denoise_ml` は推論・BYOW・代替処理の経路を持つが、C-4の標準 Mix Report 接続にcoreの追加が要るため `implemented: false`（OQ-4）。modelの空文字は内部未指定値であり、既定モデルの選択ではない。未指定での実行は拒否する。T10-15衣擦れ側は再配布可能なOSS重みが見つからず未実装。風側の `dewind` と分けて扱う。

## T10-03 AI ボーカル分離抽出

**編集段の op `edit_isolate`（派生クリップ）**｜C｜W5｜M｜Codex
既存のステム分離統合層（demucs 系）は変えない。本件は「1 本のトラック（声＋背景）から声だけ（または背景だけ）を取り出して差し替える」op。

| id | 単位 | 範囲 | 省略時 |
|---|---|---|---|
| `keep` | 列挙 | `voice`／`background` | `voice` |
| `model` | モデル ID（BB-16。種別 `separate`） | 登録済み | 既存の分離統合層の既定モデル（その `vocals` 出力を使う） |
| `strength` | 0..1 | 0〜1 | 1（1＝分離結果そのもの。<1＝原音を混ぜ戻す） |
| `residual_db` | dB | −90〜0 | −90（捨てる側を残す量） |
| `section` | — | — | クリップ全体 |

- 既定は**新しいモデルを足さない**：既存の分離統合層が持つモデルを 1 トラックに対して呼ぶ経路を作るだけ。会話向けの別モデル（T10-02 の候補は雑音除去であって分離ではない）を足す場合は C-1〜C-3 を通す。調査レッグ：コミュニティ配布の分離モデル（MDX 系、RoFormer 系）は重みのライセンスが不明・非商用のものが多い。**不明なものは `byo` のみ**
- フォールバック：モデル不在は明示エラー（決定論の代替は無い）
- 記録：使ったモデルの ID・sha256・実行プロバイダ、keep 側と捨てた側のエネルギー、**両者の和が原音に戻るか（再構成誤差）**
- テスト（C-6）：モデル無し＝op の検査、派生クリップの台帳、エラー経路、含まない指揮書はバイト同一。モデルあり＝2 回一致、`strength=0` で派生を作らない、keep＋捨てた側＝原音（モデルが残差型ならヌル ≤ −60 dBFS、そうでなければ誤差を記録）
- 依存：BB-16、BB-18

## T10-04 デクリック ／ T10-05 デクラックル ／ T10-06 マウスデクリック

`declick`｜B｜W3｜M（T10-04）＋S（05）＋S（06）｜Codex
**T10-05・06 は別型を作らず、本型の `kind` で満たす**（検出の帯域・長さ・閾値の既定が違うだけで核は同じ）。

RP（`amount` 既定 1）に加えて：

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `kind` | e | — | `click`／`crackle`／`mouth` | `click`（下の `auto` の既定値を決める） |
| `threshold` | f | σ | 1.5〜20 | `click` 6／`crackle` 3.5／`mouth` 4.5（予測残差の頑健な標準偏差に対する倍率。小さい＝多く取る） |
| `max_len_ms` | f | ms | 0.1〜20 | `click` 4／`crackle` 1／`mouth` 8（これより長い事象は触らない） |
| `ar_order` | i | — | 8〜128 | 32（48 kHz 基準。sr に比例） |
| `band_lo_hz`・`band_hi_hz` | f | Hz | 0〜20000／0〜24000 | `click` 0／0、`crackle` 0／0、`mouth` 1500／12000（検出に使う帯域。0＝全帯域） |
| `voiced_only` | b | — | — | `mouth` のとき true（発声区間とその前後 300 ms だけ見る。BB-12 の有声判定＋レベル） |
| `protect_transients` | f | 0..1 | 0〜1 | 0.7（発音点〈BB-22〉の頭 `max_len_ms` を検出から外す度合い。打楽器を削らないため） |
| `guard_ms` | f | ms | 0〜2 | 0.3（検出した区間を前後に広げる） |
| `repair_band` | e | — | `full`／`detect_band` | `click`・`crackle`：`full`、`mouth`：`detect_band`（補間した分を検出帯域だけに限って戻す。低域を触らない） |

- アルゴリズム：(1) ブロック（約 20 ms、50 % 重なり）ごとに AR 係数を推定（Burg 法）(2) 予測残差を計算、頑健な尺度（中央絶対偏差）で正規化し、閾値超えを事象とする（前向き・後ろ向きの残差の両方で確かめる）(3) 事象区間を、前後のサンプルと AR モデルから**最小二乗で補間**（LSAR）(4) `crackle`：事象が密なので、補間後に残差を再計算して 2 巡する（巡回数は 2 に固定）
- 正典：Godsill & Rayner 1998（検出と LSAR 補間の章。**これが正**）／Janssen, Veldhuis & Vries「Adaptive Interpolation of Discrete-Time Signals That Can Be Modeled as Autoregressive Processes」IEEE Trans. ASSP 1986／Vaseghi & Rayner「Detection and Suppression of Impulsive Noise in Speech Communication Systems」IEE Proc. 1990
- テスト（RP に加えて）：(1) 合成母音・正弦の和に、既知の位置へクリック（1〜40 サンプル、振幅 −20〜0 dBFS）を 200 個：検出率 ≥ 95 %、誤検出 ≤ 5 個、補間区間の誤差（元の無傷信号との差）が区間内 RMS で −30 dB 以下 (2) `crackle`：密度 200 個/s の微小クリック（−40 dBFS）で、差分信号のうちクリック成分のエネルギーの 80 % 以上を除去、無傷部分の変化 ≤ −50 dB (3) `protect_transients`：バースト列の頭のピーク変化 ≤ 0.5 dB (4) `mouth`：2〜8 kHz・2〜6 ms の合成クリックを母音区間に入れて (1) と同じ基準、`voiced_only` で無音区間の事象は触らない (5) `max_len_ms` より長い事象は不変 (6) RP4
- 依存：BB-12、BB-21、BB-22

## T10-07 デクリップ

`declip`｜B｜W3｜M｜Codex

RP（`amount` 既定 1）に加えて：

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `threshold_db` | f | dBFS | −24〜0 | 0（0＝自動：振幅の度数分布の端の山から、潰れた水準を推定。正負別） |
| `min_run` | i | サンプル | 2〜32 | 3（この長さ以上、水準に張り付いた区間を潰れとみなす） |
| `max_run_ms` | f | ms | 0.5〜20 | 5（これより長い潰れは触らない） |
| `ar_order` | i | — | 8〜128 | 48 |
| `headroom` | e | — | `auto`／`none` | `auto`（復元で伸びたピークが 0 dBFS を超えないよう、全体を下げる。下げた量を記録） |
| `oversample` | e | x | 1／2／4 | 1（サンプル間で潰れた素材〈符号化・変換後〉向けに上げる） |

- アルゴリズム：潰れた区間を「値が不明、ただし |x| ≥ 水準」の欠落として、LSAR 補間を**不等式制約つき**で解く（制約を破る解は、破ったサンプルを水準に固定して解き直す。反復は最大 8 回に固定）。`headroom=auto` は処理後のピークから一意に決まる利得
- 正典：Janssen ほか 1986／Godsill & Rayner 1998／Záviška, Rajmic, Ozerov & Rencker「A Survey and an Extensive Evaluation of Popular Audio Declipping Methods」IEEE JSTSP 2021（方式の比較。疎表現系へ差し替える場合の入口）
- 記録：推定した水準（正負）、潰れたサンプルの割合、復元後のピーク、下げた量
- テスト（RP に加えて）：(1) 合成母音・正弦の和・ミックス相当の素材を −3／−6／−12 dB 相当で潰したもの：潰れ区間の SDR 改善（元信号に対し）≥ 6 dB（−6 dB 潰し）、数値を記録 (2) 復元した区間が制約を満たす（|x| ≥ 水準、符号一致） (3) 水準の自動推定が真値 ±0.2 dB (4) 潰れていない素材：検出 0 件、ビット一致（`headroom` も動かない） (5) `headroom=auto`：出力ピーク ≤ 0 dBFS (6) 矩形波（意図的な平坦部）：`max_run_ms` より長い平坦部は不変
- 弱点：強い潰れ（−12 dB 以上）は元に戻らない（もっともらしい形にするだけ）。リミッターで丸まった音（張り付かない）には効かない
- 依存：BB-21

### 実装時の確定（統括の判断 D-13）

C7c で `declip.min_run` の既定を3→2へ変更し、範囲2〜32は維持した。8 kHz・母音・−6 dB潰しでは3サンプル以上の平坦部が持つ誤差電力割合0.6217162111666261から改善上限4.221822697859387 dBとなり、6 dB基準へ到達できない。2サンプル以上の割合は0.9995345499406841、実出力の改善29.09324021385214 dB。明示3は引き続き尊重する。RP区間を指定したheadroomもその区間内だけに適用する。

## T10-08 デハム／バズ除去

`dehum`｜A｜W1｜S｜Codex

RP（`amount` 既定 1）に加えて：

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `base_hz` | f | Hz | 0、または 40〜70 | 0（0＝自動：45〜65 Hz の最も強く安定な線を探す。0.01 Hz 刻み） |
| `harmonics` | i | 本 | 1〜40 | 8 |
| `odd_only` | b | — | — | false |
| `depth_db` | f | dB | 3〜60 | 30 |
| `width_hz` | f | Hz | 0.2〜10 | 1（ノッチの −3 dB 幅。次数に依らず一定の Hz 幅） |
| `slope` | f | dB/次 | 0〜6 | 0（高次ほど浅くする傾き） |
| `track` | b | — | — | false（true＝基本周波数のゆっくりした変動〈±0.5 Hz〉を追う。10 s 窓） |
| `mode` | e | — | `notch`／`subtract` | `notch`（`subtract`＝各倍音の振幅・位相を推定して正弦を引く。周りを削らない。ハムが定常のとき向き） |

- アルゴリズム：`notch`＝2 次ノッチの直列、**前向き・後ろ向きのゼロ位相**（オフラインなので位相を回さない）。`subtract`＝区間ごと（1 s、50 % 重なり）に最小二乗で各倍音の複素振幅を当て、合成して引く
- 正典：Zölzer 編『DAFX』（ノッチ）／Godsill & Rayner 1998／Kay『Modern Spectral Estimation』（正弦の最小二乗推定）
- テスト（RP に加えて）：(1) 合成母音＋ 50.07 Hz とその倍音 8 本：自動推定が ±0.02 Hz、各倍音が `depth_db` ±3 dB 減る (2) 倍音の中間（例 75 Hz、125 Hz）の正弦のレベル変化 ≤ 0.2 dB (3) `subtract`：ハムの倍音が 40 dB 以上減り、同じ周波数に重ねた別の過渡成分（バースト）の変化 ≤ 1 dB (4) ハムの無い素材：`auto` が「見つからない」と記録し、ビット一致 (5) `track`：49.8→50.2 Hz へ 20 s で動くハムを 25 dB 以上除去 (6) ゼロ位相：インパルスの応答が対称
- 依存：BB-01 だけ（scipy のフィルタ設計は BSD）

## T10-09 デリバーブ

`dereverb`｜B（カタログ：「難関」）｜W3｜L（調査レッグが先）｜**Opus 中**｜`stages: ["track"]`

RP（`amount` 既定 0.5）に加えて：

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `method` | e | — | `spectral`／`wpe` | `spectral` |
| `rt60_s` | f | s | 0、または 0.1〜10 | 0（0＝自動推定。`spectral` が使う） |
| `reduction_db` | f | dB | 0〜30 | 9（後期残響の最大の減衰） |
| `early_ms` | f | ms | 10〜150 | 50（ここまでは直接音・初期反射として守る） |
| `time_smooth_ms` | f | ms | 0〜300 | 60 |
| `band_tilt` | f | dB/oct | −3〜3 | 0（高域ほど残響が短い補正） |
| `wpe_taps` | i | — | 4〜40 | 12（`wpe`：予測に使う過去フレーム数） |
| `wpe_delay` | i | フレーム | 1〜6 | 3 |
| `wpe_iter` | i | 回 | 1〜5 | 3（固定回数。収束判定で止めない） |
| `window` | e | — | 1024／2048 | 1024 |

- アルゴリズム：
  - `spectral`：後期残響のパワーを「`early_ms` 前の自分のパワー × 指数減衰（RT60 から）」と見積もり、T10-01 と同じゲイン則で引く。RT60 の自動推定は、音の切れ目の減衰曲線から（最尤法。区間の選び方を固定）
  - `wpe`：STFT 領域で、各周波数ごとに「遅れた過去フレームから現在を線形予測し、予測できた分（＝残響）を引く」。重みは出力のパワーで反復更新。線形・決定的。単チャンネルでは効きが弱いが、ステレオなら 2 チャンネルを使う
- 正典：Lebart, Boucher & Denbigh「A New Method Based on Spectral Subtraction for Speech Dereverberation」Acta Acustica 2001／Habets『Single- and Multi-Microphone Speech Dereverberation using Spectral Enhancement』（学位論文 2007）／Nakatani, Yoshioka, Kinoshita, Miyoshi & Juang「Speech Dereverberation Based on Variance-Normalized Delayed Linear Prediction」IEEE TASLP 2010（WPE）／Löllmann ほか「An Improved Algorithm for Blind Reverberation Time Estimation」IWAENC 2010。permissive の参考：nara_wpe（MIT と記憶。**調査レッグが確かめ、参考にしたら出典を記録**）。**Zynaptiq UNVEIL の方式は公開されていない。追わない**
- テスト（RP。RP4 は −40 dB に緩める）：(1) 乾いた合成素材（母音列、バースト列）に既知の RT60（0.5／1.0／2.0 s）の合成残響を掛けたもの：処理後の帯域別 RT60（T20）が 30 % 以上短くなる、直接音/残響比が 3 dB 以上上がる（`amount=1`。数値を記録） (2) 直接音の区間（発音後 `early_ms` まで）のレベル変化 ≤ 1 dB (3) RT60 の自動推定が真値 ±25 % (4) 乾いた素材：取り除いたエネルギー ≤ −40 dB (5) `wpe`：`wpe_iter` 固定で 2 回一致、行列が悪条件でも NaN なし（対角荷重を固定値で入れる）
- 弱点：音楽（持続音が重なる素材）では、残響と「長い音」を区別できず、音の尾を削る。**測定基準を満たしても聴感で使えない可能性が高い件**（PM_PLAN §9）
- 依存：BB-06、BB-20

### 実装時の確定（統括の判断 D-13・D-19）

`dereverb` は `implemented: false`。C9b の母音/雑音バースト・2方式・RT0.5/1/2秒の12条件でT20 30 %短縮とDRR +3 dBの同時合格は未達、乾いた打楽器のRP4も未達。合格数値は変更していない。音量の低下と残響時間の短縮を区別し、残響除去の一般的な効き目は主張しない。

## T10-10 スペクトルリペア

`spectral_repair`｜D＋B（PM 判断：カタログ「自動化部分は ML」。**自動検出は作らない。**場所は指揮者が指定し、埋め方は決定論）｜W3（GUI の領域選択は W4）｜M｜Codex

RP の `delta` に加えて（領域は配列。全部同じ長さ、最大 64 個）：

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `t0_s`・`t1_s` | a | s | 0〜36000（`t1`＞`t0`、長さ ≤ 2 s） | `[]`（空＝ビット一致の素通し） |
| `lo_hz`・`hi_hz` | a | Hz | 0〜24000（`hi`＞`lo`） | `[]` |
| `mode` | e | — | `attenuate`／`replace_time`／`replace_freq`／`pattern` | `replace_time` |
| `attenuate_db` | f | dB | 0〜60 | 12（`attenuate`：領域内を周囲の水準まで下げる上限） |
| `context_ms` | f | ms | 20〜2000 | 200（埋めるのに使う前後の長さ） |
| `feather_ms`・`feather_oct` | f | ms／oct | 0〜100／0〜0.5 | 10／0.05（領域の縁のぼかし） |
| `window` | e | — | 1024／2048／4096 | 2048 |

- `mode`：`attenuate`＝領域内の各ビンを、前後 `context_ms` の同じビンの中央値まで下げる（上げない）／`replace_time`＝前後の同じ帯域の振幅を時間方向に補間し、位相は前側から各ビンの瞬時周波数で進める（調波成分の欠けに向く）／`replace_freq`＝同じ時刻の上下の帯域から周波数方向に補間（広帯域の短い欠け・過渡に向く）／`pattern`＝前後 `context_ms` の中から、領域の縁と最も似た断片を探して写す（似ている度合いの尺度と探索順を固定）
- 表面：プロセッサ（領域は数値で書く）。GUI（W4）はスペクトログラム上の矩形選択→同じ配列を指揮書へ書き出すだけ（**GUI にしか無い操作を作らない**）。下見 `direction query spectrogram`（区間の時間−周波数のレベルを JSON で。T12-08 と共通）で、指揮者が数値で場所を決められる
- 正典：Godsill & Rayner 1998（欠落の補間）／Smaragdis, Raj & Shashanka「Missing Data Imputation for Time-Frequency Representations of Audio Signals」J. Signal Process. Syst. 2011（`pattern` の考え方）／Perraudin ほか「Inpainting of Long Audio Segments with Similarity Graphs」IEEE TASLP 2018
- テスト（RP2・6 に加えて）：(1) 空でビット一致 (2) 領域の外（縁のぼかしの外）のビンが不変：領域外に置いた正弦のレベル変化 ≤ 0.05 dB (3) 定常な調波音に 1 kHz・200 ms の妨害音を重ねたもの：`attenuate` で妨害が 20 dB 以上減り、同じ帯域の調波は ±2 dB (4) 調波音の帯域を 100 ms 消したもの：`replace_time` で、埋めた区間のスペクトルが元と ±3 dB、継ぎ目のクリックなし（広帯域エネルギーの突出 ≤ 3 dB） (5) 配列長の不一致・長さ超過は拒否
- 依存：BB-06、BB-21（位相の進め方）

### 実装時の確定（統括の判断 D-28）

領域選択GUIはOQ-3で保留。`spectral_repair` は矩形の時刻・周波数を数値指定する。GUIの有無は型の `implemented` と別に表示する。

## T10-11 スペクトルリカバリー

`hf_restore`｜B（PM 判断：カタログは学習系と書いていない。帯域複製の決定論で作る）｜W3｜M｜Codex

RP（`amount` 既定 0.7）に加えて：

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `cutoff_hz` | f | Hz | 0、または 2000〜20000 | 0（0＝自動：長時間平均スペクトルの崖〈1/3 oct で 20 dB 以上の落ち〉を探す） |
| `top_hz` | f | Hz | 4000〜22000 | 16000（どこまで作るか） |
| `source` | e | — | `copy_up`／`harmonic` | `copy_up`（`copy_up`＝崖の直下の帯域を上へ写す。`harmonic`＝崖の直下の帯域を非線形で倍音化） |
| `slope_db_oct` | f | dB/oct | −24〜0 | 0（0＝自動：崖より下 1 オクターブの傾きを延長） |
| `level_db` | f | dB | −12〜6 | 0（延長した傾きに対するずれ） |
| `noise_mix` | f | 0..1 | 0〜1 | 0.3（写した成分に、同じ包絡の雑音を混ぜる。調波が不自然に揃うのを避ける） |
| `transient_follow` | f | 0..1 | 0〜1 | 0.7（作った高域の時間包絡を、崖の直下の帯域の包絡に合わせる度合い） |
| `seed` | i | — | 0〜65535 | 0 |

- アルゴリズム：STFT → 崖の直下の帯域（幅＝`top_hz`−`cutoff_hz` を上限に、足りなければ繰り返し写す）を上へ平行移動 → 包絡を延長した傾きに整える → 時間包絡を元帯域に合わせる → 雑音を混ぜる → **`cutoff_hz` より下はビット一致**（作った高域を足すだけ。相補フィルタで下を触らない）
- 正典：Dietz, Liljeryd, Kjörling & Kunz「Spectral Band Replication, a Novel Approach in Audio Coding」AES Conv. 112（2002）／Larsen & Aarts『Audio Bandwidth Extension』（Wiley 2004。高域側の章）
- 記録：推定した崖の周波数と確からしさ（崖の深さ）。崖が見つからなければ何もしない（ビット一致）と記録
- テスト（RP に加えて）：(1) ピンクノイズ・合成のミックス相当素材を 8 kHz で急峻に切ったもの：崖の自動推定が ±5 %、処理後の 8〜16 kHz の 1/3 oct レベルが、切る前の元素材と ±4 dB（数値を記録） (2) `cutoff_hz` より下 1/3 oct 以下：入力と遅延補償後ヌル ≤ −100 dBFS (3) 切っていない素材：崖なし→ビット一致 (4) バースト列：作った高域の包絡のピークが元帯域のピークと ±3 ms (5) 同一 `seed` で一致
- 弱点：作った高域は**推定であって復元ではない**。元の高域にあった固有の成分（シンバルの個性など）は戻らない。記録にその旨を固定で書く
- 依存：BB-06、BB-13

## T10-12 ブレスコントロール

**mix 段の op `breath`（検出して、フェーダーの線を書く）＋下見コマンド `direction query breaths`**｜D（カタログ：「edit／gain の発展」）｜W4｜M｜Codex

op `breath` の `params`：

| id | 単位 | 範囲 | 省略時 |
|---|---|---|---|
| `reduce_db` | dB | 0〜24（範囲可） | 6（ブレス区間を下げる量） |
| `mode` | 列挙 | `reduce`／`target` | `reduce`（`target`＝各ブレスを `target_db` まで下げる。小さいブレスは触らない） |
| `target_db` | dB（そのトラックの活動レベル比） | −40〜−6 | −24 |
| `sensitivity` | 0..1 | 0〜1 | 0.5（検出の厳しさ。低い＝確かなものだけ） |
| `min_ms`・`max_ms` | ms | 50〜500／200〜2000 | 120／900 |
| `fade_ms` | ms | 5〜100 | 25 |
| `only`・`skip` | 時刻の配列（`query breaths` の ID） | 最大 256 | 空（検出結果のうち一部だけに掛ける／外す） |

- `target` はトラック ID。`section` を書ける。同じトラックの `duck`／`gain`／`gain_curve`／`ride` とは既存の規則で 1 本に合成（T01-11 と同じ）
- 検出（決定論。BB-12・BB-22）：区間の候補＝有声でない・レベルが活動レベルより 8〜40 dB 下・長さが `min_ms`〜`max_ms`・前後どちらかが発声。特徴＝スペクトルの平坦さ、1〜6 kHz の比率、ゼロ交差率、包絡の形（なだらかな山）。固定の重みの線形判別（**重みは合成データと自前の録音から調査レッグが決め、定数として持つ。学習モデルは持たない**）。各候補に当てになり度
- `direction query breaths`：検出結果の一覧（ID＝`b_<開始サンプル>`、時刻、長さ、レベル、当てになり度）。読み取り専用
- 正典：Ruinskiy & Lavner「An Effective Algorithm for Automatic Detection and Exact Demarcation of Breath Sounds in Speech and Song Signals」IEEE TASLP 2007（特徴の選び方。同論文の型紙照合は使わず、特徴だけ）
- テスト：(1) 合成（母音区間の間に、帯域雑音で作った擬似ブレス 20 個と、摩擦音相当の短い雑音 20 個）：ブレスの検出 ≥ 85 %、摩擦音の誤検出 ≤ 10 % (2) 書かれた線が区間内で −`reduce_db`、縁が `fade_ms`、区間外 0 (3) `only`／`skip` が効く (4) `breath` を含まない指揮書はバイト同一 (5) 点列が再現一致 (6) `query` が読み取り専用、CLI と MCP の等価性
- 弱点：合成の擬似ブレスでしか検出率を測れない（実録音の正解データを同梱しない）。当てになり度を必ず出し、低いものは既定で触らない
- 依存：BB-03、BB-12、BB-14、BB-22

## T10-13 デプロッシブ

`deplosive`｜A｜W2｜S｜Codex｜`offline_only: True`

RP（`amount` 既定 1）に加えて：`freq_hz`（f、60〜300、既定 150：これより下を抑える）、`threshold_db`（f、0〜24、既定 8：低域/中域のエネルギー比が、そのトラックの中央値をこれだけ超えたら事象）、`max_reduce_db`（f、3〜36、18）、`min_ms`・`max_ms`（f、5〜50／30〜300、既定 10／150）、`lookahead_ms`（f、0〜20、5）、`release_ms`（f、10〜300、60）。

- アルゴリズム：検出＝`freq_hz` 以下の帯域エネルギーの急な立ち上がり（発音点検出 BB-22 を低域だけで）かつ低域/中域比の突出。作用＝事象の間だけ、`freq_hz` の動的ハイパス（`dynamic_eq` と同じ y＝x＋(g−1)·B(x) の構造で、B を低域に）。事象の外はビット一致
- 正典：Giannoulis ほか 2012（検出器）／既存 `dynamic_eq`
- テスト（RP に加えて）：(1) 合成母音に、40〜120 Hz・60 ms の減衰バーストを 30 個重ねたもの：検出 ≥ 90 %、バーストの低域エネルギーが 10 dB 以上減る、同時刻の 300 Hz 以上の変化 ≤ 0.5 dB (2) ベース音（80 Hz の持続音）：検出 0 件（持続する低域は破裂音でない）、ビット一致 (3) 事象の外がビット一致
- 依存：BB-03、BB-22

## T10-14 デブリード

**編集段の op `edit_debleed`（派生クリップ）**｜B｜W3｜M｜Codex
2 本以上の音が要る（かぶりの元のトラック）ので op（spec/08 §0.1）。

| id | 単位 | 範囲 | 省略時 |
|---|---|---|---|
| `sources` | トラック ID の配列 | 1〜8 個、`target` と別 | （必須：かぶりの元） |
| `reduction_db` | dB | 0〜30 | 9 |
| `max_delay_ms` | ms | 0〜50 | 20（かぶりの到達遅れの探索幅） |
| `time_smooth_ms` | ms | 0〜300 | 50 |
| `protect` | 0..1 | 0〜1 | 0.6（`target` 自身が鳴っている帯域・時刻を守る度合い） |
| `section` | — | — | クリップ全体 |

- アルゴリズム：(1) 元ごとに、`target` との相互相関で到達遅れを推定（BB-17）、揃える (2) 元→`target` への漏れの伝達（周波数別の利得）を、**`target` 自身が鳴っていない区間**（`target` のレベルが低く、元のレベルが高いフレーム）から推定 (3) フレームごとに、かぶりのパワー推定＝Σ 伝達×元のパワー (4) T10-01 と同じゲイン則で引く（ウィーナー）。位相を使った引き算（適応フィルタ）はしない：部屋の応答の時間変化に弱いため
- 正典：Kokkinis, Reiss & Mourjopoulos「A Wiener Filter Approach to Microphone Leakage Reduction in Close-Microphone Applications」IEEE TASLP 2012（**これが正**）／Clifford & Reiss「Microphone Interference Reduction in Live Sound」DAFx-11
- 記録：元ごとの遅れ・漏れの水準（dB）・推定に使えたフレーム数（少なければ当てになり度 `low`）
- テスト：(1) 合成の 2 音源（別々の調波列）を、互いに −12 dB・遅れ 3 ms・軽い色づけで漏らした 2 トラック：`target` 中の元の成分が 8 dB 以上減り、`target` 自身の成分の変化 ≤ 1.5 dB (2) 遅れの推定 ±0.1 ms (3) かぶりの無い組：取り除いたエネルギー ≤ −45 dB (4) 派生の再現一致 (5) 含まない指揮書はバイト同一 (6) `sources` に `target` 自身・存在しない ID は拒否
- 依存：BB-06、BB-17、BB-18、BB-20

## T10-15 衣擦れ／風ノイズ除去

**`dewind`（決定論の型）＋衣擦れは T10-02 の学習モデル経路（モデルが見つかるまで未実装）**｜C（衣擦れ側。風は B）｜W3（`dewind`）／W5（衣擦れ）｜M｜Codex
カタログ：「映像・フィールド録音系」。音楽制作での優先度は最下位。

`dewind`：RP（`amount` 既定 1）に加えて `max_hz`（f、80〜1000、既定 300：風の成分が及ぶ上限の探索幅）、`threshold_db`（f、0〜24、6）、`max_reduce_db`（f、3〜40、24）、`release_ms`（f、20〜1000、150）、`use_coherence`（b、true：ステレオのとき、左右の無相関な低域を風とみなす）。

- アルゴリズム：風は低域に偏った、時間的に乱れた、**2 本のマイク間で無相関**な雑音。フレームごとに、低域の左右コヒーレンスが低く・スペクトルの傾きが急（−10 dB/oct 以上）な帯域を風とし、その上限周波数を追う可変ハイパス＋帯域別ゲイン。モノではコヒーレンスを使えないので、傾きと時間的な乱れ（低域の変調スペクトル）だけで判定（当てになり度 `low` と記録）
- 正典：Nelke & Vary「Dual Microphone Wind Noise Reduction by Exploiting the Complex Coherence」ITG Speech Communication 2014／Nelke, Chatlani, Beaugeant & Vary「Single Microphone Wind Noise PSD Estimation Using Signal Centroids」ICASSP 2014
- テスト（RP に加えて）：合成（無相関の低域雑音を乱れた包絡で変調したもの＋合成母音）：風区間の 300 Hz 以下が 12 dB 以上減り、300 Hz 以上は ±1 dB／相関した低域（ベース音）は検出 0 件

衣擦れ：決定論の方式を PM は知らない（広帯域・非定常・過渡的で、統計的推定の前提に合わない）。**調査レッグが、再配布可能な重みを持つ OSS モデルを探す。見つからなければ本件の衣擦れ側は `implemented: False` のまま据え置き**、指揮書の `tool_requests` の受け口だけ残す。見つかれば `denoise_ml` の `model` の 1 エントリとして登録（新しい型は作らない）。
- 依存：BB-06、BB-20、（BB-16）

## T10-16 ギター専用ノイズ除去

`guitar_denoise`｜A｜W3（部品の後）｜S｜Codex｜**コンポジット**

展開：`dehum` → `denoise`（`profile=auto`）→ `gate`（T01-07。アンプの残留雑音）→ `resonance_suppressor`（T02-03。フィンガーノイズ〈弦の擦れ〉の帯域 2〜8 kHz に限定）→ `transient_shaper`（T01-04。ピッキングのアタックを下げる）。各段は量 0 で展開から外す。

| id | 型 | 範囲 | 既定 | 展開先 |
|---|---|---|---|---|
| `hum` | f | 0〜1 | 0.5 | `dehum.depth_db`＝60·h、`harmonics`＝16 |
| `hum_hz` | f | 0、40〜70 | 0 | `dehum.base_hz` |
| `amp_noise` | f | 0〜1 | 0.3 | `denoise.reduction_db`＝30·a、`gate.range_db`＝−30·a |
| `gate_threshold_db` | f | −80〜0 | −55 | `gate.threshold_db` |
| `squeak` | f | 0〜1 | 0 | `resonance_suppressor` の量（`lo_hz=2000, hi_hz=8000`） |
| `pick` | f | 0〜1 | 0 | `transient_shaper.attack_db`＝−9·p |

- テスト：T07-04 と同じ 4 項目（展開の一致、記録、全 0 で素通し、範囲検査）
- 依存：BB-00、T01-04、T01-07、T02-03、T10-01、T10-08

### 実装時の確定（統括の判断 D-23）

`hum` の許容集合は `[0,1]` → `{0} ∪ [0.05,1]`、既定0.5は維持。宣言min/maxは0/1を残し、交差検査で `(0,0.05)` を拒否する。指定の子展開 `depth_db=60*hum` と `dehum` の下限3 dBから必要な条件であり、0.05は正確に3 dB、直前のfloat64は拒否を実測した（C8c）。clampや展開式の置換はしない。

## T10-17 ワウフラッター／アジマス補正

**2 つの型：`dewow`（速度の揺れを戻す）と `azimuth_fix`（左右の時間ずれを戻す）**｜B｜W3｜L（`dewow` が L・調査レッグが先。`azimuth_fix` は S）｜Codex｜マスターには置かない（マスター済み素材の修復は、トラックとして取り込んで行う）

`dewow`：RP（`amount` 既定 1）に加えて

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `reference` | e | — | `partials`／`pilot` | `partials`（`pilot`＝既知の定常音〈ハム、バイアス漏れ、パイロット信号〉を基準にする） |
| `pilot_hz` | f | Hz | 0、または 20〜24000 | 0（`pilot` のとき必須） |
| `max_dev` | f | % | 0.05〜5 | 1（追う揺れの最大幅） |
| `min_rate_hz`・`max_rate_hz` | f | Hz | 0.05〜2／1〜50 | 0.2／12（戻す揺れの速さの範囲。これより遅い＝演奏のテンポ・音程と区別できないので触らない） |
| `curve` | c | x：秒／y：速度偏差（%） | 最大 65536 点 | `[]`（書けば推定をせず、この曲線の逆を当てる。推定結果を書き出して手で直す用） |

- アルゴリズム：(1) 多数の正弦成分の瞬時周波数を追う (2) 全成分に**共通な**相対偏差（どの成分も同じ比率で同時に動く分）を、頑健な平均（中央値）で取り出す。楽器のビブラートは成分ごと・音ごとに違うので共通成分にならない、という前提 (3) 帯域制限（`min_rate`〜`max_rate`）(4) 逆の速度曲線で可変リサンプル（既存 `resample` の核を可変比で。T08-12 `edit_varispeed` と同じ）。尺は変えない（平均速度 1 に正規化）
- 正典：Czyżewski, Ciarkowski, Kostek, Kotus & Maziewski「DSP Techniques for Determining "Wow" Distortion」JAES 2007／Godsill & Rayner 1998（ワウの章）／IEC 60386（測定）
- 記録：推定した偏差曲線の統計（IEC 60386 の重み付き値、処理前後）、推定に使えた成分の数、**推定した曲線そのもの**（`curve` に貼れる形で）
- テスト：(1) 調波音の列（合成の旋律、ビブラートなし）に既知の揺れ（0.5 Hz・0.5 %、8 Hz・0.1 %）を掛けたもの：推定した曲線と真の曲線の相関 ≥ 0.9、処理後の重み付きワウ・フラッタ値が 1/3 以下 (2) 揺れの無い素材：推定の偏差 ≤ 0.02 %（→ 触らない閾値を置き、ビット一致） (3) 1 音だけに 6 Hz のビブラートがある和音：その音のビブラートが 80 % 以上残る（共通成分でないので取らない） (4) 尺がサンプル単位で不変 (5) `curve` 指定：T06-12 `wow_flutter` を同じ曲線で掛けたものが、遅延補償後ヌル ≤ −60 dBFS で元に戻る（往復試験）

`azimuth_fix`：`mode`（e、`auto`／`manual`、`auto`）、`delay_us`（f、−500〜500 µs、0：`manual`。正＝右を遅らせる）、`band_lo_hz`（f、1000〜8000、3000：推定に使う帯域の下端。ずれは高域で効く）、`track_s`（f、0〜60、0：>0 でゆっくり変わるずれを追う窓）、`max_us`（f、10〜500、200）。

- アルゴリズム：高域の左右の相互相関（GCC-PHAT、放物線補間でサンプル以下）→ 分数遅延で片側を合わせる（遅らせる側だけ。固定の基準遅延をレイテンシとして宣言）
- 正典：Knapp & Carter「The Generalized Correlation Method for Estimation of Time Delay」IEEE Trans. ASSP 1976
- テスト：左右同一の広帯域信号の片側を 37 µs 遅らせたもの：推定 ±2 µs、処理後のモノ合算の 10 kHz の損失が 0.1 dB 以下に戻る／もともと広がりのある素材（無相関成分が多い）：確からしさが低いと記録し、触らない／モノは拒否
- 依存：BB-06、BB-09、BB-17、T06-12（試験の往復）

## T10-18 ルームトーン／アンビエンスマッチング

**下見コマンド `direction suggest ambience`（測る）＋既存の新型 `noise_bed`（T09-09。当てる）**｜D｜W4｜S｜Codex

- 引数：`--project`、`--target trk_<stem>`、`--region t0,t1`（**必須**：環境音だけが鳴っている区間。自動では探さない。`--find-quiet` を付けると、レベルの低い区間の候補を一覧するだけ）、`--points`（8〜64、既定 32）、`--smooth-oct`（既定 1/3）
- アルゴリズム：区間の長時間平均スペクトル（ウェルチ法）→ 平滑 → 点列。左右の相関も測る
- 出力（JSON）：スペクトル曲線、レベル（dBFS）、左右相関、貼れる `chain_add`（`noise_bed`：`spectrum`＝曲線、`hiss_db`＝測ったレベル、`width`＝1−相関、`seed`）。**区間の音そのものは保存しない**（測った値だけ。T02-08 と同じ）。無音で空いた編集点を埋める用途には、`noise_bed` を別トラックに置いて `gain_curve` で区間を切る、という使い方を docs に書く
- テスト：(1) 読み取り専用・再現一致 (2) 既知のスペクトルの定常雑音を測り、出力の `noise_bed` で作った雑音の 1/3 oct スペクトルが元と ±1.5 dB、レベル ±0.5 dB (3) 区間に発声が混じる（レベルの変動が大きい）と当てになり度 `low` (4) CLI と MCP の等価性
- 依存：T09-09、T02-08 のスペクトル測定

## T10-19 ギャップ補間

`interpolate`｜B｜W3｜S（T10-04・T10-10 の後。同じ核の窓口）｜Codex

RP の `delta` に加えて：`t0_s`・`t1_s`（a、最大 64 組、各長さ ≤ 500 ms。空＝ビット一致）、`method`（e、`auto`／`ar`／`spectral`、既定 `auto`：長さ ≤ 30 ms は `ar`、それより長ければ `spectral`）、`ar_order`（i、16〜512、既定 128）、`context_ms`（f、20〜2000、300）、`fade_ms`（f、0〜20、2）。

- アルゴリズム：`ar`＝前後の文脈から AR 係数を推定し、LSAR で埋める（T10-04 と同じ。前向き予測と後ろ向き予測を交差で混ぜる版）。`spectral`＝T10-10 の `replace_time`（全帯域）
- 正典：Janssen ほか 1986／Godsill & Rayner 1998／Etter「Restoration of a Discrete-Time Signal Segment by Interpolation Based on the Left-Sided and Right-Sided Autoregressive Parameters」IEEE Trans. SP 1996
- テスト：(1) 空でビット一致、区間外がビット一致 (2) 調波音（合成母音、正弦の和）に 5／20／100 ms の欠落（0 埋め）：埋めた区間の SDR ≥ 20／12／6 dB（数値を記録） (3) 継ぎ目のクリックなし（区間の端の広帯域エネルギー突出 ≤ 3 dB） (4) 白色雑音の欠落：埋めた区間の RMS が前後の ±3 dB（雑音は形を当てられないが、穴にならない） (5) 500 ms 超は拒否
- 依存：BB-06、BB-21

---

## 実装単位

| 単位 | 中身 | 前提 | 量 | 実働 |
|---|---|---|---|---|
| U-10a | `dehum`、`deplosive` | BB-03、BB-22 | S＋S | Codex |
| U-10b | BB-21（AR 補間）と `declick`（3 つの `kind`）、`interpolate`（`ar`） | BB-12、BB-22 | S＋M＋S＋S＋S | Codex |
| U-10c | `declip` | U-10b | M | Codex |
| U-10d | BB-20（雑音推定・ゲイン則）と `denoise` | BB-06 | M＋M | Codex |
| U-10e | `spectral_repair`、`interpolate`（`spectral`）、`hf_restore`、`dewind` | BB-06、U-10d | M＋M＋M | Codex |
| U-10f | `dereverb` | 調査レッグ、U-10d | L | Opus 中 |
| U-10g | op `edit_debleed` | U-10d、BB-17、BB-18 | M | Codex |
| U-10h | `dewow`、`azimuth_fix` | 調査レッグ（`dewow`）、BB-17、U-06b | L＋S | Codex |
| U-10i | `guitar_denoise` | U-10a、U-10d、U-01a、U-02c | S | Codex |
| U-10j | op `breath`、`direction query breaths`、`direction suggest ambience`、GUI の領域選択 | BB-14、BB-22、U-09d | M＋S | Codex |
| U-10k | `denoise_ml`、op `edit_isolate`、衣擦れのモデル探索 | 調査レッグ（ライセンス）、BB-16、BB-18 | M＋M | Codex |
### 実装時の確定（統括の判断 D-13）

W3c の実測較正で `interpolate.ar_order` の既定を128→512に変更した。範囲16〜512は不変。16 kHz・F0 100 Hzの母音の周期は160サンプルで、旧128の5/20/100 ms欠損のSDRは4.99930220783021/5.048882518744012/4.5300662643332466 dB。雑音文脈では観測残差を再生しRMSを合わせるが、元雑音の波形復元は主張しない。最終形はW3jのspectral経路も含む。
