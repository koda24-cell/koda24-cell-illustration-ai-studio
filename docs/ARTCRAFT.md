# ArtCraft CPU 制作ジョブ

PhotoCraft 0.23.1 と VectorCraft 0.24.1 の公式 Linux x86_64 配布を使用します。両ソフトのソースは MIT OR Apache-2.0。固定版とリリース資産 SHA256 は `config/artcraft.json` に記録します。

- [PhotoCraft 公式リリース](https://github.com/storytold/photocraft/releases/tag/v0.23.1)
- [VectorCraft 公式リリース](https://github.com/storytold/vectorcraft/releases/tag/v0.24.1)

## GPT・Claude 共通の操作

`jobs/artcraft/` の JSON を使用します。各操作は公式 MCP の `tools/call` と同じ `name` と `arguments` を指定します。新しい操作は成果物の `tools.json` にある入力スキーマと操作履歴を参照してください。Actions の ArtCraft CPU はプッシュまたは手動選択で両エンジンを並行実行します。MCP は各コンテナの標準入出力で起動します。

| エンジン | CLI | 現在のジョブ |
|---|---|---|
| PhotoCraft | `photocraft-cli --version` / `photocraft-cli mcp` | PNG 読み込み、レイヤー追加、選択範囲のマスク化、彩度補正、合成 PNG と .pcraft の出力、再読み込み |
| VectorCraft | `vectorcraft-cli --version` / `vectorcraft-cli mcp --headless` | 新規文書、図形・ベジェパス・グラデーション・パス結合、SVG・PNG・.vectorcraft 出力、再読み込み |

両 CLI に `--automation-read-root` と `--automation-write-root` を設定します。入力は読み取り専用、出力は別ディレクトリです。編集はネットワークを無効化した Docker で実行します。一般公開できる合成テスト素材のみを扱う検証構成です。

## 更新・復旧

1. 公式リリースの Linux x86_64 tar.gz と SHA256 を照合し、固定版を更新します。
2. 既存 CPU イメージは `config/runtime.yaml` の digest を再利用します。ArtCraft 配布は現時点で実行ごとに取得します。
3. ClamAV 更新 → 外部アーカイブ検査 → SHA256 照合 → 構造検査と隔離展開 → 展開後検査を順に行います。検査エラーは停止し、Actions のログで原因を確認します。
4. MCP エラー時は `operations.json` と `mcp.stderr.log` を確認し、ジョブ定義を修正して再実行します。結果は新規ディレクトリに出力します。正式採用はユーザーが判断します。

## 検証範囲

バッチ実装と公式ソース上の操作確認を実施。Actions の実動作は成功ランと成果物で確認します。`verification.json` は CLI 版、実行時間、PNG 解像度、SHA256、ネイティブ保存後の再レンダリング比較を記録します。

公開テストの成功結果は main の実行時に studio-runs へ追記し、既存サイトへ掲載します。編集データと加工後の画像、PhotoCraft の加工前後比較、操作・検証記録を確認できます。新エンジンは公式 CLI の起動引数・ツール・保存形式を確認して固定版台帳と Actions のマトリクスに追加します。

## 追加検証

- テストジョブの `quality_goal` に色の見本と評価範囲を指定し、VectorCraft の場合は対象名と目標座標も指定できます。途中PNGの測色とMCPから得た構造を用い、彩度・色相・明度、パスの塗り、座標移動から修正を選びます。修正ごとに再描画し、得点が悪化するか保護領域の画素が変化した場合はネイティブ保存から戻します。最大3反復です。
- `quality.json` が確定した反復を記録し、一時的な通信エラー時は同一ジョブの最良ネイティブファイルから最大3回再試行します。別ランナーでは Actions の ArtCraft CPU で resume_run_id と engine を指定すると、保存済みチェックポイントから再開できます。Artifacts をアップロードする前にランナーが消失した場合は、そのランナーだけにあった変更は復元できません。
- 既存の公開GHCRパッケージにArtCraft専用のタグを追加し、実行時は取得したdigestを使用します。ラン概要にdigestを記録します。
- `studio-push`・`produce` の成功後、同じActions URLを持つ公開可能なStudio成果物を検査してPhotoCraftへ渡します。公開不可や状態不明の結果は対象外です。
- PhotoCraftでPSD・PSB、VectorCraftでPDFの保存と読み込みを検証ジョブに追加しました。
- 対話接続はDockerホスト上のstdioで使用できます。MCPクライアントに `bash` をコマンド、`scripts/artcraft_mcp.sh` の絶対パス、エンジン、ラン概要に記録されたイメージdigest、作業ディレクトリの絶対パスを引数として渡します。Actionsの一時ランナーへの対話ブリッジは提供していません。
- 色や位置を測って判断する方式です。絵柄・キャラクターらしさ・自然言語の制作意図の意味的な判断は、許可済み視覚モデルがないため未実装です。

### 参考画像から色目標を作る

`quality_goal.reference.image_id` に公開および派生物の公開が許可された登録済み画像のID、`reference.sample` にその画像の矩形、`quality_goal.sample` に制作途中のPNG上の評価矩形を指定します。参照画像の不透明画素の中央値RGBを色目標に使い、比較範囲のSSIMも記録します。配色の判断にはRGB差を用います。テスト用ジョブでは `swatch_fixture` から見本画像を生成します。両方の領域は作品全体の類似性を表しません。

VectorCraft は対象名と `stroke: {width, color}` を指定できます。幅の差が許容値を超えるとMCPで対象パスの線を設定し、書き出し後のオブジェクト構造を再測定します。制作意図を記録する `intent` は確認サイトに表示されます。自然言語から目標値や修正方法を推論する視覚モデルには、別途ユーザー指定と許可リスト登録が必要です。

### SmolVLM2 による視覚評価

`quality_goal.vision_review: true` のジョブは、現行プレビューと参照スウォッチを許可済みの SmolVLM2 に渡し、測定で検出済みの修正候補のうち次の操作を選びます。修正前後を比較するモデルの選択と処理秒数も履歴へ記録します。採否には測定上の改善と保護領域の一致を使用します。モデルに任意のMCPコマンドやパスを書かせません。PhotoCraft と VectorCraft の Actions 検証ジョブで有効にします。

CPU版の既存イメージを再利用し、固定リビジョン・SHA256のモデルを既存の取得・ClamAV検査で用意します。推論時はネットワークを無効化します。絵柄・キャラクター同一性の評価精度と、日本語での制作指示への対応は今後の検証範囲です。
