# spec/03 リバーブ（11 件）

カタログ §3。共通規約は `spec/01_dynamics.md` §0。既存 `reverb`（プレート系 FDN）は変えない。

## 0. カテゴリ共通

- 全型：`stages: ["track","bus"]`、`master_slot: None`、`realtime.allocates: True`。`channel` 欄は不可（spec/02 T02-02）
- 実行 2 方式（BB-10）：
  - `lti`：自分のインパルス応答を描画し、FFT 畳み込みで当てる（既存 `reverb` と同じ。入力の終わりより後の尾は描画しない、も同じ）
  - `tv`：時間領域のループ（変調・凍結・ループ内ピッチシフトがある型）。曲頭から描画した結果が正で、途中からの描画は曲頭からの状態を再生して作る（結果は一致させる）
- 実測ベクトルの記録（R-10）：`lti` の型は自分の IR から、帯域別 RT60・初期／後期比・直接／残響比・モノ合算損失を記録に残す（既存 `reverb` と同じ項目）。`tv` の型は「変調を止めた状態の IR」から測り、その旨を記す
- 乱数：遅延長の選択・タップ列・変調の位相に使う。全部 `seed` から（§0.4）

**RV ブロック（共通パラメータ）**

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `rt60_s` | f | s | 型ごと | 型ごと |
| `predelay_ms` | f | ms | 0〜250 | 20 |
| `mix` | f | 0..1 | 0〜1 | 0.2（1＝センド用の 100 % ウェット。`mix=0` はビット一致の素通し） |
| `lowcut_hz` | f | Hz | 20〜2000 | 300 |
| `highcut_hz` | f | Hz | 1000〜20000 | 8000（0.45×sr 以上では掛けない） |
| `bpm` | f | BPM | 0〜400 | 0（プリディレイと RT60 を音価で記録するためだけ。R-11） |
| `seed` | i | — | 0〜65535 | 0 |
| SD ブロック | | | | spec/01 §0.6（`duck_db=0` で無効） |

**共通テスト（RT）**：(RT1) `mix=0` でビット一致 (RT2) 帯域別 RT60 の実測（シュレーダー積分、T20）が宣言値×倍率に対し ±10 %（個別に緩める型はそこに書く） (RT3) CT-8（入力停止後に減衰し切る） (RT4) 同一 `seed` でビット一致、別 `seed` で IR が異なり、RT60 は ±5 % 以内で同じ (RT5) 後期の尾の左右相関 |ρ| ≤ 0.3（ステレオ、幅最大） (RT6) 尾のスペクトルに突出した鳴きが無い：1/3 oct 平滑した尾のスペクトルで、隣接帯との差 ≤ 6 dB

カテゴリの正典（最初に読む）：Välimäki, Parker, Savioja, Smith, Abel「Fifty Years of Artificial Reverberation」IEEE TASLP 2012／J. O. Smith『Physical Audio Signal Processing』（オンライン公開）／Schroeder「New Method of Measuring Reverberation Time」JASA 1965／ISO 3382-1（指標の定義）。**Dragonfly Reverb ほか GPL 実装は読まない。**

---

## T03-01 コンボリューション（IR）リバーブ

`conv_reverb`｜A｜W2｜M｜Codex｜`lti`
FB2 の「部屋 IR」（`scene.room`）と同件。**FB2 確定後に、部屋の宣言から本型の `ir` を引く経路を突き合わせる（FB2 が正）。**

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `ir` | as | `irs` レジストリ | 登録済み ID | `synth_room_a`（同梱の自作合成） |
| `start_ms` | f | ms | 0〜500 | 0（IR の頭を切る） |
| `length_s` | f | s | 0.05〜20 | 20（これより後を切る。末尾 `fade_ms`） |
| `fade_ms` | f | ms | 1〜500 | 50 |
| `decay` | f | 倍 | 0.25〜1 | 1（RT60 を縮める指数窓。伸ばす方向は無い） |
| `gain_mode` | e | — | `energy`／`peak`／`none` | `energy`（IR のエネルギーを 1 に正規化） |
| `predelay_ms`・`mix`・`lowcut_hz`・`highcut_hz`・`bpm`・SD | | | RV | RV |

- IR のチャンネル：1（各入力チャンネルに同じ IR）／2（L→L、R→R。モノ入力はステレオ出力）／4（LL・LR・RL・RR の真ステレオ）
- IR 資産（BB-08）：`registry/irs.json` に `id`・`sha256`・`sr`・`channels`・`length_s`・`origin`（`synthetic`：生成器と引数とシード／`measured`：誰がどこで）・`license`（`spdx`・`evidence`・`checked_on`）・`tier`（`official`／`byo`）
  - **同梱（`official`）は自作合成（本プログラムの残響型や鏡像法で生成スクリプトから作る）と、CC0 を一次資料で確認したものだけ**。第三者の測定 IR・製品付属 IR は同梱しない（PM_PLAN OD-7）
  - 持ち込み（`byo`）はローカル登録。正本には ID と sha256 だけ。ライセンス欄は必須（不明なら「不明」と書けるが警告し、Mix Report に残す。BYOW と同じ規則）
  - sr が違えば既存 `resample` の核で変換（変換後のハッシュもキャッシュ鍵に入れる）
- 正典：Gardner「Efficient Convolution without Input-Output Delay」JAES 1995／Wefers『Partitioned Convolution Algorithms for Real-Time Auralization』（学位論文、2015。native 移植時）／ISO 3382-1
- テスト（RT1・RT3 に加えて）：(1) IR＝単位インパルスで入力とヌル ≤ −120 dBFS (2) IR＝遅延・減衰インパルスで遅延とゲインが厳密 (3) 短い信号で直接畳み込みとのヌル ≤ −120 dBFS (4) sha256 不一致・未登録 ID は明示エラー（黙って素通ししない） (5) 44.1k の IR を 48k・96k で使い、RT60 が ±2 % (6) 4 チャンネル IR の経路行列 (7) `decay=0.5` で RT60 が 0.5 倍 ±5 % (8) R-10 のベクトルが記録される (9) `ir` のライセンス欄が無いレジストリは検証で落ちる
- 依存：BB-00（asset）、BB-07、BB-08

## T03-02 アルゴリズミック・ホール／ルーム

`reverb_hall`｜A｜W2｜M（BB-10 の後）｜Codex｜`mod_depth=0` で `lti`、>0 で `tv`

RV（`rt60_s` 0.2〜20、既定 2.2）に加えて：

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `size_m` | f | m | 3〜60 | 25（遅延長と初期反射の間隔。小さい値がルーム） |
| `diffusion` | f | 0..1 | 0〜1 | 0.7 |
| `er_late_db` | f | dB | −24〜24 | 0 |
| `rt60_low_mult` | f | 倍 | 0.1〜4 | 1.2 |
| `rt60_high_mult` | f | 倍 | 0.1〜4 | 0.6 |
| `low_xover_hz` | f | Hz | 100〜1000 | 250 |
| `high_xover_hz` | f | Hz | 1000〜12000 | 4000 |
| `width` | f | 0..1 | 0〜1 | 1 |
| `mod_depth` | f | 0..1 | 0〜1 | 0 |
| `mod_rate_hz` | f | Hz | 0.05〜5 | 0.5 |

- アルゴリズム：初期反射タップ（`size_m` から）→ 全通過拡散 → 16 本 FDN（互いに素な遅延長を `size_m` と `seed` から決める。直交行列。各線に帯域別吸収フィルタ：宣言 RT60 から線ごとの減衰量を解析的に決める）→ 出力タップの行列でステレオ化
- 正典：Schroeder「Natural Sounding Artificial Reverberation」JAES 1962／Moorer「About This Reverberation Business」CMJ 1979／Jot & Chaigne「Digital Delay Networks for Designing Artificial Reverberators」AES 90th 1991／Schlecht & Habets「On Lossless Feedback Delay Networks」IEEE TSP 2017／Rocchesso & Smith 1997（IEEE TSAP）／Abel & Huang「A Simple, Robust Measure of Reverberation Echo Density」AES 121st 2006
- テスト（RT1〜6 に加えて）：(1) 正規化エコー密度（Abel & Huang）が 0.9 に達する時刻 ≤ `size_m` から導く上限（既定で 150 ms） (2) 最初の反射の到達時刻が `size_m` に対して単調 (3) `mod_depth=0` で、`tv` の核で描画した結果と `lti` の結果のヌル ≤ −100 dBFS（核の整合） (4) `mod_depth>0`：定常正弦の尾の周波数偏移 ≤ ±10 セント
- 依存：BB-09、BB-10

## T03-03 ヴィンテージ・デジタル

`reverb_vintage`｜B｜W3｜L｜**Opus 中**（声づくりの判断が重い）｜既定で `tv`

RV（`rt60_s` 0.3〜20、既定 2.5）に加えて：

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `input_diffusion` | f | 0..1 | 0〜1 | 0.75 |
| `tank_diffusion` | f | 0..1 | 0〜1 | 0.6 |
| `damping_hz` | f | Hz | 1000〜20000 | 6000 |
| `bass_mult` | f | 倍 | 0.5〜2 | 1.2 |
| `mod_depth` | f | 0..1 | 0〜1 | 0.3 |
| `mod_rate_hz` | f | Hz | 0.1〜3 | 1 |
| `bandwidth_hz` | f | Hz | 4000〜20000 | 10000（内部帯域の上限） |
| `bits` | e | bit | 0／12／14／16 | 0（0＝量子化なし。それ以外はシード付き TPDF を足して内部を量子化） |

- アルゴリズム：入力拡散（全通過 4 段）→ 8 の字に交差する 2 本の全通過ループ・タンク（各ループに変調つき全通過・遅延・減衰・ダンピング）→ タンク内の複数タップの和でステレオ出力。係数と構造は論文に全て公開されているものを出発点にし、遅延長は sr に比例して換算
- 正典：Dattorro「Effect Design, Part 1: Reverberator and Other Filters」JAES 1997（構造と係数が載っている。これを正とする）／Griesinger「Practical Processors and Programs for Digital Reverberation」AES 7th Conf. 1989／Blesser「An Interdisciplinary Synthesis of Reverberation Viewpoints」JAES 2001。**実機の ROM・ファームウェア・逆アセンブル資料は読まない**
- テスト（RT1・3・4・5 に加えて。RT2 は ±15 %）：(1) `mod_depth=0, bits=0` の IR が論文の構造から計算した参照 IR とヌル ≤ −100 dBFS (2) `mod_depth>0`：尾の周波数偏移 ≤ ±15 セント、同一シードでビット一致 (3) `bits=12`：無入力時の出力は 0（ゲートされる）、入力時の雑音床が 6.02·bits＋1.76 dB の理論値 ±3 dB (4) `bandwidth_hz` より上 1 オクターブで尾が −24 dB 以下
- 弱点：「あの機種」ではなく「同じ系統の構造」。型名にも機種名を使わない
- 依存：BB-09、BB-10（tv）

## T03-04 チェンバー

`reverb_chamber`｜A｜W2｜S（T03-02 の後。同じ核の別構成）｜Codex｜`lti`

RV（`rt60_s` 0.3〜8、既定 1.8、`predelay_ms` 既定 5）に加えて：`size_m`（f、2〜15、6）、`density`（f、0〜1、0.9）、`rt60_low_mult`（f、0.1〜4、1.0）、`rt60_high_mult`（f、0.1〜4、0.8）、`distance`（f、0〜1、0.5：近いほど初期の立ち上がりが速い）、`width`（f、0〜1、1）。

- アルゴリズム：離散的な初期反射を置かず、直列全通過で最初から密にしてから 8 本 FDN（短い遅延長）。`distance` は尾の立ち上がり包絡（0〜40 ms）を決める
- 正典：T03-02 と同じ＋Kuttruff『Room Acoustics』（小空間のエコー密度と固有振動の式）
- テスト（RT1〜6 に加えて）：(1) 正規化エコー密度が 30 ms 以内に 0.9 (2) 先頭 50 ms に孤立した強い反射が無い（包絡のピーク対中央値 ≤ 6 dB） (3) `distance` に対して立ち上がり時間が単調
- 依存：BB-10

## T03-05 スプリングリバーブ

`reverb_spring`｜B｜W3｜L（調査レッグが先）｜Codex｜`lti`（`drive_db` は前段）

RV（`rt60_s` 0.5〜6、既定 2.5、`lowcut_hz` 既定 100、`highcut_hz` 既定 6000、`predelay_ms` 既定 0）に加えて：

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `springs` | i | 本 | 1〜3 | 2 |
| `delay_ms` | f | ms | 20〜80 | 45（バネの往復時間。本ごとに `seed` でずらす） |
| `chirp_hz` | f | Hz | 2000〜8000 | 4300（分散が切り替わる周波数） |
| `dispersion` | f | 0..1 | 0〜1 | 0.7 |
| `damping_hz` | f | Hz | 1000〜12000 | 5000 |
| `drive_db` | f | dB | 0〜12 | 0（0＝飽和段を通さない） |

- アルゴリズム：分散性の全通過連鎖（伸長した全通過を数十〜百段）＋遅延のフィードバック・ループ。低域側（`chirp_hz` より下）の強いチャープと高域側の弱いチャープの 2 経路。論文のパラメトリック構造をそのまま出発点にする
- 正典：Välimäki, Parker & Abel「Parametric Spring Reverberation Effect」JAES 2010（これを正とする）／Abel, Berners, Costello & Smith「Spring Reverb Emulation Using Dispersive Allpass Filters in a Waveguide Structure」AES 121st 2006／Parker & Bilbao「Spring Reverberation: A Physical Perspective」DAFx-09／Bilbao & Parker「A Virtual Model of Spring Reverberation」IEEE TASLP 2010
- テスト（RT1・3・4 に加えて。RT2 は ±15 %、RT6 は適用しない＝チャープは仕様）：(1) 最初の反響の群遅延が 200 Hz〜`chirp_hz` で周波数に対し単調（向きは論文の記述に合わせ、調査レッグが確定） (2) 反響の間隔が `delay_ms` ±5 % (3) `springs` 本数ぶんの反響列が分離して数えられる (4) `drive_db=0` で線形（入力 −20 dB で応答同一）
- 依存：BB-09、BB-10、BB-13

## T03-06 シマーリバーブ

`reverb_shimmer`｜B｜W3｜L（BB-11 の後）｜Codex｜`tv`

RV（`rt60_s` 0.5〜30、既定 6）に加えて：

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `shift_semitones` | f | 半音 | −12〜24 | 12 |
| `shimmer` | f | 0..1 | 0〜1 | 0.5（シフトした帰還の量。0＝通常の残響） |
| `grain_ms` | f | ms | 20〜200 | 80（シフタの粒長） |
| `diffusion` | f | 0..1 | 0〜1 | 0.8 |
| `damping_hz` | f | Hz | 1000〜20000 | 7000 |
| `mod_depth` | f | 0..1 | 0〜1 | 0.2 |

- アルゴリズム：T03-02 の FDN の帰還路に、遅延線 2 タップ交差型のピッチシフタ（BB-11a）を並列に入れる。帰還の総ゲインは 0.98 以下に制約（`shimmer` と RT60 から計算して上限を掛ける。ループ内に安全用のソフトリミッタ）
- 正典：Välimäki ほか 2012（総説）／Zölzer 編『DAFX』（遅延線変調によるピッチシフト）／Laroche & Dolson「New Phase-Vocoder Techniques for Pitch-Shifting, Harmonizing and Other Exotic Effects」WASPAA 1999（BB-11c）
- テスト（RT1・3・4 に加えて）：(1) 440 Hz のバースト入力、`shift=12`：尾の 880 Hz 成分／440 Hz 成分の比が時間とともに増え、`shimmer` に対し単調 (2) `shimmer=0` で、同じ設定の `reverb_hall` 相当の核とヌル ≤ −100 dBFS (3) 全パラメータ最大（`shimmer=1`、`rt60_s=30`）でフルスケール入力 60 s：出力が有限、入力停止後に減衰 (4) シフト量の実測が ±10 セント
- 依存：BB-10（tv）、BB-11

## T03-07 ゲーテッド／ノンリニアリバーブ

`reverb_gated`｜A｜W2｜M｜Codex｜`mode=nonlin` は `lti`、`keyed` は TV

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `mode` | e | — | `nonlin`（IR の包絡そのものを切る）／`keyed`（残響の返りを乾音で開閉） | `nonlin` |
| `gate_ms` | f | ms | 50〜1000 | 250 |
| `note` | e | — | `NOTE_VALUES` | `none`（`gate_ms` を音価で与える。`bpm` 必須） |
| `shape` | e | — | `flat`／`decay`／`ramp_up` | `flat`（`nonlin` の包絡） |
| `density` | f | 0..1 | 0〜1 | 0.8 |
| `damping_hz` | f | Hz | 1000〜20000 | 8000 |
| `width` | f | 0..1 | 0〜1 | 1 |
| `rt60_s` | f | s | 0.3〜10 | 2（`keyed` の元残響） |
| `threshold_db` | f | dBFS | −60〜0 | −30（`keyed`） |
| `hold_ms` | f | ms | 10〜1000 | 150（`keyed`） |
| `release_ms` | f | ms | 5〜500 | 30（`keyed`） |
| `predelay_ms`・`mix`・`lowcut_hz`・`highcut_hz`・`bpm`・`seed` | | | RV | RV |

- アルゴリズム：`nonlin`：シード付きのベルベットノイズ（疎な ±1 パルス列。密度は `density`）に包絡（`flat` は末尾 5 ms のフェードで切る）とダンピングを掛けた IR。`keyed`：T03-02 の核の返りに T01-07 のゲート（検出は乾音）
- 正典：Karjalainen & Järveläinen「Reverberation Modeling Using Velvet Noise」AES 30th Conf. 2007／Välimäki, Holm-Rasmussen, Alary & Lehtonen「Late Reverberation Synthesis Using Filtered Velvet Noise」Applied Sciences 2017
- テスト（RT1・3・4 に加えて。RT2 は適用しない）：(1) `nonlin`：`predelay_ms`＋`gate_ms`＋10 ms 以降のウェットが相対 −80 dB 以下 (2) `flat`：ゲート内の 50 ms 窓 RMS が ±2 dB (3) IR のスペクトルが平坦（1/3 oct で ±3 dB、ダンピング補正後） (4) `keyed`：スネア状バースト列で、返りが保持後に `release_ms` ±10 % で閉じる
- 依存：BB-03、BB-07、BB-10

## T03-08 リバースリバーブ

`reverb_reverse`｜A｜W2｜S（T03-07 の後）｜Codex｜`mode=true` は `offline_only` 相当（非因果）

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `mode` | e | — | `envelope`（因果。立ち上がる包絡の残響が音の後に付く）／`true`（非因果。残響が音の手前から膨らんで音の頭で終わる） | `envelope` |
| `length_ms` | f | ms | 100〜4000 | 800 |
| `note` | e | — | `NOTE_VALUES` | `none` |
| `gap_ms` | f | ms | 0〜100 | 0（`true`：膨らみの終わりと音の頭の間） |
| `rt60_s` | f | s | 0.3〜10 | 2（`true` の元残響） |
| `density`・`damping_hz`・`width` | | | T03-07 と同じ | 同じ |
| `mix`・`lowcut_hz`・`highcut_hz`・`bpm`・`seed` | | | RV | RV |

- アルゴリズム：`envelope`＝T03-07 の `ramp_up` 包絡 IR。`true`＝元残響の IR を `length_ms` で切って時間反転し、畳み込んだ結果を `length_ms`＋`gap_ms` だけ手前へずらす（オフラインなので可能。線形・時不変のまま）。曲頭より前に出る分は捨て、捨てた量を記録に残す
- テスト：(1) `true`：時刻 t0 のインパルスに対し、ウェットのエネルギーが全て [t0−length−gap, t0−gap] にあり、50 ms 窓 RMS が単調増加（±2 dB） (2) `true` のウェットの振幅スペクトルが、同じ元残響を順方向に掛けたものと一致（±0.5 dB、1/3 oct） (3) `envelope`：全ウェットが [t0, t0+length] (4) RT1・RT4
- 依存：BB-07、T03-07

## T03-09 アーリーリフレクション専用機

`early_reflections`｜A｜W2｜M｜Codex｜`lti`
Dragonfly Early Reflections（GPL）は読まない。**FB2 の `scene.room` の宣言と寸法の対応を、FB2 確定後に突き合わせる。**

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `room_w_m` | f | m | 2〜50 | 8 |
| `room_l_m` | f | m | 2〜80 | 12 |
| `room_h_m` | f | m | 2〜20 | 4 |
| `absorption` | f | 0..1 | 0.05〜0.9 | 0.3（壁の吸音率。全面共通） |
| `distance_m` | f | m | 0.5〜30 | 3（音源と聴取点の距離） |
| `azimuth` | f | −1..1 | −1〜1 | 0（`pan.position` と同じ座標） |
| `max_order` | i | 次 | 1〜6 | 3 |
| `max_ms` | f | ms | 20〜200 | 80 |
| `damping_hz` | f | Hz | 1000〜20000 | 10000（反射 1 回ごとの高域損失） |
| `direct` | b | — | — | false（直接音のタップを含めるか） |
| `width`・`mix`・`lowcut_hz`（既定 100）・`highcut_hz`（既定 12000） | | | RV | RV |

- アルゴリズム：直方体の鏡像法。聴取点は部屋の中心から固定の比率でずらした点（規則を spec 化して決定的に）。各鏡像の到達時刻（分数サンプルは窓付き sinc で置く）、ゲイン＝1/距離×(1−吸音率)^(次数/2)、方位から等パワーのパン。`max_ms` 以降は置かない
- 正典：Allen & Berkley「Image Method for Efficiently Simulating Small-Room Acoustics」JASA 1979（これを正とする）／Lehmann & Johansson「Prediction of Energy Decay in Room Impulse Responses Simulated with an Image-Source Model」JASA 2008／Kuttruff『Room Acoustics』
- テスト：(1) 1 次反射 6 本の到達時刻が幾何の計算値 ±1 サンプル、ゲインが式どおり ±0.1 dB (2) タップ数が次数の理論値どおり (3) `max_ms` 以降のウェットが 0 (4) `azimuth` を反転すると左右が入れ替わる (5) RT1 (6) IR のモノ合算損失を記録
- 依存：BB-07、BB-09

## T03-10 フリーズ／インフィニットリバーブ

`reverb_freeze`｜B｜W3｜M（BB-10 `tv` の後）｜Codex｜`tv`

RV（`rt60_s` 0.3〜60、既定 4）に加えて：

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `freeze_start_s` | a | s | 0〜36000、最大 16 個、昇順 | `[]` |
| `freeze_end_s` | a | s | 同数。各々対応する開始より後で、次の開始より前 | `[]` |
| `freeze_fade_ms` | f | ms | 5〜2000 | 50 |
| `freeze_input` | e | — | `mute`／`pass` | `mute`（凍結中にタンクへ入れるか） |
| `size_m` | f | m | 3〜60 | 30 |
| `diffusion` | f | 0..1 | 0〜1 | 0.8 |
| `damping_hz` | f | Hz | 1000〜20000 | 8000 |
| `mod_depth` | f | 0..1 | 0〜1 | 0 |

- アルゴリズム：直交行列の FDN。凍結区間では、吸収フィルタを `freeze_fade_ms` で迂回へ交差させて帰還を厳密に無損失にし、入力ゲインを 0 へ。区間の時刻は曲頭からの絶対時刻（オフラインなので時刻で書ける。リアルタイムの「ボタン」ではない）
- 正典：Jot & Chaigne 1991／Schlecht & Habets 2017（無損失の条件）／Rocchesso & Smith 1997
- テスト（RT1・3・4 に加えて）：(1) 凍結 10 s の間、尾のエネルギーの変動 ≤ 0.1 dB、スペクトル重心の変動 ≤ 1 %（`mod_depth=0`） (2) 凍結の終了後、RT60 が宣言 ±15 % で減衰 (3) 配列が空のとき、同じ設定の通常残響として動く (4) 区間の重なり・順序違い・個数不一致は拒否 (5) `freeze_input=mute`：凍結中に入れた音がウェットに現れない
- 依存：BB-10（tv）

## T03-11 ダッキングリバーブ

**新しい型を作らない**｜A｜W2｜S｜Codex。2 つの経路で満たす。

1. 新しい残響型は全部 SD ブロック（spec/01 §0.6）を持つ：`duck_db > 0` で、乾音が鳴っている間だけウェットが下がる
2. 既存 `reverb`（変えない）は、センドバスに置き、op `duck_curve`（spec/01 T01-10。`target` にバス、`key` に送り元のトラック）で返りを下げる。DESIGN_PHILOSOPHY §3.3 の配線そのもの

- テスト：(1) 500 ms のトーンバースト列：バースト中のウェットが `duck_db` ±1 dB 下がり、バースト後 `duck_release_ms`×3 以内に戻る (2) `duck_db=0`：SD ブロックを持たない描画とビット一致 (3) 経路 2：`duck_curve` のバス対象のテスト（spec/01 T01-10 (4)）
- 依存：BB-14

---

## 実装単位

| 単位 | 中身 | 前提 | 量 | 実働 |
|---|---|---|---|---|
| U-03a | BB-10 残響核（FDN、全通過ループ、`lti`／`tv`、RT60→吸収の解析式、試験の RT 群） | BB-09、BB-01 | L | Opus 中 |
| U-03b | `reverb_hall`、`reverb_chamber` | U-03a | M＋S | Codex |
| U-03c | `conv_reverb`、IR レジストリ、同梱 IR の生成スクリプト | BB-00、07、08、FB2 確定 | M | Codex |
| U-03d | `reverb_gated`、`reverb_reverse` | BB-07、U-03a | M＋S | Codex |
| U-03e | `early_reflections` | BB-07、09、FB2 確定 | M | Codex |
| U-03f | `reverb_vintage` | U-03a | L | Opus 中 |
| U-03g | `reverb_spring` | 調査レッグ、U-03a | L | Codex |
| U-03h | `reverb_shimmer`、`reverb_freeze` | U-03a、BB-11 | L＋M | Codex |
| U-03i | SD ブロック（全残響型へ）と T03-11 の試験 | BB-14 | S | Codex |
