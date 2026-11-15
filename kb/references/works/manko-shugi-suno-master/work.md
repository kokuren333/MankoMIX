---
id: work_manko-shugi-suno-master
kind: work
title: "マンコ主義（生成サービスの整合済みフルミックス）"
created: 2026-11-15
status: active
visibility: public
artist: "オーナー（本リポジトリの利用者本人）"
release: { title: "マンコ主義", year: null }
credits: []
credits_source: "利用者提供（オーナー自身の曲。生成サービスのフルミックス／ステム）"
genre: [hiphop]
rights: own
materials: [{ type: master, lossy: false, format: "48k/32f", sha256: "ba9a2aafb69207678c7831636fe87c242cb1f908736dedc54da24afb06e0dccd", obtained: "利用者申告（オーナー自身の制作物）" }]
study: { sha256: "971fbcdb6bf9e7558c11b27cf2111a8b1eecd7ecbce1953214a40413cd88cbef", engine: { version: "0.1.0", refstudy: 1 } }
evidence: measured
backing: [refstudy.md]
---

# work_manko-shugi-suno-master

## 何の作品か

公式サンプル曲 [manko-shugi](../../../songs/manko-shugi/song.md)（hiphop、約 99 秒）の、生成サービスが書き出したフルミックスを公式ステムの時間軸に整合したもの（2mix）。**生成サービスのフルミックスであり、プロのマスターではない。この作品で実証できるのは原液経路の機構で、原液の効き目ではない。**

## 測定の要点

[refstudy.md](refstudy.md) からの書き写し（〔測定〕〔兆候〕のみ）。

- ラウドネス: LUFS-I -15.50、トゥルーピーク -2.48 dBTP、PLR 13.02 dB、短期ラウドネスの幅（p95−p10）3.32 LU、広帯域クレスト 14.95 dB
- 帯域: bass（60–250 Hz）のエネルギー比 0.6441、air（6–20 kHz）0.0069、LTAS の傾き -3.27 dB/oct
- 空間: 全帯域 S/M -17.28 dB、相関 0.963。低域のモノ化の境界は見えない（20–40 Hz の S/M -9.2 dB）
- 区間（自動区分）: 最大区間と最小区間のラウドネス差 7.13 LU
- 兆候: RS-LIMIT 立つ（弱い、確度 low）、RS-CONTRAST 立つ（medium）、RS-DELIVERY 立つ（high）、RS-MONO-LOW・RS-HF 立たず。確度の機械的上限なし（可逆・分離なし）

## 読み

指揮者の〔推定〕（p4 の分析メモ ana_71399c8d372a から。生成サービスのフルミックスの読みで、プロのマスターの読みではない）。

- 〔推定・確度 medium〕山場は声の抜けた outro に置かれている。最大の 3 秒（90.8–93.8 s）は全体比 +2.1 LU、狭く（S/M -22.9 dB）低域主導（sub -8.5 dB）で、同じ曲のステムが outro で drums・bass 最大であることと向きが合う。
- 〔推定・確度 medium〕重心は低域寄りで、中域（声の胴）は控えめ。床のマスターに対し sub 比が 1.6 dB 高く、mid 比が 1.5 dB 低い（全曲でも最大区間でも同じ向き）。声のレベルが原因だとまでは言えない〔確度 low〕。
- 〔推定・確度 low〕最終段はほとんど抑えていない（RS-LIMIT の確度のまま）。-15.5 LUFS／-2.48 dBTP が狙いか書き出しの都合かは分からない。
- 〔推定・確度 low〕20–40 Hz の側成分（S/M -9.2 dB）と高域の側成分は生成由来の残りの可能性があり、意図とは読まない。
- 〔不明〕個別トラックのレベル・処理・パン、バス／マスター段の処理、verse・hook・break ごとの値（自動区分は最大・最小の 2 区間だけ）。

## 使った案件

- p4（経路 1、マスターをリファレンスに）: [曲資料](../../../songs/manko-shugi/2026-11-15_p4-ref-fullmix/dossier.md)、[対照表](../../../songs/manko-shugi/2026-11-15_p4-ref-fullmix/refsheet.md)
