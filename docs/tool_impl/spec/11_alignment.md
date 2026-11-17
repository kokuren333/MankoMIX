# spec/11 アライメント／編集支援（8 件）

カタログ §11。共通規約は `spec/01_dynamics.md` §0。表面の分け方は `spec/08_pitch_time.md` §0.1。タグは 2 代目 PM が付けた。**aubio（GPL）・madmom の学習済みモデル（既存の不採用）は使わない。**

## 0. カテゴリ共通

- 本カテゴリは大半が「測って、編集の指示か候補を出す」道具。置き場（PM_PLAN §6）：測るだけ＝下見コマンド／観察量、素材の時間を動かす＝編集段の op＋派生クリップ（BB-18）、信号に固定の遅延・極性を当てる＝プロセッサ
- **機械は「合っていない」と判定しない。** 出すのは測定値（ずれ・相関・当てになり度）だけ。新しい警告・ゲートは作らない
- 複数トラックをまとめて動かす op は `group`（トラック ID の配列）を取り、**全員に同じ時間写像を当てる**（マルチマイクの位相関係を壊さない）
- 部品：BB-17（遅延推定・極性）、BB-22（発音点の検出）、BB-23（DTW と時間写像）、BB-11b（写像に沿う伸縮）、BB-18（派生クリップ）

**発音点の検出（BB-22）の定義**（本カテゴリの全件が同じものを使う）：

- 特徴：スペクトル流束（対数圧縮した振幅の、フレーム間の正の増分の和）。帯域別（低 <200／中 200〜2500／高 >2500 Hz）にも出す。窓 1024・歩み 256（48 kHz 基準。sr に比例）。打楽器的でない立ち上がり（声・弦）には、位相偏差を併用した複素領域の流束を `kind=soft` で
- 山の選択：移動中央値＋移動平均×係数の適応閾値、最小間隔。**因果性は要らない**（オフライン。前後を見る）
- 位置の精密化：流束の山の前で、広帯域の包絡が立ち上がり始める点（最大傾斜の接線が雑音床と交わる点）へ戻す。精度の目標 ±2 ms
- 出力：時刻（サンプル）、強さ（流束の山の高さ、0〜1 に正規化）、ピークレベル（dBFS）、帯域の比、当てになり度
- 正典：Bello, Daudet, Abdallah, Duxbury, Davies & Sandler「A Tutorial on Onset Detection in Music Signals」IEEE Trans. SAP 2005／Dixon「Onset Detection Revisited」DAFx-06／Böck & Widmer「Maximum Filter Vibrato Suppression for Onset Detection」DAFx-13（論文だけ。同著者の madmom の学習済み部分は使わない）

**共通テスト（AT）**：(AT1) 読み取り専用のコマンドは、実行前後でプロジェクトのハッシュ一致・ファイル生成なし (AT2) 出力がビット一致で再現 (AT3) CLI と MCP の等価性 (AT4) op を含まない指揮書の全出力がバイト同一（G0-4） (AT5) 派生クリップがキャッシュ削除後に同じ sha256 で作り直せる (AT6) プロジェクトの尺が不変

---

## T11-01 ボーカルタイミングアライメント

**編集段の op `edit_align_time`（派生クリップ）＋下見 `direction query align_time`（写像だけ計算して見せる）**｜B｜W3（op の配線は W4）｜L（BB-23 と可変伸縮の受け入れを兼ねる）｜Codex

| id | 単位 | 範囲 | 省略時 |
|---|---|---|---|
| `guide` | トラック ID | `target` と別 | （必須） |
| `max_shift_ms` | ms | 10〜500 | 120（各時点で動かせる上限） |
| `tightness` | 0..1 | 0〜1 | 0.7（1＝写像どおり。<1＝写像と恒等の間を配分。元の間合いを残す） |
| `stretch_min`・`stretch_max` | 倍 | 0.25〜1／1〜4 | 0.5／2（局所の伸縮率の上下限＝DTW の傾き制約） |
| `feature` | 列挙 | `onset_env`／`spectral`／`both` | `both`（発音の包絡／帯域エネルギーの形／両方の重み付き） |
| `smooth_ms` | ms | 0〜500 | 80（写像の平滑） |
| `anchors` | 配列（最大 64 組の `[target の秒, guide の秒]`） | 単調増加 | 空（書けば、その点を必ず通る。DTW が外したときの手直し） |
| `protect_sustain` | 0..1 | 0〜1 | 0.5（伸縮を、持続音の中〈音程が安定した区間〉へ寄せ、子音・発音の頭を伸縮しない度合い） |
| `quality` | 列挙 | `standard`／`high` | `standard`（声は WSOLA が向く） |
| `group` | トラック ID の配列 | 最大 8 | 空（`target` と同じ写像を当てる仲間） |
| `section` | — | — | クリップ全体 |

- アルゴリズム：(1) 両者の特徴列（歩み 5 ms）：発音の包絡（BB-22 の流束）＋ 対数メル帯域エネルギー（24 帯。時間方向の差分も）。レベルの違いに鈍くするため各帯を正規化 (2) DTW：傾き制約（`stretch_min`〜`stretch_max`）と帯幅（`max_shift_ms`）、局所コストはコサイン距離。同点の経路選択は固定の優先順（対角→横→縦） (3) 経路 → 時間写像（単調）→ `smooth_ms` で平滑 → `tightness` で恒等と配分 → `protect_sustain`：局所の伸縮率を、持続区間に重く・発音点の前後 30 ms に軽く再配分（写像の端点と各発音点の対応は保つ） (4) 写像に沿って可変伸縮（BB-11b。T08-10 `edit_stretch` の `map`） 。両者が無音の区間は恒等
- 正典：Sakoe & Chiba「Dynamic Programming Algorithm Optimization for Spoken Word Recognition」IEEE Trans. ASSP 1978（傾き制約と帯）／Müller『Fundamentals of Music Processing』（Springer。DTW・音楽同期の章）／Verhelst & Roelands 1993（WSOLA）／Driedger & Müller 2016。**Synchro Arts の特許・製品は読まない**
- 記録：写像の統計（動かした量の中央値・最大、伸縮率の範囲）、DTW の平均コスト（合い具合）、対応が怪しい区間（局所コストが高い区間の一覧。当てになり度 `low`）、処理前後の「発音点のずれ」の分布（`guide` に対し）
- テスト（AT に加えて）：(1) 合成母音列（音節 16 個）を `guide`、同じ列に既知の滑らかな時間写像（±80 ms）を掛けたものを `target`：処理後の各発音点のずれが中央値 ≤ 10 ms・最大 ≤ 25 ms（処理前は 80 ms 級） (2) 推定した写像と真の写像の差の RMS ≤ 12 ms (3) 既に合っている組：写像が恒等 ±3 ms → 派生を作らない（閾値を置く） (4) 音程不変（±3 セント）、子音相当のバーストの時間的な広がりが PT5 の基準 (5) `anchors`：指定点を ±1 ms で通る (6) `group`：仲間のトラックと `target` の相互相関のずれが処理前後で同じ（±1 サンプル） (7) `tightness=0`：派生を作らない (8) 歌詞の違う組（特徴が合わない）：平均コストが高く、当てになり度 `low` と記録される（止めはしない）
- 依存：BB-06、BB-11、BB-18、BB-22、BB-23

## T11-02 ボーカル ピッチ＋タイミングアライメント

**編集段の op `edit_align_pitch`（派生クリップ）**｜B｜W3（T11-01・T08-01 の後）｜M｜Codex

`edit_align_time` の全パラメータ（時間も合わせる。`time=false` で音程だけ）に加えて：

| id | 単位 | 範囲 | 省略時 |
|---|---|---|---|
| `time` | 真偽 | — | true |
| `interval` | 列挙／半音 | `unison`／`auto`／−24〜24 | `auto`（`auto`＝音符ごとに、`guide` との音程差を最寄りの半音に丸めて保つ＝ハモリはハモリのまま。`unison`＝同じ高さへ） |
| `pitch_tightness` | 0..1 | 0〜1 | 0.6 |
| `keep_vibrato` | 0..1 | 0〜1 | 0.7（`target` 自身の揺れを残す度合い。0＝`guide` の線をなぞる） |
| `max_cents` | セント | 0〜300 | 100（動かす上限。超える音符は触らず、記録に出す） |
| `formant` | 真偽 | — | true |

- アルゴリズム：(1) T11-01 の写像で時間を対応づける（`time=false` でも対応づけだけは使う）(2) 両者の音程の軌跡（BB-12）を音符に区切る（T08-01 と同じ）(3) 音符ごとの目標＝`guide` の対応する音符の中央値＋`interval` (4) 補正曲線を `pitch_tightness`・`keep_vibrato` で整形 (5) T08-14 `pitch_curve` と同じ核（PSOLA、フォルマント保存）で適用。時間の伸縮と同じ 1 回の合成で行う（2 回通さない）
- 正典：T11-01・T08-01 の正典
- テスト（AT に加えて）：(1) `guide`＝合成の旋律、`target`＝同じ旋律を音符ごとに ±40 セントずらし、時間も写像でずらしたもの：処理後の音符ごとの音程差が ≤ 8 セント（`pitch_tightness=1`）、発音点のずれは T11-01 (1) の基準 (2) `target` が 3 度上のハモリ：`interval=auto` で 3 度（長・短）が保たれ、各音符が最寄りの半音差 ±8 セント (3) `max_cents` 超えの音符は不変で、記録に載る (4) `keep_vibrato=1`：`target` のビブラート幅が 80 % 以上残る (5) PT6（フォルマント）
- 依存：BB-11、BB-12、BB-18、BB-19、BB-23、T08-01、T08-14、T11-01

## T11-03 位相／タイムアライメント

**下見コマンド `direction suggest align`（測る）＋プロセッサ `time_align`（当てる）**｜D＋A｜W4（`time_align` は W1）｜M｜Codex

`time_align`（`stages: ["track","bus"]`、時不変、`channel` 欄は可）：

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `delay_ms` | f | ms | 0〜100 | 0（分数遅延。**進める方向は無い**：早い側を遅らせて合わせる） |
| `polarity_invert` | b | — | — | false |
| `allpass_hz` | f | Hz | 0、または 20〜20000 | 0（0＝無効。1 次全通過の折点：低域と高域の位相関係だけを回す。遅延で合わない位相ずれ用） |
| `allpass_stages` | i | 段 | 1〜4 | 1 |

- アルゴリズム：整数部は整数遅延、小数部は窓付き sinc（BB-09）。全パラメータ既定で経路を通さない。**遅延はレイテンシとして補償しない**（わざと遅らせるため）
- テスト：既定でビット一致／インパルスの遅延が設定 ±0.01 サンプル（重心で測る）、振幅特性 ±0.01 dB（0.9×ナイキスト以下）／極性反転が厳密に符号反転／全通過：振幅平坦、位相が折点で −90°×段数

`direction suggest align`：

| 引数 | 範囲 | 省略時 |
|---|---|---|
| `--project`、`--tracks trk_a,trk_b,…` | 2〜16 本（同じ音源を録った仲間） | 必須 |
| `--reference` | トラック ID／`auto` | `auto`（最も遅く届いているトラックを基準に＝他を遅らせるだけで済む） |
| `--max-ms` | 0.1〜100 | 30 |
| `--section` | — | 全体（区間ごとの値のばらつきも出す） |
| `--band-hz lo hi` | — | 40 8000 |
| `--mode` | `delay`／`delay_polarity`／`phase` | `delay_polarity` |

- アルゴリズム：対ごとに GCC-PHAT（BB-17。10 s ごとの区間で推定し、中央値とばらつき）→ サンプル以下は放物線補間 → 極性は、揃えた後の相関の符号 → 全員の遅延を、対ごとの推定の最小二乗で整合させる（3 本以上のとき、a–b・b–c・a–c の矛盾を均す）→ `phase`：残った位相ずれを帯域別（1/3 oct）に測り、1 次全通過で減らせるなら提案
- 出力（JSON）：トラックごとの `delay_ms`・極性・（全通過）、対ごとの「揃える前後の相関」「合算の帯域別レベル変化（揃えると何 dB 増えるか）」、当てになり度（区間ごとのばらつき、相関の山の鋭さ）、貼れる `chain_add`（`time_align`）
- **注意を出力に固定で付ける**：「相関が最大になる位置が、音として最良とは限らない（オーバーヘッドとスネアの関係など）。合算の帯域別変化を見て決める」
- 正典：Knapp & Carter 1976（GCC）／Clifford & Reiss「Calculating Time Delays of Multiple Active Sources in Live Sound」AES Conv. 125（2008）／Perez-Gonzalez & Reiss「Determination and Correction of Individual Channel Time Offsets for Signals Involved in an Audio Mixture」AES Conv. 125（2008）
- テスト（AT1〜3 に加えて）：(1) 同じ合成音源を 3 本に、遅延（0／1.37／4.02 ms）・片方だけ極性反転・別々の軽い色づけ・無相関雑音（SNR 20 dB）を付けたもの：遅延の推定 ±0.02 ms、極性が正しい (2) 提案を貼って描画すると、3 本の合算の 100 Hz〜4 kHz のレベルが、ずれの無い場合の ±0.5 dB (3) 無関係な 2 トラック：相関の山が低く、当てになり度 `low`、提案は出すが注記つき (4) 候補が validate の範囲検査を通る
- 依存：BB-09、BB-17

## T11-04 ドラムアライメント＋ゲート

**`direction suggest align` の `--preset drums`（T11-03 と同じコマンド）＋プロセッサ `drum_gate`**｜D＋A｜W2（`drum_gate`）／W4（コマンド）｜M｜Codex

`--preset drums`：`--tracks` に役割を付ける（`kick:trk_k,snare:trk_s,oh:trk_oh,…`）。近接マイク（キック・スネア・タム）を、オーバーヘッド／ルームへ届く時刻に対して測る。**打音ごとに測る**（BB-22 で近接マイクの打点を拾い、各打点の前後 30 ms で相関）ので、他の太鼓のかぶりに惑わされにくい。出力は T11-03 と同じ＋「どちらに合わせる案もある」（近接を遅らせる／オーバーヘッドはそのまま、を既定の提案に。逆は `time_align` が進められないので出さない）。

`drum_gate`（`stages: ["track"]`、TV、`offline_only: True`）：

| id | 型 | 単位 | 範囲 | 既定 |
|---|---|---|---|---|
| `threshold_db` | f | dBFS | −80〜0 | −30（検出帯域の打点のピーク） |
| `detect_lo_hz`・`detect_hi_hz` | f | Hz | 20〜20000 | 40／200（狙う太鼓の帯域。既定はキック） |
| `reject_lo_hz`・`reject_hi_hz` | f | Hz | 0〜20000 | 0／0（0＝無効。かぶりの帯域：ここのエネルギーが検出帯域より `reject_ratio_db` 以上強い打点は開けない） |
| `reject_ratio_db` | f | dB | −12〜24 | 6 |
| `range_db` | f | dB | −90〜0 | −40 |
| `lookahead_ms` | f | ms | 0〜20 | 5 |
| `attack_ms` | f | ms | 0.05〜20 | 0.5 |
| `hold_ms` | f | ms | 0〜2000 | 60 |
| `release_ms` | f | ms | 10〜3000 | 200 |
| `decay_follow` | f | 0..1 | 0〜1 | 0.6（閉じ方を、その打音の実際の減衰〈検出帯域の包絡〉に沿わせる度合い。0＝固定の `release_ms`） |
| `velocity_sense` | f | 0..1 | 0〜1 | 0.3（弱い打音ほど開く量を減らす〈0＝全部同じに開く〉。ゴーストノートを残すなら 0） |
| `min_interval_ms` | f | ms | 5〜500 | 30 |
| `resonance_cut` | f | 0..1 | 0〜1 | 0（閉じる間、検出帯域の下 1 oct だけ先に閉じる＝胴鳴りの尾を短く） |

- アルゴリズム：T01-07 `gate` の状態機械に、(a) 発音点検出（BB-22。包絡の閾値越えでなく「打点」で開く）(b) 帯域比によるかぶりの拒否 (c) 打音ごとの減衰追従、を足したもの。記録に打点の一覧（時刻・強さ・開けた／拒否した理由）
- 正典：Bello ほか 2005／Giannoulis ほか 2012。**Sonnox の製品の挙動は測らない**
- テスト：(1) 合成のキック（60 Hz の減衰正弦＋クリック）20 打と、スネア相当のかぶり（200 Hz＋雑音、−10 dB）20 打：キックで全部開き、かぶりで開かない（`reject` 設定あり） (2) 開いている間は入力とビット一致（先読み補償後）、打音の頭 5 ms のエネルギー損失 ≤ 0.1 dB (3) 閉じた区間が `range_db` ±0.5 dB (4) `decay_follow=1`：長い減衰の打音では閉じ始めが遅い（単調） (5) 記録の一覧と実際の開閉が一致 (6) CT-5
- 依存：BB-03、BB-17、BB-22、T01-07 の核

## T11-05 ドラムリプレイスメント／サンプル補強

**mix 段の op `drum_replace`（打点を拾い、サンプルを並べたトラックを足す）**｜D｜W4｜M｜Codex

| id | 単位 | 範囲 | 省略時 |
|---|---|---|---|
| `sample` | 資産 ID（`samples` レジストリ。BB-24） | 登録済み。**または** `samples`：強さ別の配列（最大 8 層、各 `{id, min_velocity}`） | （必須） |
| `mode` | 列挙 | `add`／`replace` | `add`（`replace`＝元トラックを打点の間だけ `original_db` へ下げる線も書く） |
| `blend_db` | dB | −24〜6（範囲可） | −6（足すサンプルのレベル。元の打音のピーク比） |
| `original_db` | dB | −90〜0 | −90（`replace` のとき） |
| `threshold_db`・`detect_lo_hz`・`detect_hi_hz`・`reject_*`・`min_interval_ms` | | T11-04 と同じ | 同じ |
| `velocity_curve` | curve（x：検出した強さ 0〜1／y：サンプルのゲイン dB −24〜0） | 最大 16 点、単調非減少 | `[[0,-18],[1,0]]` |
| `align` | 列挙 | `onset`／`phase` | `phase`（`onset`＝打点の時刻に置く。`phase`＝±2 ms の範囲で、元の打音との相互相関が最大の位置へ〈極性も合わせる〉） |
| `tune_semitones` | 半音 | −12〜12 | 0（サンプルの再生速度） |
| `humanize_db` | dB | 0〜3 | 0（打点ごとのシード付きのレベルの揺れ） |
| `round_robin` | 真偽 | — | false（同じ強さの層に複数のサンプルがあるとき順に使う） |
| `seed` | — | 0〜65535 | 0 |
| `only`・`skip` | 打点 ID の配列 | 最大 1024 | 空 |

- 展開：打点の一覧（T11-08 と同じ ID）→ 新しいトラック（`bus_add` と同じ「指揮書がノードを足す」流儀。ID は op の `move_ref` から決まる）に、サンプルのクリップを打点ごとに置く（台帳。クリップは資産 ID・位置・ゲイン・極性・速度）。新トラックは元トラックと同じバスへ送る。**元素材は書き換えない**
- **サンプル資産（BB-24）の規律**：`registry/samples.json`。BB-08（IR）と同じ規則。**同梱は自作合成（生成スクリプトつき）と CC0 を一次で確かめたものだけ**。市販のサンプルパック・ドラム音源の付属音は同梱しない（PM_PLAN OD-13）。持ち込みはローカル登録、ライセンス欄必須
- 記録：打点ごとの「時刻・強さ・使ったサンプル・ゲイン・ずらした量・極性」
- 正典：Bello ほか 2005／Knapp & Carter 1976（位置合わせ）
- テスト（AT4 に加えて）：(1) 合成のスネア 40 打（強さ 4 段階）：全打点を ±2 ms で拾い、置いたサンプルの頭が打点 ±0.5 ms（`onset`） (2) `phase`：置いたサンプルと元の打音の相互相関が、±2 ms の範囲の最大に一致、極性が正の相関側 (3) `velocity_curve` どおりのゲイン（±0.1 dB）、層の選択が `min_velocity` どおり (4) `replace`：元トラックの線が打点の間 `original_db`、外は 0 (5) 同一 `seed` で台帳がバイト同一 (6) 未登録の資産・ライセンス欄なしは明示エラー (7) `only`／`skip`
- 依存：BB-00（asset、curve）、BB-14、BB-17、BB-22、BB-24

## T11-06 オーディオ→MIDI 変換

**コマンド `direction extract midi`（読み取り専用。`--out` を書いたときだけ、指定のファイルを 1 つ書く）**｜D｜W4｜M｜Codex

| 引数 | 範囲 | 省略時 |
|---|---|---|
| `--project`、`--target trk_<stem>` | 必須 | — |
| `--kind` | `drums`／`mono` | 必須（`drums`＝打点と強さ。`mono`＝単音の旋律。**和音は対象外**） |
| `--note` | 0〜127 | 36（`drums`：全打点をこの番号へ）。`--map lo:hi:note,…` で帯域の比ごとに番号を分ける（例：キック／スネア／ハットを 1 本のトラックから） |
| `--threshold-db`・`--min-interval-ms` | T11-04 と同じ | 同じ |
| `--velocity-range lo hi` | 1〜127 | 20 127（検出した強さの最小〜最大を写す） |
| `--bpm`・`--origin` | 20〜400／秒 | プロジェクトのテンポ（無ければ 120 で、時刻は秒から換算） |
| `--quantize` | `off`／`NOTE_VALUES` | `off`（出力の位置だけ丸める。音は動かさない） |
| `--min-note-ms`・`--lo-hz`・`--hi-hz`・`--a4`・`--bend` | `mono` 用。`--bend`＝音符内の音程の動きをピッチベンドで出す | 60／70／1000／440／off |
| `--section`、`--out FILE.mid` | — | 標準出力に JSON だけ |

- アルゴリズム：`drums`＝BB-22 の打点。強さ＝流束の山とピークレベルの合成。`mono`＝T08-02 `direction pitch notes` と同じ音符化（pYIN＋区切り）。SMF（標準 MIDI ファイル。形式 0、480 ティック/四分）は**自前で書く**（仕様が単純。依存を足さない）
- 出力：JSON（音符の一覧：時刻・長さ・番号・強さ・当てになり度）と、任意で SMF
- 正典：MIDI 1.0 仕様と Standard MIDI Files 1.0（MIDI Manufacturers Association の公開仕様）／Bello ほか 2005／Mauch & Dixon 2014
- テスト（AT1〜3 に加えて）：(1) 既知の打点 60 個の合成ドラム：F 値 ≥ 0.95（許容 ±10 ms）、時刻の誤差の中央値 ≤ 3 ms (2) 強さ 4 段階がベロシティの大小関係に写る（順位が保たれる） (3) 合成の旋律 16 音：番号が全部正しい、頭 ±20 ms、長さ ±40 ms (4) 書いた SMF を自前の読み取りで読み戻すと JSON と一致（ティックの丸めの範囲） (5) `--out` 無しでは何も書かない。`--out` はプロジェクトの外でも中でもよいが、プロジェクトの正本・台帳には触れない (6) `--map`：帯域比で 3 種に分けた合成素材で分類の正解率 ≥ 90 %
- 弱点：1 本のトラックに複数の太鼓が混じる素材の分類（`--map`）は帯域比だけで、当てにならない。和音の採譜はしない（学習系の領域。`tool_requests` へ）
- 依存：BB-12、BB-22、T08-02 の音符化

## T11-07 オーディオクオンタイズ

**編集段の op `edit_quantize`（派生クリップ）**｜D（PM 判断：検出＋編集の組み立て。新しいアルゴリズムは無い）｜W4｜M｜Codex

| id | 単位 | 範囲 | 省略時 |
|---|---|---|---|
| `grid_note` | `NOTE_VALUES`（`none` 不可） | — | `1/16` |
| `bpm`・`origin_s` | BPM／秒 | 20〜400／0〜36000 | （`bpm` 必須。テンポ一定が前提） |
| `swing` | 0..1 | 0〜0.75 | 0 |
| `strength` | 0..1 | 0〜1（範囲可） | 0.7（各打点を格子へ寄せる割合。1＝格子の上） |
| `max_shift_ms` | ms | 1〜200 | 40（これより遠い打点は動かさない＝意図した外しとみなす） |
| `min_shift_ms` | ms | 0〜50 | 3（これより近い打点は動かさない） |
| `mode` | 列挙 | `slice`／`stretch` | `slice`（`slice`＝打点の直前で切って動かし、隙間を伸ばして埋める・重なりを交差で消す。打楽器向き。`stretch`＝打点を通る時間写像で伸縮。持続音向き） |
| `slice_pre_ms` | ms | 0〜20 | 3（打点のどれだけ前で切るか） |
| `fill` | 列挙 | `stretch_tail`／`silence` | `stretch_tail`（隙間の埋め方：前の断片の尾を伸ばす／無音） |
| `threshold_db`・`detect_lo_hz`・`detect_hi_hz`・`min_interval_ms` | | T11-04 と同じ | 同じ（全帯域） |
| `detect_from` | トラック ID | — | `target` 自身（別のトラックの打点で `target` を動かす。例：キックの打点でベースを切る） |
| `group` | トラック ID の配列 | 最大 16 | 空（同じ切り位置・同じ移動量を全員に当てる。**マルチマイクのドラムは必ず `group`**） |
| `only`・`skip` | 打点 ID の配列 | 最大 1024 | 空 |
| `section` | — | — | クリップ全体 |

- アルゴリズム：打点（BB-22）→ 最寄りの格子点（`swing` 込み。同距離は前）→ 移動量＝`strength`×差（`min`〜`max` の外は 0）→ 打点の順序が入れ替わる移動は拒否（その打点を動かさない）→ `slice`：切り位置は打点の `slice_pre_ms` 前の最寄りのゼロ交差（±1 ms の範囲。`group` では基準トラックのゼロ交差を全員に使う）、断片を移動、隙間は尾の伸縮（BB-11b）か無音、重なりは 5 ms の交差／`stretch`：打点と移動後の時刻の組を T08-10 の `map` にして伸縮
- 正典：Bello ほか 2005／Driedger & Müller 2016
- 記録：打点ごとの「元の時刻・格子・動かした量・動かさなかった理由」、処理前後の「格子からのずれ」の分布
- テスト（AT に加えて）：(1) 既知のずれ（±25 ms の一様乱数）を持つ合成ドラム 64 打：処理後のずれが (1−`strength`)×元 ±2 ms (2) `strength=1`：全打点が格子 ±1 ms (3) `max_shift_ms` より遠い打点は不変 (4) `slice`：断片の内部（切り位置と交差の外）が元とビット一致（位置だけ違う） (5) 継ぎ目のクリックなし（広帯域エネルギーの突出 ≤ 3 dB） (6) `group`：仲間どうしの相互相関のずれが処理前後で同じ（±0 サンプル：`slice` は整数サンプル移動） (7) `strength=0`：派生を作らない
- 依存：BB-11、BB-18、BB-22

## T11-08 トランジェント／ヒットポイント検出

**観察量 `onsets`（`observations` の primitive の追加）＋下見 `direction query onsets`**｜D（カタログ：「分析量として」）｜W4（核の BB-22 は W2）｜S｜Codex

- primitive `onsets`：`target`（`trk_<stem>`／`master`）、`section`、`params`：`kind`（`percussive`／`soft`、既定 `percussive`）、`band`（`full`／`low`／`mid`／`high`）、`threshold`（0〜1、0.3）、`min_interval_ms`（5〜500、30）。値：打点の数、1 秒あたりの数、強さの分布（中央値・四分位）、**格子を渡したとき**（`grid_note`・`bpm`・`origin_s`）は格子からのずれの分布（中央値・四分位・最大。符号つき＝前ノリ／後ノリ）。観察量なので、指揮書の「意図に対する実測」に使える。**合否・警告は作らない**
- `direction query onsets`：一覧（ID＝`o_<サンプル位置>`、時刻、強さ、ピークレベル、帯域の比、当てになり度）。`--against trk_x` で、2 本の打点の対応と時間差の分布（T11-01・T11-07 の前後比較に使う）。T11-05・06・07 の `only`／`skip` はこの ID を使う
- **ID の安定性**：ID は打点のサンプル位置から決まる。素材と検出パラメータが同じなら同じ ID。パラメータを変えると ID の集合が変わるので、`only`／`skip` を書いた op は検出パラメータも一緒に固定して書く（op の検査で、`only`／`skip` があるのに検出パラメータが省略なら警告ではなく**拒否**）
- 映像側（MV の signals）と同じ系統の量だが、**共有コードにはしない**（別プロジェクト。定義だけ docs で揃える）
- テスト（AT1〜3 に加えて）：(1) §0 の定義の受け入れ試験：合成ドラム（既知 200 打点、強さ 3 段階、かぶり雑音あり）で F 値 ≥ 0.95（±10 ms）、位置の誤差の中央値 ≤ 2 ms／合成母音列（`soft`）で F 値 ≥ 0.85（±30 ms） (2) 定常音・ゆっくりしたフェードで検出 0 件 (3) sr 44.1k／48k／96k で同じ打点（±1 ms） (4) 格子からのずれの分布が、既知のずれを仕込んだ素材で ±1 ms (5) primitive を使わない指揮書はバイト同一、既存の primitive の値が不変
- 依存：BB-22

---

## 実装単位

| 単位 | 中身 | 前提 | 量 | 実働 |
|---|---|---|---|---|
| U-11a | BB-22（発音点検出）とその受け入れ試験（T11-08 (1)〜(3)） | BB-01、BB-06 | S | Codex |
| U-11b | `time_align`、BB-17（遅延推定・極性） | BB-07、BB-09 | S＋S | Codex |
| U-11c | `drum_gate` | U-11a、U-01a（`gate`） | M | Codex |
| U-11d | BB-23（DTW・時間写像）と op `edit_align_time`、`direction query align_time` | U-11a、BB-11、BB-18 | M＋L | Codex |
| U-11e | op `edit_align_pitch` | U-11d、U-08e、U-08c | M | Codex |
| U-11f | `direction suggest align`（`--preset drums` 含む） | U-11a、U-11b | M | Codex |
| U-11g | primitive `onsets`、`direction query onsets`、`direction extract midi` | U-11a、U-08i の音符化 | S＋M | Codex |
| U-11h | op `edit_quantize` | U-11a、BB-11、BB-18 | M | Codex |
| U-11i | BB-24 のうち `samples` レジストリ、op `drum_replace` | U-11a、U-11b、BB-14 | S＋M | Codex |
### 実装時の確定（統括の判断 D-24・D-29）

観察量 `onsets` と `direction query onsets` は測定用。direction層の新コマンドはCLI専用で、MCPの計画名はツール公開を意味しない。この規則は本カテゴリのsuggest align・extract midi・query align_timeにも適用する。下見の実施・順序を新しいゲートにしない。
