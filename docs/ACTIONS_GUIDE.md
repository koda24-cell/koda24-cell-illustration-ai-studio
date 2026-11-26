# GitHub Actions 実行手順

すべて無料の標準ランナー（`ubuntu-latest`, CPU）で動きます。GPU・有料ランナーは使いません。

## 初回設定（ユーザー作業・1回だけ）
1. **Secrets**（Settings → Secrets and variables → Actions）
   - `CIVITAI_API_TOKEN`: Civitai の API キー（ログイン必須モデルの取得に必要。公開モデルだけなら無くても可）
   - `HF_TOKEN`: 任意（Hugging Face の依存ファイルが要認証の場合のみ）
   - `STUDIO_INPUT_KEY`: 任意（非公開画像を暗号化して使う場合）
2. **Pages**: Settings → Pages → Source を **GitHub Actions** に（制作確認サイト用）
3. **Billing**: 支出上限（Spending limit）が **$0** のままであることを確認（追加課金の最終防衛線）
4. 任意: Settings → Actions → General → 「Allow GitHub Actions to create and approve pull requests」を ON（register-model が PR を自動作成できる）

## ワークフロー一覧
| 名前 | きっかけ | 内容 |
|---|---|---|
| `ci` | PR / main push | 単体テスト、許可リスト検査、無料ランナー静的検査、自己診断ラン、サイト生成、ClamAV ゲート検証（EICAR） |
| `register-model` | 手動 | Civitai URL から許可リスト下書き → ブランチ / PR（モデル本体は取得しない） |
| `fetch-models` | 手動 / models.yaml 更新 | 許可モデルのみ取得 → ClamAV → SHA256 → actions/cache |
| `produce` | 手動 | 制作ジョブ実行（最大 345 分）、途中保存・再開 |
| `site` | main push / produce 完了 / 手動 | 制作確認サイトを Pages に公開 |
| `docker` | Dockerfile 変更 PR / 手動 | CPU コンテナのビルドと自己診断 |

## produce の実行
Actions → **produce** → Run workflow
- `job`: ジョブ YAML のパス（例 `jobs/my-job.yaml`）
- `time_budget`: 分（最大 345。セットアップ時間を含めて 6 時間以内に収まるよう制限）
- `resume_run_id`: 中断した run を再開するときに指定（新規なら空）

実行中は 15 分ごとに `studio-runs` ブランチへ途中保存されます。タイムアウトや失敗でも保存済み分は残り、
`resume_run_id` で続きから再開できます。結果はジョブの Summary、成果物（Artifacts）、制作確認サイトで確認。

## ローカル / 他環境での実行（任意）
```bash
pip install -r requirements/base.txt                 # 基盤（モデル不要の機能・評価・サイト）
pip install -r requirements/gen.txt                  # 生成（CPU torch + diffusers）
python -m studio doctor
python -m studio selftest                            # モデル不使用の総合テスト
python -m studio run jobs/my-job.yaml --time-budget 30
python -m studio site --out _site
```
Docker: `docker build -t illustration-ai-studio . && docker run --rm illustration-ai-studio python -m studio selftest`

## CPU での目安（未検証。実測後に台帳 `cpu_status` へ記録）
- SD1.5 系 512×512・20 steps: 1 枚あたり数十秒〜数分程度の見込み
- SDXL 系 1024×1024: 1 枚あたり十数分以上の見込み → 768 前後・steps 少なめを推奨
- ランナーのディスク・メモリ上限により、大きなモデルの同時読込は避ける
