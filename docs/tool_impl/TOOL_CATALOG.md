# MankoMIX ツール・カタログ — 世にあるのに MankoMIX に無いもの

作成：2026-11-17（オーナーの発注「今ないけど楽曲制作では普通に使われているツール群をプラグインレベルの粒度で探しまくって上げまくって分類して」）
方法：4 方面並列の Web 調査（ダイナミクス+EQ／空間+モジュレーション+ディレイ・リバーブ／歪み+ピッチ・タイム+クリエイティブ／修復+アライメント+マスタリング・計測）。生リスト 187 件を重複統合し、現行 MankoMIX（プロセッサ 21 種・op 13 種、2026-11-17 実測）と照合した。

## 分類タグ（実装ルート）

- 自前実装が素直 — 既存部品の組み立て、または定番 DSP で決定論のまま作れる
- 決定論だが新規アルゴリズム開発が要る
- 学習系が本質（品質が ML モデルに依存する）
- プロセッサではなく編集・計測・ワークフロー機能

## 0. 既に MankoMIX にあるもの（調査リストから除外した分）

静的 EQ／ダイナミック EQ（1 バンド）／単バンドコンプ／ディエッサー／サチュレータ（汎用）／クリッパー／帯域別ステレオ幅＋低域モノ化（stereo）／プレート系アルゴリズミック・リバーブ／基本ディレイ／リミッター＋ラウドネスゲイン／リサンプル／ディザ／ダッキング（duck op）／編集トリム・ゲート（edit op）／ステム分離（demucs 系）／ラウドネス計測と検証（verify・gate）／リファレンス測定と比較（ref study・compare）／レベルマッチ A/B（direction check）。コンソール色付けは aw.console7 系が一部カバー。

以下、無いもの **143 件**。

## 1. ダイナミクス（15）

1. マルチバンドコンプレッサー（FabFilter Pro-MB／Waves C6）— 帯域ごとに独立コンプ。クロスオーバーは stereo の完全再構成 FIR が流用でき、本体は既存コンプ
2. マルチバンドエクスパンダー／ゲート（Pro-MB のエクスパンダー／Ozone Dynamics）— 帯域ごとに小さい音を持ち上げ／絞る
3. マルチバンド・トランジェントシェイパー（Neutron Transient Shaper）— 帯域ごとにアタック／サステイン増減
4. トランジェントシェイパー（単バンド）（SPL Transient Designer／Waves Smack Attack）— アタックと余韻を独立に増減
5. アップワードコンプレッサー（Xfer OTT／Neutron Density）— 小さい音を持ち上げて密度を上げる
6. 双方向レベラー（Waves MaxxVolume）— 大きい音は下げ小さい音は上げる複合ダイナミクス
7. ゲート／エクスパンダー（音響型）（FabFilter Pro-G／Waves C1）— edit_gate（オフライン無音化）とは別の、比率と包絡を持つ型
8. パラレルコンプ専用機（Baby Audio Parallel Aggressor）— 強圧縮と原音のブレンド特化の型
9. ボリュームシェイパー（描画カーブ周期変調）（Cableguys VolumeShaper／Xfer LFOTool）— FB2 の gain_curve と地続き
10. サイドチェインダッカー専用機（カーブ型）（Devious Machines Duck／Kickstart 2）— duck op の発展形（帯域限定ダック含む）
11. ゲインライダー（Waves Vocal Rider）— 目標レベルへフェーダーを自動で書き込む
12. マルチバンドリミッター（DMG Limitless／Waves L3）— 帯域別リミッティングで潰れを分散
13. 適応型（ダイナミック）リミッター（Ozone Maximizer IRC／Newfangled Elevate）— 信号に応じてリリース等を自動調整
14. 多段リミッターチェイン（TDR Limiter No.6 GE）— コンプ→クリッパー→HF→ピークのモジュール直列型（既存部品の型として）
15. リニアフェイズ・マルチバンド（Waves Linear Phase Multiband）— 位相ズレのない帯域分割版

## 2. EQ／スペクトル（12）

1. リニアフェイズ EQ（DMG EQuilibrium／Waves Linear Phase EQ）— 位相を回さない EQ
2. ミッド／サイド EQ（bx_digital V3／Pro-Q 4）— M/S 分離＋既存 EQ の組み立て
3. ダイナミック共振抑制（Soothe 系）（oeksound soothe2／Smooth Operator）— 共振ピークを自動検出し発生時のみカット
4. スペクトル EQ（FFT ビン単位）（ZL SpectrumEqualizer／Pro-Q 4 Spectral Dynamics）— ビン単位の動的ゲイン制御
5. ピッチ追従 EQ（SurferEQ 2）— 音程に追随して帯域が動く
6. 自動スペクトルバランス（Gullfoss 系）（Soundtheory Gullfoss／Voxengo TEOTE）— 知覚モデルでマスキングを解析し自動補正
7. AI アシスト EQ（提案系）（sonible smart:EQ 4／Neutron）— 解析して初期カーブを提案する指揮者支援
8. マッチ EQ（Ozone Match EQ／Voxengo CurveEQ）— リファレンスのスペクトルへ寄せるカーブ生成。ref compare の発展
9. ターゲット型ローエンド EQ（BASSROOM）— 低域専用の目標カーブ誘導
10. ビンテージ EQ モデリング（Pultec EQP-1A／Neve 1073／API 550／Dangerous BAX）— 実機カーブの再現＋軽い飽和
11. チルト EQ（Softube Tonelux Tilt）— 軸周波数で全体を傾ける
12. カット専用フィルタ集（ブリックウォール）（bx_cleansweep Pro）— 急峻 HPF/LPF と共振調整。filter の拡張

## 3. リバーブ（11）

1. コンボリューション（IR）リバーブ（Altiverb／Waves IR-1）— 実空間の IR を畳み込む。FB2 の T2「部屋 IR」と同件。IR 資産の調達と権利が論点
2. アルゴリズミック・ホール／ルームの型（Valhalla VintageVerb／FabFilter Pro-R 2）— 現行プレート以外のアルゴリズムと型
3. ヴィンテージ・デジタル（Lexicon 224 系）（UAD Lexicon 224）— 初期デジタル機の太い残響
4. チェンバー（UAD Capitol Chambers）— エコーチェンバーの濃密な残響
5. スプリングリバーブ（Softube Spring Reverb）— バネの金属的残響
6. シマーリバーブ（Valhalla Shimmer）— ピッチシフト＋フィードバック（ピッチシフト部品に依存）
7. ゲーテッド／ノンリニアリバーブ（AMS RMX16 系）— 残響をゲートでスパッと切る
8. リバースリバーブ（Crystalline のリバース系）— 包絡を反転させた吸い込み残響
9. アーリーリフレクション専用機（Dragonfly Early Reflections〈OSS〉）— 初期反射だけを出す
10. フリーズ／インフィニットリバーブ（Eventide Blackhole／Valhalla Supermassive）— 残響の無限保持
11. ダッキングリバーブ（Crystalline／Magic7）— 原音の間だけ残響を下げる。duck との組み合わせ

## 4. ディレイ（11）

1. テープエコー（UAD Galaxy Tape Echo／Softube Tape Echoes）— ワウフラッター＋飽和でこもる反復
2. BBD アナログディレイ（Valhalla Delay の BBD モード）— 暗く荒い繰り返し
3. ピンポンディレイ（D16 Repeater）— 左右交互に跳ねる反復
4. スラップバックディレイ（EchoBoy）— 50〜120ms の単発反響。現行 delay の型として
5. マルチタップディレイ（Eventide UltraTap）— タップごとの量・パン・間隔の設計
6. モジュレーションディレイ（FabFilter Timeless 3）— ディレイ時間／フィルタへの LFO
7. グラニュラーディレイ（UrsaDSP Lagrange）— 粒に砕いて遅延・再配置
8. ダッキングディレイ（Valhalla Delay）— 発音中はエコーを下げる
9. ピッチシフト／周波数シフトディレイ（Soundtoys Crystallizer）— フィードバックで音程がずれていく反復
10. ルーパー／フリーズディレイ（Eventide H90 Looper 系）— 反復を保持してループ化する
11. ダブディレイ（Arturia Delay ETERNITY のダブ系）— 劣化するフィードバックで奥へ沈む反復

## 5. 空間／ステレオ（7）

1. Haas ワイドナー（Kilohearts Haas）— 片 ch の微小遅延で広がりを作る
2. バイノーラル／3D パンナー（DearVR／SPAT Revolution）— HRTF で頭外定位させる
3. オートパン（Soundtoys PanMan／Melda MAutoPan）— LFO や包絡で定位を動かす。vC のようなパンの「遊び」の自動化に直結
4. Doppler（Waves Doppler）— 移動音源の音程・音量・パンの変化
5. 周波数別ステレオ配置（Nugen Stereoplacer）— 狙った帯域だけを左右へ移す。stereo の発展
6. M/S プロセッシング基盤（Voxengo MSED）— M/S 変換と各 ch への処理差し込みの土台
7. アンビソニックス処理（SPAT Revolution）— 全天球音場の回転・変換（用途は特殊）

## 6. モジュレーション（12）

1. コーラス一族（UAD Galaxy／TAL-Chorus-LX〈フリー〉／Arturia Chorus DIMENSION-D／Eventide TriceraChorus）— BBD、Juno 系、Dimension 系、トライコーラス、ストリングアンサンブル等の型バリエーション
2. フランジャー（Eventide Instant Flanger Mk II）— 極短ディレイ＋フィードバックの櫛状うねり
3. フェイザー（Eventide Instant Phaser Mk II／Soundtoys PhaseMistress）— オールパス段数で作るノッチのうねり
4. ユニバイブ（UAD Uni-Vibe）— フォトセル式の脈動するコーラス／ビブラート
5. トレモロ（ハーモニック含む）（Soundtoys Tremolator／UAD Fender '55 系）— 音量の周期変調、帯域別交互変調
6. ビブラート（Goodhertz Wow Control）— 音程だけの周期変調
7. ロータリースピーカー（UAD Waterfall／IK Leslie）— 回転スピーカーのドップラーと振幅変調
8. リングモジュレーター（Eventide H910 系／Melda MRingModulator）— 搬送波との乗算で金属音を作る
9. 周波数シフター（Soundtoys Little AlterBoy の shift 系／Echobode）— 倍音関係を崩す Hz 単位の平行移動
10. マイクロピッチ／デチューン（H3000 系）（Eventide MicroPitch）— ±数セントのピッチシフトで厚みを作る。ピッチシフト部品に依存
11. ADT／ダブラー（Waves Reel ADT／Abbey Road ADT）— 人工ダブルトラック。ディレイ＋微変調の組み立て
12. ワウフラッター（テープ揺らぎ）（Goodhertz Wow Control／Aberrant DSP SketchCassette）— 再生速度の揺れそのもの

## 7. ハーモニック／歪み（15）

1. テープエミュレーション（Studer A800 系／Softube Tape）— ヒステリシス、バイアス、飽和と周波数特性の複合モデル
2. マルチバンド・サチュレーション（FabFilter Saturn 2）— 帯域ごとに歪みの種類と量を変える。クロスオーバー＋既存 saturator
3. トランスフォーマー・サチュレーション（Kazrog True Iron）— 入出力トランスの色付け
4. カセット／ローファイ劣化（Aberrant DSP SketchCassette II）— ワウフラ、ノイズ、劣化の束ね型
5. エキサイター（Aphex Aural Exciter 系／BBE）— 倍音を新規生成して明瞭度を足す
6. 位相系エンハンサー（BBE Sonic Maximizer／Plugin Alliance SPL Vitalizer）— 帯域間の位相・時間差で明瞭化
7. ラウドネス・エンハンサー（Inflator 系）（Oxford Inflator）— ピークを増やさず聴感音量を上げる非線形
8. ベース倍音エンハンサー（RBass 系）（Waves Renaissance Bass／MaxxBass）— 心理音響で低域の存在感を合成
9. サブハーモニック生成（Waves LoAir／Avid Subharmonic）— 1 オクターブ下を合成して重低音を足す
10. マルチバンド・ディストーション（iZotope Trash／Saturn の歪み側）— 帯域別に激しい歪み
11. ファズ（各社ファズモデリング）— saturator／clipper の型バリエーション
12. ビットクラッシャー／SR リダクション（TAL-Bitcrusher〈フリー〉／Decimort 2）— ビット深度と標本化周波数の意図的劣化
13. アンプシミュレータ（Neural DSP／NAM〈OSS〉）— ギターアンプの再現。NAM は学習モデルが本質
14. キャビネット IR ローダー（Lancaster Pulse／NadIR〈フリー〉）— スピーカーキャビネットの IR 畳み込み。リバーブの畳み込みと共通部品
15. コンソールエミュレーション（バス色付け）（Waves NLS／Brainworx Console）— バス側のクロストークと色付け。aw.console7 が一部カバー、クロストークは無い

## 8. ピッチ／タイム（14）

1. リアルタイム自動ピッチ補正（Antares Auto-Tune Pro／Waves Tune Real-Time）— 音程検出＋補正。品質はモデルと検出精度に依存
2. グラフィカル・ピッチ／タイミング編集（Celemony Melodyne／RePitch）— 音符単位の手作業編集環境
3. ハーモニー生成（Antares Harmony Engine／Waves Harmony）— リードから和声を自動生成
4. ハーモナイザー（Eventide H949／Quadravox）— ピッチシフト声部の重ね
5. ピッチシフター（高品質）（Soundtoys Little AlterBoy／élastique 系）— 多くのツールの土台部品。品質が全体の上限を決める
6. ポリフォニック再調律（PITCHMAP 系）（Zynaptiq PITCHMAP）— 和声音源の音程マッピング書き換え
7. フォルマントシフター（Little AlterBoy／Manipulator）— 音程と独立に声質を変える
8. ボコーダー（Waves Morphoder／TAL-Vocoder〈フリー〉）— 古典的チャンネルボコーダは決定論で書ける
9. トークボックス（Waves OVox の talkbox 系）— 口腔共鳴のモデル
10. タイムストレッチ（高品質）（Serato Pitch 'n Time／élastique）— 音程を保つ伸縮。WSOLA／位相ボコーダは自前可だが高品質化が課題
11. 極端タイムストレッチ（PaulStretch）（Audacity 内蔵）— アルゴリズム公開済み。環境音的な伸ばし
12. ハーフスピード／バリスピード（Cableguys HalfTime）— 速度と音程の連動変化
13. テープストップ／スタート（Kilohearts Tape Stop）— 再生速度のランプで作る停止・始動
14. ワーミー系ピッチベンド（Digitech Whammy モデリング）— ペダル式の連続ピッチベンド

## 9. クリエイティブ（10）

1. グラニュラーエフェクト（Portal／Quanta 系）— 音を粒に砕いて再配置する
2. スペクトルプロセッシング（Zynaptiq 系／GRM Tools）— FFT 領域での変形一般
3. スペクトル・フリーズ（GRM Freeze 系）— 一瞬のスペクトルを保持・伸長する
4. スタッター／グリッチ（ステップ型）（iZotope Stutter Edit／Glitch2〈フリー〉）— パターンで切り刻む
5. ランダム・グリッチ（Freakshow Industries 系）— シード固定で決定論化する前提のランダム変形
6. リバースエフェクト（各 DAW 標準）— 逆再生とその派生
7. フィルターシーケンサー（Soundtoys FilterFreak のリズム系）— パターンでフィルタを動かす
8. エンベロープフォロワー・フィルター（オートワウ）（Waves MondoMod 周辺／各社 Auto-Wah）— 入力の包絡でフィルタを開閉
9. ローファイ・マルチラック（RC-20 系）（XLN RC-20 Retro Color）— ノイズ・揺れ・劣化の部品束＋プリセットの概念
10. 描画型モジュレーションラック（ShaperBox 系）（Cableguys ShaperBox 3）— 描いたカーブで何でも変調する基盤。gain_curve の一般化

## 10. 修復／クリーンアップ（19）

1. 定常ノイズリダクション（iZotope RX Spectral De-noise／Audacity Noise Reduction〈OSS〉）— ノイズプロファイル学習＋スペクトル減算。決定論で書ける
2. 適応型／AI ノイズリダクション（RX Voice De-noise／Waves Clarity Vx）— 変化するノイズへの追従は学習系が本質
3. AI ボーカル分離抽出（RX Dialogue Isolate／Supertone Clear）— 混ざった背景から声だけを抽出。demucs 系の発展
4. デクリック（RX De-click／Audacity Click Removal〈OSS〉）— インパルス性ノイズの検出と補間
5. デクラックル（RX De-crackle）— 連続した微小クラックルの除去
6. マウスデクリック（RX Mouth De-click）— 口内ノイズ専用の検出
7. デクリップ（RX De-clip）— 潰れたピークの補間・再構成
8. デハム／バズ除去（RX De-hum／Waves X-Hum）— 電源ハムと倍音のノッチ列
9. デリバーブ（RX De-reverb／Zynaptiq UNVEIL）— 焼き付いた残響の除去。UNVEIL 系 DSP もあるが難関
10. スペクトルリペア（RX Spectral Repair／SpectraLayers）— スペクトログラム上の外科的編集。自動化部分は ML
11. スペクトルリカバリー（RX Spectral Recovery）— 失われた高域の推定復元
12. ブレスコントロール（RX Breath Control／Waves DeBreath）— ブレス検出＋ゲイン整え。edit／gain の発展
13. デプロッシブ（RX De-plosive）— 破裂音の低域バースト検出と抑制
14. デブリード（RX De-bleed）— 他トラックからのかぶり除去
15. 衣擦れ／風ノイズ除去（RX De-rustle／De-wind）— 映像・フィールド録音系の専用除去
16. ギター専用ノイズ除去（RX Guitar De-noise）— ハム＋フィンガーノイズ＋ピッキングの複合処理
17. ワウフラッター／アジマス補正（RX Wow & Flutter／Azimuth）— テープ転送の揺れと位相劣化の補正
18. ルームトーン／アンビエンスマッチング（RX Ambience Match）— テイク間の環境音を揃える
19. ギャップ補間（RX Interpolate）— 欠落区間を前後から補間生成

## 11. アライメント／編集支援（8）

1. ボーカルタイミングアライメント（VocAlign 系）（Synchro Arts VocAlign 7）— ガイドに合わせてダブル／ハモリのタイミングを伸縮同期。DTW が核
2. ボーカル ピッチ＋タイミングアライメント（VocAlign 7 Pro／Revoice Pro 5）— 音程までガイドに寄せる
3. 位相／タイムアライメント（Sound Radix Auto-Align 2／Melda MAutoAlign）— マルチマイク間の到達差を相互相関で補正
4. ドラムアライメント＋ゲート（Sonnox Oxford Drum Gate 2）— ドラム各マイクの整列と専用ゲート
5. ドラムリプレイスメント／サンプル補強（Slate Trigger 2／Drumagog）— トランジェント検出でサンプルに置換／ブレンド。サンプル資産の扱いが論点
6. オーディオ→MIDI 変換（Pro Tools Audio to MIDI／Superior Drummer Tracker）— ヒット位置と強弱の抽出
7. オーディオクオンタイズ（Beat Detective／Flex Time）— スライスしてグリッドへ整列
8. トランジェント／ヒットポイント検出（Cubase Hitpoints／REAPER Dynamic Split）— 打点・音節開始点の自動検出。分析量として（MV 側の signals 技術と同系）

## 12. マスタリング／計測／リファレンス（9）

1. 適応型マキシマイザー（Ozone Maximizer）— 自動リリース制御で透明に音圧を上げる
   - **重複注記**（2026-11-17、実装統括）：本項は §1-13「適応型（ダイナミック）リミッター」と同一機能。T12-01 は T01-13 `adaptive_limiter` で充足する（新しい型を作らない。仕様は `spec/12_mastering.md` T12-01）。件数 143 はカタログの数え方のまま据え置く。
2. モノ互換チェック（Mastering The Mix LEVELS／bx_control Mono-Maker）— 位相相関とモノ崩れの検出。既存の観察量の発展
3. DC オフセット除去（Audacity Normalize 内蔵／各波形エディタ）— 直流成分の除去
4. フェード／クロスフェード編集（RX Fade／WaveLab）— 頭尾と編集点のフェード形状。edit の発展
5. ノーマライズ（RX Normalize／Auphonic）— ピーク／ラウドネス基準のレベル統一。loudness_gain と地続き
6. レベラー／ラウドネスコントロール（RX Leveler／Auphonic Leveler）— 長期的な音量変動の均し
7. コーデックプレビュー／配信シミュレーション（NUGEN MasterCheck 2／Sonnox Codec Toolbox）— エンコード後の音と配信ノーマライズの事前確認
8. 統合メータリング（iZotope Insight 2／Voxengo SPAN〈フリー〉／Correlometer〈フリー〉）— スペクトル・相関・ゴニオ等の可視化。判定ではなく観察系
9. トーンバランス比較（iZotope Tonal Balance Control／true:balance）— リファレンスの目標カーブとの重ね比較。ref compare の発展

## 使い方

- このカタログは指揮書の tool_requests と、FB2 の T2 判断リストへの入力になる。
- 実装はシンJTC で回す：第1層 Fable 5.2 が要件・設計（パラメータ範囲、アルゴリズム概要、テスト基準）、第2層 Opus 5.5 高が統括、第3層 Codex／Opus 中が実装。
- ライセンス線引き：GPL／AGPL のコード移植は禁止（Pedalboard、Essentia、Matchering は不採用の前例）。アルゴリズムは論文・公開知識からのクリーンルーム再構成、permissive な実装は出典を記録して参考にする。
