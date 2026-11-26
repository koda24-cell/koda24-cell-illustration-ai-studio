# 制作計画: Obsession 編集機能の検証（透過・表情差分・img2img・Outpaint）

- run_id: `obsession-feature-check-20261126-175348`
- backend: `diffusers`
- 時間予算: 330.0 分 / 上限ラウンド 2 / 候補数 2 / 目標スコア 1.5
- 使用モデル（許可リスト内）: obsession-illustrious-xl-v-pred-v1-1, sdxl-base-1-0-config
- 評価用参考画像: なし

## ステージ
- **cutout** `remove_bg` 入力: run:obsession-bench-fp32-20261126-155303/standing
- **expression_laugh** `inpaint` 入力: run:obsession-bench-fp32-20261126-155303/standing
- **autumn_variant** `img2img` 入力: run:obsession-bench-fp32-20261126-155303/standing
- **wider** `outpaint` 入力: stage:cutout

自動評価は改善の参考値であり、最終的な採用判断はユーザーが行う。
