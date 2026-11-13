# Mel-Band RoFormer — 出所の記録

| 項目 | 内容 |
|---|---|
| 作者 | Phil Wang（lucidrains） |
| リポジトリ | https://github.com/lucidrains/BS-RoFormer （`bs_roformer/mel_band_roformer.py`、`bs_roformer/attend.py`）、回転位置埋め込みは https://github.com/lucidrains/rotary-embedding-torch |
| 照合に使った版 | ZFTurbo/Music-Source-Separation-Training のコミット `1f700c386e0dd763fe0a57242bb9420dce987354`（2026-11-12）の `models/bs_roformer/mel_band_roformer.py`（MIT、Copyright (c) 2024 Roman Solovyev）。Kim Mel-Band RoFormer はこの系統のコードで学習された |
| ライセンス | MIT（`LICENSE` は lucidrains/BS-RoFormer の `LICENSE` をそのまま複写。blob `2e201f6e81ea23df185549039b1386559815ce8f`、確認時のコミット `4b951924b57f46f817fc80ac17b828c7af01094d`） |
| 取得方法 | raw ファイルを読んだだけ。上流のスクリプトやビルドは実行していない |

## 移植したファイル

| 移植先 | 内容 |
|---|---|
| `mel_band_roformer.py` | 推論に要る部分だけの移植。モジュール構成とパラメータ名は上流と同じにしてあり、上流で学習したチェックポイントがそのまま読める |

## 変更点

- 推論専用にした。学習用の損失（多重解像度 STFT 損失）、線形注意、PoPE、勾配チェックポイント、スキップ接続を削った
- メルフィルタバンク（`librosa.filters.mel`、Slaney 尺度・Slaney 正規化）を numpy で書き直した。librosa（とその依存の LGPL の soxr）を読み込まないため（D-057）。librosa 1.0.0 の出力と完全一致することを確認した
- 回転位置埋め込みをこのファイルに内蔵した（学習しない固定周波数のみ）
- beartype、einops への依存をなくした

## 照合

Kim Mel-Band RoFormer のチェックポイントで、上流の実装（ZFTurbo 版）とこの移植の出力を 3 秒のステレオ入力で比べ、最大差 0.0 を確認した（2026-11-13）。

## 使う場所

分離ワーカー（`core/separation/archs.py` の `run_mel_band_roformer`）が別プロセスの中で読み込む。
