# spec/05 空間／ステレオ（7 件）

カタログ §5。共通規約は `spec/01_dynamics.md` §0。既存 `pan`・`stereo` は変えない。タグは 2 代目 PM が付けた（カタログの行にタグが無い。WORKLOG §0）。

## 0. カテゴリ共通

- 特記の無い型：`stages: ["track","bus"]`、`master_slot: None`。`channel` 欄は不可（左右の関係そのものを変える型のため。`ms_gain` も不可）
- モノ入力はステレオ出力になる（`haas`・`binaural_pan`・`autopan`・`doppler`・`band_pan`）
- パン則は既存 `pan` と同じ等パワー則（中央 −3 dB）。別の則は持たない
- 実測ベクトルの記録（R-10。既存 `delay`・`stereo` と同じ項目）：モノ合算損失（広帯域と 1/3 oct の最悪帯）、左右相関、左右のレベル差。**どの型も合否は作らない**（記録だけ）

**共通テスト（ST）**：(ST1) 中立設定でビット一致（各件に定義） (ST2) モノ合算損失の実測が記録の値と一致（±0.1 dB） (ST3) 左右入れ替え対称：入力の L/R を入れ替え、左右対称なパラメータも入れ替えると、出力が入れ替わる（ビット一致）

---

## T05-01 Haas ワイドナー

`haas`｜A｜W1｜S｜Codex

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `delay_ms` | f | ms | 0〜40 | 12（0＝ビット一致の素通し） |
| `side` | e | — | `left`／`right` | `right`（遅らせる側） |
| `delayed_db` | f | dB | −12〜6 | 0（遅らせた側のレベル） |
| `delayed_highcut_hz` | f | Hz | 0〜20000 | 0（0＝無効。遅らせた側だけ、6 dB/oct） |
| `lo_keep_hz` | f | Hz | 0〜500 | 120（これより下は遅らせない。低域のモノ互換。0＝無効） |
| `input` | e | — | `mono_sum`／`stereo` | `mono_sum` |

- アルゴリズム：整数サンプル遅延（既存 `delay` の核を複製）。`lo_keep_hz>0` のとき、相補リニアフェイズ分割（BB-02a）で低域を両チャンネル同時刻のまま通し、高域だけ片側を遅らせる（分割のレイテンシは宣言・補償）
- 正典：Haas「The Influence of a Single Echo on the Audibility of Speech」JAES 1972（独語原著 1951 の英訳）／Litovsky ほか「The precedence effect」JASA 1999（総説。融合の上限とエコー知覚域）
- 記録：遅延がハース領域（1〜35 ms）の内か外か、モノ合算の櫛（最初のノッチ周波数＝1000/(2·`delay_ms`) Hz）を明記
- テスト（ST に加えて）：(1) `delay_ms=0` でビット一致 (2) インパルス：遅らせた側の遅延が設定 ±0.5 サンプル、レベルが `delayed_db` ±0.05 dB (3) `lo_keep_hz=120`：60 Hz 正弦の左右位相差 ≤ 1°、モノ合算損失 ≤ 0.1 dB (4) モノ合算の最初のノッチ周波数が理論値 ±2 %（`lo_keep_hz=0`） (5) CT-5
- 依存：BB-02、BB-09

## T05-02 バイノーラル／3D パンナー

`binaural_pan`｜B｜W3｜L（調査レッグが先）｜Codex｜TV（曲線を書いたとき）

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `hrtf` | as | `hrtfs` レジストリ（BB-24） | 登録済み ID | `model_sphere`（同梱の構造モデル。測定資産なし） |
| `azimuth_deg` | f | 度 | −180〜180 | 0（正＝右） |
| `elevation_deg` | f | 度 | −90〜90 | 0 |
| `distance_m` | f | m | 0.2〜50 | 1.5 |
| `path` | c | x：曲頭からの秒／y：方位（度） | 最大 4096 点 | `[]`（空＝`azimuth_deg` 固定） |
| `elevation_path` | c | x：秒／y：仰角（度） | 最大 4096 点 | `[]` |
| `distance_gain` | b | — | — | false（true＝1/r の減衰と空気吸収。基準 1.5 m） |
| `room` | f | 0..1 | 0〜1 | 0（頭外定位の補助。内部の固定初期反射 6 本を足す量。別型の残響は呼ばない） |
| `input` | e | — | `mono_sum`／`stereo` | `mono_sum`（`stereo`＝L/R を方位 ±`spread_deg` の 2 音源に） |
| `spread_deg` | f | 度 | 0〜90 | 30 |
| `lo_bypass_hz` | f | Hz | 0〜300 | 0（これより下は HRTF を通さず中央へ。0＝無効） |

- アルゴリズム：
  - `model_sphere`：剛球頭の構造モデル。ITD は Woodworth の式、頭の影は 1 極 1 零の方位依存フィルタ、耳介は方位・仰角依存の少数の反射（遅延＋ゲイン）。資産不要で完全に決定的
  - 測定 HRTF：HRIR を最小位相成分＋ITD（純遅延）に分け、最小位相成分を周囲 3〜4 点で補間（球面上の重み）、ITD は別に補間して分数遅延で当てる。動く音源は 64 サンプルごとに係数を更新し、区間内を交差フェード（クリック防止）
  - 資産の形：レジストリには SOFA（AES69）から変換した配列（`.npz`：方位・仰角・HRIR・sr）を登録。SOFA の読み込みは登録用スクリプトの中だけ（h5py は BSD。本体の依存に足さない）
- **資産の規律（BB-24。BB-08 と同じ）**：同梱は `model_sphere` だけ。測定 HRTF は持ち込み（`byo`）が既定。公開データセットの同梱は PM_PLAN OD-9
- 正典：Brown & Duda「A Structural Model for Binaural Sound Synthesis」IEEE Trans. SAP 1998（`model_sphere` の正）／Kistler & Wightman「A model of head-related transfer functions based on principal components analysis and minimum-phase reconstruction」JASA 1992（最小位相＋ITD）／AES69-2015（SOFA）／Xie『Head-Related Transfer Function and Virtual Auditory Display』。調査レッグ：公開 HRTF セット（MIT KEMAR、CIPIC、SADIE II、HUTUBS）のライセンスを一次で確認して `hrtfs.json` の `license` 欄の書き方を決める
- 決定論：係数更新の格子は曲頭からの絶対サンプル位置（64 の倍数）。補間の近傍探索は同距離のとき ID の小さい順
- テスト（ST1：`azimuth=0, elevation=0, room=0` は左右同一。ビット一致は要求しない、に加えて）：(1) `model_sphere`：方位 90° の ITD が 0.6〜0.75 ms、1 kHz 以上の ILD が 5 dB 以上、方位 0° で ITD 0・ILD 0 (2) 方位 +θ と −θ で左右が入れ替わる（ビット一致） (3) 測定 HRTF（試験用の合成セット）：格子点上の方位で、出力が該当 HRIR の畳み込みとヌル ≤ −100 dBFS (4) 動く音源：定常正弦で、係数更新周期（64 サンプル）に同期した側帯が −70 dB 以下 (5) `path` を途中から描画しても全長描画の該当部分と一致 (6) 未登録 ID・sha256 不一致は明示エラー (7) モノ合算損失を記録（バイノーラルはモノ互換が悪い。記録に固定の注記を付ける）
- 弱点：ヘッドホン専用。スピーカー再生では意図どおりに聞こえない。個人差（他人の耳）で前後・上下の定位は当てにならない。**聴感の主張は一切しない**
- 依存：BB-00（asset、curve）、BB-05、BB-07、BB-09、BB-24

## T05-03 オートパン

`autopan`｜A｜W2｜S｜Codex｜TV

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `source` | e | — | `lfo`／`shape`／`envelope` | `lfo` |
| `depth` | f | 0..1 | 0〜1 | 0.5（振れ幅。1＝端から端。0＝ビット一致の素通し） |
| `center` | f | −1..1 | −1〜1 | 0 |
| `rate_hz` | f | Hz | 0.01〜20 | 1（`note=none` のとき） |
| `note`・`bpm` | e・f | — | `NOTE_VALUES`／0〜400 | `none`／0 |
| `lfo_shape` | e | — | `sine`／`triangle`／`square`／`random` | `sine`（`random`＝シード付きの滑らかなランダムウォーク） |
| `shape` | c | x：周期内位相 0〜1／y：−1〜1 | 最大 64 点 | `[[0,-1],[0.5,1],[1,-1]]`（`source=shape`） |
| `origin_s`・`phase` | f | s／0..1 | T01-09 と同じ | 0／0 |
| `env_attack_ms`・`env_release_ms` | f | ms | 1〜500／10〜3000 | 20／300（`source=envelope`：レベルが上がるほど `center`＋`depth` 側へ） |
| `env_threshold_db` | f | dBFS | −80〜0 | −40 |
| `smooth_ms` | f | ms | 0〜50 | 5 |
| `seed` | i | — | 0〜65535 | 0 |

- アルゴリズム：パン位置 p(t)＝clip(`center`＋`depth`·m(t), −1, 1)。m は LFO・描画形・包絡のどれか。モノ入力は等パワー則、ステレオ入力はバランス（既存 `pan` と同じ扱い）。位相は絶対サンプル位置から（T01-09 と同じ）
- 正典：Dattorro 1997 Part 2（LFO）／既存 `pan`（パン則の正）
- テスト（ST に加えて）：(1) `depth=0` で既存 `pan`（`center` 位置）とビット一致 (2) モノの定常正弦：左右のレベルが p(t) のパン則どおり（±0.1 dB）、L²＋R² が一定（±0.05 dB） (3) 周期の実測が音価どおり、1000 周期後もずれ ±1 サンプル (4) `envelope`：バースト入力でパン位置が包絡に追従、時定数 ±10 % (5) 途中からの描画が一致 (6) 同一 `seed` でビット一致
- 依存：BB-00、BB-03、BB-05

### 実装時の確定（統括の判断 D-16）

depth0の既存panとのビット一致を優先し、ST3の鏡像対称はヌル ≤−240 dBFSで判定する。C4 の元反例は −325.1123953170997 dBFS、44.1/48/96 kHz・17位置の最悪は −313.07119549054045 dBFS。動的形状の鏡像と既存pan互換の試験は維持し、公開値は変更していない。

## T05-04 Doppler

`doppler`｜A｜W2｜M｜Codex｜TV

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `start_s`・`end_s` | f | s | 0〜36000（`end`＞`start`） | 0／4（通過の区間。外側は端点の位置で静止） |
| `x0_m`・`x1_m` | f | m | −500〜500 | −30／30（聴取者を原点に、左右方向の始点・終点） |
| `y_m` | f | m | 0.5〜200 | 5（最接近距離。前方） |
| `path` | c | x：区間内位置 0〜1／y：軌道上の位置 0〜1 | 最大 64 点、単調非減少 | `[[0,0],[1,1]]`（等速。曲げて加減速） |
| `speed_of_sound` | f | m/s | 300〜360 | 343 |
| `gain_ref_m` | f | m | 0.5〜50 | 5（この距離で 0 dB。1/r 則） |
| `max_gain_db` | f | dB | 0〜12 | 0（近距離の持ち上げ上限） |
| `air` | f | 0..1 | 0〜1 | 0.5（距離に比例する高域減衰の量） |
| `pan_amount` | f | 0..1 | 0〜1 | 1 |
| `pitch_amount` | f | 0..1 | 0〜1 | 1（0＝遅延を固定し音程を変えない） |
| `mix` | f | 0..1 | 0〜1 | 1 |

- アルゴリズム：音源位置 (x(t), y) → 距離 r(t) → 伝搬遅延 r/c を分数遅延線の読み出し位置として使う（音程変化は遅延の時間変化から自然に出る。別にピッチシフタを通さない）。ゲイン＝`gain_ref_m`/r（上限つき）。パン＝atan2(x, y) を等パワー則へ。空気吸収は距離に比例してカットオフが下がる 1 次ローパス。レイテンシ＝最小距離の伝搬遅延を差し引いて 0 に正規化
- 正典：Smith, Serafin, Abel & Berners「Doppler Simulation and the Leslie」DAFx-02（遅延線によるドップラー）／ISO 9613-1（空気吸収。簡略化して使う）／J. O. Smith『Physical Audio Signal Processing』
- テスト（ST に加えて）：(1) `pitch_amount=0, air=0, pan_amount=0`、`x0=x1`：ゲインだけの静止音源（定数ゲイン） (2) 等速通過・1 kHz 正弦：接近時と離反時の瞬時周波数が理論値 f·c/(c∓v_r) に ±0.5 % (3) 最接近時刻のレベルが最大、レベル曲線が 1/r ±0.3 dB (4) パン位置が幾何どおり（±0.02） (5) 超音速になる設定（|dr/dt| ≥ 0.9c）は `check_runtime` で拒否 (6) 途中からの描画が一致
- 依存：BB-00、BB-05、BB-09

## T05-05 周波数別ステレオ配置

`band_pan`｜A｜W1｜S｜Codex

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| MB ブロック（spec/01 §0.6） | | | | 既定 `phase` は `linear`、`crossovers_hz` 既定 `[200, 2000]` |
| `pan` | a | −1..1 | −1〜1 | `[]`→ 0（帯域ごとのバランス） |
| `width` | a | 倍 | 0〜2 | `[]`→ 1（帯域ごとのサイド量。既存 `stereo` と同じ意味） |
| `level_db` | a | dB | −12〜12 | `[]`→ 0 |
| `lo_protect_hz` | f | Hz | 0〜300 | 120（これより下の帯域は `pan`・`width` を無視して中央・幅 1。0＝無効） |

- アルゴリズム：帯域分割 → 帯域ごとに M/S の S へ `width`、L/R へバランス則（ステレオ素材なので等パワーのパンではなくバランス：片側を下げるだけ。中央 0 dB）→ 加算。既存 `stereo`（帯域別の幅）との違いは「帯域を左右へ寄せる」こと
- 正典：既存 `stereo`（分割と M/S）／Blumlein 1931 の英国特許 394,325（M/S・シャッフリングの原典。原理だけ）
- テスト（ST に加えて）：(1) 中立（全帯域 `pan=0, width=1, level=0`）：`linear` は遅延補償後ヌル ≤ −120 dBFS (2) 1 帯域だけ `pan=+1`：その帯域中心の正弦は左が −120 dBFS 以下、他帯域中心の正弦の左右差 ≤ 0.1 dB (3) `width=0` の帯域：左右同一（差 ≤ −120 dBFS） (4) `lo_protect_hz`：それ以下の帯域に `pan=1` を書いても変化なし（記録に「無視した」と残る） (5) モノ入力は拒否（`ParamError`）
- 依存：BB-02

## T05-06 M/S プロセッシング基盤

**新しい仕組みは作らない。チェーン項目の `channel` 欄（BB-04、spec/02 T02-02）が「各 ch への処理差し込みの土台」。足すのは小さな型 1 つ：`ms_gain`**｜A｜W1｜S｜Codex｜`stages: ["track","bus","master"]`、`master_slot` は既存 `stereo` と同じ番号（実働が `processors.py` で確かめて写す。PM は番号を確かめていない）

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `mid_db` | f | dB | −24〜12 | 0 |
| `side_db` | f | dB | −24〜12 | 0 |
| `mid_mute`・`side_mute` | b | — | — | false（聴き分け用。指揮の下見でミッドだけ／サイドだけを聴く） |
| `swap` | b | — | — | false（L/R を入れ替える） |
| `mode` | e | — | `process`／`encode`／`decode` | `process`（`encode`＝L/R→M/S を出力に残す。`decode`＝その逆。M/S 収録素材の受け入れ用） |

- アルゴリズム：M＝(L＋R)/2、S＝(L−R)/2。`process` は符号化→ゲイン→復号。全パラメータ既定のときは経路を通さない
- テスト：(1) 既定でビット一致 (2) `encode`→`decode` の往復が入力とビット一致（float64 で厳密に戻る式の順序を固定） (3) `side_mute`：出力の左右が同一／`mid_mute`：左右が逆相で同振幅 (4) `side_db`：既存 `stereo` の全帯域 `width`＝10^(side_db/20) とヌル ≤ −120 dBFS (5) モノ入力は拒否
- 依存：BB-04（同じ符号化の式を共有）

### 実装時の確定（統括の判断 D-9）

`channel` の処理差し込みと `ms_gain` の真偽を区別する。任意float64の符号化→復号のビット一致は丸めにより未達で、`ms_gain` は `implemented: false`。ヌルの許容値へ読み替える判断はまだ適用しない。

## T05-07 アンビソニックス処理

**コマンド `spatial ambi …`（CLI／MCP。ファイル間の変換。ミックスのグラフには入れない）**｜D｜W4｜M｜Codex
エンジンはモノ／ステレオ。多チャンネルのバスをグラフに通すのは不変領域に触れるので既定では行わない（PM_PLAN OD-10）。カタログも「用途は特殊」。

| サブコマンド | 引数 | 中身 |
|---|---|---|
| `encode` | `--in`（モノ／ステレオ）、`--azimuth`・`--elevation`（度）、`--order` 1〜3（既定 1）、`--out` | 点音源を AmbiX（ACN 順・SN3D）へ |
| `rotate` | `--in`（AmbiX）、`--yaw`・`--pitch`・`--roll`（度）、`--out` | 音場の回転 |
| `decode` | `--in`、`--to stereo`（仮想カーディオイド対、`--angle` 既定 ±90°）／`--to binaural`（`--hrtf` ID。T05-02 の資産） 、`--out` | ステレオかバイノーラルへ |
| `convert` | `--in`、`--from fuma\|ambix`、`--to …`、`--out` | 1 次の FuMa⇔AmbiX |
| `info` | `--in` | 次数・チャンネル数・正規化の推定、各成分のレベル |

- アルゴリズム：実球面調和関数（ACN／SN3D）。回転は球面調和の回転行列（1 次は 3×3、高次は漸化式）。バイノーラル復号は仮想スピーカー法（正多面体配置の各方向を T05-02 の HRIR で畳む）
- 正典：Zotter & Frank『Ambisonics』（Springer 2019、オープンアクセス）／Nachbar, Zotter, Deleflie & Sontacchi「AmbiX — A Suggested Ambisonics Format」Ambisonics Symposium 2011／Ivanic & Ruedenberg「Rotation Matrices for Real Spherical Harmonics」J. Phys. Chem. 1996（訂正版 1998）
- 置き場の規則：プロジェクトを読まない・書かない（`--out` で明示したファイルだけ書く）。変換結果をステムとして取り込むのは通常の取り込み経路
- テスト：(1) `encode`（方位 θ）→ `rotate`（yaw −θ）＝ `encode`（方位 0）とヌル ≤ −120 dBFS (2) 回転行列が直交（誤差 ≤ 1e−12）、3 軸の合成順が仕様どおり (3) FuMa→AmbiX→FuMa が入力と一致 (4) `decode --to stereo`：正面の音源で左右同一、左 90° の音源で左右差が仮想マイクの指向性どおり (5) 出力ファイルがビット一致で再現 (6) CLI と MCP の等価性 (7) チャンネル数が (N＋1)² でない入力は明示エラー
- 依存：BB-24（バイノーラル復号のとき）、T05-02

---

## 実装単位

| 単位 | 中身 | 前提 | 量 | 実働 |
|---|---|---|---|---|
| U-05a | `haas`、`band_pan`、`ms_gain` | BB-02、BB-04、BB-09 | S×3 | Codex |
| U-05b | `autopan`、`doppler` | BB-00、BB-05、BB-09 | S＋M | Codex |
| U-05c | BB-24 のうち `hrtfs` レジストリと `model_sphere` | BB-00 | S | Codex |
| U-05d | `binaural_pan` | 調査レッグ、U-05c、BB-07、BB-09 | L | Codex |
| U-05e | `spatial ambi` | U-05d（バイノーラル復号だけ） | M | Codex |
### 実装時の確定（統括の判断 D-24・D-29）

`spatial ambi` は CLI 専用のファイル変換で、ミックスグラフやMCPへは公開しない。次数1〜3・既定1、座標はx前・y左・z上、正方位は左。右手系能動回転は `Rz(yaw) Ry(pitch) Rx(roll)`（roll→pitch→yaw）。方位・仰角・回転角の既定0度、ステレオ復号は左右±90度が既定。ステレオ入力の点音源化は `(L+R)/2`、出力は明示したfloat64 WAV。`info` は音声だけから並び・正規化を判別できないので unknown/undetermined とし、処理上のACN/SN3D仮定と区別する（W4h）。
