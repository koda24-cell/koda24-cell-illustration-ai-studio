# 検証結果と実行ログ

凡例: ✅ 実動作確認済み（ログあり） / 🟡 実装済み・未検証 / ⛔ 未実装

## 2026-11-26 基盤（PR #1, モデル不使用）
| 項目 | 状態 | 証拠 |
|---|---|---|
| 単体テスト 47 件（許可リスト検証・ジョブ照合・取得ゲート・圧縮検査・評価・改善・再試行3回・時間予算停止と再開・非公開派生物の非掲載・テンプレート） | ✅ | [ci #45833371241](https://github.com/koda24-cell/koda24-cell-illustration-ai-studio/actions/runs/45833371241)（`46 passed`）、[ci #45834327037](https://github.com/koda24-cell/koda24-cell-illustration-ai-studio/actions/runs/45834327037) |
| 許可リスト（空）の検査 / 無料ランナー・従量課金APIの静的検査 | ✅ | 同上 `allowlist-check`, `budget-lint` |
| 自己診断ラン（procedural・9ステージ: 生成/inpaint/outpaint/hires/透過/線画/拡大/背景合成）と制作確認サイト生成 | ✅ | 同上（Artifacts `selftest-run-and-site`） |
| ClamAV ゲート: freshclam 更新、通常ファイル合格、EICAR テストファイルを `QUARANTINED_DETECTION` で隔離 | ✅ | 同上 job `clamav-gate`（ClamAV 1.5.4 / DB 28194） |
| Docker（CPU）イメージのビルドとコンテナ内自己診断（torch 2.15.0+cpu, diffusers 0.43.0） | ✅ | [docker #45833371139](https://github.com/koda24-cell/koda24-cell-illustration-ai-studio/actions/runs/45833371139) |
| `produce` / `site` / `fetch-models` / `register-model` ワークフロー | 🟡 | workflow_dispatch はデフォルトブランチに存在する必要があるため、**PR #1 マージ後に実行・確認** |
| studio-runs への途中保存 push・実 Actions 上での再開 | 🟡 | 同上（ロジックは単体テストで確認済み） |
| GitHub Pages 公開 | 🟡 | Pages の有効化（Settings → Pages → GitHub Actions）が必要 |
| Civitai API 連携（登録下書き・ダウンロード） | 🟡 | モデル指定後に確認 |
| Diffusers による全生成機能（txt2img〜IP-Adapter） | 🟡 | **許可リストが空のため未検証**。モデル指定後に CPU 所要時間とともに記録 |
| 意味的評価（CLIP 等）・ポーズ/人体バランス評価 | ⛔ | 評価モデル未指定（「評価不能」と記録する実装） |

## 既知の制約
- 背景透過はモデル不要の単色背景キー方式。複雑な背景や髪と背景が同色の場合は不正確（許可済みセグメンテーションモデルの指定があれば拡張可能）。
- 自動評価は統計的な代理指標。手指・人体の破綻や絵柄の意味的な近さは判定できない。
- 長いプロンプト（77トークン超）は切り捨てられる（Diffusers 標準の挙動）。
- Public リポジトリのため `studio-runs` の結果は誰でも閲覧可能。そのため非公開画像から派生する制作は `produce` が実行前に停止する（評価用参考画像は指標のみ保存されるため可）。
