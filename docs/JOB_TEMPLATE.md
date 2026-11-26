# 制作指示テンプレート

GPT・Claude・ユーザーの誰が書いても同じ形式。`jobs/` に YAML で保存し、`python -m studio job-validate` で確認してから `produce` で実行します。

## 依頼文テンプレート（チャットで AI に渡す用）
```
【制作依頼】
- 作品・用途: （例: コタマのぼうけん / 主人公の立ち絵）
- 内容: （キャラ・ポーズ・表情・衣装・背景など）
- 使用モデル: （許可リストのID。未指定なら「許可済みから選択」）
- 参考画像: （許可リストのID。公開可否）
- サイズ・枚数: （例: 512x768, 候補3枚×最大6ラウンド）
- 時間予算: （分, 最大345）
- 重視する評価: （色彩/線画/構図/一貫性 など）
- 割当先（予定）: （例: kotama-no-bouken:hero_standing）
```

## ジョブ YAML の書式
```yaml
job_id: kotama-hero-standing-v1      # 英小文字・数字・._-
title: コタマ 主人公立ち絵
backend: diffusers                    # 本番。procedural はテスト専用（AI 不使用）
time_budget_minutes: 120              # ≤345
publish: true                         # サイト掲載（非公開入力の派生物は自動で非掲載）
assign_to: {project: kotama-no-bouken, targets: ["hero_standing"]}   # 使用予定（採用ではない）
limits:
  max_rounds: 6                       # 改善ラウンド上限
  candidates_per_round: 3             # 1ラウンドの候補数
  patience: 2                         # 改善しないラウンドが続いたら終了
  target_score: 0.8                   # 到達したら早期終了
  max_error_retries: 3                # ≤3
  vary_seeds: false                   # true でラウンドごとに seed を変える
defaults:                             # 全ステージ共通の生成設定
  model: auto                         # 許可済み checkpoint の ID か auto
  purpose: [anime, character]         # auto 時の選択ヒント（台帳 strengths と照合）
  loras: [{id: my-style-lora, weight: 0.7}]
  width: 512
  height: 768
  steps: 24
  cfg: 7
  scheduler: euler_a                  # euler_a / euler / dpmpp_2m / dpmpp_2m_karras / ddim / unipc
  negative_prompt: "lowres, bad anatomy"
evaluation:
  references: ["images:kotama-ref-01"]
  metrics: [color, value_saturation, lineart, shading, composition, similarity, artifacts, consistency]
  weights: {color: 1.5}
improve: {enabled: true, tune: [cfg, steps, denoise, prompt]}
recipe:                               # または stages: [...] を直接書く
  type: character_standing
  prompt: "1girl, kotama, green cloak, smile"
  hires_scale: 1.5
  transparent: true
```

## 参照の書き方
- `images:<id>` … 許可リストの画像
- `stage:<name>` … 同じランの前のステージのベスト
- `run:<run_id>/<stage>` … 過去ランのベスト（このリポジトリの生成物）
URL や任意のファイルパスは指定できません。

## テンプレート集
`jobs/templates/` に各レシピの雛形があります（モデルIDは仮。実行前に許可済みIDへ置換）。

## 以前の設定の再利用
```bash
python -m studio rerun runs/<run_id>/stages/<stage>/r02_c1.json --job-id reuse-1 --out jobs/reuse-1.yaml
```
サイトの「設定をコピー」「ジョブをコピー」でも取得できます。
