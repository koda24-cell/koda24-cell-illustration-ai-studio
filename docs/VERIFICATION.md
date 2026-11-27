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
| `produce`（自己診断ジョブ）: 無料枠ガード → studio-runs ブランチ新規作成 → 実行 → 途中保存 push | ✅ | [produce #45840964002](https://github.com/koda24-cell/koda24-cell-illustration-ai-studio/actions/runs/45840964002)（初回は studio-runs 作成処理の不具合で失敗 [#45840293619](https://github.com/koda24-cell/koda24-cell-illustration-ai-studio/actions/runs/45840293619) → PR #2 で修正） |
| `produce` の再開（resume_run_id）: 完了済みステージを飛ばし sessions=2 を記録 | ✅ | [produce #45841287922](https://github.com/koda24-cell/koda24-cell-illustration-ai-studio/actions/runs/45841287922) |
| `fetch-models`: 許可リストが空のとき何も取得しない | ✅ | [fetch-models #45840249224](https://github.com/koda24-cell/koda24-cell-illustration-ai-studio/actions/runs/45840249224) |
| GitHub Pages 公開（制作確認サイト） | ✅ | [site #45841808100](https://github.com/koda24-cell/koda24-cell-illustration-ai-studio/actions/runs/45841808100) → https://koda24-cell.github.io/koda24-cell-illustration-ai-studio/ |
| `register-model`（Civitai URL → 許可リスト下書き PR） | 🟡 | モデル指定時に確認（`CIVITAI_API_TOKEN` Secret 推奨） |
| 時間切れで中断したランの Actions 上での再開 | 🟡 | ロジックは単体テストで確認済み。長時間の本番ジョブで確認予定 |
| Civitai API 連携（登録下書き・ダウンロード） | 🟡 | モデル指定後に確認 |
| Diffusers による全生成機能（txt2img〜IP-Adapter） | 🟡 | **許可リストが空のため未検証**。モデル指定後に CPU 所要時間とともに記録 |
| 意味的評価（CLIP 等）・ポーズ/人体バランス評価 | ⛔ | 評価モデル未指定（「評価不能」と記録する実装） |

## 2026-11-27 Obsession (Illustrious-XL) v-pred_v1.1 による実生成（CPU・無料標準ランナー）
| 項目 | 状態 | 証拠 / 結果 |
|---|---|---|
| Civitai 連携: URL → 許可リスト下書き（register-model） | ✅ | [#45848906667](https://github.com/koda24-cell/koda24-cell-illustration-ai-studio/actions/runs/45848906667) → PR #4 |
| HF 依存（SDXL 構成ファイル, ユーザー承認）の登録（register-hf） | ✅ | [#45850470597](https://github.com/koda24-cell/koda24-cell-illustration-ai-studio/actions/runs/45850470597) → PR #6 |
| 取得 → ClamAV（6.94GB を 1GB×7 分割検査）→ SHA256 照合 → safetensors 検査（`v_pred`/`ztsnr` キー確認）→ cache | ✅ | [fetch-models #45850710834](https://github.com/koda24-cell/koda24-cell-illustration-ai-studio/actions/runs/45850710834) |
| テキストから画像生成（832×1216, 20 steps, v-pred, fp32） | ✅ | [produce #45852576694](https://github.com/koda24-cell/koda24-cell-illustration-ai-studio/actions/runs/45852576694)：約41分/枚（読込込み）、目視で破綻なし |
| bfloat16 での高速化 | ❌ 不採用 | [produce #45860151186](https://github.com/koda24-cell/koda24-cell-illustration-ai-studio/actions/runs/45860151186)：69分経過でも1枚未完了 → 中止。CPU では fp32 が速い |
| 部分修正 Inpaint ＝ 表情差分（2ラウンド×2候補、改善ループ・一貫性評価） | ✅ | [produce #45868147350](https://github.com/koda24-cell/koda24-cell-illustration-ai-studio/actions/runs/45868147350)：約13〜14分/枚、笑顔差分は自然 |
| 背景透過（実イラスト） | ✅ | 同上：白背景 70% を透明化。輪郭に薄い白縁・足元の影は残る（限界） |
| 参考画像からの生成 img2img（denoise 0.45） | ✅（動作） / ⚠️（意図） | [produce #45884581582](https://github.com/koda24-cell/koda24-cell-illustration-ai-studio/actions/runs/45884581582)：約20分。衣装の色変更（緑→赤）は反映されず → 色や衣装の変更は Inpaint か denoise 0.6 以上が必要 |
| 描画範囲の拡張 Outpaint（832×1216 → 1216×1216） | ✅ | 同上：約58分 |
| ランナー強制終了からの再開 | ✅ | 初回 #45868147350 がメモリ不足で強制終了（ピーク RSS 約15GB）→ PR #9（スワップ12GB・ラウンド毎保存）→ resume #45884581582 で完了済みステージを飛ばして完了 |
| 途中保存（studio-runs への push）・制作確認サイト反映 | ✅ | studio-runs ブランチ / https://koda24-cell.github.io/koda24-cell-illustration-ai-studio/ |

未検証（モデル未指定）: LoRA / LyCORIS / Embedding / VAE差し替え / ControlNet / IP-Adapter / 専用アップスケーラ / CLIP 等の評価モデル。Hires 再描画は機能上は img2img と同じ経路だが、1216px 超で 1 時間を超える見込みのため未実行。

### CPU 実用性の評価（Obsession / SDXL 系）
- 6時間ジョブで生成できるのは目安として **txt2img 約8枚、または Inpaint 差分 約20枚**。複数候補×多ラウンドの自動改善は数ラウンドが上限。
- 推奨運用: txt2img は 1〜2 候補に絞り、良い 1 枚を起点に Inpaint で差分・修正（読込1回で済むよう同一ジョブにまとめる）。

## 2026-11-27 共通 Docker 実行基盤と高速化の実測（PR #13）
共通イメージ `ghcr.io/koda24-cell/illustration-ai-studio-cpu@sha256:27e0eba5…`（Public, 約635MB, torch 2.15.0+cpu / diffusers 0.43.0 / transformers 5.24.1 / ClamAV 1.4.6）。

### 基盤の検証
| 項目 | 状態 | 証拠 |
|---|---|---|
| イメージのビルド・GHCR 公開・digest 固定、イメージ内で pytest/自己診断/ClamAV 更新/EICAR 隔離 | ✅ | [build-image #45905570703](https://github.com/koda24-cell/koda24-cell-illustration-ai-studio/actions/runs/45905570703), [#45915667798](https://github.com/koda24-cell/koda24-cell-illustration-ai-studio/actions/runs/45915667798)（`IMAGE_CLAMAV_GATE_OK`, `PUBLIC`） |
| プッシュ起動（`jobs/queue/*.yaml` → studio-push → studio-run） | ✅ | [#45906498656](https://github.com/koda24-cell/koda24-cell-illustration-ai-studio/actions/runs/45906498656) ほか |
| 時間切れ → `produce` を resume 付きで自動起動 ×2 → 完了（引き継ぎ） | ✅ | [push #45914780671](https://github.com/koda24-cell/koda24-cell-illustration-ai-studio/actions/runs/45914780671) → [#45914987949](https://github.com/koda24-cell/koda24-cell-illustration-ai-studio/actions/runs/45914987949) → [#45915196886](https://github.com/koda24-cell/koda24-cell-illustration-ai-studio/actions/runs/45915196886)（handoff-test: sessions=3, 全ステージ done） |
| キャッシュ復元後の SHA256 全量照合（6.94GB） | ✅ | 約10秒 |
| 並行実行時の途中保存 push 競合 → rebase 再試行 | ✅（修正済み） | コンテナ内で git 識別情報が無く rebase 失敗していた → `checkpoint_push.sh` で設定 |

### 速度比較（同一モデル Obsession v-pred・同一プロンプト・832×1216・20 steps・fp32・seed 20261127/20261128）
| 計測項目 | A 旧方式（毎回 pip） | B Docker（同一設定） | C Docker＋高速設定 | D Docker（SDPAのみ） |
|---|---|---|---|---|
| 実行環境の準備（pip・ディスク・スワップ） | 164秒 | 2秒 | 2秒 | 2秒 |
| Docker イメージの取得 | — | 17秒 | 20秒 | 22秒 |
| モデルキャッシュの復元（6.94GB） | 83秒 | 45秒 | 50秒 | 51秒 |
| 安全性検査（キャッシュ時: SHA256照合 / 旧方式は ClamAV 導入含む） | 19秒 | 5秒※ | 10秒 | 9秒 |
| 実行開始までの合計 | **約270秒** | **約76秒** | **約90秒** | 約90秒 |
| モデルのメモリ読込 | 50秒 | 43秒 | 59秒 | 66秒 |
| 1枚目の生成 | 2174秒 | 2293秒 | **2079秒** | 2263秒 |
| 2枚目の生成（読込なし） | 2080秒 | 2192秒 | **1996秒** | — |
| 成果物の保存（最終 push） | 32秒（失敗→成果物から復元） | 2秒 | 2秒 | — |
| 制作セッション全体 | 4442秒 | 4546秒 | **4153秒** | — |
| **ジョブ全体** | **4749秒** | **4627秒** | **4252秒（−10.5%）** | 2445秒（1枚） |
| Actions | [#45905173128](https://github.com/koda24-cell/koda24-cell-illustration-ai-studio/actions/runs/45905173128) | [#45906498656](https://github.com/koda24-cell/koda24-cell-illustration-ai-studio/actions/runs/45906498656) | [#45906870731](https://github.com/koda24-cell/koda24-cell-illustration-ai-studio/actions/runs/45906870731) | [#45913553402](https://github.com/koda24-cell/koda24-cell-illustration-ai-studio/actions/runs/45913553402) |

※ B は旧仕様（キャッシュ内の検証済み印を信用）。以降は毎回全量照合（約10秒）。
C の設定: `attention_slicing: false`（PyTorch SDPA）＋ `channels_last: true`。**画質設定は同一で、B と C の出力は1枚目が完全一致・2枚目もほぼ一致**（平均画素差 0.003/255）。

### 分析
- **Docker 化の効果は準備時間に限られる**: 実行開始までが約270秒 → 約80秒（約3分短縮）。最大の要因は毎回の pip install（生成ライブラリ）とディスク整理の省略。
- **生成そのものは CPU 演算が律速**で、Docker 化だけでは速くならない。1枚あたりは A（旧方式）2174/2080秒、B（Docker 同一設定）2293/2192秒と B が約5%遅かったが、両者の出力は同一（平均画素差 0.003/255）で処理内容は同じ。標準ランナーは実行ごとに割り当てられる CPU 世代が異なり得るため、この差はランナー個体差の可能性が高い（当時は CPU 型番を記録しておらず断定できない → 以後は `backend_info.cpu_model` に記録）。
- **生成の高速化は channels_last が主因**: 同じ Docker 環境で比べると SDPA のみ（D）は B とほぼ同じ（−1%）、SDPA＋channels_last（C）は 1枚あたり約9%短縮（旧方式 A 比でも約4%短縮）。→ 既定値に採用（出力は同一）。
- **全体では A 4749秒 → C 4252秒（−497秒, −10.5%）**。内訳は準備の短縮 約3分＋生成の短縮 約3分（2枚）。1ジョブで作る枚数が多いほど生成側の効果が大きくなる。
- 旧方式の A は、並行実行中の push 競合で最終保存に失敗（旧 `checkpoint_push.sh` の rebase がコミッタ不明で失敗）。画像・ログは Actions の成果物から `recover-artifact`（[#45917927176](https://github.com/koda24-cell/koda24-cell-illustration-ai-studio/actions/runs/45917927176)）で studio-runs へ復元済み。この不具合は PR #13 で修正済み。
- モデルキャッシュ復元（約45〜50秒）は actions/cache の展開速度で律速。モデルをイメージに含めれば短縮できるが、許可リスト管理と分離の方針・GHCR 容量の観点から採用しない。
- 同一ジョブ内では、モデルは1回だけ読み込み、生成・Inpaint・img2img・Outpaint で同じ重みを再利用する（feature-check で 1回 64秒の読込のみ）。

### 共通 Docker 環境での実制作（プッシュ起動・既定の高速設定）
[studio-push #45917955420](https://github.com/koda24-cell/koda24-cell-illustration-ai-studio/actions/runs/45917955420)（`jobs/examples/docker-production-check.yaml`）: 立ち絵2枚の連続生成 → 表情差分（Inpaint・改善2ラウンド）→ 背景透過。**ジョブ全体 約94分で完了**。
| 工程 | 秒 |
|---|---|
| モデル読込（1回のみ。以降の生成・Inpaint で再利用） | 33 |
| 立ち絵 1枚目 / 2枚目（832×1216, 20 steps） | 1694 / 1688 |
| 表情差分 Inpaint ×2（denoise 0.55） | 1027 / 1029 |
| 背景透過 | 1未満 |
- このランナーは比較ランより約2割速く（1枚 約28分）、**標準ランナーの個体差が ±2割程度ある**ことを確認。速度比較は同時期の複数ランで行う必要がある。
- 表情差分は目（驚き）は反映されたが、口がマスク範囲（顔の上側）から外れて笑顔のまま → 顔の矩形は口まで含めて指定する（`face_rect` の高さを広げる）。
- 改善ループの探索が同じ cfg を繰り返していた不具合を修正（ベストを起点に上下交互）。

## 既知の制約
- 背景透過はモデル不要の単色背景キー方式（実イラストで輪郭に薄い白縁、接地影は残ることを確認）。複雑な背景や髪と背景が同色の場合は不正確（許可済みセグメンテーションモデルの指定があれば拡張可能）。
- 自動評価は統計的な代理指標。手指・人体の破綻や絵柄の意味的な近さは判定できない。
- 長いプロンプト（77トークン超）は切り捨てられる（Diffusers 標準の挙動）。
- Public リポジトリのため `studio-runs` の結果は誰でも閲覧可能。そのため非公開画像から派生する制作は `produce` が実行前に停止する（評価用参考画像は指標のみ保存されるため可）。

## ArtCraft
- 公式リリースの固定版と SHA256、公式ソースにある CLI・MCP 操作を確認。
- [ArtCraft CPU #46035241208](https://github.com/koda24-cell/koda24-cell-illustration-ai-studio/actions/runs/46035241208) で両エンジンの並列実行、CLI バージョン照合、MCP スキーマ取得と編集、配布アーカイブおよび展開済みファイルの ClamAV 検査を確認。
- PhotoCraft は 64×48 PNG と .pcraft、VectorCraft は 96×96 PNG・SVG と .vectorcraft を生成。両方で保存後の再読み込みと PNG の画素一致を確認。PhotoCraft のレイヤーマスクが再読み込み後も維持された。
- 実際の成果物を入力して既存の制作確認サイトをローカルでビルドし、加工前後比較 PNG と編集形式のコピーを確認。本番の掲載は main の Actions で確認する。
- 既存テスト 49 件と費用ルール検査はローカルで合格。実装と未統合の範囲は [ARTCRAFT.md](ARTCRAFT.md)。

## ArtCraft の途中評価と形式試験

[Actions #46037538290](https://github.com/koda24-cell/koda24-cell-illustration-ai-studio/actions/runs/46037538290) で PhotoCraft の色差が 118.33 から 6.67 へ3回のMCP修正で減少。VectorCraft は塗りと移動を別の反復で選択し、目標色・目標座標に到達。両案の途中PNGと判定ログを保存。PSD/PSB/PDFを出力し、それぞれを開いてPNG出力を確認。
