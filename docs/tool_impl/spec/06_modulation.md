# spec/06 モジュレーション（12 件）

カタログ §6。共通規約は `spec/01_dynamics.md` §0。遅延線は spec/04 §0 の核（BB-09）。タグは 2 代目 PM が付けた。

## 0. カテゴリ共通

- 全型：`stages: ["track","bus"]`、`master_slot: None`、TV、`realtime.allocates: True`。`channel` 欄は可（`rotary`・`chorus`・`adt` を除く：モノ→ステレオ化する型）
- LFO の位相は**曲頭からの絶対サンプル位置**から毎回計算する（累積しない。途中からの描画が一致する。T01-09 と同じ）
- 変調する遅延の読み出しはラグランジュ 3 次（spec/04 §0 の規則「変調の速い型」）。フランジャーの 0 遅延通過（through-zero）は乾側に固定遅延を入れて作り、その分をレイテンシとして宣言
- 帰還の安全：帰還つきの型は |`feedback`| ≤ 0.95、ループ内利得 ≤ 1（CT-8）
- 乾音の経路は `mix=0` でビット一致

**MOD ブロック（共通パラメータ）**

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `rate_hz` | f | Hz | 0.01〜20（型ごとに上限を上書き） | 型ごと |
| `note` | e | — | `NOTE_VALUES` | `none`（LFO 1 周期の音価。`bpm>0` 必須） |
| `bpm` | f | BPM | 0〜400 | 0 |
| `depth` | f | 0..1 | 0〜1 | 型ごと |
| `lfo_shape` | e | — | `sine`／`triangle`／`random` | `sine`（`random`＝シード付きランダムウォーク、帯域 ≤ `rate_hz`） |
| `stereo_phase` | f | 0..1 | 0〜1 | 型ごと（左右の LFO 位相差。周期に対する比） |
| `origin_s` | f | s | 0〜36000 | 0（LFO 位相 0 の時刻） |
| `phase` | f | 0..1 | 0〜1 | 0 |
| `mix` | f | 0..1 | 0〜1 | 型ごと |
| `seed` | i | — | 0〜65535 | 0 |

**共通テスト（MT）**：(MT1) `mix=0` でビット一致 (MT2) `depth=0` で「変調なしの同じ構造」（各件に定義）と一致 (MT3) LFO 周期の実測が宣言どおり、1000 周期後もずれ ±1 サンプル (MT4) 途中から描画しても全長描画の該当部分と一致 (MT5) `stereo_phase=0` で左右同一（ステレオ入力が左右同一のとき）、`0.5` で変調が逆相 (MT6) 同一 `seed` でビット一致 (MT7) モノ合算損失を記録（R-10）

カテゴリの正典（最初に読む）：Dattorro「Effect Design, Part 2: Delay-Line Modulation and Chorus」JAES 1997／Zölzer 編『DAFX』（変調と復調、遅延系の章）／J. O. Smith『Physical Audio Signal Processing』（フランジ、フェイズ、時間変化遅延）／Laakso ほか 1996（分数遅延）

---

## T06-01 コーラス一族

`chorus`｜A｜W2｜M｜Codex

MOD（`rate_hz` 既定 0.6、`depth` 0.5、`stereo_phase` 0.25、`mix` 0.5）に加えて：

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `model` | e | — | `clean`／`bbd`／`dual`／`tri`／`ensemble` | `clean` |
| `delay_ms` | f | ms | 2〜40 | 12（中心の遅延） |
| `depth_ms` | f | ms | 0〜10 | 3（`depth`=1 のときの振れ幅。`delay_ms` を下回る分は切る） |
| `voices` | i | 本 | 1〜4 | 2（`clean`・`bbd` のとき。位相を等分） |
| `feedback` | f | −1..1 | −0.5〜0.5 | 0 |
| `highcut_hz` | f | Hz | 0〜20000 | 0（ウェット側。0＝無効。`bbd` は内部で追従フィルタを持つ） |
| `lowcut_hz` | f | Hz | 0〜1000 | 0 |
| `width` | f | 0..1 | 0〜1 | 1（声部の左右への散らし） |

- `model`（方式名。機種名ではない）：
  - `clean`：補間遅延線の多声コーラス
  - `bbd`：遅延部を T04-02 の BBD モデルに差し替え（クロック変調。圧伸あり）
  - `dual`：2 本の遅延を**逆相の LFO** で動かし、左右へ交差配分（音程の揺れが打ち消し合い、うねりの少ない広がりになる方式）。`rate_hz` は内部で 2 つの固定比の和にしない：書いた値 1 つで動く
  - `tri`：3 本、LFO 位相 0°／120°／240°、左・中・右
  - `ensemble`：3 本×2 つの LFO（遅い 0.6 Hz 付近と速い 6 Hz 付近の和。各 120° ずらし）。`rate_hz` は遅い方、速い方は `rate_hz`×10 に固定
- 正典：Dattorro 1997 Part 2／`bbd` は Holters & Parker DAFx-18（T04-02 と同じ）／`ensemble`（ストリングアンサンブルの 3 相コーラス）と `dual` は PM が挙げられる査読資料が無い：調査レッグが方式の公開解説を 1 本ずつ選ぶ。見つからなければ上記の定義だけで実装する（定義は自己完結している）
- テスト（MT に加えて）：(1) MT2：`depth=0` で固定遅延 `delay_ms` の和と一致（`clean`、ヌル ≤ −100 dBFS） (2) 1 kHz 正弦：ウェットの周波数偏移の最大値が理論値（2π·rate·depth_ms）±10 % (3) `dual`：左右の和（モノ）で周波数偏移が相殺され、偏移の実測が単声の 20 % 以下 (4) `tri`：3 声の LFO 位相差が 120° ±2° (5) `voices`：声部数に依らずウェットの RMS が ±1 dB（1/√N 正規化） (6) `feedback=±0.5` で有界
- 依存：BB-05、BB-09、BB-13（`bbd`）、T04-02 の核

### 実装時の確定（統括の判断 D-13・D-21）

C7e の声部正規化は固定 `1/sqrt(N)` から正相関を含む正規化へ変更した。MT2の同相固定遅延和も正規化後の和を期待値とし、RMS ±1 dBの許容値は維持する。相関の内部推定時定数は50 ms。逆相打消しの除去や任意の全信号のRMS一定は保証しない。公開範囲・既定は不変。

## T06-02 フランジャー

`flanger`｜A｜W2｜S｜Codex

MOD（`rate_hz` 0.25、`depth` 0.7、`stereo_phase` 0、`mix` 0.5）に加えて：`delay_ms`（f、0.1〜15、既定 2：掃引の上端）、`min_delay_ms`（f、0〜5、既定 0.2）、`feedback`（f、−0.95〜0.95、既定 0.5。負＝奇数倍音側の櫛）、`through_zero`（b、false：true で乾側に `delay_ms`/2 の固定遅延を入れ、相対遅延が 0 を横切る。その分のレイテンシを宣言）、`invert`（b、false：ウェットの極性）、`sweep`（e、`linear`／`log`、既定 `log`：遅延時間の掃引の尺度）、`highcut_hz`（f、0〜20000、0）。

- アルゴリズム：1 本の変調遅延＋帰還。`mix=0.5` で櫛の深さ最大
- テスト（MT に加えて）：(1) 変調を止めた状態（`depth=0`）で、白色雑音入力のスペクトルのノッチ間隔が 1/遅延時間 ±2 %、`invert` でノッチと山が入れ替わる (2) `through_zero`：相対遅延 0 の瞬間に（`invert=true`、`mix=0.5`）出力が −60 dBFS 以下まで打ち消される (3) `feedback=0.95` で有界、共振の山が入力比 +26 dB 以下 (4) CT-5（`through_zero` のレイテンシ）
- 依存：BB-05、BB-09

## T06-03 フェイザー

`phaser`｜A｜W2｜S｜Codex

MOD（`rate_hz` 0.4、`depth` 0.7、`stereo_phase` 0.1、`mix` 0.5）に加えて：`stages`（e、2／4／6／8／12、既定 4）、`center_hz`（f、100〜8000、既定 800）、`range_oct`（f、0〜6、既定 3：掃引幅。`depth`=1 のとき）、`feedback`（f、−0.95〜0.95、0.3）、`spread`（f、0〜1、0：段ごとの折点周波数のずらし。0＝全段同じ）、`invert`（b、false）。

- アルゴリズム：1 次全通過の直列（TPT 型。係数を毎サンプル更新しても安定）＋帰還（1 サンプル遅延を挟む。**遅延なしループは解かない**と決める：決定性と native 一致を優先）。ノッチ数＝段数/2
- 正典：J. O. Smith「An Allpass Approach to Digital Phasing and Flanging」ICMC 1984／Zavalishin『The Art of VA Filter Design』（TPT 全通過）
- テスト（MT に加えて）：(1) `depth=0`：ノッチの数＝段数/2、最初のノッチ周波数が理論値 ±3 % (2) ウェット単独（`mix=1`、`feedback=0`）の振幅特性が平坦 ±0.01 dB（全通過） (3) 掃引の上下端が `center_hz`·2^(±range_oct/2) ±3 % (4) `feedback=±0.95` で有界 (5) sr 44.1k／96k でノッチ周波数が同じ（CT-7）
- 依存：BB-05

## T06-04 ユニバイブ

`vibe`｜B（PM 判断：受光素子の応答モデルの導出が要る）｜W2｜M（調査レッグが先）｜Codex

MOD（`rate_hz` 範囲 0.3〜12、既定 3、`depth` 0.7、`stereo_phase` 0、`mix`→下の `mode` が決める）に加えて：`mode`（e、`chorus`／`vibrato`、既定 `chorus`：乾＋湿の等量和／湿だけ）、`lamp_ms_up`（f、5〜100、既定 20）・`lamp_ms_down`（f、20〜400、既定 120：光源の立ち上がり・立ち下がりの時定数。非対称が脈動の正体）、`asym`（f、0〜1、0.5：受光素子の抵抗変化の非線形の度合い）、`drive_db`（f、0〜12、0：前段の軽い飽和）、`output_db`（f、−12〜12、0）。

- アルゴリズム：1 次全通過 4 段。各段の折点は**段ごとに違う固定比**（約 1：15：220：4700 の容量比に相当する広い散らばり。フェイザーのような揃ったノッチにならない）。LFO → 光源の熱慣性（上り・下りで別の 1 次遅れ）→ 受光素子の抵抗（光量のべき乗則、段ごとに少し違う感度）→ 各段の折点周波数。**機種名・回路定数の複写はしない**：公開の回路解析に書かれた構造と比を使い、定数は方式の説明から置く
- 正典：Darabundit, Wedelich & Bischoff「Digital Grey Box Model of the Uni-Vibe Effects Pedal」DAFx-19（これを正とする。調査レッグが式を確定）／Zavalishin（TPT 全通過）
- テスト（MT1・3・4・6 に加えて）：(1) `mode=vibrato`：振幅特性が平坦 ±0.05 dB（全通過） (2) `mode=chorus`、変調停止：ノッチが 2 つ以下で、深さが段数 4 の `phaser` より浅い（揃っていないことの確認。数値を記録） (3) 光源の非対称：掃引の上り時間と下り時間の比が `lamp_ms_up`/`lamp_ms_down` の向きと一致（瞬時位相の実測） (4) `rate_hz` を上げると掃引幅が狭まる（熱慣性。単調） (5) `drive_db=0` で線形（THD ≤ −100 dB）
- 依存：BB-05、BB-13

### 実装時の確定（統括の判断 D-16）

chorusモードの内部乾湿比を1:1→11:9とし、`y=0.55*dry+0.45*wet`。全通過の振幅1なら連続周波数で振幅下限0.1、最深 −20 dBとなる。C4 の連続極小の実測振幅は0.10000000000000003。vibratoはwetのみ。合格数値・公開パラメータは変えず、内部の非平衡加算で満たす。実機同等性は主張しない。

## T06-05 トレモロ（ハーモニック含む）

`tremolo`｜A｜W1｜S｜Codex

MOD（`rate_hz` 5、`depth` 0.5、`stereo_phase` 0、`mix` は持たない）に加えて：

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `mode` | e | — | `amplitude`／`harmonic` | `amplitude` |
| `depth_db` | f | dB | 0〜48 | 6（`depth`=1 のときの谷の深さ。ゲイン＝−depth_db·depth·(1−m)/2） |
| `lfo_shape` | e | — | `sine`／`triangle`／`square`／`random` | `sine`（MOD に `square` を足す） |
| `square_smooth_ms` | f | ms | 0.5〜20 | 3（`square` の角を丸める） |
| `crossover_hz` | f | Hz | 200〜4000 | 800（`harmonic`：低域と高域を逆相の LFO で揺らす） |
| `bias` | f | 0..1 | 0〜1 | 0（`amplitude`：変調波の非対称。真空管バイアス変調型の「谷が長い」形） |

- アルゴリズム：`amplitude`＝dB 領域のゲイン変調。`harmonic`＝最小位相 LR4（BB-02b）で 2 帯域に分け、低域に m(t)、高域に −m(t) のゲイン変調、加算（総音量はほぼ一定で音色が揺れる）
- 正典：Dattorro 1997 Part 2（LFO）／Linkwitz 1976（分割）
- テスト（MT2〜6 に加えて）：(1) `depth=0` でビット一致 (2) 定常正弦：包絡の谷が `depth_db`·`depth` ±0.1 dB、周期が宣言どおり (3) `harmonic`：`crossover_hz` の 2 oct 下と 2 oct 上の正弦の包絡が逆相（位相差 180° ±5°）、ピンクノイズ入力の広帯域 RMS の変動 ≤ 1.5 dB (4) `square`：切り替わりの広帯域クリックが無い（立ち上がり時間が `square_smooth_ms` ±20 %） (5) `stereo_phase=0.5`：左右の包絡が逆相（＝オートパン。T05-03 と同じ結果にはならなくてよい：則が違う。その旨を docs に書く）
- 依存：BB-02、BB-05

## T06-06 ビブラート

`vibrato`｜A｜W2｜S｜Codex

MOD（`rate_hz` 5、`stereo_phase` 0、`mix` 固定 1 で持たない）に加えて：`depth_cents`（f、0〜200、既定 20：音程の振れの片側最大。`depth` は掛け算で効く）、`onset_ms`（f、0〜2000、既定 0：無音明け（−50 dBFS 超え）から変調が立ち上がるまで。0＝常時）、`base_delay_ms`（内部固定。レイテンシとして宣言）。

- アルゴリズム：遅延の時間微分＝音程比。目標の音程偏移（セント）から遅延の変調幅を逆算する（幅＝偏移比/(2π·rate)）。固定のベース遅延をレイテンシとして宣言・補償
- テスト（MT3・4・6 に加えて）：(1) `depth_cents=0`：遅延補償後ヌル ≤ −120 dBFS (2) 1 kHz 正弦：瞬時周波数の偏移が ±`depth_cents` ±5 %、平均周波数の偏移 ≤ 0.5 セント (3) 振幅変調が付かない（包絡のリップル ≤ 0.05 dB） (4) `onset_ms`：立ち上がり時間 ±10 % (5) CT-5
- 依存：BB-05、BB-09

## T06-07 ロータリースピーカー

`rotary`｜B（PM 判断：ホーンの指向性と加減速のモデルが要る）｜W2｜M（調査レッグが先）｜Codex

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `speed` | e | — | `slow`／`fast`／`stop` | `slow` |
| `speed_curve` | c | x：曲頭からの秒／y：0（stop）〜1（slow）〜2（fast） | 最大 256 点 | `[]`（空＝`speed` 固定。書けば加減速を時刻で指定） |
| `horn_slow_hz`・`horn_fast_hz` | f | Hz | 0.3〜2／4〜10 | 0.8／6.8 |
| `drum_slow_hz`・`drum_fast_hz` | f | Hz | 0.3〜2／4〜10 | 0.7／5.9 |
| `horn_accel_s`・`drum_accel_s` | f | s | 0.1〜10 | 1／4.5（速度変化の時定数。ドラムが遅い） |
| `crossover_hz` | f | Hz | 400〜1600 | 800 |
| `horn_depth`・`drum_depth` | f | 0..1 | 0〜1 | 0.7／0.4（ドップラーと振幅変調の量） |
| `mic_angle_deg` | f | 度 | 0〜180 | 90（仮想マイク 2 本の開き） |
| `mic_distance` | f | 0..1 | 0〜1 | 0.5（近いほど振幅変調が深い） |
| `drive_db` | f | dB | 0〜24 | 0（前段アンプの飽和） |
| `balance` | f | −1..1 | −1〜1 | 0（ホーン／ドラムのレベル比） |
| `mix`・`seed` | | | MOD | 1／0 |

- アルゴリズム：クロスオーバー（最小位相 LR4）→ 高域＝ホーン、低域＝ドラム。各ロータ：回転角 θ(t)（**速度の積分は絶対時刻からの閉形式**：`speed_curve` を区分線形に 1 次遅れを掛けた解析解で角度を出す。累積誤差なし）→ 2 本の仮想マイクへの距離変化を分数遅延（ドップラー）、指向性による振幅変調、角度依存の高域フィルタ。ホーンは 2 つの開口の一方だけが鳴る構造として扱う
- 正典：Smith, Serafin, Abel & Berners「Doppler Simulation and the Leslie」DAFx-02／Herrera, Hanson & Abel「Discrete Time Emulation of the Leslie Speaker」AES Conv. 127（2009）／Henricksen「Unearthing the Mysteries of the Leslie Cabinet」Recording Engineer/Producer 1981（機構の説明だけ）
- テスト（MT1・4・6・7 に加えて）：(1) `stop`・`drive_db=0`：時不変（定常正弦の包絡リップル ≤ 0.01 dB） (2) `fast`：3 kHz 正弦の瞬時周波数の変調周期が 1/`horn_fast_hz` ±1 %、100 Hz 正弦の振幅変調周期が 1/`drum_fast_hz` ±1 % (3) `speed_curve` で slow→fast：ホーンの回転数が 63 % に達する時間が `horn_accel_s` ±10 %、ドラムは `drum_accel_s` ±10 % (4) 左右の変調の位相差が `mic_angle_deg` と一致（±5°） (5) 途中から描画しても回転角が一致（閉形式の確認）
- 依存：BB-00、BB-02、BB-05、BB-09、BB-13

## T06-08 リングモジュレーター

`ring_mod`｜A｜W2｜S｜Codex

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `freq_hz` | f | Hz | 0.1〜10000 | 440 |
| `carrier` | e | — | `sine`／`triangle`／`square` | `sine`（`triangle`・`square` は帯域制限した加算合成。倍音は 0.45×sr まで） |
| `freq_curve` | c | x：秒／y：Hz 0.1〜10000（対数補間） | 最大 1024 点 | `[]`（書けば `freq_hz` の代わり） |
| `lfo_depth_oct` | f | oct | 0〜4 | 0（MOD の LFO で搬送波周波数を揺らす幅） |
| `am` | f | 0..1 | 0〜1 | 0（0＝リング変調 x·c、1＝振幅変調 x·(1＋c)/2） |
| `diode` | f | 0..1 | 0〜1 | 0（ダイオードリングの非線形の量。0＝理想乗算） |
| `oversample` | e | x | 1／2／4 | 2 |
| MOD の `rate_hz`・`note`・`bpm`・`lfo_shape`・`origin_s`・`mix`・`seed` | | | MOD | `mix` 1 |

- アルゴリズム：搬送波の位相は周波数曲線の**解析的な積分**（区分ごとの閉形式）で絶対時刻から求める。乗算は帯域が和になるので 2 倍オーバーサンプル（BB-13）の中で行う。`diode>0` は 4 ダイオード・リングの区分モデル（Parker の論文）
- 正典：Parker「A Simple Digital Model of the Diode-Based Ring-Modulator」DAFx-11／Zölzer 編『DAFX』（変調の章）
- テスト：(1) `mix=0` でビット一致 (2) 1 kHz 正弦×`freq_hz`=300・`sine`：出力に 700・1300 Hz だけ（±1 Hz）、元の 1 kHz は −80 dB 以下、折り返し成分 −80 dB 以下 (3) `am=1`：搬送波成分＋両側波帯、変調度 100 % (4) `square`：倍音が 0.45×sr で打ち切られ、折り返し −70 dB 以下 (5) `freq_curve` の途中から描画して位相が一致 (6) `diode=1`：奇数次の搬送波倍音の側帯が現れ、レベルが論文の図の傾向（単調増加）に合う（数値は調査レッグが確定）
- 依存：BB-00、BB-05、BB-13

## T06-09 周波数シフター

`freq_shifter`｜A｜W2｜S｜Codex
**T04-09 `pitch_delay` の `freq` モードと同じ核（ヒルベルト対）。本型の単位で先に作り、T04-09 が呼ぶ**（WORKLOG §4 記録 4）。

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `shift_hz` | f | Hz | −5000〜5000 | 5 |
| `shift_curve` | c | x：秒／y：Hz | 最大 1024 点 | `[]` |
| `sideband` | e | — | `single`／`both` | `single`（`both`＝左に上側、右に下側。バーバーポール型の広がり） |
| `feedback` | f | 0..1 | 0〜0.9 | 0（短い固定遅延 10 ms を挟む。螺旋状の反復） |
| `lo_hz` | f | Hz | 0〜500 | 20（これより下はヒルベルト対の精度外。シフト前に HPF） |
| MOD の `rate_hz`・`lfo_shape`・`depth`・`mix`・`seed` | | | MOD | `depth` 0（LFO でシフト量を ±`shift_hz`·depth 揺らす）、`mix` 1 |

- アルゴリズム：全通過 IIR の対で 90° 位相差の 2 信号（解析信号）を作り、複素正弦を掛けて実部を取る（単側波帯変調）。対の位相誤差は 20 Hz〜0.45×sr で ≤ 0.1°（逆側波帯の抑圧 ≥ 60 dB）を設計条件にする。負方向で 0 Hz を跨いだ成分は折り返す（仕様として記録に明記。防がない）。上方向でナイキストを超える成分は事前の LPF で落とす
- 正典：Wardle「A Hilbert-Transformer Frequency Shifter for Audio」DAFx-98／Ansari「IIR Discrete-Time Hilbert Transformers」IEEE Trans. ASSP 1987（全通過対の設計）／Bode & Moog「A High-Accuracy Frequency Shifter for Professional Audio Applications」JAES 1972（原理）
- テスト：(1) `mix=0` でビット一致 (2) 正弦 f（100 Hz〜10 kHz の 10 点）：出力が f＋`shift_hz` ±0.1 Hz、逆側波帯 ≤ −60 dB、元の周波数 ≤ −60 dB (3) `shift_hz=0`：全通過（振幅 ±0.05 dB） (4) `sideband=both`：左が f＋Δ、右が f−Δ (5) `shift_curve` の途中から描画して位相が一致 (6) `feedback=0.9` で有界 (7) CT-5（全通過対の群遅延は補償しない＝レイテンシ 0 と宣言し、位相の回りを記録に明記）
- 依存：BB-00、BB-05

## T06-10 マイクロピッチ／デチューン

`micro_pitch`｜A｜W3（BB-11a の後）｜S｜Codex

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `left_cents`・`right_cents` | f | セント | −50〜50 | −9／+9 |
| `left_delay_ms`・`right_delay_ms` | f | ms | 0〜100 | 10／15 |
| `grain_ms` | f | ms | 10〜80 | 30（交差タップの窓） |
| `feedback` | f | 0..1 | 0〜0.5 | 0 |
| `highcut_hz` | f | Hz | 0〜20000 | 0 |
| `input` | e | — | `mono_sum`／`stereo` | `mono_sum` |
| `mix` | f | 0..1 | 0〜1 | 0.3 |

- アルゴリズム：BB-11a（遅延線 2 タップ交差）を左右 1 本ずつ。±数セントでは粒の継ぎ目の位相ずれが小さいので、位相合わせ（相関最大のタップ選択）は**しない**（決定性と軽さを優先。音程の大きいシフトは T08-05）
- 正典：Zölzer 編『DAFX』（遅延線変調によるピッチシフト）
- テスト：(1) `mix=0` でビット一致 (2) 1 kHz 正弦、ウェット単独：左右の周波数が 1000·2^(cents/1200) ±0.5 セント (3) 粒の継ぎ目の振幅変調 ≤ 0.5 dB（定常正弦） (4) セント 0・0 で、固定遅延の和と一致（ヌル ≤ −80 dBFS） (5) モノ合算損失を記録
- 依存：BB-09、BB-11

## T06-11 ADT／ダブラー

`adt`｜A｜W2｜S｜Codex

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `delay_ms` | f | ms | 5〜80 | 30 |
| `wander_ms` | f | ms | 0〜20 | 4（遅延の揺れ幅） |
| `wander_rate_hz` | f | Hz | 0.05〜5 | 0.4 |
| `wander_shape` | e | — | `random`／`sine` | `random`（人の二度録りに近いのは不規則な方） |
| `level_wander_db` | f | dB | 0〜3 | 0.5（複製側のレベルの揺れ） |
| `voices` | i | 本 | 1〜2 | 1 |
| `spread` | f | 0..1 | 0〜1 | 0.7（原音と複製の左右配置。1＝原音が左・複製が右、2 声なら複製が左右） |
| `double_db` | f | dB | −24〜6 | −3 |
| `highcut_hz` | f | Hz | 0〜20000 | 0 |
| `seed` | i | — | 0〜65535 | 0 |

- アルゴリズム：変調遅延（T04-06 の核）＋レベルの揺れ。揺れはシード付きの帯域制限ランダムウォーク。遅延の時間微分による音程偏移は副産物として出る（最大偏移を記録：2π·rate·wander から）
- 正典：Dattorro 1997 Part 2／ADT の原理は公開の技術史（テープ 2 台の速度差。原理だけ）
- テスト：(1) 揺れなし（`wander_ms=0, level_wander_db=0`）：原音＋固定遅延の和と一致（ヌル ≤ −100 dBFS）。本型に素通しの設定は無い（外すときはチェーンから外す） (2) 遅延の実測の範囲が `delay_ms`±`wander_ms`（±5 %） (3) 同一 `seed` で一致、別 `seed` で揺れの系列が異なる (4) `spread=1`・1 声：左に原音だけ、右に複製だけ (5) モノ合算損失と櫛の最初のノッチを記録 (6) 途中からの描画が一致（ランダムウォークを絶対時刻の格子から生成）
- 依存：BB-05、BB-09

## T06-12 ワウフラッター（テープ揺らぎ）

`wow_flutter`｜A｜W2｜S｜Codex
T04-01 `tape_delay` の揺れ生成器と同じもの（複製せず共通関数にする）。T07-01・T07-04・T09-09 が使う。

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `wow_depth` | f | % | 0〜3 | 0.2（速度偏差） |
| `wow_rate_hz` | f | Hz | 0.1〜4 | 0.6 |
| `flutter_depth` | f | % | 0〜1 | 0.05 |
| `flutter_rate_hz` | f | Hz | 4〜50 | 9 |
| `drift` | f | 0..1 | 0〜1 | 0.3（不規則成分の割合） |
| `scrape` | f | 0..1 | 0〜1 | 0（数 kHz 帯の微小な速度雑音。ざらつき） |
| `stereo_link` | f | 0..1 | 0〜1 | 1（1＝左右同じ揺れ。テープは同じ走行系なので既定 1） |
| `seed` | i | — | 0〜65535 | 0 |

- アルゴリズム：速度偏差 v(t)（%）を合成 → **積分して**遅延の変位に変える（速度の揺れなので、遅延幅は v/(2π·rate) に比例）→ 分数遅延で読み出す。固定ベース遅延をレイテンシとして宣言・補償。不規則成分は絶対時刻の格子上の乱数から補間（途中描画の一致）
- 正典：IEC 60386（ワウ・フラッタの測定法。重み付けの定義）／AES6-2008（同）／Dattorro 1997 Part 2
- 記録：IEC 60386 の方法で測った重み付きワウ・フラッタ値（%）を R-10 のベクトルとして残す
- テスト：(1) 全深さ 0：遅延補償後ヌル ≤ −120 dBFS (2) 3150 Hz 正弦（規格の試験周波数）：瞬時周波数の偏差の実測が `wow_depth`・`flutter_depth` に ±10 % (3) 平均速度の偏り ≤ 0.001 %（長さ 60 s で尺がずれない：末尾の位置ずれ ≤ 1 サンプル相当） (4) `stereo_link=1` で左右の遅延が同一（ステレオ像が揺れない：左右相関の変化 ≤ 0.001） (5) 同一 `seed` で一致 (6) 途中からの描画が一致 (7) CT-5
- 依存：BB-05、BB-09

---

## 実装単位

| 単位 | 中身 | 前提 | 量 | 実働 |
|---|---|---|---|---|
| U-06a | `tremolo` | BB-02、BB-05 | S | Codex |
| U-06b | `flanger`、`phaser`、`vibrato`、`adt`、`wow_flutter`（揺れ生成器を T04-01 と共通化） | BB-05、BB-09、U-04a | S×5 | Codex |
| U-06c | `chorus` | U-06b、U-04d（`bbd`） | M | Codex |
| U-06d | `ring_mod`、`freq_shifter`（ヒルベルト対。T04-09 より先） | BB-00、BB-05、BB-13 | S＋S | Codex |
| U-06e | `vibe` | 調査レッグ、BB-05、BB-13 | M | Codex |
| U-06f | `rotary` | 調査レッグ、BB-02、BB-09 | M | Codex |
| U-06g | `micro_pitch` | BB-11a | S | Codex |
