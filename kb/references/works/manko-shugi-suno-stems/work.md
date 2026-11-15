---
id: work_manko-shugi-suno-stems
kind: work
title: "マンコ主義（生成サービスの配布ステム 12 本＋整合済みフルミックス）"
created: 2026-11-15
status: active
visibility: public
artist: "オーナー（本リポジトリの利用者本人）"
release: { title: "マンコ主義", year: null }
credits: []
credits_source: "利用者提供（オーナー自身の曲。生成サービスのフルミックス／ステム）"
genre: [hiphop]
rights: own
materials: [{ type: master, lossy: false, format: "48k/32f", sha256: "ba9a2aafb69207678c7831636fe87c242cb1f908736dedc54da24afb06e0dccd", obtained: "利用者申告（オーナー自身の制作物）" }, { type: stems, count: 12, lossy: false, format: "48k/32f", sha256_set: "52965d82bfffcd487de6d1f8a028af33dac03507059a135479f2edb91540a3a4", obtained: "利用者申告（オーナー自身の制作物）" }]
study: { sha256: "90f9b14ee7ed95edf6dbc5361d7db3ea7a63c0183e8ffa7d88970559ce9ea9eb", engine: { version: "0.1.0", refstudy: 1 } }
evidence: measured
backing: [refstudy.md]
---

# work_manko-shugi-suno-stems

## 何の作品か

公式サンプル曲 [manko-shugi](../../../songs/manko-shugi/song.md)（hiphop、約 99 秒）の、生成サービスが配布したステム 12 本（整合済みの正本。派生の合算ファイルは含めない）と、同じ時間軸の整合済みフルミックス。**生成サービスのフルミックス／ステムであり、プロのマスター／ステムではない。この作品で実証できるのは原液経路の機構で、原液の効き目ではない。**

## 測定の要点

[refstudy.md](refstudy.md) からの書き写し（〔測定〕〔兆候〕のみ）。

- 役割の割り当て: 12 役割に 1 本ずつ（名前から推定）。ステム和の LUFS-I -15.03
- 相対レベル（和との差）: drums -3.7 LU、vocals -4.9 LU、bass -8.0 LU、backing_vocals -8.7 LU。主役（vocals）対伴奏 -3.12 LU（全体）
- 定位と幅: 全役割で L/R 差は ±0.6 dB 以内。S/M は backing_vocals -5.2 dB、keyboard -9.3 dB が広く、drums -32.2 dB、woodwinds -28.1 dB が狭い
- 低域の分け合い: drums の取り分 sub 0.956、bass 0.712
- 和とマスターの差分: **信頼できない**（合わせた後の残差 -3.99 dB、相関 0.7587）。この節から引く結論の確度上限は low。ステム和がフルミックスに一致しないのは素材の既知の事情
- マスターの兆候は [work_manko-shugi-suno-master](../manko-shugi-suno-master/work.md) と同じ素材・同じ値

## 読み

指揮者の〔推定〕（p5 の分析メモ ana_07d5fb9f2022 から。生成サービスの配布ステムの読みで、プロのステムの読みではない）。

- 〔推定・確度 medium〕釣り合いは、声を伴奏の上に大きく浮かせない。主役対伴奏 -3.12 LU で、lowmid〜air の帯域を drums と vocals が並んで担当している。
- 〔推定・確度 medium〕広がりはパンではなくステムの中の側成分が作っている。全役割が中央（L/R 差 ±0.6 dB 以内）で、S/M が広いのは backing_vocals・keyboard・synth だけ。
- 〔推定・確度 low〕和声の 4 本（guitar・keyboard・synth・woodwinds）は和に対し -13.5〜-15.2 LU の「聞こえる脇役」の大きさ。ゲイン 0 の和が意図した釣り合いかどうかは分からない。
- 〔推定・確度 low（上限）〕和とマスターの差分（幅 -1.81 dB、クレスト -1.47 dB）はバス段の絞りを示唆するが、差分は信頼できないので結論にしない。
- 〔不明〕フルミックスでの各ステムのフェーダー・パン・処理（ステム和がフルミックスを再現しない）、中央定位が意図か書き出しの既定か、ステムごとの処理と機材。

## 使った案件

- p5（経路 2 素材 B、ステムをリファレンスに。p3 の結果と対照）: [曲資料](../../../songs/manko-shugi/2026-11-15_p5-ref-stems/dossier.md)、[対照表](../../../songs/manko-shugi/2026-11-15_p5-ref-stems/refsheet.md)
