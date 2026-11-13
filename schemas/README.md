# schemas — JSON Schema

正本とデータ定義の JSON Schema（draft 2020-12）を置く。

| ファイル | 対象 | 仕様 |
|---|---|---|
| `project.schema.json` | プロジェクトの正本 `project.json`（timebase、provenance、assets、ingest、tracks、buses、objective、variants など） | `docs/SPEC.md` §9、§6.1 |
| `objective.schema.json` | 目的関数の定義（`objectives/catalog.json`、またはユーザー定義の単体ファイル） | §4.4、§4.8 |
| `profile.schema.json` | 媒体プロファイル（`profiles/media_profiles.json`） | §5.2 |
| `delivery.schema.json` | 納品形式（`profiles/delivery_formats.json`） | §5.3 |
| `registry.schema.json` | モデルレジストリ（`registry/models.json` と BYOW の登録） | §12.2 |
| `report.schema.json` | Mix Report（`report.json`）の骨格。各章の型だけを決め、追加の項目を許す | §6.8 |

スキーマで表せない検査は、コードの側で行う。

- `core/schema.py`: 目的関数の重みの合計（`kind: "score"` は 1.0 ± 1e-6。`gate` は対象外）、ID の重複、媒体プロファイルの既定の納品形式の存在、目標ラウドネスが許容幅の中にあること、別名の衝突
- `core/project.py`: 正本のパスが全てプロジェクト相対であること（ドライブ名、先頭の `/`、`..`、バックスラッシュを拒否）、ID の一意性（素材、トラック、バス、クリップ、プロセッサ）、参照の解決（クリップの素材、トラックの出力と送り先のバス、`fullmix_asset`）、目的関数とジャンルと媒体プロファイルがカタログに存在すること

目的関数の定義は、安全不変条件（S-nn）を緩和する項目を持てない。`relax`、`waive`、`disable` などを含む名前の項目は拒否する（§4.3、§4.8）。

`chain.schema.json`（プロセッサグラフ。プラグインとの共有契約。§6.5.2、§14.2）は、DSP のプロセッサ定義が固まった段階で追加する。
