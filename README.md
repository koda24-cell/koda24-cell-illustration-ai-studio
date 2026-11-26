# Illustration AI Studio

GitHub Actions の**無料標準ランナー（CPU）だけ**で、AI イラストの制作・評価・修正・保存まで完結させる汎用環境です。
PC へのインストールや常時稼働は不要。GPT・Claude・Codex から同じ手順で使えます（ルールは [AGENTS.md](AGENTS.md)）。

## 特徴
- **許可リスト制**: ユーザーが明示指定したモデル・画像だけを取得/使用（初期状態は空、自動収集・自動更新なし）
- **安全ゲート**: 取得直後の ClamAV 検査、圧縮ファイルの展開前後検査、SHA256 固定、safetensors 優先
- **生成**: Diffusers（CPU）で txt2img / img2img / Inpaint / Outpaint / Hires / LoRA / ControlNet / IP-Adapter
- **制作レシピ**: 立ち絵・表情/衣装/ポーズ差分・三面図・線画・着彩・背景・イベントスチル
- **長時間制作**: 最大 6 時間、候補生成 → 評価 → 改善 → 再生成、途中保存・再開、最大3回の自動復旧
- **評価**: 参考画像との類似・色彩・明度彩度・線画・陰影・構図・破綻・一貫性（根拠と限界つき、採否はユーザー）
- **制作確認サイト**: GitHub Pages に全履歴・設定・評価・承認状態を表示（非公開入力は非掲載）
- **追加課金ゼロ**: 有料ランナー・従量課金 API 不使用、無料枠ガード

## すぐ使う
1. 初回設定（Secrets・Pages・支出上限 $0）: [docs/ACTIONS_GUIDE.md](docs/ACTIONS_GUIDE.md)
2. モデルを指定: Actions → **register-model**（Civitai URL を入力）→ PR をマージ → 自動で取得・検査
3. 制作指示を書く: [docs/JOB_TEMPLATE.md](docs/JOB_TEMPLATE.md)（雛形は `jobs/templates/`）
4. Actions → **produce** で実行 → 制作確認サイトで確認 → 採用は `approvals/approvals.yaml`

## ドキュメント
| | |
|---|---|
| [機能カタログ](docs/FEATURE_CATALOG.md) | 全機能の対応モデル・入力・実行方法・検証状況 |
| [モデル/画像の登録](docs/MODEL_REGISTRATION.md) | 許可リスト・台帳・必須依存 |
| [Actions 実行手順](docs/ACTIONS_GUIDE.md) | 各ワークフローと設定 |
| [保存ルール](docs/STORAGE_RULES.md) / [引き継ぎ](docs/HANDOFF.md) / [エラー対応](docs/ERROR_RUNBOOK.md) | 運用 |
| [安全性・費用](docs/SECURITY_AND_COST.md) | 必須条件の実装方法 |
| [検証結果](docs/VERIFICATION.md) | 実装済み / 実動作確認済み / 未検証 |
| [コタマでの利用](docs/KOTAMA_INTEGRATION.md) | コタマのぼうけんへの反映ルール |

## 現在の状態
基盤・許可リスト・モデル管理・パイプラインは実装済み。**許可リストは空**のため、AI モデルを使う生成はまだ検証していません。
モデル指定後に実画像で検証します（詳細は [VERIFICATION.md](docs/VERIFICATION.md)）。
