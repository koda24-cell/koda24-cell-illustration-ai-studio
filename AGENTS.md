# AGENTS.md — Illustration AI Studio 共同作業ルール（GPT・Claude・Codex 共通）

GitHub Actions の無料標準ランナー（CPU）だけで、AI イラストの制作・評価・修正・保存まで完結させる汎用環境。
ゲームやイラスト制作に再利用できる独立リポジトリであり、特定作品の正式素材置き場ではない。

## 0. 最重要ルール（違反は即停止）
1. **モデル・データは許可リストのものだけ**使う。対象: Checkpoint / LoRA / LyCORIS / VAE / Embedding / ControlNet /
   IP-Adapter（＋画像エンコーダ）/ アップスケーラ / 評価モデル / Diffusers 構成ファイル / 参考・学習・評価用画像。
   - `allowlist/models.yaml`・`allowlist/images.yaml` に**ユーザーが明示指定したもの**だけを登録する（`added_by_user_instruction` に指示の出典を書く）。
   - 自動収集・人気ランキングや AI 判断による追加・自動更新・自動置換は**禁止**。バージョン（version_id）と SHA256 で固定する。
   - 必須依存（構成ファイル、IP-Adapter の画像エンコーダ等）が足りなくても**勝手に追加しない**。`DEPENDENCY_MISSING` として報告する。
   - 許可済みモデルの中から用途に合うものを選ぶこと、生成設定・パラメータの調整は許可されている。
2. **追加課金ゼロ**。従量課金 API（OpenAI 等）・有料/GPU ランナー・有料ストレージは使わない。`runs-on` は `ubuntu-latest` 等の標準ランナーのみ（`python -m studio budget-lint` が CI で検査）。無料枠を超えそうなら `budget-check` が停止させる。
3. **外部ファイルは取得直後に ClamAV 検査**（定義更新失敗・未導入は `BLOCKED_UNSCANNED` で停止）。圧縮ファイルは展開前の構造検査＋展開後の再スキャン。safetensors 優先、pickle 形式は既定で拒否。不明な外部コードは実行しない。
4. **認証情報を公開しない**。トークンは GitHub Secrets（`CIVITAI_API_TOKEN`, `HF_TOKEN`, `STUDIO_INPUT_KEY`）のみ。ログ・コミット・サイトに出さない。
5. **既存データを破壊・削除しない**。`studio-runs` ブランチは追記のみ（force push 禁止）。過去の生成結果は消さない。
6. **完成素材の無断正式採用は禁止**。自動評価は制作途中の改善用。採否は `approvals/approvals.yaml` にユーザーが記入する（AI は「承認」と書かない）。
7. 非公開の参考画像・個人データを公開サイトや公開リポジトリに平文で置かない（`public_ok: false` は `encrypted_path`）。

## 1. どこに何があるか
| 目的 | 場所 |
|---|---|
| 使用許可モデル / 画像 | `allowlist/models.yaml`, `allowlist/images.yaml` |
| モデル台帳（特徴・推奨設定・CPU実績） | `catalog/model_ledger.yaml`（Actions 実行中の実績は `studio-runs:ledger/`） |
| 機能カタログ（対応モデル・入力・実行方法・検証状況） | `docs/FEATURE_CATALOG.md` |
| モデル/画像の登録手順・必須依存 | `docs/MODEL_REGISTRATION.md` |
| Actions 実行手順 | `docs/ACTIONS_GUIDE.md` |
| 共通実行環境（イメージ digest・スワップ・引き継ぎ上限） | `config/runtime.yaml`, `Dockerfile`, `requirements/lock-cpu.txt` |
| プッシュ起動用の制作指示置き場 | `jobs/queue/` |
| 制作指示テンプレート | `docs/JOB_TEMPLATE.md`, `jobs/templates/` |
| 成果物の保存ルール | `docs/STORAGE_RULES.md` |
| 制作途中の引き継ぎ | `docs/HANDOFF.md` |
| エラー時の対応 | `docs/ERROR_RUNBOOK.md` |
| 安全性・費用・利用条件 | `docs/SECURITY_AND_COST.md` |
| 検証結果と実行ログ（実装済み/実動作確認済み/未検証） | `docs/VERIFICATION.md` |
| コタマのぼうけんへの反映 | `docs/KOTAMA_INTEGRATION.md` |
| 採用判断（ユーザーのみ） | `approvals/approvals.yaml` |
| コード | `studio/`（CLI: `python -m studio --help`） |

## 1.5 共通実行環境（すべてのイラストAI制作で使う）
- 実行は **共通 Docker イメージ**（`config/runtime.yaml` の digest 固定、GHCR `ghcr.io/koda24-cell/illustration-ai-studio-cpu`）。PyTorch/Diffusers/Transformers/ClamAV 導入済みで、毎回の pip install は不要。
- 制作の起動方法は2つ。どちらも**制作指示 YAML を書くだけ**（ワークフローを新規作成しない）:
  1. **プッシュ起動**: `jobs/queue/<名前>.yaml` を追加/更新して push → `studio-push`
  2. **手動起動**: Actions → `produce`（`job` に YAML パス、再開は `resume_run_id`）
- 実体は再利用ワークフロー `studio-run`。時間切れ（1ジョブ最大345分）になると自動で `produce` を `resume_run_id` 付きで起動して続きから再開（`max_chain` 回まで）。
- モデル本体はイメージに含めない。キャッシュは必要モデルの SHA256 集合をキーにした actions/cache で、復元後は毎回 SHA256 を全量照合。未取得時だけ ClamAV 検査付きで取得。
- イメージ更新: `Dockerfile` / `requirements/lock-cpu.txt` 変更 → `build-image` が公開 → 出力 digest を `config/runtime.yaml` に PR で反映。
- 旧方式（毎回 pip で構築）は `produce-native` として互換用に残す。

## 2. 作業の流れ
1. ユーザーの指示を確認。モデル指定が無ければ**モデルを使わない範囲**（procedural バックエンド・画像処理）だけで進める。
2. モデル指定を受けたら: `register-model` ワークフロー or `python -m studio allowlist-draft --url ... --instruction "..." --append` → PR → マージ → `fetch-models` が取得・検査・ハッシュ照合・キャッシュ。
3. 制作指示を `jobs/` に YAML で作成（`docs/JOB_TEMPLATE.md`）。`python -m studio job-validate <job>` で許可リスト照合。
4. `jobs/queue/` に置いて push、または `produce` を手動起動（1ジョブ最大 345 分）。途中保存は `studio-runs` へ自動 push、時間切れは自動引き継ぎ、強制終了時は `resume_run_id` で再開。
5. `site` ワークフローが制作確認サイトを更新。結果・評価・限界をユーザーに報告し、採否はユーザーに委ねる。
6. 機能を検証したら `docs/VERIFICATION.md` と `docs/FEATURE_CATALOG.md` の状態を更新（証拠: Actions run URL）。

## 3. 報告ルール
- 「実装済み（コードあり）」「実動作確認済み（Actions/テストのログあり）」「未検証」を必ず区別する。ログ・run ID が無いものを確認済みと言わない。
- CPU で実用性が低い機能は、完成扱いせず所要時間と制約を記録する。
- 失敗・未取得・評価不能は隠さず記録する。

## 4. ブランチ・PR
- 機能追加・設定変更は機能ブランチ → PR → CI 合格後にマージ。`main` への直接 push はしない。
- `studio-runs` は Actions が制作結果を追記するデータ専用ブランチ（コードを置かない）。
- 必要な機能が一通り揃ったら区切る。過剰な制限や細かすぎる機能を際限なく追加しない。
