# docs/tool_impl — 「無いツール 143 件」の設計資料

楽曲制作で普通に使われているのに MankoMIX に無い処理・道具 143 件を、MankoMIX の契約（決定論、床のビット同一、ゲート定義の不変、ライセンスの線引き）の中で実装するための設計資料。

| ファイル | 中身 |
|---|---|
| `TOOL_CATALOG.md` | 143 件のカタログ（12 カテゴリ）。代表的な市販品の名前は「どんな役割の道具か」を示すためだけに挙げている。実装はその製品の内部や出力を参照しない |
| `PM_PLAN.md` | 計画書：共有部品 BB-00〜25、ウェーブ W0〜W6、学習系（タグ C）の「完全実装」の定義、オーナー判断 OD-1〜18、弱点と未決事項 |
| `spec/01_dynamics.md`〜`spec/12_mastering.md` | 全 143 件の実装仕様（型名・パラメータの範囲と既定値・アルゴリズム・正典資料・テスト基準）。`spec/01` の §0 が全カテゴリ共通の規約 |

- 位置づけ：設計段階の資料。パラメータの範囲・既定値は机上の値で、実装時に測定で確かめてから確定する（確定前の型は `implemented: false`）。実装で動かした値は、その型の `describe()` が正になる。
- ライセンス：アルゴリズムは論文・教科書・公開仕様から書く。GPL／AGPL の実装は移植も参照もしない（`spec/01` §0.2）。
- 重複：カタログ §1-13 と §12-1 は同一機能（T12-01 は T01-13 で充足）。カタログに注記がある。

<!-- tool-status:begin -->
## 実装状況（143 件）

型の `implemented` は実行時の `describe()` から取得する。op・コマンド・観察量には同名のフラグがないため、登録の有無を表示する。登録は実録音での品質の保証ではない。

再生成: `python -X utf8 tools/tool_status_table.py`。検査だけなら `--check`。対応表は同スクリプト、名前と ID は各 spec、型の真偽と表面の在否は実装の宣言を正とする。

T12-01 は T01-13 の重複で、同じ `adaptive_limiter` により充足する（件数は143のまま）。GUI の3部分は OQ-3（D-28）で保留。T10-15 の衣擦れ側は再配布可能な OSS 重みが見つからず未実装（D-29）。

| ツール ID | 名前 | 実装した表面／予定の表面 | implemented／登録 | 未実装・保留の理由／注記 |
|---|---|---|---|---|
| T01-01 | マルチバンドコンプレッサー | 型 `mb_compressor` | `mb_compressor`: `true` | — |
| T01-02 | マルチバンドエクスパンダー／ゲート | 型 `mb_expander` | `mb_expander`: `true` | — |
| T01-03 | マルチバンド・トランジェントシェイパー | 型 `mb_transient` | `mb_transient`: `true` | — |
| T01-04 | トランジェントシェイパー（単バンド） | 型 `transient_shaper` | `transient_shaper`: `true` | — |
| T01-05 | アップワードコンプレッサー | 型 `upward_compressor` | `upward_compressor`: `true` | — |
| T01-06 | 双方向レベラー | 型 `leveler` | `leveler`: `true` | — |
| T01-07 | ゲート／エクスパンダー（音響型） | 型 `gate` | `gate`: `true` | — |
| T01-08 | パラレルコンプ専用機 | 型 `parallel_comp` | `parallel_comp`: `true` | — |
| T01-09 | ボリュームシェイパー（描画カーブ周期変調） | 型 `volume_shaper` | `volume_shaper`: `true` | — |
| T01-10 | サイドチェインダッカー専用機（カーブ型） | 型 `band_automation`、型 `gain_automation`、op `duck_curve` | `band_automation`: `true`、`gain_automation`: `true`、`duck_curve`: 登録済み | — |
| T01-11 | ゲインライダー | op `ride` | `ride`: 登録済み | — |
| T01-12 | マルチバンドリミッター | 型 `mb_limiter` | `mb_limiter`: `true` | — |
| T01-13 | 適応型（ダイナミック）リミッター | 型 `adaptive_limiter` | `adaptive_limiter`: `true` | — |
| T01-14 | 多段リミッターチェイン | 型 `limiter_chain` | `limiter_chain`: `true` | — |
| T01-15 | リニアフェイズ・マルチバンド | 型 `mb_compressor` | `mb_compressor`: `true` | — |
| T02-01 | リニアフェイズ EQ | 型 `linear_eq` | `linear_eq`: `false` | 100 Hz・0.3 oct・±24 dB・mid の誤差 ≤0.1 dB が未達（D-9） |
| T02-02 | ミッド／サイド EQ | 型 `eq`、欄 `channel` | `eq`: `true` | — |
| T02-03 | ダイナミック共振抑制 | 型 `resonance_suppressor` | `resonance_suppressor`: `true` | — |
| T02-04 | スペクトル EQ（FFT ビン単位） | 型 `spectral_dynamics` | `spectral_dynamics`: `true` | — |
| T02-05 | ピッチ追従 EQ | 型 `pitch_eq` | `pitch_eq`: `true` | — |
| T02-06 | 自動スペクトルバランス | 型 `spectral_balancer` | `spectral_balancer`: `true` | — |
| T02-07 | AI アシスト EQ（提案系） | コマンド `direction suggest eq` | `direction suggest eq`: 登録済み | — |
| T02-08 | マッチ EQ | 型 `fir_eq`、コマンド `direction ref matcheq` | `fir_eq`: `true`、`direction ref matcheq`: 登録済み | — |
| T02-09 | ターゲット型ローエンド EQ | コマンド `direction suggest lowend` | `direction suggest lowend`: 登録済み | — |
| T02-10 | ビンテージ EQ モデリング | 型 `passive_eq`、型 `inductor_eq`、型 `proportional_eq`、型 `baxandall_eq` | `passive_eq`: `true`、`inductor_eq`: `true`、`proportional_eq`: `true`、`baxandall_eq`: `true` | — |
| T02-11 | チルト EQ | 型 `tilt_eq` | `tilt_eq`: `true` | — |
| T02-12 | カット専用フィルタ集（ブリックウォール） | 型 `cut_filter` | `cut_filter`: `true` | — |
| T03-01 | コンボリューション（IR）リバーブ | 型 `conv_reverb` | `conv_reverb`: `true` | — |
| T03-02 | アルゴリズミック・ホール／ルーム | 型 `reverb_hall` | `reverb_hall`: `true` | — |
| T03-03 | ヴィンテージ・デジタル | 型 `reverb_vintage` | `reverb_vintage`: `true` | — |
| T03-04 | チェンバー | 型 `reverb_chamber` | `reverb_chamber`: `true` | — |
| T03-05 | スプリングリバーブ | 型 `reverb_spring` | `reverb_spring`: `true` | — |
| T03-06 | シマーリバーブ | 型 `reverb_shimmer` | `reverb_shimmer`: `true` | — |
| T03-07 | ゲーテッド／ノンリニアリバーブ | 型 `reverb_gated` | `reverb_gated`: `true` | — |
| T03-08 | リバースリバーブ | 型 `reverb_reverse` | `reverb_reverse`: `true` | — |
| T03-09 | アーリーリフレクション専用機 | 型 `early_reflections` | `early_reflections`: `true` | — |
| T03-10 | フリーズ／インフィニットリバーブ | 型 `reverb_freeze` | `reverb_freeze`: `true` | — |
| T03-11 | ダッキングリバーブ | 型 `reverb_hall`、op `duck` | `reverb_hall`: `true`、`duck`: 登録済み | — |
| T04-01 | テープエコー | 型 `tape_delay` | `tape_delay`: `true` | — |
| T04-02 | BBD アナログディレイ | 型 `bbd_delay` | `bbd_delay`: `true` | — |
| T04-03 | ピンポンディレイ | 型 `pingpong_delay` | `pingpong_delay`: `true` | — |
| T04-04 | スラップバックディレイ | 型 `slapback` | `slapback`: `true` | — |
| T04-05 | マルチタップディレイ | 型 `multitap_delay` | `multitap_delay`: `true` | — |
| T04-06 | モジュレーションディレイ | 型 `mod_delay` | `mod_delay`: `true` | — |
| T04-07 | グラニュラーディレイ | 型 `granular_delay` | `granular_delay`: `true` | — |
| T04-08 | ダッキングディレイ | 型 `tape_delay`、op `duck` | `tape_delay`: `true`、`duck`: 登録済み | — |
| T04-09 | ピッチシフト／周波数シフトディレイ | 型 `pitch_delay` | `pitch_delay`: `true` | — |
| T04-10 | ルーパー／フリーズディレイ | 型 `freeze_delay` | `freeze_delay`: `true` | — |
| T04-11 | ダブディレイ | 型 `dub_delay` | `dub_delay`: `true` | — |
| T05-01 | Haas ワイドナー | 型 `haas` | `haas`: `true` | — |
| T05-02 | バイノーラル／3D パンナー | 型 `binaural_pan` | `binaural_pan`: `true` | — |
| T05-03 | オートパン | 型 `autopan` | `autopan`: `true` | — |
| T05-04 | Doppler | 型 `doppler` | `doppler`: `true` | — |
| T05-05 | 周波数別ステレオ配置 | 型 `band_pan` | `band_pan`: `true` | — |
| T05-06 | M/S プロセッシング基盤 | 型 `ms_gain`、欄 `channel` | `ms_gain`: `false` | 任意 float64 の M/S 往復のビット一致が未達（D-9、丸め） |
| T05-07 | アンビソニックス処理 | コマンド `spatial ambi encode`、コマンド `spatial ambi rotate`、コマンド `spatial ambi decode`、コマンド `spatial ambi convert`、コマンド `spatial ambi info` | `spatial ambi encode`: 登録済み、`spatial ambi rotate`: 登録済み、`spatial ambi decode`: 登録済み、`spatial ambi convert`: 登録済み、`spatial ambi info`: 登録済み | — |
| T06-01 | コーラス一族 | 型 `chorus` | `chorus`: `true` | — |
| T06-02 | フランジャー | 型 `flanger` | `flanger`: `true` | — |
| T06-03 | フェイザー | 型 `phaser` | `phaser`: `true` | — |
| T06-04 | ユニバイブ | 型 `vibe` | `vibe`: `true` | — |
| T06-05 | トレモロ（ハーモニック含む） | 型 `tremolo` | `tremolo`: `true` | — |
| T06-06 | ビブラート | 型 `vibrato` | `vibrato`: `true` | — |
| T06-07 | ロータリースピーカー | 型 `rotary` | `rotary`: `true` | — |
| T06-08 | リングモジュレーター | 型 `ring_mod` | `ring_mod`: `true` | — |
| T06-09 | 周波数シフター | 型 `freq_shifter` | `freq_shifter`: `true` | — |
| T06-10 | マイクロピッチ／デチューン | 型 `micro_pitch` | `micro_pitch`: `true` | — |
| T06-11 | ADT／ダブラー | 型 `adt` | `adt`: `true` | — |
| T06-12 | ワウフラッター（テープ揺らぎ） | 型 `wow_flutter` | `wow_flutter`: `true` | — |
| T07-01 | テープエミュレーション | 型 `tape` | `tape`: `true` | — |
| T07-02 | マルチバンド・サチュレーション | 型 `mb_saturator` | `mb_saturator`: `true` | — |
| T07-03 | トランスフォーマー・サチュレーション | 型 `transformer` | `transformer`: `true` | — |
| T07-04 | カセット／ローファイ劣化 | 型 `cassette` | `cassette`: `true` | — |
| T07-05 | エキサイター | 型 `exciter` | `exciter`: `true` | — |
| T07-06 | 位相系エンハンサー | 型 `phase_enhancer` | `phase_enhancer`: `true` | — |
| T07-07 | ラウドネス・エンハンサー（波形整形型） | 型 `loudness_shaper` | `loudness_shaper`: `true` | — |
| T07-08 | ベース倍音エンハンサー | 型 `bass_enhancer` | `bass_enhancer`: `true` | — |
| T07-09 | サブハーモニック生成 | 型 `sub_synth` | `sub_synth`: `true` | — |
| T07-10 | マルチバンド・ディストーション | 型 `mb_distortion` | `mb_distortion`: `true` | — |
| T07-11 | ファズ | 型 `fuzz` | `fuzz`: `true` | — |
| T07-12 | ビットクラッシャー／SR リダクション | 型 `bitcrush` | `bitcrush`: `true` | — |
| T07-13 | アンプシミュレータ | 型 `amp_sim`、型 `amp_basic` | `amp_sim`: `false`、`amp_basic`: `true` | 代替実行の Mix Report 接続に core の追加が必要（OQ-4、D-30） |
| T07-14 | キャビネット IR ローダー | 型 `cab_ir` | `cab_ir`: `true` | — |
| T07-15 | コンソールエミュレーション（バス色付け） | 型 `console_bus` | `console_bus`: `true` | — |
| T08-01 | 自動ピッチ補正 | 型 `pitch_correct` | `pitch_correct`: `true` | — |
| T08-02 | グラフィカル・ピッチ／タイミング編集 | 型 `pitch_curve`、コマンド `direction pitch notes`、op `edit_pitch`、GUI `音符表示` | `pitch_curve`: `true`、`direction pitch notes`: 登録済み、`edit_pitch`: 登録済み、GUI: 保留 | GUI API の追加が core 差分0と両立しない（OQ-3、D-28） |
| T08-03 | ハーモニー生成 | 型 `harmony_voices` | `harmony_voices`: `true` | — |
| T08-04 | ハーモナイザー | 型 `harmonizer` | `harmonizer`: `true` | — |
| T08-05 | ピッチシフター（高品質） | 型 `pitch_shift` | `pitch_shift`: `true` | — |
| T08-06 | ポリフォニック再調律 | 型 `poly_retune` | `poly_retune`: `true` | — |
| T08-07 | フォルマントシフター | 型 `formant_shift` | `formant_shift`: `true` | — |
| T08-08 | ボコーダー | 型 `vocoder`、型 `band_envelope`、op `vocode` | `vocoder`: `true`、`band_envelope`: `true`、`vocode`: 登録済み | — |
| T08-09 | トークボックス | 型 `talkbox` | `talkbox`: `true` | — |
| T08-10 | タイムストレッチ（高品質） | op `edit_stretch` | `edit_stretch`: 登録済み | — |
| T08-11 | 極端タイムストレッチ | op `edit_stretch_extreme` | `edit_stretch_extreme`: 登録済み | — |
| T08-12 | ハーフスピード／バリスピード | 型 `halftime`、op `edit_varispeed` | `halftime`: `true`、`edit_varispeed`: 登録済み | — |
| T08-13 | テープストップ／スタート | 型 `tape_stop` | `tape_stop`: `true` | — |
| T08-14 | ワーミー系ピッチベンド | 型 `pitch_curve` | `pitch_curve`: `true` | — |
| T09-01 | グラニュラーエフェクト | 型 `granular` | `granular`: `true` | — |
| T09-02 | スペクトルプロセッシング | 型 `spectral_fx` | `spectral_fx`: `true` | — |
| T09-03 | スペクトル・フリーズ | 型 `spectral_freeze` | `spectral_freeze`: `true` | — |
| T09-04 | スタッター／グリッチ（ステップ型） | 型 `stutter` | `stutter`: `true` | — |
| T09-05 | ランダム・グリッチ | 型 `glitch` | `glitch`: `true` | — |
| T09-06 | リバースエフェクト | 型 `reverse_chunks`、op `edit_reverse` | `reverse_chunks`: `true`、`edit_reverse`: 登録済み | — |
| T09-07 | フィルターシーケンサー | 型 `filter_seq` | `filter_seq`: `true` | — |
| T09-08 | エンベロープフォロワー・フィルター（オートワウ） | 型 `env_filter` | `env_filter`: `true` | — |
| T09-09 | ローファイ・マルチラック | 型 `lofi`、型 `noise_bed` | `lofi`: `true`、`noise_bed`: `true` | — |
| T09-10 | 描画型モジュレーションラック | 型 `curve_shaper` | `curve_shaper`: `true` | — |
| T10-01 | 定常ノイズリダクション | 型 `denoise` | `denoise`: `true` | — |
| T10-02 | 適応型／AI ノイズリダクション | 型 `denoise_ml` | `denoise_ml`: `false` | 代替実行の Mix Report 接続に core の追加が必要（OQ-4、D-30） |
| T10-03 | AI ボーカル分離抽出 | op `edit_isolate` | `edit_isolate`: 登録済み | — |
| T10-04 | デクリック | 型 `declick` | `declick`: `true` | — |
| T10-05 | デクラックル | 型 `declick` | `declick`: `true` | — |
| T10-06 | マウスデクリック | 型 `declick` | `declick`: `true` | — |
| T10-07 | デクリップ | 型 `declip` | `declip`: `true` | — |
| T10-08 | デハム／バズ除去 | 型 `dehum` | `dehum`: `true` | — |
| T10-09 | デリバーブ | 型 `dereverb` | `dereverb`: `false` | T20 の30 %短縮と DRR +3 dB の同時合格、乾いた打楽器の RP4 が未達 |
| T10-10 | スペクトルリペア | 型 `spectral_repair`、GUI `領域選択` | `spectral_repair`: `true`、GUI: 保留 | GUI API の追加が core 差分0と両立しない（OQ-3、D-28） |
| T10-11 | スペクトルリカバリー | 型 `hf_restore` | `hf_restore`: `true` | — |
| T10-12 | ブレスコントロール | op `breath`、コマンド `direction query breaths` | `breath`: 登録済み、`direction query breaths`: 登録済み | — |
| T10-13 | デプロッシブ | 型 `deplosive` | `deplosive`: `true` | — |
| T10-14 | デブリード | op `edit_debleed` | `edit_debleed`: 登録済み | — |
| T10-15 | 衣擦れ／風ノイズ除去 | 型 `dewind`、型 `denoise_ml`、未実装部分 `衣擦れ` | `dewind`: `true`、`denoise_ml`: `false` | 代替実行の Mix Report 接続に core の追加が必要（OQ-4、D-30）。衣擦れ側は再配布可能な OSS 重みが見つからず未実装（D-29） |
| T10-16 | ギター専用ノイズ除去 | 型 `guitar_denoise` | `guitar_denoise`: `true` | — |
| T10-17 | ワウフラッター／アジマス補正 | 型 `dewow`、型 `azimuth_fix` | `dewow`: `true`、`azimuth_fix`: `true` | — |
| T10-18 | ルームトーン／アンビエンスマッチング | 型 `noise_bed`、コマンド `direction suggest ambience` | `noise_bed`: `true`、`direction suggest ambience`: 登録済み | — |
| T10-19 | ギャップ補間 | 型 `interpolate` | `interpolate`: `true` | — |
| T11-01 | ボーカルタイミングアライメント | op `edit_align_time`、コマンド `direction query align_time` | `edit_align_time`: 登録済み、`direction query align_time`: 登録済み | — |
| T11-02 | ボーカル ピッチ＋タイミングアライメント | op `edit_align_pitch` | `edit_align_pitch`: 登録済み | — |
| T11-03 | 位相／タイムアライメント | 型 `time_align`、コマンド `direction suggest align` | `time_align`: `true`、`direction suggest align`: 登録済み | — |
| T11-04 | ドラムアライメント＋ゲート | 型 `drum_gate`、コマンド `direction suggest align` | `drum_gate`: `true`、`direction suggest align`: 登録済み | — |
| T11-05 | ドラムリプレイスメント／サンプル補強 | op `drum_replace` | `drum_replace`: 登録済み | — |
| T11-06 | オーディオ→MIDI 変換 | コマンド `direction extract midi` | `direction extract midi`: 登録済み | — |
| T11-07 | オーディオクオンタイズ | op `edit_quantize` | `edit_quantize`: 登録済み | — |
| T11-08 | トランジェント／ヒットポイント検出 | 観察量 `onsets`、コマンド `direction query onsets` | `onsets`: 登録済み、`direction query onsets`: 登録済み | — |
| T12-01 | 適応型マキシマイザー | 型 `adaptive_limiter` | `adaptive_limiter`: `true` | T01-13 と同一（重複） |
| T12-02 | モノ互換チェック | 観察量 `mono_loss`、観察量 `correlation_bands`、コマンド `direction query mono` | `mono_loss`: 登録済み、`correlation_bands`: 登録済み、`direction query mono`: 登録済み | — |
| T12-03 | DC オフセット除去 | 型 `dc_remove` | `dc_remove`: `true` | — |
| T12-04 | フェード／クロスフェード編集 | 型 `fade`、op `edit_fade` | `fade`: `true`、`edit_fade`: 登録済み | — |
| T12-05 | ノーマライズ | op `edit_normalize` | `edit_normalize`: 登録済み | — |
| T12-06 | レベラー／ラウドネスコントロール | op `level_phrases` | `level_phrases`: 登録済み | — |
| T12-07 | コーデックプレビュー／配信シミュレーション | コマンド `direction preview codec` | `direction preview codec`: 登録済み | — |
| T12-08 | 統合メータリング | コマンド `direction query meters`、GUI `メータ画面` | `direction query meters`: 登録済み、GUI: 保留 | GUI API の追加が core 差分0と両立しない（OQ-3、D-28） |
| T12-09 | トーンバランス比較 | コマンド `direction ref balance` | `direction ref balance`: 登録済み | — |
<!-- tool-status:end -->
