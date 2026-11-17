# spec/07 ハーモニック／歪み（15 件）

カタログ §7。共通規約は `spec/01_dynamics.md` §0。既存 `saturator`・`clipper`・`aw.*` は変えない。タグは 2 代目 PM が付けた。

## 0. カテゴリ共通

- 特記の無い型：`stages: ["track","bus","master"]`、`master_slot`＝既存 `saturator` と同じ番号（実働が `processors.py` で確かめて写す）、時不変（TV ではない）。`channel` 欄は可
- 非線形は全部オーバーサンプルの中で行う（BB-13。既存のポリフェーズ・オーバーサンプラの複製）。レイテンシは倍率ごとに宣言・補償。乾側にも同じ遅延（`mix` の位相整合）
- **小信号利得の規約**：`drive_db=0`（または各件の中立）で経路を通さずビット一致。飽和曲線は小信号利得 1 に正規化してから `drive_db` を掛ける
- 「その機種の音」は作らない。「その方式の音」を作る（PM_PLAN §9.9）。型名・パラメータ名に機種名を使わない。**市販プラグイン・実機の出力を測って曲線を合わせることは禁止**。使えるのは回路・物理の公開解析と、失効特許の原理記述

**NL ブロック（共通パラメータ）**

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `drive_db` | f | dB | 0〜36（型ごとに上書き） | 0 |
| `output_db` | f | dB | −36〜12 | 0 |
| `auto_gain` | b | — | — | false（true＝`output_db` に −`drive_db`×型ごとの係数を足す。**測って合わせるのではなく固定式**：結果が素材に依らず決定的） |
| `mix` | f | 0..1 | 0〜1 | 1 |
| `oversample` | e | x | 1／2／4／8 | 4 |

**共通テスト（NT）**：(NT1) 中立でビット一致 (NT2) 折り返し：5 kHz・10 kHz・15 kHz の −6 dBFS 正弦、既定 `oversample` で、非調波成分（折り返し）が −80 dBc 以下（各件で緩める型はそこに書く） (NT3) 1 kHz 正弦の THD と 2〜7 次の倍音レベルを `drive_db` の 5 点で測り、記録（R-10 のベクトル）。各件の「形」の基準はそこに書く (NT4) 小信号（−60 dBFS）で利得が `output_db` ±0.05 dB（`drive_db` を掛けた後の正規化の確認） (NT5) DC：無音入力で出力 DC 0、非対称な型でも定常信号の出力 DC ≤ −80 dBFS（DC 阻止を内蔵） (NT6) `mix=0.5` で乾・湿の時間ずれ 0 サンプル (NT7) CT-5

カテゴリの正典（最初に読む）：Zölzer 編『DAFX』（非線形処理の章）／Parker, Zavalishin & Le Bivic「Reducing the Aliasing of Nonlinear Waveshaping Using Continuous-Time Convolution」DAFx-16（ADAA）／Bilbao, Esqueda, Parker & Välimäki「Antiderivative Antialiasing for Memoryless Nonlinearities」IEEE SPL 2017／Pakarinen & Yeh「A Review of Digital Techniques for Modeling Vacuum-Tube Guitar Amplifiers」CMJ 2009

---

## T07-01 テープエミュレーション

`tape`｜B｜W3｜L（調査レッグが先）｜Codex

NL（`drive_db` 0〜24、既定 0。**中立は `amount=0`**）に加えて：

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `amount` | f | 0..1 | 0〜1 | 1（0＝ビット一致の素通し。全段を迂回） |
| `speed` | e | ips | 3.75／7.5／15／30 | 15（ヘッドの山の周波数、高域の損失、等化の時定数を決める） |
| `bias` | f | 0..1 | 0〜1 | 0.5（0.5＝最小歪み付近。低い＝交差歪みが出る、高い＝高域が丸まる） |
| `saturation` | f | 0..1 | 0〜1 | 0.5（磁化の飽和の強さ） |
| `hysteresis` | b | — | — | true（false＝記憶なしの飽和曲線。軽い・速い） |
| `head_bump_db` | f | dB | 0〜6 | 1.5 |
| `gap_loss` | f | 0..1 | 0〜1 | 0.5（再生ヘッドのギャップ損失・スペーシング損失の量） |
| `wow_depth`・`flutter_depth` | f | % | 0〜3／0〜1 | 0／0（T06-12 の生成器。0 で通さない） |
| `noise_db` | f | dBFS | −120〜−50 | −120（−120＝足さない。シード付き、速度依存の色） |
| `seed` | i | — | 0〜65535 | 0 |

- アルゴリズム（順）：録音等化（プリエンファシス）→ 磁化の非線形（`hysteresis=true`：Jiles–Atherton モデルの常微分方程式を 4 次ルンゲ＝クッタで解く。8 倍オーバーサンプル固定。バイアスは高周波を足さず、モデルのパラメータへの写像として扱う／`false`：tanh 系の記憶なし曲線）→ 再生側の損失（ギャップ損失 sinc 型、スペーシング損失 指数型、厚み損失：`speed` で波長が決まる）→ ヘッドの山（`speed` に比例した周波数のピーキング）→ 再生等化（ディエンファシス）→ 揺れ → 雑音。損失フィルタはリニアフェイズ FIR（BB-07）で、レイテンシを宣言
- 正典：Chowdhury「Real-Time Physical Modelling for Analog Tape Machines」DAFx-19（**論文だけ。同著者の公開コードは GPL。読まない**）／Jiles & Atherton「Theory of Ferromagnetic Hysteresis」J. Magn. Magn. Mater. 1986／Bertram『Theory of Magnetic Recording』（Cambridge 1994。損失の式）／IEC 60094-1（等化の時定数。規格の数値）。調査レッグ：常微分方程式の数値安定条件（剛性、ステップ幅）と、8 倍で足りるかを先に確かめる
- 決定論：ODE の解法・ステップ・初期磁化（0）を固定。反復解法（ニュートン法）は使わない（反復回数の環境差を避ける）
- テスト（NT に加えて）：(1) `amount=0` でビット一致 (2) `saturation` を上げると 3 次倍音が単調増加、`bias` を 0.5 から下げると小信号（−40 dBFS）の THD が増える（交差歪み） (3) `speed` を半分にすると、ヘッドの山の周波数が 1/2 ±10 %、−3 dB 高域端が下がる（単調） (4) `hysteresis=true`：10 Hz〜1 kHz の正弦で入出力のリサージュが面積を持つ（記憶の確認）、`false` では面積 0 (5) フルスケール・全周波数で出力有界、NaN なし（ODE の安定） (6) 揺れ・雑音 0、`hysteresis=false` のとき時不変（2 つの時刻のバーストで同じ応答） (7) NT2 は −70 dBc に緩める
- 依存：BB-07、BB-13、T06-12

### 実装時の確定（統括の判断 D-13・D-21）

C7d の確定形は速度3.75/7.5/15/30 ipsに対する等化の高域時定数を120/90/50/35→90/70/35/17.5 μsとする。3.75 ipsの低域時定数3180 μs、他は無限大。1 kHzで正規化する等化と逆等化の対を使い、DC零点は2 Hz、高域は0.45*srの極で正則化する。これは追加の規範時定数ではない。

記憶ありは固定8倍、記憶なしの内部倍率は公開 oversample の2倍とする。公開の範囲・既定・合格数値は不変。磁化強度写像は `0.006+0.12*saturation` に改良した。規格全体への適合や実機の再現は主張しない。

## T07-02 マルチバンド・サチュレーション

`mb_saturator`｜A｜W2｜S｜Codex

MB ブロック（spec/01 §0.6。既定 `phase=linear`）＋帯域別配列：`drive_db`（0〜24、→ 0）、`level_db`（−24〜12、→ 0）、`mix`（0〜1、→ 1）。スカラー：`mode`（e：既存 `saturator` の `mode` と同じ列挙・同じ意味。実働が写す）、`oversample`（NL）、`output_db`。

- アルゴリズム：分割 → 帯域ごとに既存 `saturator` と同じ計算 → 加算。全帯域 `drive_db=0` は分割も通さない
- テスト：(1) 全帯域 0 でビット一致 (2) 単帯域（`crossovers_hz=[]`）で既存 `saturator` とヌル ≤ −120 dBFS (3) 1 帯域だけ駆動：他帯域中心の正弦の THD 増加なし（≤ −100 dBc）、レベル変化 ≤ 0.1 dB (4) 生成した倍音が帯域の外へ出ることを記録に明記（帯域で切り直さない：仕様）
- 依存：BB-02、BB-13

### 実装時の確定（統括の判断 D-16）

単帯域の既存 `saturator` とのヌル ≤−120 dBFSを正本とする。NT2/NT5は絶対 −80基準から、同設定の既存型より悪くない（差 ≤+0.5 dB）へ読み替える。NT5の両者共通窓は100〜500 ms。C4 の5 kHz/tanh/drive12の折り返しはMB −49.214595417262494、既存 −49.21460192662332 dBc、非対称DCの差0.2652815386674803 dB。公開値と他の合格条件は維持する。

## T07-03 トランスフォーマー・サチュレーション

`transformer`｜B（PM 判断：磁束の飽和モデルの導出）｜W2｜M（調査レッグが先）｜Codex

NL（`drive_db` 0〜24）に加えて：`lf_corner_hz`（f、5〜80、既定 20：一次インダクタンスによる低域の折点）、`core` （f、0〜1、0.5：鉄心の飽和の硬さ）、`lf_emphasis`（f、0〜1、0.7：歪みが低域に偏る度合い。0＝周波数に依らない飽和）、`hf_resonance_db`（f、0〜6、0：漏れインダクタンスと巻線容量の共振の山）、`hf_resonance_hz`（f、15000〜60000、既定 30000。0.45×sr 以上では掛けない）。

- アルゴリズム：磁束＝電圧の時間積分なので、**低い周波数ほど鉄心が飽和する**。構造：積分器（漏れ付き、折点 `lf_corner_hz`）→ 飽和曲線（磁化曲線。`hysteresis` は持たない：T07-01 と重ねない）→ 微分器。`lf_emphasis` は積分・微分の経路と直通の経路の配分。奇数次が主、わずかな直流バイアスで偶数次
- 正典：Macak「Nonlinear Transformer Simulation for Real-Time Digital Audio Signal Processing」DAFx-11（調査レッグが式を確定）／Jiles & Atherton 1986（参考）
- テスト（NT に加えて）：(1) 同じレベルで 40 Hz の THD が 1 kHz の THD より 12 dB 以上高い（`lf_emphasis=0.7`）、`lf_emphasis=0` で差 ≤ 1 dB (2) 小信号の振幅特性：`lf_corner_hz` で −3 dB ±0.5 dB、中域平坦 ±0.05 dB (3) 3 次 ＞ 2 次（既定） (4) 50 Hz フルスケールで出力有界、DC なし
- 依存：BB-13

## T07-04 カセット／ローファイ劣化

`cassette`｜A｜W3（T07-01 に依存）｜S｜Codex｜**コンポジット**

展開：`wow_flutter` → `tape`（`speed=3.75`）→ `cut_filter`（T02-12。帯域制限）→ `noise_bed`（T09-09）→ `stereo`（既存。クロストーク相当の幅縮め）。各段は量 0 で展開から外す。

| id | 型 | 範囲 | 既定 | 展開先 |
|---|---|---|---|---|
| `wobble` | f | 0〜1 | 0.3 | `wow_flutter.wow_depth`＝1.5·w、`flutter_depth`＝0.4·w |
| `saturation` | f | 0〜1 | 0.5 | `tape.saturation`、`tape.drive_db`＝6·s |
| `tape_type` | e | `normal`／`chrome`／`metal` | `normal` | `tape.bias`・`gap_loss`・`cut_filter` の上端（10／14／16 kHz）の固定表 |
| `age` | f | 0〜1 | 0.3 | `tape.gap_loss`、`cut_filter` の上端を下げる、`noise_bed.dropout`（瞬間的なレベル落ち） |
| `hiss_db` | f | −120〜−40 | −66 | `noise_bed.hiss_db` |
| `narrow` | f | 0〜1 | 0.2 | 既存 `stereo` の幅を全帯域 1−0.5·n に（パラメータ ID は実働が `processors.py` から写す） |
| `seed` | i | 0〜65535 | 0 | 各段の `seed` |

- テスト：(1) 展開後の列を手で書いたチェーンとビット一致 (2) 記録に展開後の項目が残る (3) 全量 0・`hiss_db=−120` で展開が空（ビット一致の素通し） (4) 展開後の各項目に範囲検査
- 依存：BB-00（コンポジット）、T06-12、T07-01、T09-09、T02-12

### 実装時の確定（統括の判断 D-21）

全段の量0による空展開は拒否せず素通し。監査用bypass記録に `expansion: []` を残す。子ID・非空展開の順序と固定対応表は不変。T09-09 `lofi` にも同じ規則を適用する（C7d）。

## T07-05 エキサイター

`exciter`｜A｜W2｜S｜Codex

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `freq_hz` | f | Hz | 500〜12000 | 3000（これより上から倍音を作る） |
| `amount_db` | f | dB | −60〜0 | −60（生成倍音を足す量。−60＝足さない＝ビット一致） |
| `harmonics` | e | — | `even`／`odd`／`both` | `both` |
| `drive_db` | f | dB | 0〜36 | 12（倍音生成段への入力） |
| `dynamic` | f | 0..1 | 0〜1 | 0.5（1＝生成量が入力レベルに依らない〈包絡で正規化〉。0＝固定曲線） |
| `out_lowcut_hz` | f | Hz | 500〜20000 | `freq_hz` と同じ（0 を書けば `freq_hz`） |
| `oversample` | e | x | 2／4／8 | 4 |

- アルゴリズム：側鎖だけを加工して足す。HPF（`freq_hz`、12 dB/oct）→ 包絡正規化（`dynamic`）→ 非線形（`even`＝全波整流系、`odd`＝tanh、`both`＝非対称 tanh）→ HPF（`out_lowcut_hz`：原音と同じ帯域の成分を落とし、新しい倍音だけ残す）→ `amount_db` で原音に加算。**原音の経路は触らない**
- 正典：Zölzer 編『DAFX』（エキサイタ、エンハンサの節）／Aphex の失効特許 US 4,150,253（原理の記述だけ）
- テスト：(1) `amount_db=−60` でビット一致 (2) 出力−入力（差分）に、入力に無い周波数成分だけが含まれる：4 kHz 正弦入力で差分の 4 kHz 成分が生成倍音より 20 dB 以上低い (3) `freq_hz` の 1 oct 下の正弦入力：差分 ≤ −80 dBFS (4) `even`：2 次 ＞ 3 次、`odd`：3 次 ＞ 2 次（10 dB 以上） (5) `dynamic=1`：入力を −20 dB しても差分/入力の比が ±1.5 dB (6) NT2
- 依存：BB-03、BB-13

## T07-06 位相系エンハンサー

`phase_enhancer`｜A｜W2｜M｜Codex

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `amount` | f | 0..1 | 0〜1 | 0（0＝ビット一致の素通し） |
| `lo_xover_hz`・`hi_xover_hz` | f | Hz | 80〜400／1200〜5000 | 150／2400 |
| `lo_delay_ms` | f | ms | 0〜5 | 2.5（`amount`=1 のときの低域の遅れ） |
| `mid_delay_ms` | f | ms | 0〜2 | 0.5 |
| `lo_contour_db` | f | dB | 0〜12 | 0（低域の持ち上げ） |
| `hi_process_db` | f | dB | 0〜12 | 4（高域の持ち上げの最大。レベル依存） |
| `hi_dynamic` | f | 0..1 | 0〜1 | 0.5（高域の持ち上げを、中域レベルが低いほど増やす度合い） |
| `mid_invert` | b | — | — | true（3 帯域を状態変数フィルタで分けたとき、中域を反転して和の振幅を平坦にする構成） |

- アルゴリズム：2 次状態変数フィルタで低・中・高に分け、低域を最も遅らせ、中域を少し遅らせ、高域を遅らせずに（先に）出す。和の小信号振幅特性は `lo_contour_db=hi_process_db=0` で平坦。高域ゲインは包絡追従で動く（レベルが下がると持ち上げが増える）
- 正典：BBE の失効特許 US 4,638,258・US 4,482,866（原理の記述だけ。**製品の出力測定はしない**）／Zölzer 編『DAFX』（エンハンサ）
- テスト：(1) `amount=0` でビット一致 (2) 等化 0 のとき小信号振幅特性が ±0.3 dB で平坦、群遅延が低域 `lo_delay_ms`・中域 `mid_delay_ms`・高域 0 に ±15 %（帯域中心で） (3) `hi_dynamic=1`：入力 −40 dBFS と −10 dBFS で高域ゲイン差が `hi_process_db` の 50 % 以上 (4) インパルス応答で高域成分が低域成分より先に到達 (5) TV の一覧に載せる（高域ゲインが動くため）。`hi_dynamic=0` なら時不変
- 依存：BB-03、BB-09

## T07-07 ラウドネス・エンハンサー（波形整形型）

`loudness_shaper`｜A｜W2｜S｜Codex｜`master_slot`：スロット 5（最終 `limiter` の前だけ。OD-1 と同じ扱い）

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `effect` | f | 0..1 | 0〜1 | 0（0＝ビット一致の素通し） |
| `curve` | f | 0..1 | 0〜1 | 0.5（0＝2 次型の曲線、1＝3 次型。下の式の配分） |
| `input_db` | f | dB | −12〜12 | 0 |
| `clip` | b | — | — | true（|x|>1 を曲線の前に ±1 へ切る。false＝1 を超えた分は直線で通す） |
| `band_split` | b | — | — | false（true＝3 帯域〈240／2400 Hz、リニアフェイズ〉で別々に整形して加算。帯域間の相互変調を減らす） |
| `output_db` | f | dB | −12〜0 | 0 |
| `oversample` | e | x | 1／2／4／8 | 4 |

- アルゴリズム：記憶なしの奇関数 f(x)＝x＋a·[(1−c)·(x−x|x|)＋(c/2)·(x−x³)]、a＝`effect`、c＝`curve`、|x|≤1。**PM が置いた独自の曲線族**で、性質は式から保証される：f(±1)＝±1（ピークを増やさない）、f′(0)＝1＋a(1−c/2)（小さい音を持ち上げる）、a≤1 で単調。**市販品の曲線の再現ではない**（公開されている市販品の係数は出力測定からの逆算であり、使わない。PM_PLAN §9.9）
- 正典：Zölzer 編『DAFX』（波形整形）／Bilbao ほか 2017（この多項式は原始関数が閉形式なので ADAA を使える）
- テスト（NT に加えて）：(1) `effect=0` でビット一致 (2) 性質テスト：ランダムな入力（|x|≤1）で |出力| ≤ 1（`output_db=0`）、f が単調 (3) −20 dBFS 正弦の利得が 20·log10(1＋a(1−c/2)) ±0.05 dB (4) ピンクノイズ（ピーク −1 dBFS）：サンプルピークが増えず、積分ラウドネスが `effect=1` で 1 LU 以上増える（数値を記録） (5) `band_split=true`：19 kHz＋20 kHz の 2 音で 1 kHz の差音が `false` より 10 dB 以上低い (6) **トゥルーピークは保証しない**（実測を記録）
- 依存：BB-02、BB-13

### 実装時の確定（統括の判断 D-16）

指定多項式を正本とし、零点微分ではなく有限振幅の基本波利得 `G(A)=1+a*(1-c/2)-8*a*(1-c)*A/(3*pi)-3*a*c*A**2/8` で判定する（a=effect、c=curve）。C4 の a1/c0.5/A0.1は予測4.637969892224802 dB、実描画4.637970506978861 dB。許容±0.05 dBは維持。

ピーク性は曲線の `abs(x)<=1 ⇒ abs(f(x))<=1` とし、任意素材のsample peak不増は要求しない。相互変調は別帯域の2音で検査し、≤−10 dBを維持する（200/1400 Hz、1000 Hzの成分は分割なし比 −24.18890124191449 dB）。曲線の境界はマルチバンド再合成後のtrue peak保証ではない。

## T07-08 ベース倍音エンハンサー

`bass_enhancer`｜B｜W2｜M｜Codex

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `freq_hz` | f | Hz | 40〜250 | 90（これより下の成分から倍音を作る） |
| `amount_db` | f | dB | −60〜12 | −60（−60＝ビット一致） |
| `original_db` | f | dB | −60〜0 | 0（元の低域の量。下げれば小型スピーカー向けの置き換え） |
| `harmonics` | e | — | `integrator`／`rectifier`／`clipper` | `integrator`（倍音生成器の方式） |
| `hi_limit_hz` | f | Hz | 150〜1000 | 400（生成倍音の上限） |
| `decay` | f | 0..1 | 0〜1 | 0.5（高次倍音ほど弱める傾き） |
| `attack_ms`・`release_ms` | f | ms | 1〜100／20〜500 | 10／120（生成倍音のレベルを元の低域の包絡に合わせる） |
| `oversample` | e | x | 2／4 | 4 |

- アルゴリズム：欠落基音（倍音列があれば基音が無くても低さを感じる）を使う。LPF（`freq_hz`、リニアフェイズ）で低域を取り出す → 倍音生成器（`integrator`＝全波積分リセット型、`rectifier`＝全波整流、`clipper`＝対称クリップ）→ BPF（`freq_hz`〜`hi_limit_hz`）→ 包絡合わせ → 加算。元の低域は `original_db` で増減
- 正典：Larsen & Aarts「Reproducing Low-Pitched Signals through Small Loudspeakers」JAES 2002／Larsen & Aarts『Audio Bandwidth Extension』（Wiley 2004。倍音生成器の比較の章）／Gan, Kuo & Toh「Virtual bass for home entertainment, multimedia PC, game station and portable audio systems」IEEE Trans. Consumer Electron. 2001
- テスト：(1) `amount_db=−60, original_db=0` でビット一致 (2) 60 Hz 正弦：差分に 120・180・240 Hz が現れ、`hi_limit_hz` より上の倍音 ≤ −60 dBc、`decay` で次数ごとの傾きが単調 (3) 1 kHz 正弦：差分 ≤ −90 dBFS (4) 生成倍音のレベルが入力レベルに ±2 dB で比例（−30〜−6 dBFS。`integrator`） (5) `original_db=−60`：60 Hz 成分が 50 dB 以上下がり、倍音は残る (6) バースト入力：倍音の立ち上がりが元の低域の包絡に追従（遅れ ≤ 15 ms） (7) NT2・NT5
- 依存：BB-03、BB-07、BB-13

## T07-09 サブハーモニック生成

`sub_synth`｜B｜W2｜M｜Codex

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `mode` | e | — | `divider`／`tracked` | `divider` |
| `lo_hz`・`hi_hz` | f | Hz | 30〜120／60〜250 | 50／110（この帯域の成分の 1 オクターブ下を作る） |
| `amount_db` | f | dB | −60〜6 | −60（−60＝ビット一致） |
| `sub_highcut_hz` | f | Hz | 30〜120 | 60（生成したサブの上限。矩形の倍音を落とす） |
| `attack_ms`・`release_ms` | f | ms | 1〜100／20〜1000 | 10／150 |
| `threshold_db` | f | dBFS | −80〜0 | −45（帯域内のレベルがこれより下では作らない） |
| `mono` | b | — | — | true（サブは中央に足す） |

- アルゴリズム：
  - `divider`：BPF（`lo_hz`〜`hi_hz`）→ ゼロ交差（ヒステリシスつき）で反転するフリップフロップ → 周波数が 1/2 の矩形 → 元の帯域の包絡を掛ける → LPF（`sub_highcut_hz`、4 次）。和音・複数音には弱い（誤動作する。仕様として明記）
  - `tracked`：BB-12 で基音を追い、基音/2 の正弦を位相連続で合成、包絡を掛ける。`offline_only` 相当の先読みが要るので、**`mode=tracked` は別型にせず、型全体を `offline_only: True` と宣言する**（`divider` も同じ宣言の下で動く）
- 正典：Larsen & Aarts『Audio Bandwidth Extension』（低域側への拡張の章）／de Cheveigné & Kawahara「YIN」JASA 2002（`tracked`）
- 決定論：ゼロ交差のヒステリシス幅と初期状態を固定。`tracked` の位相は絶対時刻からの積分（途中描画の一致）
- テスト：(1) `amount_db=−60` でビット一致 (2) 80 Hz 正弦：差分に 40 Hz ±0.5 Hz、差分の 80 Hz 以上の成分 ≤ −40 dBc (3) `lo_hz`〜`hi_hz` の外（200 Hz、30 Hz）の正弦：差分 ≤ −80 dBFS (4) バースト：サブの立ち上がり・減衰が時定数 ±20 % (5) `threshold_db` 未満の入力で差分 0 (6) `mono=true`：差分の左右が同一 (7) 出力 DC ≤ −80 dBFS
- 依存：BB-03、BB-12

### 実装時の確定（統括の判断 D-13・D-20）

`sub_synth.attack_ms` の範囲は1〜100→10〜100 ms、既定10は維持（C6a）。旧要求1/5 msの40 Hz搬送波の実測はdivider 0.6666666666666666/6.625 ms、tracked 0.125/6.3125 msで±20 %に未達。10/20/50/100 msの24条件で確定した。生成4次LPFは通過域0.1 dB・阻止域40 dBの設計へ変更し、highcutと検出周波数の0.75倍の小さい方を使う。他の公開範囲・既定と許容値は不変。

## T07-10 マルチバンド・ディストーション

`mb_distortion`｜A｜W2｜S（T07-11・12 の後）｜Codex

最大 4 帯域に固定（列挙の配列を型として持たないため、帯域ごとの方式は番号つきの ID で持つ）。

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `crossovers_hz` | a | Hz | 20〜20000、最大 3 個、狭義昇順 | `[200, 2000]` |
| `phase` | e | — | `minimum`／`linear` | `linear` |
| `kind_1`〜`kind_4` | e | — | `off`／`tanh`／`hard`／`fold`／`rectify`／`fuzz`／`crush` | `off`（帯域数より大きい番号は `off` 以外を拒否） |
| `drive_db` | a | dB | 0〜48 | `[]`→ 0 |
| `tone_hz` | a | Hz | 200〜20000 | `[]`→ 20000（帯域ごとの歪み後 LPF） |
| `level_db` | a | dB | −36〜12 | `[]`→ 0 |
| `mix` | a | 0..1 | 0〜1 | `[]`→ 1 |
| `oversample` | e | x | 2／4／8 | 8 |

- `kind`：`tanh`（対称ソフト）、`hard`（対称ハードクリップ、ADAA）、`fold`（折り返し：三角波写像）、`rectify`（全波整流＋DC 阻止）、`fuzz`（T07-11 の曲線）、`crush`（T07-12 の量子化。標本化周波数の低減は含めない）
- テスト：(1) 全 `off` でビット一致 (2) 1 帯域だけ作用：他帯域中心の正弦に変化なし（≤ 0.1 dB、THD 増加なし） (3) 各 `kind` の倍音の形：`rectify` は偶数次だけ、`tanh`・`hard`・`fold` は奇数次だけ（±偶奇の漏れ ≤ −60 dBc） (4) `fold`：入力を上げると出力ピークが上がり続けない（|出力| ≤ 1） (5) NT2 は −60 dBc に緩める（`hard`・`fold`、8 倍）
- 依存：BB-02、BB-13、T07-11、T07-12

## T07-11 ファズ

`fuzz`｜A｜W2｜S｜Codex｜`stages: ["track","bus"]`

NL（`drive_db` 0〜60、既定 30／`oversample` 既定 8）に加えて：`bias`（f、−1〜1、0.2：動作点のずれ。非対称＝偶数次倍音と「途切れ」）、`gate`（f、0〜1、0.2：小さい音が消える度合い。バイアス不足のかすれ）、`shape`（e、`soft`／`hard`／`octave`、既定 `hard`：`octave`＝全波整流を前段に足し 1 オクターブ上が乗る）、`tone_hz`（f、200〜20000、3000：後段 LPF）、`lowcut_hz`（f、0〜500、60：前段。入力結合の低域削り）、`input_z`（f、0〜1、0：入力の高域が `drive` と連動して丸まる度合い。ギターのボリュームを絞ったときの挙動の簡易モデル）。

- アルゴリズム：前段 HPF → 利得 → 動作点シフト（`bias`）→ 2 段の非対称クリップ（1 段目ソフト、2 段目 `shape`）→ `gate`：|x| が閾値未満の区間を滑らかな不感帯で 0 へ → DC 阻止 → LPF。機種の回路は写さない（2 石ファズの一般構造だけ）
- 正典：Pakarinen & Yeh 2009／Yeh, Abel & Smith「Simplified, Physically-Informed Models of Distortion and Overdrive Guitar Effects Pedals」DAFx-07
- テスト（NT に加えて）：(1) `bias=0`：偶数次 ≤ −60 dBc、`bias=0.5`：2 次 ≥ −30 dBc (2) `gate=1`：−50 dBFS の正弦が −90 dBFS 以下になり、−10 dBFS は通る（減衰する音の尾が途切れる） (3) `octave`：1 kHz 入力で 2 kHz が基本波より強い (4) NT2 は −60 dBc に緩める (5) NT5
- 依存：BB-13

## T07-12 ビットクラッシャー／SR リダクション

`bitcrush`｜A｜W2｜S｜Codex｜`stages: ["track","bus"]`

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `bits` | f | bit | 1〜24 | 24（24＝量子化段を通さない。小数可：段数＝2^bits を実数で） |
| `rate_hz` | f | Hz | 100〜192000 | 192000（sr 以上＝標本化段を通さない） |
| `antialias` | b | — | — | false（false＝折り返しを**わざと**出す。true＝低減前に LPF） |
| `hold` | e | — | `zoh`／`linear` | `zoh`（低減後の再構成。`zoh`＝階段） |
| `jitter` | f | 0..1 | 0〜1 | 0（保持間隔のシード付きの揺れ） |
| `dither` | f | 0..1 | 0〜1 | 0（量子化前の TPDF の量。シード付き） |
| `quantizer` | e | — | `midtread`／`midrise` | `midtread`（`midrise` は無音でも ±半段が出る：CT-3 の例外として宣言） |
| `mix`・`output_db`・`seed` | | | NL／i | 1／0／0 |

- アルゴリズム：標本化段＝絶対サンプル位置から保持点を計算（位相累積しない。点 k の時刻＝k·sr/`rate_hz` を丸める）→ 保持。量子化段＝round(x·L)/L。**オーバーサンプルしない**（折り返しが目的）
- 正典：Zölzer『Digital Audio Signal Processing』（量子化、ディザ）／Lipshitz, Wannamaker & Vanderkooy「Quantization and Dither: A Theoretical Survey」JAES 1992
- テスト：(1) 既定でビット一致 (2) `bits=8`：出力が 256 段の格子上（全サンプル）、定常正弦の SNR が 6.02·8＋1.76 ±1 dB (3) `rate_hz=sr/4`・`zoh`：出力が 4 サンプルごとに一定、折り返し周波数が理論値 (4) `antialias=true`：`rate_hz`/2 より上の入力成分の折り返しが 40 dB 以上減る (5) 途中からの描画が一致（保持点が絶対位置） (6) `jitter`・`dither`：同一 `seed` で一致 (7) `midtread`：無音→無音
- 依存：なし（BB-01 だけ）

## T07-13 アンプシミュレータ

**`amp_sim`（学習モデル）＋ `amp_basic`（決定論。単独でも使え、`amp_sim` のフォールバックでもある）**｜C（`amp_basic` は B）｜W5（`amp_basic` は W3）｜L｜Codex｜`stages: ["track"]`
カタログ：「NAM は学習モデルが本質」。PM_PLAN §5 の 6 条件に従う。

`amp_basic`：NL（`drive_db` 0〜60、既定 24／`oversample` 既定 8）に加えて

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `stages` | i | 段 | 1〜4 | 2（増幅段の数） |
| `bright` | b | — | — | false（初段の高域持ち上げ） |
| `bass`・`mid`・`treble` | f | 0..1 | 0〜1 | 0.5（受動トーンスタックのつまみ） |
| `tonestack` | e | — | `scoop`／`flat`／`mid_forward` | `scoop`（部品比の 3 通り。機種名ではない） |
| `power_drive_db` | f | dB | 0〜24 | 0（出力段の飽和） |
| `sag` | f | 0..1 | 0〜1 | 0.2（電源の沈み：包絡で利得が下がる。TV） |
| `presence_db` | f | dB | −6〜6 | 0 |

- アルゴリズム：各段＝結合 HPF → 非対称な三極管型の飽和（グリッド電流による正側の早いクリップ）→ 段間 LPF。トーンスタックは受動 3 素子回路の解析的な伝達関数（つまみ→係数の閉形式）。出力段はプッシュプル型の対称飽和＋`sag`。**キャビネットは含めない**（`cab_ir` を後ろに置く）
- 正典：Pakarinen & Yeh 2009（総説）／Yeh & Smith「Discretization of the '59 Fender Bassman Tone Stack」DAFx-06（トーンスタックの解析法。**部品値は方式の一般値を使い、特定機種の回路図の値を写さない**）／Koren「Improved Vacuum Tube Models for SPICE Simulations」1996（真空管の式）
- テスト（NT。NT2 は −60 dBc）：トーンスタックの振幅特性が解析解と ±0.1 dB／`drive_db` に対し THD 単調増加／`sag=1`：持続音で 3 dB 以内の利得低下、時定数を記録／出力有界

`amp_sim`：

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `model` | as | `models` レジストリ（BB-16。種別 `amp_capture`） | 登録済み ID | （必須。同梱の既定は持たない） |
| `input_db` | f | dB | −24〜24 | 0 |
| `output_db` | f | dB | −36〜12 | 0 |
| `fallback` | e | — | `amp_basic`／`error` | `error`（モデル不在時。`amp_basic` は「似た音」にはならないので既定は明示エラー） |

- `offline_only: True`、`backends: ["model"]`。推論：NAM 形式（WaveNet 型／LSTM 型）の重みを読み、**自前の numpy 推論**か ONNX Runtime（C-2）。sr はモデルの学習 sr（通常 48 kHz）へ既存 `resample` で往復
- ライセンス（C-3）：NAM のコード（neural-amp-modeler、NeuralAmpModelerCore）は MIT と PM は記憶しているが、**調査レッグが一次で確かめる**。個々のキャプチャ（重み）は作者ごとにライセンスが違い、実機の商標・意匠に関わる留保があるので、**`official` 同梱は 0 本**、全部 `byo`。`caveats` に「実機メーカーとの関係なし」を固定で書く
- テスト（C-6）：モデル無しで回るもの＝形式の読み込み（合成した小さな重み）、チャンク継ぎ目のビット一致、未登録 ID・ハッシュ不一致の明示エラー、`fallback` の記録。モデルを与えたとき＝2 回描画一致、既知入力の出力ハッシュ
- 依存：BB-00（asset）、BB-13、BB-16

### 実装時の確定（統括の判断 D-30）

`amp_basic` は実装済み、`amp_sim` は C-4（代替実行の標準 Mix Report 接続）未達で `implemented: false`。coreの追加はOQ-4の判断待ち。推論やBYOWの試験合格と完全実装を混同しない。modelの内部未指定値は空文字であり、既定キャプチャを意味しない。未指定での実行は拒否する。

## T07-14 キャビネット IR ローダー

`cab_ir`｜A｜W2｜S（T03-01 の後。同じ畳み込み核）｜Codex｜`stages: ["track","bus"]`

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `ir` | as | `irs` レジストリ（BB-08。`kind: cabinet`） | 登録済み ID | `synth_cab_a`（同梱の自作合成：2 次共振＋コーン分割振動の櫛＋高域の落ちをフィルタ設計で作ったもの） |
| `length_ms` | f | ms | 5〜500 | 200 |
| `phase` | e | — | `as_is`／`minimum` | `as_is`（`minimum`＝実ケプストラムで最小位相化。レイテンシ 0、複数 IR の混合で位相が揃う） |
| `ir_b` | as | 同上 | ID または空 | 空（2 本目。空＝使わない） |
| `blend` | f | 0..1 | 0〜1 | 0（a と b の混合比） |
| `b_delay_ms` | f | ms | 0〜5 | 0（2 本目のマイク距離差） |
| `lowcut_hz`・`highcut_hz` | f | Hz | 0〜500／0〜20000 | 0／0 |
| `gain_mode` | e | — | `energy`／`peak`／`none` | `energy` |
| `mix` | f | 0..1 | 0〜1 | 1 |

- 資産の規律は T03-01 と同じ（同梱は自作合成と CC0 だけ。第三者・製品付属の IR は持ち込み）。レジストリの項目に `kind`（`room`／`cabinet`）を足す（追加の欄。BB-08 の定義は変えない：無ければ `room`）
- テスト：T03-01 の (1)〜(5)(9) に加えて、`minimum`：振幅特性が `as_is` と ±0.1 dB、エネルギーの 99 % が先頭 `length_ms`/4 以内、レイテンシ 0／`blend=0.5`・`b_delay_ms`：2 本の和の櫛が理論位置
- 依存：BB-00、BB-07、BB-08

## T07-15 コンソールエミュレーション（バス色付け）

`console_bus`｜A｜W2｜M｜Codex｜`stages: ["bus","master"]`
既存 `aw.console7_*` は変えない。カタログの指摘「クロストークは無い」を埋める。**トラック間（別チャンネル間）の漏れは作らない**：1 つのプロセッサは自分の入力しか見えず、他トラックの音を入れるにはグラフの変更が要る（PM_PLAN OD-14）。本型が作るのは左右間の漏れとチャンネル個体差。

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `crosstalk_db` | f | dB | −120〜−40 | −120（−120＝無効。20 kHz での左右間の漏れ量） |
| `crosstalk_slope` | f | dB/oct | 0〜6 | 6（容量結合：高域ほど漏れる） |
| `drive_db` | f | dB | 0〜18 | 0（加算アンプの飽和） |
| `character` | f | 0..1 | 0〜1 | 0.5（0＝3 次主体の対称、1＝2 次が乗る非対称） |
| `tolerance` | f | 0..1 | 0〜1 | 0（左右の個体差：利得 ±0.1 dB・高域端 ±3 % を上限に、シードで決まる固定値） |
| `lf_corner_hz` | f | Hz | 0〜30 | 0（出力結合の低域折点。0＝無効） |
| `hf_corner_hz` | f | Hz | 0〜80000 | 0（0＝無効。0.45×sr 以上は掛けない） |
| `noise_db` | f | dBFS | −120〜−70 | −120 |
| `oversample`・`output_db`・`seed` | | | NL／i | 4／0／0 |

- アルゴリズム：L′＝L＋k·H(R)、R′＝R＋k·H(L)（H は 1 次ハイパスの傾き）→ 飽和 → 帯域端のフィルタ → 個体差 → 雑音
- 正典：Zölzer 編『DAFX』／コンソールのクロストークの一般的な技術解説（調査レッグが 1 本選ぶ。数値は方式の典型値として置き、実機の測定値を写さない）
- テスト（NT に加えて）：(1) 既定でビット一致 (2) 左だけに 10 kHz：右の漏れが `crosstalk_db`−`crosstalk_slope`·log2(20k/10k) ±0.5 dB、1 kHz では傾きどおり低い (3) `tolerance=1`：左右の利得差 ≤ 0.1 dB、同一 `seed` で同じ差 (4) `character` で 2 次/3 次の比が単調に変わる (5) モノ入力は左右対称の部分だけ動く（漏れ・個体差は無効と記録）
- 依存：BB-13

---

## 実装単位

| 単位 | 中身 | 前提 | 量 | 実働 |
|---|---|---|---|---|
| U-07a | `exciter`、`loudness_shaper`、`fuzz`、`bitcrush` | BB-13 | S×4 | Codex |
| U-07b | `mb_saturator`、`mb_distortion` | BB-02、U-07a | S＋S | Codex |
| U-07c | `transformer`、`bass_enhancer`、`sub_synth` | 調査レッグ（`transformer`）、BB-03、BB-12、BB-13 | M×3 | Codex |
| U-07d | `phase_enhancer`、`console_bus` | BB-03、BB-09、BB-13 | M＋M | Codex |
| U-07e | `cab_ir`（`synth_cab_a` の生成スクリプト含む） | U-03 の畳み込み核、BB-08 | S | Codex |
| U-07f | `tape` | 調査レッグ、BB-07、BB-13、U-06b | L | Codex |
| U-07g | `cassette` | U-07f、`noise_bed`（U-09）、`cut_filter` | S | Codex |
| U-07h | `amp_basic` | BB-13 | M | Codex |
| U-07i | `amp_sim` | 調査レッグ（ライセンス）、BB-16、U-07h | M | Codex |
