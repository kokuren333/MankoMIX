---
id: out_retro-v01-v02
kind: outcome
title: マンコ主義 × comfort／bass_heavy（streaming_universal）— 同一収束の実測
song: manko-shugi
created: 2026-11-14
status: active
visibility: public
applies_to: { genre: [hiphop], profile: [streaming_universal, club] }
---

# 結果（遡及収蔵）: v01／v02 の同一収束

## 主張

目的関数 comfort（v01）と bass_heavy（v02）を streaming_universal で描画すると、同じミックス・同じマスター計画（`mpl_0fc2f2fc9ff7`）になり、音が同じだった。

## 実測（二重レビュー報告 DR-01、FINISH_REPORT §5 から写す）

- v01 と v02 の差はディザーだけ: 差分 RMS −141.5 dBFS、最大 2.4e-7、LUFS は 1e-8 dB で一致
- club（v09〜v11）でも同じ: ミックス changes のハッシュ一致、マスター入力 −17.63 LUFS、チェーン（ゲイン 10.779 dB ＋リミッター）同一
- club_impact が試したキックのダッキングは床で実測 0.0017 dB の効果しかなく、棄却された（解く対象がない）
- 床 v01: −14.007 LUFS、−1.01 dBTP、verify pass

## 出典

二重レビュー報告 DR-01、FINISH_REPORT §5 の 1（いずれもリポジトリ外の非公開記録。数値のみ写す）
