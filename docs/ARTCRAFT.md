# ArtCraft CPU 制作ジョブ

PhotoCraft 0.23.1 と VectorCraft 0.24.1 の公式 Linux x86_64 配布を使用します。両ソフトのソースは MIT OR Apache-2.0。固定版とリリース資産 SHA256 は `config/artcraft.json` に記録します。

- [PhotoCraft 公式リリース](https://github.com/storytold/photocraft/releases/tag/v0.23.1)
- [VectorCraft 公式リリース](https://github.com/storytold/vectorcraft/releases/tag/v0.24.1)

## GPT・Claude 共通の操作

`jobs/artcraft/` の JSON を使用します。各操作は公式 MCP の `tools/call` と同じ `name` と `arguments` を指定します。新しい操作は成果物の `tools.json` にある入力スキーマと操作履歴を参照してください。Actions の ArtCraft CPU はプッシュまたは手動選択で両エンジンを並行実行します。MCP は各コンテナの標準入出力で起動します。

| エンジン | CLI | 現在のジョブ |
|---|---|---|
| PhotoCraft | `photocraft-cli --version` / `photocraft-cli mcp --headless` | PNG 読み込み、レイヤー追加、選択範囲のマスク化、彩度補正、合成 PNG と .pcraft の出力、再読み込み |
| VectorCraft | `vectorcraft-cli --version` / `vectorcraft-cli mcp --headless` | 新規文書、図形とベジェパス、SVG・PNG・.vectorcraft 出力、再読み込み |

両 CLI に `--automation-read-root` と `--automation-write-root` を設定します。入力は読み取り専用、出力は別ディレクトリです。編集はネットワークを無効化した Docker で実行します。一般公開できる合成テスト素材のみを扱う検証構成です。

## 更新・復旧

1. 公式リリースの Linux x86_64 tar.gz と SHA256 を照合し、固定版を更新します。
2. 既存 CPU イメージは `config/runtime.yaml` の digest を再利用します。ArtCraft 配布は現時点で実行ごとに取得します。
3. ClamAV 更新 → 外部アーカイブ検査 → SHA256 照合 → 構造検査と隔離展開 → 展開後検査を順に行います。検査エラーは停止し、Actions のログで原因を確認します。
4. MCP エラー時は `operations.json` と `mcp.stderr.log` を確認し、ジョブ定義を修正して再実行します。結果は新規ディレクトリに出力します。正式採用はユーザーが判断します。

## 検証範囲

バッチ実装と公式ソース上の操作確認を実施。Actions の実動作は成功ランと成果物で確認します。`verification.json` は CLI 版、実行時間、PNG 解像度、SHA256、ネイティブ保存後の再レンダリング比較を記録します。

専用 GHCR イメージ、処理途中の再開、自動再試行、既存生成結果の受け渡しと制作確認サイト連携、対話接続は今後の統合範囲です。新エンジンは公式 CLI の起動引数・ツール・保存形式を確認して固定版台帳と Actions のマトリクスに追加します。
