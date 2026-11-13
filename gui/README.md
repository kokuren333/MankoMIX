# gui — Web GUI と Pages デモ

人間向けのレスポンシブな GUI（`docs/SPEC.md` §11）。TypeScript + React + Vite の SPA。

- バックエンド接続をインターフェース（`src/backend/Backend.ts`）で抽象化し、2つの実装を持つ
  - `LocalBackend`: `mankomix serve` のローカルサーバー（`/api/...` の JSON と、`/api/events` の Server-Sent Events）。全機能
  - `MockBackend`: ブラウザ内モック。`public/demo/` の事前計算データを読む。GitHub Pages のデモ用。UI は同一
- GUI にしかない処理ロジックを持たない。レベルマッチのゲインもデータ（`match_gain_db`）から取り、GUI では計算しない
- デモ用の事前計算データは本体のコアで生成する（手書きしない）。今ある `public/demo/` は合成のプレースホルダー（`DEMO_DATA.md`）
- v1 の GUI は LLM と対話するパネルを持たない（D-035）。「エージェント機能」は外部エージェントの変更の追従、提案の承認と却下、履歴の表示

## 画面

| 画面 | 内容 |
|---|---|
| プロジェクト | 概要、取り込み（ローカルのみ）、取り込み検査、出所、素材一覧とハッシュ |
| ステム | トラック一覧（レベル、パン、ミュート、ソロ、役割、主役）。狭い幅では1列のカード |
| ミックスマップ | SVG。左右＝パン、上下＝スペクトル重心（対数）、大きさと濃さ＝奥行き。マスキングの警告と図上の重なり |
| 解析 | ラウドネスの時系列、LTAS とリファレンス帯、帯域別相関、AI 生成音源の診断、代理指標の前後 |
| 意図と出口 | バリアント（目的関数 × 媒体）の切り替え、目的関数の混合と強度、主役、リファレンス、媒体プロファイルと納品形式 |
| 計画 | 提案チェーン（処理ごとの規則 ID）、承認・却下。ローカルではパラメータを入力欄で編集してから適用 |
| 試聴 | A/B（レベルマッチ ON が既定、Web Audio の GainNode でマッチゲインを適用）、再生位置を保った瞬時切り替え、除去分、モノ、小型スピーカー（帯域制限）、小音量。狭い幅では操作部を画面下部に固定 |
| 検証 | 安全不変条件 S-nn（合格／不合格／未実施）、ゲート、プロファイル適合、ノイズ戻り、コーデック往復 |
| Mix Report | report.json の 10 節を描画。日本語／英語の切り替え、JSON の保存 |
| モデル | レジストリの一覧とライセンス（デモでは閲覧のみ） |
| 履歴 | 誰が（人間／エージェント／プランナー）何をいつ。ローカルでは取り消し |

UI の言語は日本語と英語（右上の JA/EN、`?lang=ja|en`）。画面は URL のハッシュ（`#/listen` など）で選ぶので、どのサブパスに置いても動く。

## 開発

Node 24 と npm。

```
cd gui
npm install
npm run dev            # http://localhost:5173 。/api は MANKOMIX_API（既定 http://127.0.0.1:8765）へプロキシ
npm run dev:demo       # モックで起動（または ?backend=mock）
npm test               # vitest + jsdom
npm run typecheck
```

## ローカルサーバーにつなぐ（`mankomix serve`）

`mankomix serve` はコアと同じ Python プロセスで動くローカルサーバー（`core/server/`、標準ライブラリのみ）。`/api` に `API.md` の契約を実装し、`gui/dist/` があれば `/` で GUI を配る。

```
cd gui && npm run build && cd ..
mankomix serve --project song.mmx                      # http://127.0.0.1:8765/ を開く
mankomix serve --root ./work --project song.mmx --port 0   # 作業フォルダを指定、空きポート
```

- 起動時に `{"serving": "http://127.0.0.1:8765/", ...}` を 1 行出力し、Ctrl+C で止まる
- 待ち受けは既定で 127.0.0.1 だけ。それ以外のアドレスは `--allow-remote` がないと拒否する（指定すると警告を出す）。Host ヘッダーがループバック名でない要求と、別オリジンからの書き込みも拒否する
- パスは `--root` の作業フォルダの中に限る（MCP と同じ制限）。`/api/files/...` は開いているプロジェクトの中のファイルだけを配り、`Range` に対応する（試聴のシーク）
- GUI からの変更は履歴に `human` として記録される。CLI / MCP（エージェント）が同じプロジェクトを変えると、サーバーが約 1 秒ごとに `project.json` / `journal.jsonl` / `cache/proposals/` を見て `project_changed` / `proposal` イベントを送る
- 解析、レンダリング、書き出し、検証、分離、モデル取得、プランナーはジョブとして動き、`/api/jobs/{id}` と `job` イベントで進捗を返す
- 開発時は `mankomix serve --project song.mmx` を起動したうえで `npm run dev`（`/api` を `MANKOMIX_API`、既定 `http://127.0.0.1:8765` へプロキシ）

## ビルド

```
npm run build          # dist/ に出力。既定はローカル接続。mankomix serve が dist/ を配る
npm run build:demo     # Pages 用。モック接続（--mode demo、VITE_BACKEND=mock と同じ）
```

- `vite.config.ts` の `base: "./"` により、GitHub Pages の任意のサブパスで動く
- `dist/` と `node_modules/` はコミットしない（ルートの `.gitignore`）。`package-lock.json` はコミットする

## バックエンドの選択

優先順:

1. ページ URL の `?backend=mock` / `?backend=local`
2. ビルド時の環境変数 `VITE_BACKEND=mock|local`
3. `--mode demo` なら `mock`、それ以外は `local`

モックでは `capabilities()` が取り込み、DSP、エージェント連携、モデル取得などを全て「不可」で返し、GUI はそれらのボタンを無効にして理由を表示する。画面上部のバナーで、デモでできないことと、外部へ通信しないこと（同じ場所の静的ファイルの読み込みだけ）を明示する。`index.html` の CSP も同一オリジン以外への通信を禁止する。

## API

ローカルサーバーのエンドポイントの一覧と型は `API.md`。デモのデータ配置は `DEMO_DATA.md`。

`Backend` インターフェースの主なメソッド（全て async）:
`capabilities`, `getProject`, `patchProject`, `importFiles`, `history`, `undo`, `listObjectives`, `listProfiles`, `listDeliveries`, `listModels`, `pullModel`, `listVariants`, `getAnalysis`, `analyze`, `listProposals`, `proposePlan`, `applyPlan`, `rejectPlan`, `render`, `exportOutputs`, `getJob`, `getVerification`, `verify`, `getReport`, `listAudio`, `subscribe`。

## 依存とライセンス

実行時: `react`, `react-dom`（MIT）。開発時: `vite`, `vitest`, `@testing-library/react`, `@testing-library/dom`, `jsdom`, `@types/*`（MIT）、`typescript`（Apache-2.0）。UI キットは使わない。

- `@vitejs/plugin-react` は使わない（Babel 経由の依存が増えるため）。JSX は Vite 標準の esbuild で変換する（Fast Refresh はなし）
- Vite は 7 系に固定している（8 系は MPL-2.0 の lightningcss を必須依存に持つため）
- jsdom は 26 系に固定している（新しい系は BlueOak-1.0.0 の lru-cache に依存するため）
- 依存ツリーのライセンスは MIT / ISC / BSD-2-Clause / BSD-3-Clause / Apache-2.0 / MIT-0 のみ（`package-lock.json` 時点）
