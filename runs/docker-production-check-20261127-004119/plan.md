# 制作計画: 共通Docker環境の実制作確認（連続生成→表情差分→透過）

- run_id: `docker-production-check-20261127-004119`
- backend: `diffusers`
- 時間予算: 330.0 分 / 上限ラウンド 1 / 候補数 2 / 目標スコア 1.5
- 使用モデル（許可リスト内）: obsession-illustrious-xl-v-pred-v1-1, sdxl-base-1-0-config
- 評価用参考画像: なし

## ステージ
- **hero** `txt2img` 
- **expression_surprised** `inpaint` 入力: stage:hero
- **cutout** `remove_bg` 入力: stage:hero

自動評価は改善の参考値であり、最終的な採用判断はユーザーが行う。
