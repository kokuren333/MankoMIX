# SCNet — 出所の記録

| 項目 | 内容 |
|---|---|
| 作者 | starrytong（Weinan Tong ほか。論文 "SCNet: Sparse Compression Network for Music Source Separation"） |
| リポジトリ | https://github.com/starrytong/SCNet |
| コミット | `5d95bf96b19c3eede63248d171efeca8e3abb948`（2025-09-08） |
| ライセンス | MIT（`LICENSE` は同コミットの `LICENSE` をそのまま複写。blob `00fc8a87ca5c630a9ef582d6cd5ae30c184ed6ca`） |
| 学習済みウェイトのライセンス | MIT（リポジトリ所有者の声明。https://github.com/starrytong/SCNet/issues/35 、2026-07-17）。ウェイトは同梱しない。`registry/models.json` の `scnet_4stem` / `scnet_large_4stem` を参照 |
| 取得方法 | raw ファイルを取得して読んだだけ。上流のスクリプトやビルドは実行していない |

## 取り込んだファイル（無改変）

| ファイル | 移植元 | blob |
|---|---|---|
| `SCNet.py` | `scnet/SCNet.py` | `7c3e68734aa4b4c25b8a5c2aa7e7ff8f1e16cb47` |
| `separation.py` | `scnet/separation.py` | `56e2937dcf6e9836abf61380db8491e8e5f63660` |

## 使う場所

分離ワーカー（`core/separation/worker.py` → `core/separation/archs.py` の `run_scnet`）が、別プロセスの中でこのフォルダをパッケージとして読み込む。推論の分割（チャンクとクロスフェード）は `archs.py` に自前で書いた（上流の `apply.py` は取り込んでいない）。ハイパーパラメータはレジストリの `runtime.config` に置く。
