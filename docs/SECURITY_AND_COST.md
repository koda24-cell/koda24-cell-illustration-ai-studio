# 安全性・費用・利用条件

## 費用（追加課金ゼロ）
- 実行環境は GitHub Actions の**無料標準ランナー**のみ。`budget-lint` が CI で `runs-on`・`timeout-minutes`・従量課金APIの参照を検査。
- このリポジトリは **Public** のため、標準ランナーの実行時間は無料。Private に変更した場合は `config/budget.yaml` の月間上限で `budget-check` が実行前に停止（アカウント全体の無料枠は他リポジトリと共有のため保守的に判定）。
- OpenAI 等の従量課金 API、有料/GPU ランナー、有料ストレージは使わない。プロンプト改善もルールベース（`config/improvement_rules.yaml`）。
- actions/cache はリポジトリあたり 10GB（超過時は古いものから自動削除で課金なし）。合計 9GB 超のモデル群はキャッシュせず毎回再取得。
- 最終防衛線: GitHub の Spending limit を $0 に維持（ユーザー設定）。

## 外部ファイルの安全検査
- 取得は許可リストの固定バージョン・固定 SHA256 のみ。隔離ディレクトリへ取得 → **直後に ClamAV**（定義は毎回 freshclam、freshclam 成功必須、かつ定義が96時間以内でなければ停止）→ 圧縮ファイルは構造検査・隔離展開・**再スキャン** → SHA256 照合 → safetensors ヘッダ検査 → キャッシュへ昇格。
- ClamAV は 1 ファイル約 4GB を超えると全体を検査できないため、約 3GB 超のファイル（SDXL Checkpoint 等）は 1GB 単位（4MB 重なり）の分割片を全て検査し、`method: chunked` と記録する。上限超過は `--alert-exceeds-max=yes` で検出扱い（素通りさせない）。
- 記録: `scan_manifest.json`（出典・sha256・スキャナ/定義バージョン・終了コード・検出数）。
- `SAFETY_CHECK_OK` はマルウェア検査ゲートのみの合格。ライセンス・品質・採用の承認ではない。検査も絶対安全を保証しない。
- pickle 形式（.ckpt/.pt/.bin）は既定で拒否。不明な外部コード（カスタムノード・拡張・インストールスクリプト）は実行しない。
- 生成中は `HF_HUB_OFFLINE=1` 等で Diffusers/Transformers の暗黙ダウンロードを禁止。

## 認証情報
- Secrets のみ（`CIVITAI_API_TOKEN`, `HF_TOKEN`, `STUDIO_INPUT_KEY`）。ログはマスク処理。コミット・サイトに出さない。
- 生成ステップには Civitai トークンを渡さない（取得ステップのみ）。

## データ保護
- 既存データの削除・force push はしない。`studio-runs` は追記のみ。
- 非公開画像は暗号化（`encrypted_path`）。サイトには非公開入力の派生物を出さない。

## 利用条件・ライセンス
- 登録時に Civitai の商用利用フラグ（allowCommercialUse 等）を台帳に記録。**最終的な利用可否は配布ページの条件と作品の用途でユーザーが判断**。
- 生成物の正式採用はユーザーの承認後のみ。
- GitHub の利用規約・Actions の利用ポリシー・Civitai の API 利用条件を守る（大量アクセス・検索による自動収集をしない）。
