# モデル・画像の登録（許可リスト）

基盤ツール（`requirements/*.txt`, `Dockerfile`）と生成用モデル（`allowlist/`）は別管理です。
許可リストは初期状態で空。**ユーザーが明示的に指定したものだけ**を登録します。

## 1. モデルの登録手順
### A. GitHub 上だけで（スマホ可）
1. Actions → **register-model** → Run workflow
2. `url` に Civitai の URL（**`?modelVersionId=` 付き**。バージョン無しは拒否＝最新版の自動選択をしない）、`note` に用途
3. 生成された PR を確認（ライセンス・ファイル名・SHA256）→ マージ
4. マージで **fetch-models** が起動 → 取得 → ClamAV → SHA256 照合 → キャッシュ

### B. AI（GPT/Claude）に依頼する場合
ユーザーの指示文を `--instruction` に残して下書きを作り、PR にします。
```bash
python -m studio allowlist-draft --url "https://civitai.com/models/123?modelVersionId=456" \
  --instruction "2026-11-27 ユーザー指示（チャット）: コタマ立ち絵用ベース" --append
python -m studio allowlist-check && python -m studio ledger-sync
```

## 2. エントリの項目（allowlist/models.yaml）
| 項目 | 必須 | 説明 |
|---|---|---|
| `id` | ✔ | 安定ID（英小文字・数字・`._-`） |
| `kind` | ✔ | checkpoint / lora / lycoris / vae / embedding / controlnet / ip_adapter / image_encoder / upscaler / evaluator / pipeline_config |
| `source` | ✔ | `civitai` または `huggingface`（依存ファイル用） |
| `civitai.version_id` | civitai時 ✔ | バージョン固定（`model_id`, `file_id` も記録） |
| `huggingface.repo` / `revision` | HF時 ✔ | 40桁のコミットで固定 |
| `filename` + `sha256` | ✔ | 単一ファイル。複数ファイルは `files: [{filename, repo_path, sha256, size_bytes}]` |
| `added_by_user_instruction` | ✔ | ユーザー指示の記録（日時・経路・内容） |
| `base_model` | 推奨 | 例 `SD 1.5`, `SDXL 1.0`, `Illustrious`, `Pony`（アーキテクチャ判定に使用） |
| `license` | 推奨 | Civitai の商用利用フラグ等（下書きで自動記入） |
| `allow_pickle` | 任意 | pickle 形式をどうしても使う場合のみ true（理由を併記）。既定は拒否 |

## 3. 必須依存（勝手に追加しないもの）
| 使いたいもの | 追加で必要なもの | 備考 |
|---|---|---|
| Checkpoint（単一 safetensors） | **pipeline_config**（そのアーキテクチャの Diffusers 構成ファイル。重みなしの json/txt） | 例: SD1.5 系なら `stable-diffusion-v1-5/stable-diffusion-v1-5`、SDXL 系なら `stabilityai/stable-diffusion-xl-base-1.0` の `model_index.json`, `scheduler/`, `text_encoder*/config.json`, `tokenizer*/*`, `unet/config.json`, `vae/config.json`。`arch: sd15` / `sdxl` を書く |
| ControlNet（単一ファイル） | `config_entry`（ControlNet の config.json を含む pipeline_config） | Diffusers 形式（config.json + 重み）なら不要 |
| IP-Adapter | **image_encoder**（CLIP Vision, Diffusers/Transformers 形式） | |
| Embedding / LoRA | 対応する base_model の Checkpoint | |
| 意味的評価 | evaluator（CLIP 等） | 未指定なら評価不能として記録 |
| ポーズ評価 | 姿勢推定モデル | 現状未実装 |

依存不足は実行時に `DEPENDENCY_MISSING` で止まり、必要なものを報告します。ユーザーの指定を待ちます。
※ 構成ファイルは重みを含みませんが、外部ファイルのため同じく許可リスト・SHA256固定・ClamAV検査の対象です。

pipeline_config の例:
```yaml
- id: sd15-config
  kind: pipeline_config
  arch: sd15
  source: huggingface
  huggingface: {repo: stable-diffusion-v1-5/stable-diffusion-v1-5, revision: <40桁コミット>}
  files:
    - {filename: model_index.json, repo_path: model_index.json, sha256: <...>}
    - {filename: scheduler_config.json, repo_path: scheduler/scheduler_config.json, sha256: <...>}
    # ... text_encoder/config.json, tokenizer/{vocab.json,merges.txt,tokenizer_config.json,special_tokens_map.json},
    #     unet/config.json, vae/config.json
  added_by_user_instruction: "..."
```
（`filename` はキャッシュ内のファイル名。同名ファイルが複数ある場合は `filename` を変えて `repo_path` で配置先を指定）

## 4. モデル台帳（catalog/model_ledger.yaml）
`ledger-sync` で許可済みモデルの枠を作成します（既存の記入は上書きしない）。項目:
モデル名・バージョン・配布元URL・作者・ファイル形式・容量・SHA256・商用利用条件・得意な絵柄・得意な生成内容・
推奨生成設定・トリガーワード・対応するLoRA/補助機能・必須依存・CPU動作状況・実際の生成結果。
「得意な絵柄/内容」は配布元記載か実生成結果から書き、出典（`strengths.source`）を残します。
`model: auto` の場合、台帳の strengths と実績から**許可済みモデルの中だけで**選びます。

## 5. 画像の登録（allowlist/images.yaml）
```yaml
- id: kotama-ref-01
  roles: [reference]          # reference / training / evaluation / init / mask / control / background
  path: inputs/images/kotama-ref-01.png     # 公開してよい画像のみ平文で
  sha256: <...>
  public_ok: true             # サイト掲載可否
  derivatives_public_ok: false # この画像から作った生成物を掲載してよいか（既定 false）
  added_by_user_instruction: "..."
```
**非公開画像**はこのリポジトリが Public のため平文で置きません。暗号化して `encrypted_path` に置き、
復号キーを Secret `STUDIO_INPUT_KEY` に登録します。
```bash
openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -in ref.png -out inputs/encrypted/ref.png.enc -pass env:STUDIO_INPUT_KEY
sha256sum ref.png   # ← 平文の SHA256 を sha256 に記入
```
非公開画像から作った生成物は、`derivatives_public_ok: true` でない限りサイトに画像を出しません。

## 6. 取消・更新
- 取消: エントリを削除する PR（台帳は `allowed: false` として履歴保持）。
- 新バージョン: **別エントリとして追加**（自動置換しない）。旧版との比較はジョブで明示的に行う。
