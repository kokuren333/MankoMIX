# spec/04 ディレイ（11 件）

カタログ §4。共通規約は `spec/01_dynamics.md` §0。既存 `delay`（整数サンプル遅延）は変えない。

> **経緯の注記**：T04-01〜09 は前任 PM が欠損カタログ（4-9 の説明文の途中で切れていた）から書いた。完全版カタログで 4-9 の説明は「フィードバックで音程がずれていく反復」と確認でき、T04-09 の読みは合っていた（変更なし）。T04-10・11 は後任 PM が完全版から追記した。

## 0. カテゴリ共通

- 全型：`stages: ["track","bus"]`、`master_slot: None`、`realtime.allocates: True`、TV。`channel` 欄は不可
- 核（BB-09）：分数遅延線（読み出しは窓付き sinc 8 点。変調の速い型はラグランジュ 3 次。型ごとに固定し、切り替えパラメータは持たない）＋ループ内処理つきの帰還。時間領域で曲頭から描画
- 帰還の安全：ループ内に利得のある処理（飽和・フィルタの共振・ピッチ）を持つ型は、ループ利得が 1 を超えない構成にする（各件に書く）。CT-8 が全型の合格条件
- 乾音の経路は遅延なし・ビット一致（`mix=0` で素通し）

**DL ブロック（共通パラメータ）**

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `time_ms` | f | ms | 0.1〜4000 | 250（`note=none` のとき） |
| `note` | e | — | `NOTE_VALUES` | `none`（`bpm>0` 必須。音価が 4000 ms を超えたら拒否。既存 `delay` と同じ） |
| `bpm` | f | BPM | 0〜400 | 0 |
| `feedback` | f | 0..1 | 0〜0.95 | 0.3 |
| `mix` | f | 0..1 | 0〜1 | 0.2 |
| `lowcut_hz` | f | Hz | 0〜2000 | 0（0＝無効。ループ内、12 dB/oct） |
| `highcut_hz` | f | Hz | 0〜24000 | 0（同上） |
| `seed` | i | — | 0〜65535 | 0 |
| SD ブロック | | | | spec/01 §0.6 |

**共通テスト（DT）**：(DT1) `mix=0` でビット一致 (DT2) インパルス応答の反復間隔が `time_ms`（または音価）±0.5 サンプル以内（変調 0 のとき） (DT3) 反復ごとの減衰が 20·log10(`feedback`) ±0.2 dB（ループ内フィルタ・飽和なしのとき） (DT4) CT-8 (DT5) 同一 `seed` でビット一致 (DT6) モノ合算損失とハース領域の判定を記録（既存 `delay` と同じ R-10 の項目）

カテゴリの正典：Laakso, Välimäki, Karjalainen & Laine「Splitting the Unit Delay」IEEE Signal Processing Magazine 1996（分数遅延）／Dattorro「Effect Design, Part 2: Delay-Line Modulation and Chorus」JAES 1997／Zölzer 編『DAFX』（遅延系の章）

---

## T04-01 テープエコー

`tape_delay`｜A｜W2｜M｜Codex

DL（`highcut_hz` 既定 5000、`lowcut_hz` 既定 80）に加えて：

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `wow_depth` | f | % | 0〜2 | 0.2（遅延時間の偏差） |
| `wow_rate_hz` | f | Hz | 0.1〜4 | 0.8 |
| `flutter_depth` | f | % | 0〜0.5 | 0.05 |
| `flutter_rate_hz` | f | Hz | 4〜30 | 9 |
| `drift` | f | 0..1 | 0〜1 | 0.3（ワウに混ぜるシード付きの不規則成分） |
| `drive_db` | f | dB | 0〜24 | 6（ループ内の飽和） |
| `head_bump_db` | f | dB | 0〜6 | 2（80〜120 Hz の持ち上がり） |

- アルゴリズム：遅延時間＝基準×(1＋ワウ＋フラッター)。ワウは正弦＋低域濾波したシード付きノイズ。ループ内は順に：飽和（tanh、2 倍オーバーサンプル。小信号利得 1）→ ヘッドの低域の山 → 高域損失 → `feedback`。飽和が小信号利得 1・有界なので、`feedback ≤ 0.95` で発散しない
- 正典：Dattorro 1997 Part 2／Laakso ほか 1996／磁気テープのヒステリシスを入れる場合は Chowdhury「Real-Time Physical Modelling for Analog Tape Machines」DAFx-19 の**論文だけ**を読む（同著者の公開コードは GPL。読まない）。既定は tanh で、ヒステリシスは任意の後続課題
- テスト（DT1・4・5・6 に加えて）：(1) 変調 0・`drive_db=0`・フィルタ無効で DT2・DT3 (2) 1 kHz 正弦の最初の反復の周波数偏移の実測（瞬時周波数）が、ワウ・フラッターの深さと周波数に ±10 % で一致 (3) 反復を重ねるごとにスペクトル重心が下がる（単調） (4) `drive_db` に対して反復の THD が単調増加、`feedback=0.95`・フルスケール入力で出力有界
- 依存：BB-05、BB-09、BB-13

## T04-02 BBD アナログディレイ

`bbd_delay`｜B（PM 判断：モデルの導出が要る）｜W2｜M（調査レッグが先）｜Codex

DL（`time_ms` 範囲 5〜1200、既定 300）に加えて：

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `stages` | e | 段 | 1024／2048／4096／8192 | 4096（素子の段数。`time_ms` と段数からクロック周波数が決まる） |
| `compander` | b | — | — | true（2:1 圧縮→素子→1:2 伸長） |
| `tone` | f | 0..1 | 0〜1 | 0.5（入出力フィルタのカットオフの倍率） |
| `noise_db` | f | dBFS | −120〜−50 | −120（−120＝雑音を足さない。足すときはシード付き） |
| `mod_depth` | f | % | 0〜2 | 0（クロックの変調） |
| `mod_rate_hz` | f | Hz | 0.05〜10 | 0.5 |

- アルゴリズム：クロック周波数 fc＝段数/(2·遅延時間)。入力の折り返し防止フィルタと出力の再構成フィルタは fc に追従（長い遅延ほど暗くなる）。素子は fc での標本化・保持として扱い、ホスト sr との間は論文の方法で厳密に扱う。圧伸は包絡追従つきの 2:1／1:2
- 正典：Raffel & Smith「Practical Modeling of Bucket-Brigade Device Circuits」DAFx-10／Holters & Parker「A Combined Model for a Bucket Brigade Device and its Input and Output Filters」DAFx-18（これを正とする）
- テスト（DT1・4・5・6 に加えて）：(1) 変調 0 で DT2（±1 サンプル） (2) 遅延時間を 2 倍にすると、反復の −3 dB 帯域が 1/2 ±15 % (3) `compander=true`：定常正弦の入出力レベルが ±0.5 dB で一致（圧伸が相殺）、`noise_db` を上げたときの無入力時の雑音が圧伸なしより 10 dB 以上低い (4) fc/2 を超える入力成分の折り返しが −40 dB 以下
- 依存：BB-03、BB-09、BB-13

## T04-03 ピンポンディレイ

`pingpong_delay`｜A｜W1｜S｜Codex

DL に加えて：`start` e `left`／`right`（`left`）、`width` f 0〜1（1：1 で完全に左右交互、0 で中央）、`input` e `mono_sum`／`stereo`（`mono_sum`）、`ratio` f 0.5〜2（1：右の遅延時間／左の遅延時間）。

- アルゴリズム：2 本の遅延線の交差帰還（L の出力が R へ、R が L へ）。整数サンプル遅延（既存 `delay` の核を複製）。モノ入力はステレオ出力
- テスト（DT1〜6 に加えて）：(1) モノのインパルス：反復 n 回目が、奇数は `start` 側だけ・偶数は反対側だけ（`width=1`。反対チャンネルは −120 dBFS 以下） (2) `width=0` で左右が同一 (3) `ratio`：左右の間隔比が設定 ±1 サンプル (4) モノ合算の反復間隔が `time_ms`
- 依存：BB-09

## T04-04 スラップバックディレイ

`slapback`｜A｜W1｜S｜Codex｜**コンポジット**（既存 `delay` へ展開。カタログの指示「現行 delay の型として」）

| id | 型 | 範囲 | 既定 | 展開先 |
|---|---|---|---|---|
| `time_ms` | f | 40〜150 | 90 | `delay.time_ms` |
| `mix` | f | 0〜1 | 0.15 | `delay.mix` |
| `tone_hz` | f | 0〜24000 | 5000 | `delay.highcut_hz` |
| `lowcut_hz` | f | 0〜2000 | 150 | `delay.lowcut_hz` |
| `route` | e | `both`／`left`／`right` | `both` | `delay.route` |

固定：`feedback=0`、`note=none`。

- テスト：展開後の `delay` を手で書いたチェーンとビット一致／記録に展開後の項目が残る／反復が 1 回だけ（2 回目は −120 dBFS 以下）
- 依存：BB-00（コンポジット）

## T04-05 マルチタップディレイ

`multitap_delay`｜A｜W1｜S｜Codex

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `tap_ms` | a | ms | 0.1〜4000、最大 16 個、昇順 | `[125, 250, 375]` |
| `tap_db` | a | dB | −60〜6、同数 | `[-3, -6, -9]` |
| `tap_pan` | a | −1..1 | −1〜1、同数（空＝全部中央） | `[]` |
| `tap_unit` | e | — | `ms`／`beats` | `ms`（`beats` のとき `tap_ms` を拍数として読む。`bpm` 必須、範囲 0.01〜16） |
| `feedback` | f | 0..1 | 0〜0.95 | 0（最後のタップから入力へ） |
| `bpm`・`mix`・`lowcut_hz`・`highcut_hz`・SD | | | DL | DL |

- アルゴリズム：1 本の遅延線から複数の読み出し。整数サンプル。パンは既存 `pan` と同じ等パワー則（中央 −3 dB）
- テスト（DT1・4・6 に加えて）：(1) インパルス応答のタップ時刻（±0.5 サンプル）、レベル（±0.05 dB）、左右比がパン則どおり (2) `feedback>0` で、タップ列全体が最後のタップ時刻の周期で繰り返す (3) 配列長の不一致・昇順でない `tap_ms`・拍換算で 4000 ms 超は拒否
- 依存：BB-09

## T04-06 モジュレーションディレイ

`mod_delay`｜A｜W2｜M｜Codex

DL に加えて：

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `mod_depth_ms` | f | ms | 0〜20 | 1（遅延時間の振れ幅。`time_ms` を下回る分は切る） |
| `mod_rate_hz` | f | Hz | 0.01〜20 | 0.5 |
| `mod_note` | e | — | `NOTE_VALUES` | `none`（LFO 周期を音価で。`bpm` 必須） |
| `mod_shape` | e | — | `sine`／`triangle`／`random` | `sine`（`random`＝シード付きの滑らかなランダムウォーク） |
| `stereo_phase` | f | 0..1 | 0〜1 | 0.25（左右の LFO 位相差。周期に対する比） |
| `filter_hz` | f | Hz | 0〜20000 | 0（ループ内の可動ローパス。0＝無効） |
| `filter_mod_oct` | f | oct | 0〜4 | 0（LFO でカットオフを動かす幅） |
| `filter_res_db` | f | dB | 0〜12 | 0 |

- アルゴリズム：LFO の位相は曲頭からの絶対サンプル位置で計算（累積しない）。可動フィルタは TPT 型 SVF。共振があってもループ利得が 1 を超えないよう、`feedback`×共振ピークの線形値 ≤ 0.98 に帰還を自動で絞る（絞った量を記録）
- 正典：Dattorro 1997 Part 2／Zavalishin『The Art of VA Filter Design』
- テスト（DT1・4・5・6 に加えて）：(1) 変調 0 で DT2・DT3 (2) 正弦入力の反復の周波数偏移の最大値が、理論値（2π·rate·depth から）±10 % (3) `stereo_phase=0.5` で左右の偏移が逆相 (4) `filter_res_db=12`・`feedback=0.95` で出力有界、絞った量が記録に出る (5) 途中から描画しても全長描画の該当部分と一致
- 依存：BB-05、BB-09

## T04-07 グラニュラーディレイ

`granular_delay`｜B｜W2｜M｜Codex

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `time_ms`・`note`・`bpm` | | | DL（粒を読み出す基準の遅れ） | DL |
| `grain_ms` | f | ms | 5〜500 | 80 |
| `density_hz` | f | Hz | 1〜200 | 25（1 秒あたりの粒の数） |
| `spray_ms` | f | ms | 0〜1000 | 50（読み出し位置のばらつき） |
| `jitter` | f | 0..1 | 0〜1 | 0.3（粒の発生間隔のばらつき。0＝等間隔） |
| `pitch_semitones` | f | 半音 | −24〜24 | 0 |
| `pitch_spread` | f | 半音 | 0〜12 | 0 |
| `reverse` | f | 0..1 | 0〜1 | 0（逆再生する粒の割合） |
| `pan_spread` | f | 0..1 | 0〜1 | 0.5 |
| `feedback` | f | 0..1 | 0〜0.9 | 0.2 |
| `mix`・`lowcut_hz`・`highcut_hz`・`seed`・SD | | | DL | DL |

- アルゴリズム：遅延バッファから、ハン窓の粒を重ね合わせで読み出す。粒ごとの乱数（位置・間隔・音程・向き・パン）は 1 本の PCG64 列から固定の順序で引く（粒 1 個につき引く個数を固定：パラメータが 0 でも引く。値を変えても他の粒の乱数がずれない）。重なり数に応じた正規化（1/√重なり期待値）。帰還は正規化後の出力から
- 正典：Roads『Microsound』（MIT Press 2001）／Truax「Real-Time Granular Synthesis with a Digital Signal Processor」CMJ 1988／Zölzer 編『DAFX』（時間領域の粒処理）
- テスト（DT1・4・5 に加えて）：(1) `spray=jitter=pitch=reverse=0`、`grain_ms`·`density_hz`/1000 ＝ 2（ハン窓の 50 % 重なり）：出力が `time_ms` 遅れの入力に一致（ヌル ≤ −60 dBFS。窓の和が一定になる条件） (2) 粒の数の実測が `density_hz`×長さ ±1 (3) `pitch_semitones=12`：正弦の周波数が 2 倍 ±10 セント (4) `reverse=1`：非対称な包絡の入力で粒内の包絡が反転 (5) 定常ノイズ入力で出力 RMS が入力 ±3 dB（正規化の確認）、`feedback=0.9` で有界
- 依存：BB-09、BB-05

## T04-08 ダッキングディレイ

**新しい型を作らない**｜A｜W2｜S｜Codex。spec/03 T03-11 と同じ 2 経路。

1. 新しい遅延型（`slapback` を除く。展開先が既存 `delay` のため）は全部 SD ブロックを持つ
2. 既存 `delay`（変えない）と `slapback` は、センドバスに置いて op `duck_curve`（`target` にバス）

- テスト：(1) 500 ms のトーンバースト列：バースト中の反復が `duck_db` ±1 dB 下がり、バースト後に戻る (2) `duck_db=0` で SD なしの描画とビット一致
- 依存：BB-14

## T04-09 ピッチシフト／周波数シフトディレイ

`pitch_delay`｜B｜W3｜L（BB-11 の後）｜Codex
（カタログの説明文は「フィードバックで音程がず」で切れている。代表プラグインと件名から、帰還のたびに音程・周波数がずれていく遅延と読んだ。）

DL に加えて：

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `mode` | e | — | `pitch`／`freq` | `pitch` |
| `shift_semitones` | f | 半音 | −24〜24 | 12（`pitch`） |
| `shift_cents` | f | セント | −100〜100 | 0（`pitch`。半音に足す） |
| `shift_hz` | f | Hz | −2000〜2000 | 50（`freq`。全成分を同じ Hz だけずらす） |
| `grain_ms` | f | ms | 10〜500 | 100（`pitch` のシフタの窓） |
| `reverse` | b | — | — | false（粒を逆再生） |
| `shift_in_loop` | b | — | — | true（true＝反復のたびに重ねてずれる。false＝ウェット全体に 1 回だけ） |

- アルゴリズム：`pitch`＝遅延線 2 タップ交差型（BB-11a。ノコギリ波で読み出し位置を動かし、2 つの読み出しを交差フェード）。`freq`＝ヒルベルト変換による単側波帯変調（解析信号×複素正弦）。ヒルベルト対は全通過 IIR の対（群遅延の差を補償）。ループ内のシフタ利得は 1 以下
- 正典：Zölzer 編『DAFX』（遅延線変調のピッチシフト、単側波帯変調）／Wardle「A Hilbert-Transformer Frequency Shifter for Audio」DAFx-98／Laroche & Dolson 1999（位相ボコーダ版に差し替える場合）
- テスト（DT1・4・5・6 に加えて）：(1) `pitch`、440 Hz バースト、`shift=12`：n 回目の反復の周波数が 440·2^n（±15 セント） (2) `freq`、`shift_hz=50`：n 回目が 440＋50n Hz（±1 Hz）、逆側波帯の抑圧 ≥ 40 dB（100 Hz〜10 kHz） (3) `shift=0`（両モード）で、同じ設定の単純な遅延とのヌル ≤ −60 dBFS（`pitch`）、≤ −80 dBFS（`freq`） (4) `shift_in_loop=false`：全反復が同じずれ量 (5) 上向きシフトの反復がナイキストに達する前に `highcut_hz`（未設定時は 0.45×sr）で消える（折り返しが −60 dB 以下）
- 依存：BB-09、BB-11

## T04-10 ルーパー／フリーズディレイ

`freeze_delay`｜A｜W2｜M｜Codex

DL（`time_ms` はループ長。範囲 10〜8000、既定 500。音価の上限も 8000 ms）に加えて：

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `freeze_start_s` | a | s | 0〜36000、最大 32 個、昇順 | `[]` |
| `freeze_end_s` | a | s | 同数。各々対応する開始より後で、次の開始より前 | `[]` |
| `freeze_fade_ms` | f | ms | 1〜500 | 10（ループの継ぎ目と出入りの交差フェード） |
| `freeze_input` | e | — | `mute`／`overdub` | `mute`（`overdub`＝凍結中も入力を重ねる） |
| `overdub_decay` | f | 0..1 | 0〜1 | 1（`overdub` のとき、周回ごとに既存の内容へ掛ける量。1＝減らさない） |
| `quantize` | e | — | `off`／`loop` | `off`（`loop`＝開始・終了時刻を、`origin_s` からのループ長の整数倍へ丸める。丸めた時刻を記録） |
| `origin_s` | f | s | 0〜36000 | 0 |
| `dry_in_freeze` | e | — | `pass`／`mute` | `pass`（凍結中の乾音） |

- アルゴリズム：区間の外は DL どおりの遅延。区間の中は帰還を厳密に 1、ループ内フィルタを迂回、入力ゲインを `freeze_fade_ms` で 0 へ（`mute`）。ループの継ぎ目は、凍結開始時点の 1 周分の頭と尾を `freeze_fade_ms` で交差させて 1 回だけ焼き込む（以後は同じバッファの読み出しなので劣化しない）。区間の時刻は曲頭からの絶対時刻（T03-10 と同じ流儀。リアルタイムの「ボタン」ではない）。`overdub` は加算後にソフト制限なしで、`overdub_decay<1` または入力停止でしか収束しないので、`overdub` かつ `overdub_decay=1` のときは凍結区間の長さ×入力ピークから最悪値を見積もり、+12 dBFS を超えうる設定を `check_runtime` で拒否
- 正典：カテゴリの正典（Dattorro 1997 Part 2、『DAFX』）。固有の論文は不要
- 決定論：区間内の読み出しは整数サンプル（分数補間を通さない。周回でビット同一を保つため）
- テスト（DT1・4・5 に加えて）：(1) 配列が空のとき、同じ DL 設定の単純な遅延とビット一致 (2) 凍結 60 s：n 周目と n＋1 周目の出力がビット一致（`mute`、乾音を除く） (3) 継ぎ目のクリック：定常正弦をループ長と非整合な周波数で凍結し、継ぎ目の広帯域エネルギー突出が周回平均＋6 dB 以下 (4) 終了後、`feedback` どおりに減衰（DT3） (5) `mute`：凍結中に入れた音がウェットに現れない／`overdub`：現れて次周から繰り返す (6) `quantize=loop`：丸め後の時刻が格子上（±0 サンプル）で記録と一致 (7) 区間の重なり・順序違い・個数不一致は拒否
- 依存：BB-09

## T04-11 ダブディレイ

`dub_delay`｜A｜W2｜M｜Codex

DL（`feedback` 範囲 0〜0.98、既定 0.6／`highcut_hz` 既定 3500／`lowcut_hz` 既定 200）に加えて：

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `send` | c | x：曲頭からの秒／y：dB −90〜+6 | 最大 4096 点 | `[]`（空＝常時 0 dB。入力から遅延線への送り量。「投げる」箇所だけ開ける） |
| `drive_db` | f | dB | 0〜24 | 6（ループ内の飽和） |
| `narrow` | f | 0..1 | 0〜1 | 0.5（周回ごとに帯域が狭まる度合い。ループ内 HPF／LPF の Q と次数の配分） |
| `diffusion` | f | 0..1 | 0〜1 | 0.2（ループ内の全通過 2 段。反復がにじむ） |
| `time_glide_ms` | f | ms | 0〜2000 | 0（`time_curve` を使うときの追従時定数。>0 で音程が滑る） |
| `time_curve` | c | x：秒／y：遅延時間の倍率 0.25〜4 | 最大 256 点 | `[]`（空＝一定） |
| `stereo_offset_ms` | f | ms | 0〜30 | 0（右だけ遅らせる） |

- アルゴリズム：テープ式の構造（T04-01 と同じ核）。ループ内は順に：飽和（tanh、2 倍オーバーサンプル、小信号利得 1）→ 帯域の狭め（HPF・LPF。`narrow` で 12→24 dB/oct 相当へ）→ 全通過拡散 → `feedback`。遅延時間を動かすと読み出し速度が変わり音程が滑る（分数遅延の読み出し位置を 1 次遅れで追従）。**自己発振はさせない**（`feedback ≤ 0.98` と小信号利得 1 の飽和で CT-8 を満たす。発振を奏法にする案は採らない：入力停止後に消えない出力は決定的な尾の長さを定義できないため）
- 正典：カテゴリの正典／Zavalishin『The Art of VA Filter Design』（ループ内フィルタ）
- テスト（DT1・4・5・6 に加えて）：(1) `drive_db=0`・`narrow=0`・`diffusion=0`・曲線なしで DT2・DT3 (2) `send` 曲線：−90 dB の区間に入れた音が反復に現れない（−100 dBFS 以下）、0 dB の区間の音は現れる (3) 反復 n 回目の −3 dB 帯域幅が n に対して単調に狭まる（`narrow>0`） (4) `time_curve` で倍率 1→0.5 へ動かす間、反復の瞬時周波数が上がり、動かし終えると元の音程へ戻る（±5 セント） (5) `feedback=0.98`・フルスケール入力・`drive_db=24` で出力有界、入力停止 60 s 後に −120 dBFS 未満 (6) 途中から描画しても全長描画の該当部分と一致
- 依存：BB-00（curve）、BB-05、BB-09、BB-13

---

## 実装単位

| 単位 | 中身 | 前提 | 量 | 実働 |
|---|---|---|---|---|
| U-04a | BB-09 分数遅延線と帰還核、DT 群の試験 | BB-01 | M | Codex |
| U-04b | `pingpong_delay`、`multitap_delay`、`slapback` | BB-00、U-04a | S×3 | Codex |
| U-04c | `tape_delay`、`mod_delay` | U-04a、BB-05、BB-13 | M＋M | Codex |
| U-04d | `bbd_delay` | 調査レッグ、U-04a | M | Codex |
| U-04e | `granular_delay` | U-04a、BB-05 | M | Codex |
| U-04f | `pitch_delay` | U-04a、BB-11 | L | Codex |
| U-04g | SD ブロック（全遅延型へ）と T04-08 の試験 | BB-14 | S | Codex |
| U-04h | `freeze_delay`、`dub_delay` | U-04a、BB-05、BB-13 | M＋M | Codex |
