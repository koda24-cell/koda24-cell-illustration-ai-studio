# 制作途中の引き継ぎ（GPT ⇄ Claude ⇄ Codex）

引き継ぐ側は、まずこの順で確認してください。
1. `AGENTS.md`（ルール）→ `docs/VERIFICATION.md`（何が確認済みか）
2. `allowlist/models.yaml` / `images.yaml`（使ってよいもの）
3. `studio-runs` ブランチの `runs/<run_id>/run.json` と `state.json`（どこまで進んだか）
4. 下の「現在の引き継ぎ事項」

## 中断した制作の再開
- `state.json` の `status` が `time_budget_exhausted` / `failed` の run は、`produce` を `resume_run_id=<run_id>` で再実行すると続きから再開（完了ステージは飛ばす）。
- `failed` の原因は `errors.jsonl` と `run.json` の `fatal_error`。対応は [ERROR_RUNBOOK.md](ERROR_RUNBOOK.md)。
- 設定を変えてやり直す場合は `rerun` で新しいジョブを作る（元の run は残す）。

## 引き継ぎメモの書き方（このファイルの下に追記・古いものは消さない）
```
### YYYY-MM-DD 担当: Claude/GPT/Codex
- 対象ジョブ / run_id:
- 状態: 実装済み / 実動作確認済み（run URL） / 未検証
- 次にやること:
- ユーザー確認待ち（モデル指定・依存・採否など）:
```

## 現在の引き継ぎ事項
### 2026-11-26 担当: Claude
- 基盤・許可リスト・モデル管理・生成/評価/長時間セッション・Actions・サイトを実装（PR #1）。
- 許可リストは空。**生成用モデルの指定待ち**。指定後に fetch-models → produce で実生成を検証する。
- Diffusers 経由の全生成機能は未検証（🟡）。Checkpoint 指定時は pipeline_config（構成ファイル）も必須依存として指定が必要。
- 2026-11-26 追記: PR #1・#2 マージ済み。produce（自己診断）・再開・Pages 公開を Actions で確認（VERIFICATION.md）。残りはモデル指定後の実生成検証。

### 2026-11-27 担当: Claude
- Obsession (Illustrious-XL) v-pred_v1.1 と SDXL 構成ファイル（ユーザー承認の必須依存）を許可リストに登録し、実生成を検証（VERIFICATION.md）。
- CPU 実測: txt2img 約40分 / inpaint 約13分 / img2img 約20分 / outpaint 約58分。ピークメモリ約15GB → produce でスワップ12GB追加済み。
- ライセンス注意: Civitai フラグは allowCommercialUse=[RentCivit] のみ（生成画像の販売を含まない）。商用作品での使用可否はユーザー確認待ち。
- 次: ユーザーが LoRA / ControlNet / IP-Adapter 等を指定したら、それらの実機検証。評価モデル（CLIP 等）は未指定。
