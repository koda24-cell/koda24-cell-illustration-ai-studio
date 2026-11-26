# エラー発生時の対応手順

セッションは**最大3回**まで自動復旧を試み、それでも失敗したら状態を保存して停止します（無限ループなし）。
エラーは `runs/<run_id>/errors.jsonl` に「分類・分析・対処」を記録します。

| コード | 意味 | 自動対応 | 人の対応 |
|---|---|---|---|
| `NOT_ALLOWED` | 許可リスト外のモデル/画像を参照 | 即停止 | ジョブを許可済みIDに直す。追加が必要ならユーザーに依頼（勝手に追加しない） |
| `DEPENDENCY_MISSING` | 構成ファイル・画像エンコーダ等の必須依存が未登録 | 即停止 | 必要な依存をユーザーに報告し指定を待つ（MODEL_REGISTRATION.md §3） |
| `MODEL_NOT_CACHED` | 未取得 | 即停止 | `fetch-models` を実行 |
| `HASH_MISMATCH` | SHA256 不一致 | 破棄・停止 | 配布元の差し替えの可能性。自動置換せずユーザーに報告 |
| `BLOCKED_UNSCANNED` | ClamAV 未導入/定義更新失敗/検査エラー | 停止（素通りさせない） | 時間をおいて再実行（freshclam の制限の可能性） |
| `QUARANTINED_DETECTION` | マルウェア検出 | 使用禁止 | 自動再試行しない。配布元を再評価しユーザーに報告 |
| `UNSAFE_FORMAT` | pickle 形式等 | 拒否 | safetensors 版を探すようユーザーに相談 |
| `ARCHIVE_REJECTED` | 圧縮ファイルの危険構造 | 拒否 | 報告 |
| `UNSUPPORTED_ARCH` | Flux/SD3 等 | 停止 | CPU では実用外。SD1.x/SDXL 系を提案 |
| `OOM` | メモリ不足 | 解像度を 75% にして再試行 | 解像度/候補数を下げる、SDXL→小さめ設定 |
| `RUNTIME` / `NETWORK_OR_OFFLINE` | その他 | 同条件で再試行 | ログを見て修正。生成中の外部取得は禁止（offline）なので構成ファイル不足を疑う |
| `RETRY_EXHAUSTED` | 復旧3回超過 | 状態保存して停止 | 原因修正後 `resume_run_id` で再開 |
| `BUDGET_EXCEEDED` | 無料枠超過の恐れ | 実行前に停止 | 月替わりを待つ / 時間予算を減らす / config/budget.yaml を見直す（ユーザー判断） |
| `SECRET_MISSING` / `AUTH` | Secret 未設定・拒否 | 停止 | Secrets を設定（値をログに出さない） |

Actions のジョブ自体が 6 時間で強制終了された場合も、15 分ごとの途中保存までは `studio-runs` に残ります。
