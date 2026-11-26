# 成果物の保存ルール

## 保存先
| もの | 保存先 | 備考 |
|---|---|---|
| コード・設定・許可リスト・台帳・ドキュメント | `main`（PR 経由のみ） | |
| 制作結果（全候補・ベスト・比較・評価・ログ） | `studio-runs` ブランチ `runs/<run_id>/` | Actions が追記。**削除・force push 禁止** |
| 実行中のモデル実績 | `studio-runs:ledger/model_ledger.yaml` | 区切りで main の台帳へ PR で反映 |
| モデル本体 | actions/cache（`.cache/studio/models/<sha256>/`） | Git に入れない。消えても許可リストから再取得・再検査 |
| 一時成果物 | Actions Artifacts（30日） | 恒久保存は studio-runs |
| 採否 | `approvals/approvals.yaml`（ユーザーのみ） | |

## ラン・ディレクトリの構成
```
runs/<run_id>/
  run.json          # 概要（状態・使用モデルとSHA256・ステージ結果・経過時間・エラー）
  state.json        # 再開用の完全な状態（ジョブ定義・全ラウンド履歴）
  job.json, plan.md # 制作指示と制作計画
  stages/<stage>/rNN_cK.png + .json   # 全候補（プロンプト・ネガティブ・seed・設定・時間・評価）
  stages/<stage>/best.png
  comparisons/<stage>_latest.png      # 改善前後
  log.jsonl, errors.jsonl
  gen_versions.txt  # 使用した torch/diffusers 等のバージョン
```
PNG には `studio:params` テキストチャンクで生成設定を埋め込みます。

## ルール
- 過去の結果を消さない・上書きしない。同じ素材の改版は新しい run として作る。
- 非公開入力から作った画像はサイトに出さない（ブランチには残るため、**Public リポジトリでは非公開入力を使うジョブは `publish: false` にし、必要なら別の Private リポジトリで実行**することを推奨）。
- 自動評価や「ベスト」は採用ではない。採用はユーザーが `approvals.yaml` に記入。
- 他作品へ反映するときは、その作品の素材管理・承認ルールに従う（コタマは [KOTAMA_INTEGRATION.md](KOTAMA_INTEGRATION.md)）。
