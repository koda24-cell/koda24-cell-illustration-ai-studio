# 制作計画: 自己診断（モデル不使用）

- run_id: `selftest-procedural-20261126-143811`
- backend: `procedural`
- 時間予算: 10.0 分 / 上限ラウンド 3 / 候補数 2 / 目標スコア 1.01
- 使用モデル（許可リスト内）: なし
- 評価用参考画像: なし

## ステージ
- **base** `txt2img` 
- **variant** `inpaint` 入力: stage:base
- **wider** `outpaint` 入力: stage:base
- **hires** `hires_upscale` 入力: stage:base
- **cutout** `remove_bg` 入力: stage:base
- **lineart** `lineart_extract` 入力: stage:base
- **big** `upscale` 入力: stage:base
- **bg** `txt2img` 
- **composite** `replace_bg` 入力: stage:cutout

自動評価は改善の参考値であり、最終的な採用判断はユーザーが行う。
