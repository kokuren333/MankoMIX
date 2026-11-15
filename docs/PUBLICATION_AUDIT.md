# MankoMIX 公開監査（M9）: 一次資料による再確認

- 作成: 2026-11-14（M9 の監査工程）
- 位置づけ: SPEC §18 の「一次資料での確認」のうち、(1) サンプルの権利条件（§15.4）、(2) 媒体プロファイルの数値の現行値（§5.2）、(3) プラグイン関連のライセンス（§14.3）を、現行の一次資料で確認した記録である。本書は決定を行わない。決定が必要な点は §4 に「提案」として挙げ、決定記録（D-ID）は調整役が `docs/REQUIREMENTS_NOTES.md` に残す
- 確認の方法: 公式ドメインのページ（規約、ヘルプセンター、仕様書、SDK のライセンス文）を取得し、該当する文を英語のまま引用した。**アクセス日はすべて 2026-11-14**。公式ドメイン以外でしか見つからなかった事項は「未確認」とした
- 上流調査との関係: D-038 の理由欄にある「有料プランの契約期間中の生成物は商用利用可」という前提と、§5.2 の数値には、出典 URL が記録されていなかった（`UPSTREAM_REPORT.md` にも URL はない）。本書がその出典の初出となる

判定の凡例:

| 判定 | 意味 |
|---|---|
| **確認** | 公式の一次資料に、その内容を支える文がある |
| **未確認** | 一次資料で支えられない（公式の文書が見つからない、取得できない、文言の射程が不明） |
| **不一致** | 一次資料の現行値とリポジトリの値が食い違う |
| **公式値なし** | プラットフォームが数値を公表していない。リポジトリ側の値は実測や業界の一致に基づくもので、照合の対象外 |

---

## 0. 要約

| 区分 | 項目 | 判定 | 要点 |
|---|---|---|---|
| Suno | 前提（有料プランでの生成物の商用利用・再配布） | **確認**（条件付き） | 規約は Pro / Premier の生成物について Suno の権利を利用者に譲渡し、商用利用を認める。ただし 2026-09-03 発効の規約では、**有料プラン中の「許可されたダウンロード」を得ていること**が商用利用の条件になった |
| Suno | (a) 加工後の派生物の公開 | **確認** | 改変を制限する条項はない。透かし・メタデータの除去禁止は「出所を隠す目的」に限られる |
| Suno | (b) 入力ステムの公開 | **確認** | ステムは曲のダウンロードの一部であり、Studio 内のステム／マルチトラックのダウンロードは Suno 自身が提供する経路 |
| Suno | (c) フル尺での公開 | **確認** | 尺を制限する条項はない |
| Suno | (d) 帰属表示の義務 | **確認**（義務なし） | 利用者に帰属表示を課す条項はない。Suno 側が「Suno で生成された」と公表する権利を持つ |
| Suno | (e) 他ツールの実演・ベンチマークへの利用 | **未確認** | 実演・ベンチマークを名指しする条項はない。一方で「競合する製品の開発・改良」と「他の AI・機械学習のモデル、ツール、技術を動かす・可能にする・学習させる」ことを禁じる一般条項があり、その射程が規約から決まらない |
| Suno | §15.4 の規則の機械的適用 | — | 規則の対象 3 項目（入力ステム、フル尺、加工後の音声）はいずれも確認できたので、**規則の帰結は D-038 どおりの全範囲**。(e) は規則の 3 項目の外にある未確認事項で、扱いの決定が要る（§4.2 の P-1） |
| 媒体 | Spotify の数値 | **確認**（全項目一致） | −14 LUFS、両方向の正規化、TP −1 dB、−14 LUFS より大きいマスターは −2 dB、Ogg Vorbis と AAC |
| 媒体 | Apple Music の数値 | 一部確認 | 正規化は両方向（確認）、1 dB 以上のヘッドルーム推奨（確認）、AAC（確認）。−16 LUFS は**公式値なし** |
| 媒体 | YouTube、Amazon Music、Tidal、SNS | 公式値なし | ラウドネスと TP は公表されていない。コーデックの事実は確認でき、**Amazon Music の `codec_checks` に不一致が 1 件**（AAC の記載がない。標準音質は Opus） |
| 媒体 | 納品形式（TuneCore の基準線） | **不一致**（説明文） | TuneCore の現行の推奨は 24 bit / 192 kHz の WAV。16 bit / 44.1 kHz は「受け付けるが推奨しない」 |
| プラグイン | VST3 SDK | **確認**: MIT | 3.8（2025-10）から MIT。GPLv3 とプロプライエタリの選択肢は廃止。VSTGUI と mda は BSD 系 |
| プラグイン | JUCE | **確認**: AGPLv3 と商用のデュアル | Apache-2.0 の本体には取り込めない（D-049 のとおり採用しない） |
| プラグイン | CLAP / LV2 / AU | **確認**: MIT / ISC / Apache-2.0 | いずれも寛容ライセンス |
| プラグイン | 結論 | — | ネイティブ核は、GPL / AGPL のコードを持ち込まずに CLAP、VST3（3.8 以降）、AU、LV2 として包める。避けるべきは JUCE、AAX SDK、ASIO SDK、VST2 のヘッダ |

---

## 1. Suno の権利条件（§15.4）

### 1.1 前提条件

本書は、特定のアカウントや契約状況については何も主張しない。以下の判定は、次の前提条件が満たされている場合に成り立つ。前提条件が満たされているかどうかは、§15.4 が定めるとおり、オーナー側の前提である。

| ID | 前提条件 | 根拠 |
|---|---|---|
| C-1 | 曲は Pro または Premier の契約中に**生成された** | SU-3 |
| C-2 | 公開に使うファイルは、Pro または Premier の契約中に、Suno が提供する経路で**ダウンロード（書き出し）された** | SU-1（Permitted Commercial Use）、SU-2 |
| C-3 | 書き出しは Suno Studio のマルチトラック書き出しである。Suno の公式ページは Studio を Premier 専用としているので、C-2 と合わせると、書き出しは Premier の契約中に行われたことになる | SU-5、SU-6 |
| C-4 | 曲は、他の利用者が利用者の曲をリミックスできる機能から生まれた「Remix」ではない（Remix は契約プランにかかわらず非商用に限られる） | SU-1（Remixes） |
| C-5 | 公開物の出所（Suno で生成されたこと）を隠したり偽ったりしない | SU-1（Permitted Commercial Use、User Conduct） |

上流調査の前提（D-038 の理由欄の「契約期間中の生成物は商用利用可」）は C-1 だけを条件にしていた。2026-09-03 に発効した現行規約では、C-2（契約中の許可されたダウンロード）も条件になった。§4.2 の P-2 で、§15.4 の前提の書き方の修正を提案する。

### 1.2 一次資料と引用

| ID | URL | ページの表題 | 引用（原文のまま） |
|---|---|---|---|
| SU-1 | https://suno.com/terms | Terms of Service \| Suno（"Date of Last Revision: August 10, 2026" / "Effective Date: September 3, 2026"） | 下の 1.2.1 に項目別に示す |
| SU-2 | https://help.suno.com/en/articles/9601665 | What rights do I have with a paid subscription? | "Songs downloaded while subscribed are granted commercial use rights" / "without Suno claiming a stake in the earnings" / "Distribute them to streaming platforms" / "granting commercial use rights does not guarantee copyright protection" |
| SU-3 | https://help.suno.com/en/articles/2416769 | Does Suno own the music I make? | "If you were subscribed with a Pro or Premier plan when the song was created, you are considered the owner of the song." / "You also retain the rights to commercial use for the song, even if you end your subscription." |
| SU-4 | https://help.suno.com/en/articles/9601985 | What is commercial use? | "describe your ability to earn money from the music you made while subscribed." / "allowing you to monetize via distribution, traditional sales, and more." |
| SU-5 | https://suno.com/studio-welcome | Suno Studio — Be a control freak | "Studio is available for Premier subscribers only." / "Stem and Multitrack downloads within Studio are exempt from download restrictions." / "high-quality 32-bit/48kHz format" |
| SU-6 | https://suno.com/blog/studio-2 | Introducing Studio 2.0（Aug 13, 2026） | Studio 2.0 "is now available to Suno Premier subscribers." / 書き出し形式は "(32-bit/48kHz)" |
| SU-7 | https://help.suno.com/en/articles/13925249 | Exporting from Studio | "Exports all tracks as stems for mixing in your DAW of choice." / "All audio exports from Studio are delivered as high-quality WAV files." |
| SU-8 | https://help.suno.com/en/articles/13926145 | What counts as one download? | "One song counts as one download, regardless of how many files or formats you download for that song." / "Downloading stems is included with that song's download and does not count separately" |
| SU-9 | https://help.suno.com/en/articles/13614785 | Upcoming Changes FAQ: Downloads, Models, and Terms of Service | "users will still be able to download their work from Studio without limitation." / "All stems from a song are part of that song's single download." / "Download limits apply to all music on Suno starting September 3, including songs created before that date." |
| SU-10 | https://suno.com/blog/suno-updates-tos | An update to our downloads policy and Terms of Service（Aug 10, 2026） | "Songs downloaded from Suno on paid plans remain yours to use commercially or personally." / "Trial downloads are not eligible for commercial use." |

#### 1.2.1 規約（SU-1）の該当箇所

| 規約の箇所 | 引用（原文のまま） |
|---|---|
| Intellectual Property Rights / Pro and Premier Accounts | "Suno hereby assigns to you all of its right, title and interest in and to any Output owned by Suno" / "provided such Output will remain subject to these Terms of Service" / "Suno makes no representation or warranty to you that any copyright will vest in any Output." |
| 同 / Free or Basic Tier | "you covenant and agree that you will only use such Outputs for your lawful, personal and non-commercial purposes." |
| 同 / Permitted Commercial Use | "You may commercially exploit Output solely to the extent it adheres to Suno's Conditions of Access and Use" / "provided you have obtained a permitted download of that Output in accordance with the download allocations" / "in accordance with the download allocations for your applicable service tier (each, a “Download”)" / "You may not commercially exploit Output that has not been downloaded by you through an approved channel" / "the commercial use rights described in this paragraph with respect to a Download you have obtained, are perpetual" / "are perpetual and are not affected by your exhaustion of your Download allotment," / "or by the expiry, cancellation, downgrade or suspension of your subscription." / "the third party, and not Suno, governs whether you may make that use on that platform." |
| 同 / 透かしとメタデータ | "You agree not to remove, alter, obscure or circumvent any fingerprint, watermark or metadata Suno appends to an Output" "for the purpose of concealing or misrepresenting the provenance, service tier, or status of that Output." / "We reserve the right to append a fingerprint, watermark, or metadata indicating the applicable service tier of an Output" "and whether such Output was a permitted Download." |
| 同 / 取得経路 | "Obtaining a copy of an Output by any means other than a download channel made available by Suno is prohibited" |
| 同 / Remixes | "Unless otherwise provided for in connection with a separate offering, if you are a user" "that activates features that permit other users of the Service" "("Remixers") to remix your Outputs (each, a "Remix"), you agree that all Remixes shall be a joint work" … "the Remix may only be used for lawful, personal and non-commercial purposes," "regardless of your subscription tier or whether the Remix is a permitted Download." |
| 同 / Suno への許諾 | "perpetual and irrevocable right to identify to the public" "(both on and off the Service) that Output (or any of it) was generated via the Service." |
| Conditions of Access and Use / User Conduct（冒頭） | "You agree to not use the Service to:" |
| 同 / 第 4 項（なりすまし） | "including by generating, making available, promoting, labelling or otherwise using Output or a Voice Model" "in a manner that suggests that such Output or Voice Model was created by or otherwise associated with" "an individual who was not the creator thereof" |
| 同 / 第 10 項 | "use the Services (and any Output or Voice Model) to create, develop or improve any competing products or services" "or to power, enable or train other artificial intelligence and machine learning models, tools or technologies;" |
| 同 / 競合の禁止 | "In no event will you use the Output or your Voice Model to compete with Suno, including to create a competing" "music-generation product or service." |

規約に「stem」の語はない。ステムに固有の制限もない。

### 1.3 項目別の判定

**前提: 有料プランでの生成物の商用利用と公開での再配布 — 確認（C-1〜C-5 を条件として）**

- Pro / Premier の生成物については Suno の権利が利用者に譲渡され（SU-1 Pro and Premier Accounts）、許可されたダウンロードを得た Output は商用に利用できる（SU-1 Permitted Commercial Use、SU-2、SU-10）。ストリーミングへの配信も商用利用の例として明記されている（SU-2）
- 商用利用の権利は、ダウンロード後は永続し、契約の終了や解約の影響を受けない（SU-1、SU-3）。公開の時点で契約が続いているかどうかは条件にならない
- 公開リポジトリでの無償の配布は、商用利用より狭い使い方であり、譲渡された権利の範囲に入る
- 留保: Suno は Output に著作権が成立することを保証しない（SU-1、SU-2）。サンプルに第三者向けのライセンスを付ける場合、その根拠となる権利が存在しない可能性がある（§4.2 の P-3）

**(a) 加工後の派生物の公開 — 確認**

- 改変や加工を制限する条項はない。商用利用の条件は「許可されたダウンロード」と「Conditions of Access and Use の順守」だけである（SU-1）
- 透かし・フィンガープリント・メタデータの除去等の禁止は、"for the purpose of concealing or misrepresenting the provenance, service tier, or status of that Output." に限られる（SU-1）。整音やマスタリングの処理が結果として透かしに影響しても、目的要件に当たらない。ただしこの解釈は、公開物が Suno 由来であることを明示していること（C-5）を前提にする

**(b) 入力ステムの公開 — 確認**

- ステムは曲のダウンロードの一部である（SU-8、SU-9）。Suno は Studio 内の書き出しを "Stem and Multitrack downloads within Studio" と呼び、ダウンロード上限の対象外としている（SU-5、SU-9）。Studio は Suno が提供する経路であり、"download channel made available by Suno" に当たる（SU-1）
- 「有料プラン中のダウンロードは商用利用できる」（SU-2、SU-10）と、「Studio の書き出しは Suno 自身がダウンロードと呼ぶ経路である」（SU-5）を合わせて判定した。「Studio の書き出しに商用利用の権利がある」と直接書いた一文はない。判定はこの 2 段の読みに基づく
- ステムを未加工のまま公開することを制限する条項もない

**(c) フル尺での公開 — 確認**

- 尺や抜粋を条件にする条項はない（SU-1〜SU-10 のいずれにもない）

**(d) 帰属表示の義務 — 確認（義務なし）**

- 利用者に帰属表示を課す条項はない（SU-1、SU-2、SU-9 は帰属表示に触れていない）
- 関係する条項は、(1) 出所を隠す目的での透かし等の除去の禁止、(2) 作者でない者が作ったように見せることの禁止（User Conduct 第 4 項）、(3) Suno 側が「Suno で生成された」と公表する権利、の 3 つである。§15 の方針（サンプルの出所を目録と README に書く）は、これらと矛盾しない

**(e) 他ツールの実演・ベンチマークへの利用 — 未確認**

- 実演、比較、ベンチマーク、研究を名指しして許可または禁止する条項はない
- 一方、User Conduct 第 10 項は、Output を使って "create, develop or improve any competing products or services" ことと、"power, enable or train other artificial intelligence and machine learning models, tools or technologies" ことを禁じている。どちらの語も規約の中で定義されていない
  - 「競合する製品」: 競合の禁止の文は "music-generation product or service" を例に挙げている。MankoMIX は生成で音を作り直さない（§1.2、D-041）ので、この例には当たらない。しかし第 10 項は "any competing products or services" と広く、ミックス／マスタリングの機能を持つ Suno Studio との関係で MankoMIX が「競合」に当たらないと規約から言い切ることはできない。なお、この条項が適用されると、公開だけでなく、テスト素材や較正（§16.2、§4.9）への利用も対象になりうる
  - 「他の AI のツールを動かす・可能にする」: MankoMIX は AI エージェントから使う道具であり（§10）、任意でニューラル分離を使う（§6.2）。Output をその入力にすることが "power, enable" に当たるかは、規約の文言からは決まらない。MankoMIX はサンプルでモデルを学習させないので、"train" には当たらない
- 結論: 明文の禁止はないが、明文の許可もなく、一般条項の射程が不明である。一次資料だけでは「確認」とできない

### 1.4 §15.4 の絞り込み規則の機械的適用

§15.4 の規則: 確認できなかった項目は、その項目だけ公開を見送る。範囲は「入力ステム → フル尺 → 加工後の音声」の順で狭める。

| 規則の対象 | 対応する確認項目 | 判定 | 規則の帰結 |
|---|---|---|---|
| 入力ステム | (b)、前提 | 確認 | 公開する（Release 添付に限る。D-038） |
| フル尺 | (c)、前提 | 確認 | フル尺で公開する |
| 加工後の音声 | (a)、前提 | 確認 | 全種別を公開する |

**規則の帰結としての公開範囲: D-038 どおりの全範囲**（入力ステム、フル尺、加工後の全種別と処理前・除去分）。前提条件 C-1〜C-5 が成り立つことを条件とする。

規則の外に残る事項:

- **(e) は規則の 3 項目のどれにも対応しない**。実演はサンプル公開の目的そのものなので、項目として切り出して見送ることができない。仮に (e) を規則の対象に含めると、見送る範囲は入力ステムから順に最後まで進み、Suno 由来の音声は何も公開できなくなる。どちらとして扱うかは、規則の文言から機械的には決まらない。新しい決定（D-ID）として扱いを確定する必要がある（§4.2 の P-1）
- (d) は義務がないことの確認であり、公開範囲を狭めない
- 公開先のプラットフォーム（GitHub、GitHub Pages）の可否は、規約上 "the third party, and not Suno, governs" とされている（SU-1）。本監査ではプラットフォーム側の規約は確認していない

### 1.5 付随する所見

- Studio の書き出しは "32-bit/48kHz" と記載されている（SU-5、SU-6）。書き出しセットのサンプルレートと深度について、取り込み（§6.1）と D-054 の前提と食い違いがないか、実装側で確認するとよい（権利の判定には影響しない）
- 規約は "Unless otherwise provided for in connection with a separate offering" という留保を持つ。Studio 専用の別規約は、公式ドメインの検索では見つからなかった（Studio のページにも権利の記載はない）

---

## 2. 媒体プロファイルの数値（§5.2、`profiles/media_profiles.json`）

### 2.1 一次資料

| ID | URL | ページの表題 | 引用（原文のまま） |
|---|---|---|---|
| MP-1 | https://support.spotify.com/us/artists/article/loudness-normalization/ | Loudness normalization on Spotify | "We adjust tracks to -14 dB LUFS, according to the ITU 1770 standard." / "Positive gain is applied to softer masters so the loudness level is -14 dB LUFS." / "We consider the headroom of the track, and leave 1 dB headroom for lossy encodings to preserve audio quality." / "Keep it below -1dB TP (True Peak) max." / "If your master is louder than -14dB integrated LUFS, keep True Peak below -2dB to avoid extra distortion." / "We normalize an entire album at the same time, so gain compensation doesn't change between tracks." / "lossy formats (Ogg/Vorbis and AAC)" / "both compressed and lossless FLAC playback" / "Loud: -11dB LUFS" / "We apply a limiter to prevent distortion and clipping in soft dynamic tracks." |
| MP-2 | https://support.spotify.com/us/article/audio-quality/ | Audio quality - Spotify | "Very high: Equivalent to approximately 320kbit/s" / "Lossless: Equivalent up to 24-bit/44.1kHz FLAC" / ウェブプレイヤーは "AAC 128kbit/s" と "AAC 256kbit/s" |
| MP-3 | https://www.apple.com/apple-music/apple-digital-masters/docs/apple-digital-masters.pdf | Apple Digital Masters: Music as the Artist and Sound Engineer Intended（April 2021） | "Our recommendation is to leave at least 1 dB of headroom in order to avoid such clipping." / "The metadata is then used to raise or lower the volume of each track to prevent jarring volume changes while a device is shuffling songs." / "(Sound Check can also correctly set the volume per album, rather than per song," / "we ask that you deliver the highest native sample rate available." / "The deliverable for Apple Digital Masters is the original 24 bit PCM file." / "The standard for CDs is 16-bit 44.1kHz resolution" |
| MP-4 | https://help.apple.com/itc/videoaudioassetguide/en.lproj/static.html | Apple Video and Audio Asset Guide（Version 5.3.19、改訂表で September 8, 2026） | ステレオの Music Audio Source Profile: "with 16-bit or 24-bit resolution" / "44.1, 48, 88.2, 96, 176.4, or 192 kHz"。Apple Digital Masters: "Audio must be delivered at 24-bit resolution in an approved format." / "Up-sampling and/or bit-padding of 44.1 kHz/16-bit files is not allowed."。Dolby Atmos（イマーシブのみ）: "The integrated loudness value must not exceed -18 LKFS, measured per ITU-R BS. 1770-4." / "True-peak level must not exceed -1 dB TP, measured per ITU-R BS. 1770-4." ステレオにはラウドネスと TP の規定がない |
| MP-5 | https://support.google.com/youtube/answer/1722171?hl=en | YouTube recommended upload encoding settings | "Audio codec: AAC-LC or Opus or Eclipsa Audio" / "Sample rate: 48kHz"。ステレオの推奨ビットレートは表で 384 kbps。ラウドネスの記載はない |
| MP-6 | https://support.google.com/youtube/answer/6039860?hl=en | Encoding specifications for music videos - YouTube Help | "48kHz recommended. Higher sample rates are accepted but not required (for example, 96kHz)." / "The features described in this article are available only to partners who use YouTube's Content ID matching system." 可逆の音声は FLAC または Linear PCM。ラウドネスと TP の規定はない |
| MP-7 | https://digprjsurvey.amazon.com/csad/help/node/TgG1d8mPjGwf885hRP | Turn On Loudness Normalization for Amazon Music Playback（amazon.com のヘルプ） | "With Loudness Normalization, you can play all songs at the same loudness level"。数値、方向、既定の状態の記載はない |
| MP-8 | https://developer.amazon.com/docs/music/audio-formats.html | Audio Formats \| Amazon Music Developer | OPUS: "A lossy codec used to deliver SD audio" / FLAC: "A lossless codec used to deliver HD and UHD audio"。AAC の記載はない。ラウドネスの記載はない |
| MP-9 | https://support.tidal.com/hc/en-us/articles/17412130162961-HiRes-FLAC-audio | HiRes FLAC audio（更新 2026-01-09） | "Max: High fidelity lossless audio up to 24-bit, 192 kHz with HiRes FLAC" / "High: Lossless audio with FLAC (16-bit, 44.1 kHz)" / "Low (up to 320 kbps): Listen to the music you love using lower data usage with compressed AAC files." |
| MP-10 | https://support.tidal.com/hc/en-us（ヘルプセンターの記事検索） | TIDAL Support | 2026-11-14 時点で、"normalize" と "loudness" の検索結果は 0 件。正規化の公式記事は見つからない |
| MP-11 | https://support.tunecore.com/hc/en-us/articles/115006499327 | Uploading Audio Files – TuneCore | "we recommend all audio files be 24 bit (sample size) with 192 kHz (sample rate) .WAV files, but 16 bit (sample size) with 44.1 kHz (sample rate) .WAV files are also accepted." / 16 bit・44.1 kHz について "(Accepted, but not recommended)" |
| MP-12 | https://webstore.iec.ch/en/publication/3885 | IEC 60908:1999 Audio recording - Compact disc digital audio system（Edition 2.0、1999-02-10） | 規格本文は有償で、公開の要旨に数値はない。CD が 16 bit / 44.1 kHz であることは MP-3 の Apple の記述で確認した |

公式の文書が見つからなかったもの（**未確認**）:

- YouTube のラウドネス正規化の目標値、方向、TP: Google の公式ヘルプに記載が見つからない。数値は第三者の実測記事にしかない
- Amazon Music の目標値（−14 / −13 LUFS などの諸説）と TP（−1 / −2 dBTP の諸説）: 第三者の記事にしかない
- Tidal の正規化（−14 LUFS、アルバム単位、下げるのみ）: 第三者の記事にしかない（MP-10）
- TikTok / Instagram のラウドネス: 公式の文書が見つからない。第三者の記事は −14 から −10 LUFS までばらつく
- AES TD1008（音楽の曲単位正規化 −16 LUFS、コーデック入力で −1 dBTP）: aes.org 上の PDF は検索結果の抜粋でしか確認できず、本文は取得できなかった（404 / 403）。§5.2 の「AES 推奨と整合」は、現時点では未確認の扱いとする
- Amazon Music の音質ページ（標準音質が最大 320 kbps）: amazon.com のヘルプは検索結果の抜粋でのみ確認

### 2.2 照合表

「一致」の欄: **一致** / **不一致** / **公式値なし**（照合不能） / **対象外**（内部の初期値で、外部の値と照合するものではない）。

| プロファイル | フィールド | リポジトリの値 | 現行の公式値 | 出典 | 一致 |
|---|---|---|---|---|---|
| spotify | `loudness.target_lufs_i` | −14.0 | −14 LUFS（ITU 1770） | MP-1 | 一致 |
| spotify | `loudness.normalization` | `both` | 小さいマスターには正のゲインを掛ける（1 dB のヘッドルームの範囲で）。大きいものは下げる | MP-1 | 一致 |
| spotify | `loudness.window_lufs_i` | [−15.0, −13.5] | — | — | 対象外 |
| spotify | `true_peak.ceiling_dbtp` | −1.0 | "below -1dB TP" | MP-1 | 一致 |
| spotify | `true_peak.conditional` | `lufs_i > -14.0` のとき −2.0 | "louder than -14dB integrated LUFS" のとき "below -2dB" | MP-1 | 一致 |
| spotify | `codec_checks` | `ogg_vorbis`、`aac` | 非可逆は Ogg/Vorbis と AAC。可逆は FLAC（最大 24 bit / 44.1 kHz） | MP-1、MP-2 | 一致 |
| spotify | `source.confidence` | `official` | 公式に数値を公表 | MP-1 | 一致 |
| spotify | （アルバム単位） | 記載なし | アルバムの再生時はアルバム単位で正規化 | MP-1 | 一致（v1 は 1 曲なので影響なし。D-047） |
| apple_music | `loudness.target_lufs_i` | −16.0 | Apple は数値を公表していない | MP-3、MP-4 | 公式値なし |
| apple_music | `loudness.normalization` | `both` | Sound Check は "raise or lower the volume of each track" | MP-3 | 一致 |
| apple_music | `true_peak.ceiling_dbtp` | −1.0 | ステレオは "at least 1 dB of headroom" の推奨（dBTP の規定ではない）。−1 dBTP の規定は Dolby Atmos のみ | MP-3、MP-4 | 一致（推奨の趣旨と整合） |
| apple_music | `codec_checks` | `aac` | 256 kbps の AAC。可逆は ALAC | MP-3 | 一致 |
| apple_music | `default_delivery` | `hires_native` | Apple Digital Masters は 24 bit、ネイティブの最高サンプルレート、アップサンプル禁止 | MP-3、MP-4 | 一致 |
| apple_music | `source.confidence` | `consensus` | 公式値なし | — | 一致（ラベルとして妥当） |
| youtube | `loudness.target_lufs_i` | −14.0 | 公表なし | MP-5、MP-6 | 公式値なし |
| youtube | `loudness.normalization` | `down_only` | 公表なし | — | 公式値なし |
| youtube | `true_peak.ceiling_dbtp` | −1.0 | 公表なし | — | 公式値なし |
| youtube | `codec_checks` | `aac`、`opus` | アップロードの推奨コーデックは AAC-LC、Opus、Eclipsa Audio。配信側のコーデックの公式記載はない | MP-5 | 一致（アップロード側の事実として） |
| youtube | `default_delivery` | `hires_native` | アップロードの推奨は 48 kHz。音楽ビデオの納品は FLAC / LPCM、48 kHz 推奨 | MP-5、MP-6 | 一致（矛盾はない。§4.1 の M-4 は任意の改善） |
| youtube | `source.confidence` | `measured_consensus` | 公式値なし | — | 一致（ラベルとして妥当） |
| amazon_music | `loudness.target_lufs_i` | −14.0 | 公表なし。公式ヘルプはアプリの設定項目としての正規化を説明するだけ | MP-7 | 公式値なし |
| amazon_music | `loudness.normalization` | `down_only` | 公表なし。正規化は利用者がアプリで有効にする設定（Android / iOS / FireOS） | MP-7 | 公式値なし |
| amazon_music | `true_peak.ceiling_dbtp` | −2.0 | 公表なし | — | 公式値なし |
| amazon_music | `codec_checks` | `aac`、`opus` | 標準音質は Opus、HD / Ultra HD は FLAC。AAC の記載はない | MP-8 | **不一致** |
| amazon_music | `source.confidence` | `reported` | 公式値なし | — | 一致（ラベルとして妥当） |
| tidal | `loudness.target_lufs_i` | −14.0 | 公式記事なし | MP-10 | 公式値なし |
| tidal | `loudness.normalization` / `scope` | `down_only` / `album` | 公式記事なし | MP-10 | 公式値なし |
| tidal | `true_peak.ceiling_dbtp` | −1.0 | 公式記事なし | — | 公式値なし |
| tidal | `codec_checks` | `aac` | Low は最大 320 kbps の AAC。High は FLAC（16 bit / 44.1 kHz）、Max は FLAC（最大 24 bit / 192 kHz） | MP-9 | 一致 |
| tidal | `source.confidence` | `measured_consensus` | 公式値なし | — | 一致（ラベルとして妥当） |
| streaming_universal | 目標 −14 / TP −1.0 | −14.0 / −1.0 | 公式の「共通値」は存在しない。Spotify の公式値（MP-1）と同じ | MP-1 | 一致（安全既定として妥当） |
| sns_safe | 目標 −14 / TP −1.0 | −14.0 / −1.0 | TikTok / Instagram の公式値は見つからない | — | 公式値なし（ラベル `no_official_value` と一致） |
| sns_hot | 目標 −9（−11〜−7） | −9.0 | 規格・公式値なし | — | 公式値なし（ラベル `practice` と一致） |
| club | 目標 −7 / TP −0.5 | −7.0 / −0.5 | 規格なし | — | 公式値なし（ラベル `practice` と一致） |
| cd | 目標 −10 / TP −0.3 | −10.0 / −0.3 | CD の規格はラウドネスと TP を定めない | MP-12 | 公式値なし（ラベル `practice` と一致） |
| cd | `default_delivery` → `cd_redbook`（44.1 kHz / 16 bit / 2ch） | 44100 / 16 / 2 | "The standard for CDs is 16-bit 44.1kHz resolution"。規格本文（IEC 60908）は有償で未読 | MP-3、MP-12 | 一致 |
| soundcloud | 全項目 | — | 本監査では確認していない | — | 未確認 |

### 2.3 納品形式（`profiles/delivery_formats.json`、§5.3）

| 形式 | フィールド | リポジトリ | 現行の公式値 | 出典 | 一致 |
|---|---|---|---|---|---|
| `distributor_44k16` | 位置づけ（SPEC §5.3「TuneCore の基準に一致」） | 44.1 kHz / 16 bit / ステレオ WAV を「ディストリビューター納品の基準線」とする | TuneCore の推奨は 24 bit / 192 kHz の WAV。16 bit / 44.1 kHz は "Accepted, but not recommended" | MP-11 | **不一致**（説明文） |
| `distributor_44k16` | 値（44100 / 16 / 2） | 44100 / 16 / 2 | 受け付けられる形式として掲載 | MP-11 | 一致（受け付けの下限として） |
| `hires_native` | 24 bit、ネイティブのサンプルレート | 24 / native | Apple Digital Masters の要件と一致。TuneCore のページは 24 bit / 192 kHz と 16 bit / 44.1 kHz の 2 つだけを挙げており、24 bit / 48 kHz を受け付けるかは書いていない | MP-4、MP-11 | 一致（Apple）／未確認（TuneCore の 24 bit / 48 kHz） |
| `cd_redbook` | 44.1 kHz / 16 bit / 2ch | 44100 / 16 / 2 | CD は 16 bit / 44.1 kHz | MP-3 | 一致 |
| 全形式 | `wav_format_tag: WAVE_FORMAT_PCM` | 指定あり | この理由を支える一次資料は本監査では探していない | — | 未確認 |

---

## 3. プラグイン SDK のライセンス（§14、§18）

### 3.1 一次資料と判定

| ID | 対象 | URL | 表題 | 引用（原文のまま） | 判定 |
|---|---|---|---|---|---|
| PL-1 | VST3 SDK | https://github.com/steinbergmedia/vst3sdk/blob/master/LICENSE.txt | vst3sdk / LICENSE.txt | "MIT License" / "Copyright (c) 2026, Steinberg Media Technologies GmbH" / "Permission is hereby granted, free of charge, to any person obtaining a copy" | **MIT**（確認） |
| PL-2 | VST3 SDK | https://github.com/steinbergmedia/vst3sdk（README の "License & Usage guidelines"） | GitHub - steinbergmedia/vst3sdk: VST 3 Plug-In SDK | "**VST 3 SDK** is under MIT license." / "Licensing under **GPLv3** and the **Steinberg proprietary license** is no longer available." / "Trademark usage (e.g. "VST" name or logo) is optional under MIT license, but if used, must comply with Steinberg's official trademark rules." / "Non-compliance with logo guidelines does not affect your MIT rights (but may result in trademark violations)." | 確認 |
| PL-3 | VST3 SDK | https://steinbergmedia.github.io/vst3_dev_portal/pages/VST+3+Licensing/Index.html | VST 3 Licensing - VST 3 Developer Portal | "Since version 3.8 VST 3 is licensed under MIT license." / "except VSTGUI and mda files which are under BSD-like license." | 確認 |
| PL-4 | VSTGUI | https://github.com/steinbergmedia/vstgui/blob/master/LICENSE | vstgui / LICENSE | "VSTGUI LICENSE" / "Redistribution and use in source and binary forms, with or without modification," | BSD 系（確認） |
| PL-5 | VST2 | https://steinbergmedia.github.io/vst3_dev_portal/pages/FAQ/Licensing.html | Licensing - VST 3 Developer Portal | VST 2 のヘッダについて "These files are under a different license which does not allow redistribution!" | 使わない |
| PL-6 | JUCE | https://github.com/juce-framework/JUCE/blob/master/LICENSE.md | The JUCE Framework / LICENSE.md | "The JUCE Framework modules are dual-licensed under the AGPLv3 and the commercial JUCE licence." / "The JUCE examples are licensed under the terms of the ISC license." / 商用側は "JUCE 9 End User Licence Agreement" | **AGPLv3 と商用のデュアル**（確認） |
| PL-7 | CLAP | https://github.com/free-audio/clap/blob/main/LICENSE | clap / LICENSE | "MIT License" | **MIT**（確認） |
| PL-8 | clap-helpers | https://github.com/free-audio/clap-helpers/blob/main/LICENSE | clap-helpers / LICENSE | "MIT License" | MIT（確認） |
| PL-9 | clap-wrapper | https://github.com/free-audio/clap-wrapper（README の "Licensing"） | free-audio/clap-wrapper | "The `clap-wrapper` project is released under the MIT license." / 参照する SDK の表で、VST3 SDK は "MIT (use of the VST trademark/logo per Steinberg's guidelines)"、AudioUnitSDK は "Apache 2.0"、AAX SDK は "GPL3 **or** commercial Avid AAX SDK License Agreement"、ASIO SDK は "GPL3 **or** Steinberg's proprietary ASIO SDK License Agreement" | MIT（確認）。AAX と ASIO の記載は第三者の README であり、Avid と Steinberg の一次資料では未確認 |
| PL-10 | LV2 | https://gitlab.com/lv2/lv2/-/blob/main/COPYING | lv2 / COPYING | "Permission to use, copy, modify, and/or distribute this software for any purpose with or without fee is hereby granted," / README の "SPDX-License-Identifier: ISC" | **ISC**（確認） |
| PL-11 | AU（Audio Unit） | https://github.com/apple/AudioUnitSDK | apple/AudioUnitSDK | LICENSE.txt は "Apache License Version 2.0, January 2004" / "The AudioUnitSDK contains a set of base classes as well as utility sources required for Audio Unit development." | **Apache-2.0**（確認） |

補足: VST 3.8.0 の公開日（2025-10）は、Steinberg のフォーラムの告知とプレスリリースの検索結果で見たもので、本文は取得していない。ライセンスの判定は PL-1〜PL-3 の現行の文面に基づく。

### 3.2 結論

- **ネイティブ核は、GPL / AGPL のコードを持ち込まずにプラグインとして包める。** CLAP（MIT）、VST3 SDK 3.8 以降（MIT。VSTGUI と mda は BSD 系）、AudioUnitSDK（Apache-2.0）、LV2（ISC）は、いずれも §13.1 の許可リスト（MIT / BSD / ISC / Apache-2.0）に入る
- VST3 について、D-049 の条件（「SDK のライセンス条件を一次資料で確認できた場合に対応する」）は満たされた。§14.3 の「VST3 SDK のライセンス条件: 未確認」は「確認済み（3.8 以降は MIT）」に更新できる（§4.2 の P-4）
- 守るべき境界:
  - **JUCE は使わない**（AGPLv3 と商用のデュアル。D-049 のとおり）
  - **3.8 より前の VST3 SDK を使わない**（GPLv3 またはプロプライエタリ）
  - **VST2 のヘッダを使わない**（再配布不可）
  - **AAX SDK と ASIO SDK を使わない**。clap-wrapper を使う場合は、AAX のラッパーと ASIO を有効にするビルド設定（`RTAUDIO_API_ASIO=ON` など）を使わない
  - "VST" の名称やロゴは任意。使う場合は Steinberg の商標ガイドラインに従う（MIT の権利とは別の、商標の問題）
- CLAP を第一候補とする D-049 の方針は、この結果と矛盾しない。clap-wrapper（MIT）は、MIT / Apache-2.0 の SDK だけを使って CLAP から VST3 と AUv2 を作れるので、「CLAP で実装し、VST3 と AU はラッパーで出す」という形も、ライセンスの面では成り立つ

---

## 4. 変更の提案

本書はファイルを変更しない。以下は調整役への提案である。

### 4.1 プロファイル（`profiles/*.json`）

| ID | 対象 | 現在 | 提案 | 根拠 |
|---|---|---|---|---|
| M-1 | `media_profiles.json` の `amazon_music.codec_checks` | `["aac", "opus"]` | `["opus"]` | MP-8: 標準音質は Opus、HD / UHD は FLAC。AAC の記載がない |
| M-2 | `media_profiles.json` の全プロファイルの `source` | `{"confidence": ...}` だけ | SPEC §5.2 の構造例どおり `as_of` を加え、出典を持たせる。例: `{"confidence": "official", "as_of": "2026-11-14", "refs": ["https://support.spotify.com/us/artists/article/loudness-normalization/"]}`。`refs` の値は本書の §2.1 の URL | SPEC §5.2 は「各プロファイルは確認日と公式度を持つ」としているが、JSON は確認日をトップレベルの `as_of`（2026-11-13）にしか持っていない |
| M-3 | `media_profiles.json` の `amazon_music.loudness` | `"normalization": "down_only"` | 値は変えない。数値と方向に一次資料がないことを、出典の欄（M-2）に注記する。例: `"note": "Normalization is a user-enabled app setting; target, direction and TP are not published by Amazon."` | MP-7 |
| M-4 | `media_profiles.json` の `youtube`（任意） | 指定なし | 48 kHz を推奨サンプルレートとして持たせる（例: `"preferred_sample_rate_hz": 48000`）。採用するかどうかは任意 | MP-5、MP-6 |
| M-5 | `delivery_formats.json` の `distributor_44k16.use` と SPEC §5.3 の表 | 「TuneCore の基準に一致」 | 「TuneCore が受け付ける形式（TuneCore の推奨は 24 bit / 192 kHz の WAV）」に改める。ディストリビューター向けの既定を `hires_native` に寄せるかは別途判断（下の P-5） | MP-11 |
| M-6 | `media_profiles.json` のトップレベルの `as_of` | `2026-11-13` | `2026-11-14`（本監査の確認日） | 本書 |

数値（LUFS の目標、TP の天井、正規化の方向）について、一次資料と食い違う値は見つからなかった。Spotify 以外の数値は「公式値なし」であり、変更の根拠もない。

### 4.2 決定が必要な事項（新しい D-ID の候補）

| ID | 事項 | 提案の内容 |
|---|---|---|
| P-1 | Suno の (e)（実演・ベンチマークへの利用）の扱い | 規約に明文の禁止はないが、第 10 項（競合する製品の開発・改良、他の AI ツールを動かす・可能にする）の射程が不明である。§15.4 の規則は 3 項目しか定めていないので、(e) の扱いを決める必要がある。選択肢: (i) 規則の対象外として D-038 の全範囲を維持する。(ii) 規則の順序を当てはめ、まず入力ステムを見送る（未加工の Output は第三者が他の用途に転用しやすく、"enable" の懸念に最も近い）。(iii) Suno に書面で照会し、回答を得るまで公開を保留する。どの選択肢でも、テスト素材と較正への利用（非公開）が第 10 項の「開発・改良」に当たりうる点を併記しておく |
| P-2 | §15.4 と D-038 の前提の書き方 | 「有料プランの契約期間中に生成され」に加えて、「有料プランの契約期間中に Suno の提供する経路（Studio を含む）で書き出され」を前提に明記する。2026-09-03 発効の規約で、許可されたダウンロードが商用利用の条件になったため（SU-1、SU-2、SU-10）。前提条件 C-1〜C-5（§1.1）を §15.4 に移すことを提案する |
| P-3 | サンプルの利用条件の表示 | Suno は Output に著作権が成立することを保証せず、譲渡後の Output も規約に服する（SU-1）。サンプル（音声）はリポジトリの Apache-2.0 の対象外とし、「Suno で生成。利用条件は Suno の規約に従う」旨を目録・README・Release に書くことを提案する。P-1 で (i) を選ぶ場合は、「AI の学習への利用は許諾しない」旨を加えると、第 10 項の懸念を下げられる |
| P-4 | §14.3 と D-049 の更新 | VST3 SDK のライセンスは確認済み（3.8 以降 MIT）とする。VST3 の対応は「ライセンス確認後」の条件を外し、「3.8 以降の SDK を使う。VST2 のヘッダ、ASIO SDK、AAX SDK は使わない」に置き換える。JUCE を採用しない決定は維持する |
| P-5 | ディストリビューター向けの既定の納品形式 | TuneCore の推奨が 24 bit / 192 kHz になっているので、配信用の既定を `distributor_44k16` から `hires_native` に移すかを決める。TuneCore のページが 24 bit / 48 kHz（Studio の書き出しのネイティブ）を受け付けると明記していない点も考慮する |
| P-6 | §5.2 の「AES 推奨と整合」 | AES TD1008 の本文を本監査では取得できなかった。M10 の較正の前に本文を確認するまで、`apple_music` の −16 LUFS は「業界の一致」だけを根拠とする |

---

## 5. 監査観点の追加（2026-11-15、原液経路と理論ナレッジ）

指揮レイヤーに作品・技術者・理論のカード（`kb/references/`、`kb/theory/`）が加わったため、公開前の監査に次の観点を加える。§1〜§4 の記録は変えない。

| 観点 | 確認すること | 機械検査 | 人が見ること |
|---|---|---|---|
| `kb/references/` の rights と visibility | 公開 kb（リポジトリの `kb/`）の作品カードが `rights: own` だけであること。第三者（市販）作品のカード・測定資料（refstudy）・対照表（refsheet）が公開 kb に無く、非公開の `_private/kb/` に留まっていること。技術者カードが自前作品以外を参照していないこと。D-039（市販曲の統計を同梱しない）に反していないこと | `mankomix kb lint`（公開止め: どの kb でも `rights: third_party` かつ `visibility: public` を拒否、公開 kb では own 以外の work と own と確認できない作品を参照する engineer を拒否。JSON の `scope` が `public` であること） | `rights: own` の自己申告が事実か。作品カード・技術者カードに人物評・私的情報・歌詞・解説文が無いか |
| 音を残さないこと | kb とプロジェクトに音源・その変換物・再構成できる粒度のデータが無いこと。work の `materials` がハッシュだけでファイル名・パスを含まないこと | `kb lint`（音声参照・絶対パス、`materials` のファイル名・パス、refstudy／refsheet の粒度 `too_fine`）、`tools/check_hygiene.py` | — |
| 理論カードの転載の有無 | `kb/theory/` のカードが書籍・教材の文面、譜例、図表、章立てを写していないこと。教材名・講座名・ページ参照、提携や公認を示す表現が無いこと。対話から蒸留したカード（KT-0018〜0022）から発言者を特定できないこと | `kb lint`（本文 1,200 字まで、画像・引用ブロックなし、かぎ括弧・引用符の中身 80 字まで、`paraphrase: true` と `sources_note` の必須） | 特定の書籍の言い回し・例・構成をなぞっていないか（機械検査では見られない） |
