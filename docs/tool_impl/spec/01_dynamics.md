# spec/01 ダイナミクス（15 件）

カタログ §1。タグ・部品 ID・ウェーブは `PM_PLAN.md`。**冒頭の §0 は全カテゴリ共通の規約**（spec/02 以降はここを参照する）。

## 0. 共通規約（全 spec）

### 0.1 登録と命名

- 型名は小文字スネーク。商標・機種名を使わない（方式の名前で呼ぶ）
- パラメータ ID は単位を語尾に持つ：`_db`、`_ms`、`_s`、`_hz`、`_oct`、`_semitones`。帯域幅は Q でなくオクターブ（R-12）。時間は ms、拍に乗る時間は `note`＋`bpm` を併せ持つ（R-11。`NOTE_VALUES` を使う。`note != none` は `bpm > 0` を要求、`0 < bpm < 20` は拒否。既存 `delay` と同じ交差検査）
- 表の「型」：f＝float、i＝int、e＝enum、b＝bool、a＝float_array、c＝`curve`、as＝`asset`（c・as は BB-00）
- 特記の無い限り：`stages: ["track","bus","master"]`、`offline_only: False`、`backends: ["reference"]`、`implemented` はテスト基準を満たすまで False
- `master_slot` は各件に書く。**どの新型もマスター最終段（スロット 6）には置けない**（PM_PLAN §8 OD-1）。指揮書からマスター段へも置けない（OD-3）
- 時間で変わる処理（各件に「TV」と記す）は `director/direction.py` の `TIME_VARYING` に載せる（主役に掛けると E3）

### 0.2 ライセンス（実働への発注に必ず写す）

- Apache-2.0 と両立しないコードの移植・参照写経は禁止：GPL／AGPL（Pedalboard、Essentia、Matchering、master_me、ChowDSP 系、aubio、Rubber Band、Dragonfly Reverb、Calf、LSP ほか）。読むのも避ける
- アルゴリズムは論文・教科書・公開仕様から自前で書く。各件の「正典」がその入口。**巻号・式番号は調査レッグが一次で確かめる**（PM は Web 照合をしていない）
- MIT／BSD／ISC／Apache-2.0 の実装を参考にした場合は、ファイル冒頭と `third_party/` 相当の記録に出典・ライセンス・版を書く。本 spec が名指しで許す参考元：Airwindows（MIT）、scipy.signal（BSD）、librosa（ISC）
- 市販プラグインの出力を測って特性を合わせ込むことは禁止。内部実装の解析も禁止。カタログの代表プラグイン名は「何の役割か」を示すだけ

### 0.3 バックエンド

- **reference（numpy／scipy、float64）が正。** native（C++17）は W6 で選別して移植。移植したら `backends` に `native` を足す
- native 一致条件（提案値。既存 native テストの慣例に合わせて W0 で確定）：同一入力・同一パラメータで reference との差の RMS が、線形・時不変の型 ≤ −100 dBFS、ダイナミクス・非線形・再帰の型 ≤ −80 dBFS、かつ GR 曲線の差 ≤ 0.1 dB。乱数を使う型は同じ PCG64 列を両方で使う

### 0.4 決定論（既定。各件は差分だけ書く）

- 内部は float64。スレッドを使わない（`scipy.fft` は `workers=1`）。時刻・環境・辞書順に依存しない
- 乱数は PCG64。シードは「プロジェクトのシード＋チェーン項目 ID＋パラメータ `seed`」から導く（`dither` と同じ流儀。SPEC §9.6）
- 状態の初期値は 0。ブロック分割に依らない結果（ブロック長を変えて 2 回描画しビット一致）
- デノーマルは処理せず、float64 のまま通す（フラッシュ設定に依存しない）
- 同一環境でビット一致が合格条件。環境またぎは測定値の許容内（SPEC §16.3）

### 0.5 共通テスト（全プロセッサ。各件のテスト基準はこれに足す分）

| ID | 内容 | 合格 |
|---|---|---|
| CT-1 | 2 回描画 | ビット一致 |
| CT-2 | ブロック長 64／1024／全長 | ビット一致 |
| CT-3 | 無音入力 | 無音出力（乱数ノイズを明示的に足す型を除く）。NaN・Inf・DC なし |
| CT-4 | 中立設定（各件に定義） | 入力とのヌルが各件の値以下 |
| CT-5 | 宣言レイテンシ | インパルスで実測と一致。オフライン描画で補償されている |
| CT-6 | 範囲検査 | 範囲外・未知 ID・配列長の不一致を `ParamError` で拒否 |
| CT-7 | sr 44.1k／48k／96k、モノ／ステレオ | 周波数・時定数の実測が宣言どおり（sr に依らない） |
| CT-8 | フルスケール入力 | 出力が有限。発振しない（フィードバック系は 60 s の入力停止後に −120 dBFS 未満） |

### 0.6 共通パラメータ・ブロック

**MB（帯域分割。BB-02）**

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `crossovers_hz` | a | Hz | 20〜20000、最大 5 個、狭義昇順 | `[150, 2500]` |
| `phase` | e | — | `minimum`／`linear` | `minimum` |

- 帯域数 N ＝ 個数＋1（最大 6）。帯域別の配列パラメータは「空＝スカラー既定値を全帯域へ」「そうでなければ長さ N」。それ以外は拒否
- `minimum`：LR4 の木構造（和は全通過。振幅平坦）。`linear`：既存 `stereo` と同じ相補 FIR（完全再構成、レイテンシ (taps−1)/2）
- `check_runtime`：各境目 < 0.98×ナイキスト

**SD（自己ダック。BB-14。残響・遅延の新型が持つ）**

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `duck_db` | f | dB | 0〜24 | 0（＝無効。経路を通さない） |
| `duck_threshold_db` | f | dBFS | −80〜0 | −40 |
| `duck_attack_ms` | f | ms | 0.1〜200 | 10 |
| `duck_release_ms` | f | ms | 5〜3000 | 250 |

乾音の RMS 包絡が閾値を超える間、ウェット側だけを最大 `duck_db` 下げる。

---

## T01-01 マルチバンドコンプレッサー ／ T01-15 リニアフェイズ・マルチバンド

`mb_compressor`｜タグ A｜W1｜M｜Codex｜TV｜`master_slot: 2`
**T01-15 は別型を作らず、本型（と T01-02・03・12）の `phase=linear` で満たす。**

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| MB ブロック | | | | |
| `threshold_db` | a | dBFS | −60〜0 | `[]`→ −24 |
| `ratio` | a | :1 | 1〜30 | `[]`→ 2 |
| `attack_ms` | a | ms | 0.05〜300 | `[]`→ 10 |
| `release_ms` | a | ms | 5〜3000 | `[]`→ 150 |
| `makeup_db` | a | dB | −12〜24 | `[]`→ 0 |
| `range_db` | a | dB | 0〜48 | `[]`→ 48（帯域ごとの最大 GR） |
| `knee_db` | f | dB | 0〜24 | 6 |
| `detector` | e | — | `peak`／`rms` | `rms` |
| `rms_window_ms` | f | ms | 1〜300 | 10 |
| `stereo_link` | b | — | — | true |
| `up_threshold_db` | a | dBFS | −80〜0 | `[]`（空＝上向き無効） |
| `up_ratio` | a | :1 | 1〜10 | `[]`→ 2 |
| `up_max_gain_db` | a | dB | 0〜24 | `[]`→ 6 |

- アルゴリズム：MB 分割 → 帯域ごとに既存 `compressor` と同じ計算（前向き、dB 領域の平滑、分離アタック／リリース）→ 加算。上向き（`up_*`）は T01-05 の静特性を帯域ごとに重ねる（下向きと上向きの閾値の間は 1:1）
- 正典：Giannoulis, Massberg, Reiss「Digital Dynamic Range Compressor Design — A Tutorial and Analysis」JAES 2012／Zölzer 編『DAFX』ダイナミクス章／Linkwitz「Active Crossover Networks for Noncoincident Drivers」JAES 1976／完全再構成は既存 `stereo` の実装
- 決定論：既定どおり
- テスト：(1) 中立（全帯域 ratio=1、上向き無効）で、linear は遅延補償後のヌル ≤ −120 dBFS、minimum は振幅 ±0.01 dB かつ入力の全通過 (2) 帯域中心の正弦をレベル階段で入れ、定常 GR が理論静特性 ±0.3 dB (3) ステップ応答の時定数が宣言 ±10 % (4) 帯域 1 つだけ作用させ、他帯域中心の正弦のレベル変化 ≤ 0.1 dB (5) 単帯域（`crossovers_hz=[]`）で既存 `compressor` とのヌル ≤ −120 dBFS
- 依存：BB-02、BB-03

## T01-02 マルチバンドエクスパンダー／ゲート

`mb_expander`｜A｜W1｜S（T01-01 と T01-07 の後）｜Codex｜TV｜slot 2

MB ブロック＋帯域別配列：`threshold_db`（−80〜0、→ −45）、`ratio`（1〜100、→ 2）、`range_db`（−90〜0、→ −24）、`attack_ms`（0.05〜300、→ 2）、`hold_ms`（0〜2000、→ 20）、`release_ms`（5〜3000、→ 150）、`up_gain_db`（0〜12、→ 0：閾値より上を持ち上げる伸長。0＝無効）。スカラー：`knee_db`（0〜24、6）、`stereo_link`（true）。

- アルゴリズム：T01-07 の計算を帯域ごとに。先読みは持たない（帯域ごとの遅延差を作らないため）
- テスト：T01-01 の (1)(4) と、T01-07 の (1)(2) を帯域ごとに
- 依存：BB-02、BB-03

## T01-03 マルチバンド・トランジェントシェイパー

`mb_transient`｜A｜W2｜S（T01-04 の後）｜Codex｜TV｜slot 2

MB ブロック＋帯域別配列 `attack_db`（−12〜12、→ 0）、`sustain_db`（−12〜12、→ 0）。スカラーは T01-04 と同じ（`fast_ms`、`slow_ms`、`sustain_release_ms`、`max_gain_db`、`stereo_link`）。

- テスト：T01-01 (1)、T01-04 の (1)〜(3) を帯域ごとに。全帯域 0 dB で中立
- 依存：BB-02、BB-03

## T01-04 トランジェントシェイパー（単バンド）

`transient_shaper`｜A｜W1｜S｜Codex｜TV｜slot 2

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `attack_db` | f | dB | −12〜12 | 0 |
| `sustain_db` | f | dB | −12〜12 | 0 |
| `fast_ms` | f | ms | 0.1〜10 | 1 |
| `slow_ms` | f | ms | 5〜100 | 20 |
| `sustain_release_ms` | f | ms | 50〜2000 | 300 |
| `max_gain_db` | f | dB | 0〜18 | 12（瞬時ゲインの上下限 ±） |
| `stereo_link` | b | — | — | true |
| `output_db` | f | dB | −24〜12 | 0 |

- アルゴリズム：包絡の差で動くので閾値を持たない（入力レベルに依らない）。速い包絡 Ef と遅い包絡 Es（dB）を取り、アタック成分 a＝clip(Ef−Es, 0, …)、サステイン成分 s＝clip(Er−Ef, 0, …)（Er は長いリリースの包絡）を正規化し、ゲイン（dB）＝`attack_db`·a′＋`sustain_db`·s′。ゲインは `max_gain_db` で頭打ち、1 ms で平滑
- 正典：SPL Transient Designer の公開マニュアルにある動作原理の説明（差分包絡。原理の記述だけを読む）／Giannoulis ほか 2012（包絡検出）／Zölzer『DAFX』
- テスト：(1) 中立（両方 0 dB）でビット一致の素通し (2) バースト列（10 ms 立ち上がり＋300 ms 減衰）で `attack_db=+6`：先頭 10 ms のピーク増分が +6 ±1 dB、200 ms 以降のレベル変化 ≤ 0.5 dB (3) `sustain_db=±6`：減衰部（100〜300 ms）の RMS が ±6 ±1.5 dB、先頭ピーク変化 ≤ 0.5 dB (4) 入力を −20 dB しても (2)(3) の増減量が同じ（±0.3 dB。レベル非依存の確認） (5) 定常正弦でゲイン変化 ≤ 0.1 dB
- 依存：BB-03

## T01-05 アップワードコンプレッサー

`upward_compressor`｜A｜W1｜S｜Codex｜TV｜slot 2

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `threshold_db` | f | dBFS | −80〜0 | −30（これより下を持ち上げる） |
| `ratio` | f | :1 | 1〜10 | 2 |
| `max_gain_db` | f | dB | 0〜24 | 6 |
| `floor_db` | f | dBFS | −120〜−30 | −60（これより下は持ち上げない。雑音の保護） |
| `knee_db` | f | dB | 0〜24 | 6 |
| `attack_ms` | f | ms | 0.05〜300 | 20 |
| `release_ms` | f | ms | 5〜3000 | 200 |
| `detector` | e | — | `peak`／`rms` | `rms` |
| `rms_window_ms` | f | ms | 1〜300 | 20 |
| `stereo_link` | b | — | — | true |
| `mix` | f | 0..1 | 0〜1 | 1 |

- アルゴリズム：静特性 g(L)＝min((T−L)(1−1/R), `max_gain_db`)（L<T）。`floor_db` の下 12 dB で g を 0 へ滑らかに戻す。閾値より上はビット一致の素通し（`dynamic_eq` と同じ流儀）
- 正典：Giannoulis ほか 2012（静特性の一般形）／Zölzer『DAFX』
- テスト：(1) レベル階段で静特性 ±0.3 dB (2) 閾値より 6 dB 以上上の定常正弦はビット一致 (3) `floor_db` より 24 dB 下のノイズのゲイン ≤ 0.1 dB (4) 中立（ratio=1）でビット一致
- 依存：BB-03

## T01-06 双方向レベラー

`leveler`｜A｜W1｜S｜Codex｜TV｜slot 2

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `high_threshold_db` | f | dBFS | −60〜0 | −14 |
| `down_ratio` | f | :1 | 1〜30 | 3 |
| `low_threshold_db` | f | dBFS | −80〜0 | −34（`high` より 3 dB 以上下。交差検査） |
| `up_ratio` | f | :1 | 1〜10 | 2 |
| `max_gain_db` | f | dB | 0〜24 | 6 |
| `floor_db` | f | dBFS | −120〜−30 | −60 |
| `knee_db` | f | dB | 0〜24 | 6 |
| `attack_ms` | f | ms | 0.05〜300 | 15 |
| `release_ms` | f | ms | 5〜3000 | 250 |
| `rms_window_ms` | f | ms | 1〜300 | 30 |
| `stereo_link` | b | — | — | true |
| `output_db` | f | dB | −24〜12 | 0 |

- アルゴリズム：1 つの検出器から、T01-05 の上向き静特性と `compressor` の下向き静特性を合成した 1 本のゲイン曲線。2 つの閾値の間は 1:1
- テスト：静特性 3 区間 ±0.3 dB、中間区間の定常正弦はビット一致、中立（両 ratio=1）でビット一致
- 依存：BB-03

## T01-07 ゲート／エクスパンダー（音響型）

`gate`｜A｜W1｜S｜Codex｜TV｜slot 2
既存の `edit_gate`（オフラインの無音化。編集段）とは別物で、変えない。

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `threshold_db` | f | dBFS | −80〜0 | −45 |
| `ratio` | f | :1 | 1〜100 | 4（≥ 20 は実質ゲート） |
| `range_db` | f | dB | −90〜0 | −40（最大減衰） |
| `hysteresis_db` | f | dB | 0〜12 | 3（閉じる閾値＝開く閾値−この値） |
| `knee_db` | f | dB | 0〜24 | 3 |
| `attack_ms` | f | ms | 0.05〜100 | 1 |
| `hold_ms` | f | ms | 0〜2000 | 50 |
| `release_ms` | f | ms | 5〜3000 | 150 |
| `lookahead_ms` | f | ms | 0〜20 | 0 |
| `key_lo_hz` | f | Hz | 0〜2000 | 0（検出側 HPF。0＝無効） |
| `key_hi_hz` | f | Hz | 0〜20000 | 0（検出側 LPF。0＝無効） |
| `stereo_link` | b | — | — | true |

- アルゴリズム：下向き伸長の静特性＋ヒステリシスつき状態機械（開／保持／閉）＋先読み（信号側を遅延）。レイテンシ＝round(lookahead_ms·sr/1000)
- 正典：Giannoulis ほか 2012／Zölzer『DAFX』（ノイズゲート、エクスパンダー）
- テスト：(1) 静特性 ±0.3 dB、`range_db` で頭打ち (2) 閾値より 6 dB 以上上の定常信号はビット一致（先読み 0 のとき） (3) ヒステリシス：閾値±1 dB を往復する信号で開閉が 1 回だけ (4) バーストの先頭 5 ms のエネルギー損失：先読み 5 ms で ≤ 0.1 dB (5) 保持・リリース時間の実測 ±10 % (6) CT-5
- 依存：BB-03

## T01-08 パラレルコンプ専用機

`parallel_comp`｜A｜W1｜S｜Codex｜TV｜slot 2
既存 `compressor` に `mix` を足さない（OD-5）。チェーンは直列しか書けないので、並列を 1 型に閉じ込める。

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `threshold_db` | f | dBFS | −60〜0 | −30 |
| `ratio` | f | :1 | 1〜30 | 10 |
| `knee_db` | f | dB | 0〜24 | 3 |
| `attack_ms` | f | ms | 0.05〜300 | 1 |
| `release_ms` | f | ms | 5〜3000 | 80 |
| `detector` | e | — | `peak`／`rms` | `rms` |
| `rms_window_ms` | f | ms | 1〜300 | 5 |
| `wet_makeup_db` | f | dB | −12〜36 | 0 |
| `wet_hpf_hz` | f | Hz | 0〜1000 | 0（0＝無効） |
| `wet_drive_db` | f | dB | 0〜24 | 0（0＝飽和段を通さない） |
| `dry_db` | f | dB | −90〜12 | 0（≤ −90 は完全ミュート） |
| `wet_db` | f | dB | −90〜12 | −12（同上） |

- アルゴリズム：y＝dry·x＋wet·sat(HPF(comp(x)))。comp は既存 `compressor` と同じ計算。sat は既存 `saturator` の tanh（4 倍オーバーサンプル）。飽和段のレイテンシを乾側にも入れて位相を揃える
- テスト：(1) `wet_db=−90, dry_db=0` で入力とビット一致（飽和無効時） (2) `dry_db=−90, wet_hpf_hz=0, wet_drive_db=0` で既存 `compressor`＋ゲインとのヌル ≤ −120 dBFS (3) 乾・湿の時間ずれ 0 サンプル（インパルスの相互相関） (4) バースト：先頭ピーク変化 ≤ +1 dB、減衰部 RMS 増加 ≥ +3 dB（既定値）
- 依存：BB-03、BB-13

### 実装時の確定（統括の判断 D-14）

`parallel_comp` の既定を `wet_makeup_db: 0→17 dB`、`wet_db: −12→−6 dB`、`dry_db: 0→−6 dB`、`attack_ms: 1→0.1 ms`、`detector: rms→peak` と確定した。ID・単項目の範囲は不変。旧 attack/rms のまま makeup だけ18 dBにした比較はピーク +4.2529 dB、減衰部 +3.9547 dBで先頭の条件を満たさず、検出・時定数・乾湿を組として決めた（W1g 実測）。現行値は `describe()` を正とする。

## T01-09 ボリュームシェイパー（描画カーブ周期変調）

`volume_shaper`｜A｜W2｜M｜Codex｜TV｜slot なし（`stages: ["track","bus"]`）
FB2 の `gain_curve`（op。区間ごとの差分）とは別：こちらは 1 周期の形を繰り返すプロセッサ。**FB2 確定後に曲線の補間規則を `director/curve.py` と揃える。**

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `shape` | c | x：周期内位相 0〜1／y：0〜1 | 最大 64 点 | `[[0,0],[0.25,1],[1,1]]` |
| `depth_db` | f | dB | 0〜48 | 6（ゲイン＝−depth·(1−y)） |
| `note` | e | — | `NOTE_VALUES` | `1/4` |
| `bpm` | f | BPM | 0〜400 | 0 |
| `period_ms` | f | ms | 10〜8000 | 500（`note=none` のとき） |
| `origin_s` | f | s | 0〜36000 | 0（位相 0 を置く曲頭からの時刻） |
| `phase` | f | 0..1 | 0〜1 | 0 |
| `smooth_ms` | f | ms | 0〜50 | 2 |
| `band_lo_hz` | f | Hz | 0〜20000 | 0（0＝全帯域） |
| `band_hi_hz` | f | Hz | 0〜24000 | 0（0＝全帯域） |
| `interp` | e | — | `linear`／`smooth` | `linear`（smooth＝単調 3 次） |

- アルゴリズム：曲頭からの絶対サンプル位置で位相を計算（ブロック境界・描画範囲に依らない）。帯域限定時は y＝x＋(g−1)·B(x)（`dynamic_eq` と同じ構造、4 次バンドパス）
- 正典：Fritsch & Carlson「Monotone Piecewise Cubic Interpolation」SIAM J. Numer. Anal. 1980（単調 3 次）
- 決定論：位相は整数サンプル位置から毎回計算する（累積加算しない）
- テスト：(1) `depth_db=0` でビット一致 (2) 定常正弦の包絡が形どおり（各点 ±0.1 dB、`smooth_ms=0`） (3) 周期の実測が音価どおり（±1 サンプル／周期、ドリフトなし：1000 周期後も ±1 サンプル） (4) 帯域限定：帯域外の正弦のレベル変化 ≤ 0.2 dB (5) 途中から描画しても全長描画の該当部分とビット一致
- 弱点：テンポ一定を前提（テンポマップ非対応）
- 依存：BB-00（curve）、BB-05

## T01-10 サイドチェインダッカー専用機（カーブ型）

**op `duck_curve`（mix 段）＋プロセッサ `band_automation`**｜A｜W2｜M｜Codex｜TV
既存 `duck` は変えない（OD-4）。DESIGN_PHILOSOPHY §8 の「相手の側の帯域を限ったダッキング」「バスを相手にしたダッキング」を満たす。

op `duck_curve` の `params`（`duck` と同じ ID は同じ意味・同じ既定の読み方）：

| id | 単位 | 範囲 | 省略時 |
|---|---|---|---|
| `key` | トラック ID | `target` と別の `trk_<stem>` | （必須） |
| `depth_db` | dB | 0.5〜12（範囲可） | 3 |
| `band_lo_hz` | Hz | 0、または 20〜8000 | 0（0＝全帯域＝フェーダーのオートメーション） |
| `band_hi_hz` | Hz | 0、または 60〜20000、`band_lo_hz` の 1.5 倍以上 | 0 |
| `shape` | curve（x：0〜1 の回復区間内位置／y：0〜1 の戻り量） | 最大 32 点、単調非減少 | `[[0,0],[1,1]]` |
| `hold_ms` | ms | 0〜500 | 0 |
| `key_lo_hz`・`key_hi_hz`・`trigger_below_p95_db`・`attack_ms`・`release_note`・`release_ms`・`min_interval_ms` | | `duck` と同じ範囲 | `duck` と同じ |

- `target`：`trk_<stem>` に加えて既存バス・同じ指揮書の `bus_add` の ID を受ける（`master` は `bad_target`）。`section` は書けない
- 展開：全帯域のとき → `duck` と同じ合成規則でオートメーション 1 本へ。帯域限定のとき → 対象のチェーン末尾に `band_automation` を 1 つ足す（`move_ref` 付き）。適用記録に打点一覧（時刻・深さ）と前後測定

プロセッサ `band_automation`（`stages: ["track","bus"]`、slot なし）：

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `lo_hz` | f | Hz | 20〜8000 | 60 |
| `hi_hz` | f | Hz | 60〜20000 | 250 |
| `gain` | c | x：曲頭からの秒／y：dB −24〜+12 | 最大 65536 点 | `[]`（空＝ビット一致の素通し） |
| `slope_db_oct` | e | dB/oct | 12／24 | 12 |

- アルゴリズム：y＝x＋(g(t)−1)·B(x)。B はバターワースのバンドパス。g は点間を dB 直線補間
- 正典：既存 `director/duck.py` と `dynamic_eq`（社内の先行実装が正典）
- テスト：(1) `gain=[]` でビット一致 (2) 帯域中心の正弦で、曲線どおりのゲイン（±0.2 dB） (3) 帯域外 2 オクターブの正弦の変化 ≤ 0.2 dB (4) op：合成キック列をキーに、打点数・手前の開始時刻・回復完了時刻が指定どおり (5) `duck_curve` を含まない指揮書の全出力がバイト同一（G0-4） (6) 全帯域・直線形・同一パラメータで、既存 `duck` と同じオートメーション点列
- 依存：BB-00、BB-03、BB-05、BB-14

### 実装時の確定（統括の判断 D-18）

`duck_curve` の全帯域バス対象には補助型 `gain_automation` を使う。トラックの全帯域は既存のゲイン列、帯域限定は `band_automation` に展開する。補助型はカタログの件数を増やさない。既存 `duck` のパラメータ・検出・出力は変更しない。

## T01-11 ゲインライダー

**op `ride`（mix 段）**｜D｜W4｜M｜Codex｜TV（主役に書けば E3）
プロセッサではない。目標レベルへ向かうフェーダーの線を先に計算して、オートメーションとして書く（DESIGN_PHILOSOPHY §3.1）。

| id | 単位 | 範囲 | 省略時 |
|---|---|---|---|
| `mode` | 列挙 | `self`（自分の活動区間の中央値へ）／`against`（相手に対する差を保つ） | `self` |
| `against` | トラック／バス ID | `mode=against` のとき必須 | — |
| `offset_db` | dB | −12〜12 | 0（`against` のときの目標差） |
| `range_up_db` | dB | 0〜6（範囲可） | 2 |
| `range_down_db` | dB | 0〜6（範囲可） | 2 |
| `window_ms` | ms | 100〜3000 | 400（レベルを測る窓） |
| `smooth_ms` | ms | 50〜2000 | 300（ゼロ位相の平滑） |
| `max_slope_db_s` | dB/s | 1〜40 | 12 |
| `gate_below_db` | dB（活動レベル比） | −72〜−20 | −40（これより下では動かさず直前の値を保つ） |
| `simplify_tol_db` | dB | 0.05〜1 | 0.2（折れ点を間引く許容） |

- `target` はトラック ID だけ。`section` を書ける（その範囲だけ乗る）。同じトラックの `duck`／区間 `gain`／`gain_curve` とは `duck` と同じ規則で 1 本に合成
- アルゴリズム：K 特性の短時間レベル（BS.1770 の重み、`window_ms`）→ 目標との差 → 上下限で切る → ゼロ位相平滑 → 傾き制限 → 折れ点間引き（Ramer–Douglas–Peucker）。適用記録に「区間・動かした量・前後のレベル分布」
- 正典：ITU-R BS.1770-4／EBU Tech 3341（短時間レベル）／Douglas & Peucker 1973（折れ点間引き）
- テスト：(1) 6 dB の階段を持つ合成信号で、出力の短時間レベルの幅が range 設定どおり縮む (2) 動かす量が上下限を超えない、傾きが上限を超えない (3) 無音区間で値を保持 (4) `ride` を含まない指揮書はバイト同一 (5) 同じ入力で点列がビット一致
- 依存：BB-03、BB-05、BB-14

## T01-12 マルチバンドリミッター

`mb_limiter`｜A｜W2｜M｜Codex｜TV｜`master_slot: 5`（最終 `limiter` の前だけ。OD-1）

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| MB ブロック | | | | 既定 `phase` は `linear` |
| `threshold_db` | a | dBFS | −24〜0 | `[]`→ −3（帯域ごとのピーク閾値） |
| `release_ms` | a | ms | 5〜2000 | `[]`→ 100 |
| `lookahead_ms` | f | ms | 0.5〜10 | 2 |
| `stereo_link` | b | — | — | true |
| `out_ceiling_db` | f | dBFS | −24〜0 | −0.3（合算後の広帯域ピーク段） |

- アルゴリズム：帯域ごとに先読みピークリミッター（ピーク保持→最小値フィルタ→和が 1 の窓で平滑：出力が閾値を超えないことが構成から保証される）→ 加算 → 同じ構造の広帯域段。**サンプルピークの保証で、トゥルーピークは保証しない**（実測値を記録に残す）
- 正典：Hämäläinen「Smoothing of the Control Signal Without Clipped Output in Digital Peak Limiters」DAFx-02／Zölzer『DAFX』（リミッター）
- テスト：(1) 出力サンプルピーク ≤ `out_ceiling_db`（ランダムなパラメータと素材の性質テスト） (2) 帯域単独のピークが閾値以下（±0.05 dB） (3) 全閾値 0 dBFS・入力ピーク −6 dBFS で遅延補償後のヌル ≤ −120 dBFS (4) 1 kHz 定常正弦・GR 3 dB で THD ≤ −60 dB (5) CT-5
- 依存：BB-02、BB-03

## T01-13 適応型（ダイナミック）リミッター

`adaptive_limiter`｜B｜W3｜L｜**Opus 中**｜TV｜`master_slot: 5`（OD-1。最終段の代替にはしない）

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `ceiling_db` | f | dBFS | −24〜0 | −1.0 |
| `drive_db` | f | dB | 0〜24 | 0 |
| `lookahead_ms` | f | ms | 1〜10 | 4 |
| `release_min_ms` | f | ms | 5〜200 | 30 |
| `release_max_ms` | f | ms | 100〜3000 | 600 |
| `adapt` | f | 0..1 | 0〜1 | 0.7（0＝`release_min_ms` 固定） |
| `transient` | f | 0..1 | 0〜1 | 0.3（速い段の受け持ち割合） |
| `stereo_link` | f | 0..1 | 0〜1 | 1 |
| `oversample` | e | x | 1／2／4／8 | 4（検出側） |

- アルゴリズム：2 段構成。(a) 速い段：孤立ピークを先読み窓で処理（T01-12 と同じ超過なし構造）。(b) 遅い段：GR の包絡。リリース時定数を「直近の GR の持続度（GR の時間積分と最大値の比）とクレスト」から `release_min`〜`release_max` の間で連続に選ぶ。孤立ピーク→速い、持続的な超過→遅い（低域の歪みとポンピングを避ける）。検出はオーバーサンプルした絶対値（サンプル間ピークを見るが、TP の保証は主張しない。実測 TP を記録）
- 正典：Giannoulis ほか 2012（プログラム依存リリースの節）／Hämäläinen DAFx-02／ITU-R BS.1770-4 Annex 2（TP の測り方）／Zölzer『DAFX』。**調査レッグが先**：プログラム依存リリースの公開された定式化を 2〜3 通り集め、選ぶ
- 決定論：適応は因果的な状態だけから決める（全曲の先読み統計を使わない。途中からの描画でも一致させるため、状態の初期化規則を spec 化する）
- テスト：(1) 出力のオーバーサンプル後ピーク ≤ `ceiling_db` ＋0.1 dB（検出と同じ倍率で） (2) `adapt=0` で固定リリースの参照実装と一致 (3) 孤立クリック後の回復時間 ≤ `release_min_ms`×3、50 Hz 定常・GR 6 dB で GR リップル ≤ 0.5 dB かつ THD ≤ −50 dB (4) 天井未満の入力は遅延補償後ヌル ≤ −120 dBFS (5) 同じ GR 量で、固定リリース 30 ms に比べ低域 THD が下がり、固定 600 ms に比べ孤立ピーク後のレベル欠損（100 ms 窓）が小さい（比較の数値を記録）
- 依存：BB-03、BB-13

## T01-14 多段リミッターチェイン

`limiter_chain`｜A｜W3（T01-13 に依存するため）｜S｜Codex｜コンポジット｜`master_slot: 5`

展開：`compressor` → `clipper` → `dynamic_eq`（high_shelf。HF リミッター役）→ `adaptive_limiter`。各段は `*_on=false` で展開から外す。

| id | 型 | 範囲 | 既定 | 展開先 |
|---|---|---|---|---|
| `comp_on` | b | — | true | |
| `comp_threshold_db` | f | −60〜0 | −12 | `compressor.threshold_db`（ratio=2、knee=6、attack=30、release=200 固定） |
| `clip_on` | b | — | true | |
| `clip_ceiling_db` | f | −24〜0 | −1.5 | `clipper.ceiling_db`（mode=soft、softness=0.3） |
| `clip_drive_db` | f | 0〜24 | 0 | `clipper.drive_db` |
| `hf_on` | b | — | false | |
| `hf_freq_hz` | f | 2000〜16000 | 8000 | `dynamic_eq.freq_hz`（shape=high_shelf） |
| `hf_threshold_db` | f | −80〜0 | −24 | `dynamic_eq.threshold_db` |
| `hf_range_db` | f | −24〜0 | −4 | `dynamic_eq.range_db` |
| `peak_on` | b | — | true | |
| `peak_ceiling_db` | f | −24〜0 | −1.0 | `adaptive_limiter.ceiling_db` |
| `peak_release_ms` | f | 5〜200 | 30 | `adaptive_limiter.release_min_ms` |

- テスト：(1) 展開後の列を手で書いたチェーンとビット一致 (2) レンダリング記録に展開後の 4 項目が残る (3) 全段 off でビット一致の素通し (4) 展開後の各項目に既存の範囲検査が掛かる
- 依存：BB-00（コンポジット）、T01-13

---

## 実装単位（発注の粒度）

| 単位 | 中身 | 前提 | 量 | 実働 |
|---|---|---|---|---|
| U-01a | `gate`、`upward_compressor`、`leveler`、`transient_shaper` | BB-03 | S×4 | Codex |
| U-01b | `mb_compressor`（T01-15 含む）、`mb_expander`、`mb_transient` | BB-02、U-01a | M＋S＋S | Codex |
| U-01c | `parallel_comp` | BB-03、BB-13 | S | Codex |
| U-01d | `volume_shaper`、`band_automation`、op `duck_curve` | BB-00、05、14、FB2 確定 | M＋M | Codex |
| U-01e | `mb_limiter` | BB-02、03 | M | Codex |
| U-01f | `adaptive_limiter` | 調査レッグ、BB-03 | L | Opus 中 |
| U-01g | `limiter_chain` | BB-00、U-01f | S | Codex |
| U-01h | op `ride` | BB-14、FB2 確定 | M | Codex |
### 実装時の確定（統括の判断 D-21）

`limiter_chain` は `describe()` のとおり track/bus 限定。全段 on の順序は slot 2→5→2→5となり、既存のマスターの非減少順検査と両立しないため master には置かない（W3d）。全 off は D-21(b) に従い空展開 `expansion: []` を監査用 bypass 記録1件で表し、素通しする。旧報告の代替 gain 段は最終形では使わない。子の捏造・順序検査の変更はしない。
