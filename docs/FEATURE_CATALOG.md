# 機能カタログ

状態の凡例: **✅ 実動作確認済み**（テスト/Actions ログあり） / **🟡 実装済み・未検証**（コードあり、許可モデルでの実行待ち） / **⛔ 未実装**（理由を記載）
証拠は [VERIFICATION.md](VERIFICATION.md)。モデルを使う機能は、ユーザーがモデルを指定するまで検証できません。

実行方法は共通で、ジョブ YAML の `stages`（プリミティブ操作）か `recipe`（制作目的別の定型）に書き、
`produce` ワークフロー（または `python -m studio run <job.yaml>`）で実行します。テンプレートは `jobs/templates/`。

## プリミティブ操作（op）
| 機能 | op | 必要なモデル（許可リスト） | 必要な入力 | 状態 |
|---|---|---|---|---|
| テキストから画像生成 | `txt2img` | checkpoint ＋ pipeline_config（構成ファイル） | prompt | 🟡 |
| 参考画像からの生成 | `img2img` | 同上 | `init`（images:/stage:/run:）, `denoise` | 🟡 |
| 既存イラストの編集 | `img2img` / `inpaint` | 同上 | `init` ＋ prompt | 🟡 |
| 部分修正 Inpaint | `inpaint` | 同上（inpaint 専用 checkpoint があれば望ましい） | `init`, `mask`（`{rect:[x,y,w,h]}` 比率 or images:） | 🟡 |
| 描画範囲の拡張 Outpaint | `outpaint` | 同上 | `init`, `outpaint:{left,top,right,bottom}`(px) | 🟡（余白生成とマスクは ✅） |
| 高解像度化（モデル不要） | `upscale` | なし（Lanczos） | `init`, `scale` | ✅ |
| 高解像度化（Hires 再描画） | `hires_upscale` | checkpoint | `init`, `scale`, `denoise`≈0.3 | 🟡 |
| 高解像度化（専用モデル） | `upscale_model` | upscaler（ESRGAN系 safetensors, spandrel） | `init`, `upscaler` | 🟡 |
| 背景透過 | `remove_bg` | なし（外周連結の単色背景キー） | `init`, `tolerance` | ✅（単色背景向け。複雑背景は限界あり） |
| 背景の変更 | `replace_bg` | なし（合成）/ 新背景生成時は checkpoint | `init`(透過画像), `background` | ✅（合成部分） |
| 線画の抽出 | `lineart_extract` | なし（XDoG） | `init` | ✅ |
| ControlNet 入力作成 | `control_from` / `controlnet.preprocess` | なし（canny / lineart） | 画像 | ✅ |
| LoRA による絵柄調整 | 各生成 op の `loras:[{id,weight}]` | lora / lycoris | — | 🟡（LyCORIS は diffusers 対応範囲のみ） |
| Embedding | `embeddings:[id]` | embedding | — | 🟡 |
| VAE 差し替え | `vae: id` | vae | — | 🟡 |
| ControlNet 構図・ポーズ制御 | `controlnet:{id,image,scale,preprocess}` | controlnet（＋単一ファイルなら `config_entry`） | 制御画像（role: control） | 🟡 |
| IP-Adapter 参考特徴反映 | `ip_adapter:{id,image_encoder,image,scale}` | ip_adapter ＋ image_encoder | 参考画像（role: reference） | 🟡 |
| 複数候補の生成 | `limits.candidates_per_round` | — | — | ✅（procedural で確認） |

## 制作目的別レシピ（recipe.type）
| 機能 | type | 展開されるステージ | 追加で使うと良いモデル | 状態 |
|---|---|---|---|---|
| キャラクター立ち絵 | `character_standing` | txt2img →（hires）→ 背景透過 | — | 🟡 |
| 表情差分 | `expression_variants` | 顔矩形を inpaint（同一seed・一貫性評価） | inpaint 向け checkpoint | 🟡 |
| 衣装差分 | `outfit_variants` | 体の矩形を inpaint | — | 🟡 |
| ポーズ差分 | `pose_variants` | ControlNet あり: 制御画像で txt2img(+IP-Adapter) / なし: img2img（自由度低） | controlnet(openpose 等), ip_adapter | 🟡 |
| キャラクター三面図 | `turnaround` | 横長 txt2img（＋三面図テンプレの ControlNet） | controlnet | 🟡（モデル依存が大きい） |
| 線画の生成 | `lineart` | 線画プロンプトで txt2img → XDoG 整形 | 線画 LoRA | 🟡 |
| 線画からの着彩 | `colorize` | ControlNet(lineart) txt2img / なし: img2img | controlnet(lineart) | 🟡 |
| 背景イラスト | `background` | 横長 txt2img（no humans） | 背景向け checkpoint/LoRA | 🟡 |
| イベントスチル | `event_still` | 横長 txt2img（＋IP-Adapter でキャラ参照） | ip_adapter | 🟡 |
| 背景差し替え | `replace_background` | 透過 → 既存背景 or 新規背景と合成 | — | 🟡（合成は ✅） |

## 長時間制作・自動改善（session）
| 機能 | 状態 |
|---|---|
| 制作計画の作成（`plan.md`） | ✅ |
| 複数候補 → 評価 → ベスト選択 | ✅ |
| 参考画像との比較評価 | ✅ |
| プロンプト改善（ルール表 `config/improvement_rules.yaml` のタグのみ追加/削除） | ✅ |
| パラメータ調整（cfg / steps / denoise を範囲内で） | ✅ |
| 修正・再生成、改善前後の比較画像 | ✅ |
| 良好な候補の保存（`best.png`）・途中保存（studio-runs へ push）・中断後の再開 | ✅（再開はテスト、push は Actions で確認） |
| エラー原因の分析（`errors.jsonl`）・最大3回の復旧（OOM時は解像度縮小） | ✅ |
| 停止条件: 目標到達 / 改善停滞 / 上限ラウンド / 時間予算（≤345分） | ✅ |

## 評価（studio/evaluate.py）
| 観点 | 方法 | 状態 |
|---|---|---|
| 参考画像との類似性 | SSIM(128px)＋dHash | ✅ |
| 色彩 / 明度・彩度 | 色ヒストグラム重なり / 平均・分散 | ✅ |
| 線画 | エッジ密度・強度 | ✅（線の美しさは判定不可） |
| 陰影 | 明度ヒストグラム | ✅（光源の正しさは判定不可） |
| 構図 | 視覚的重心 | ✅（主題認識なし） |
| 画像の破綻 | 空白・白飛び・高周波ノイズの兆候 | ✅（手指・人体の破綻は検出不可） |
| キャラクターの一貫性 | 差分元との配色の近さ（代理指標） | ✅（顔の同一性は不可） |
| 絵柄・塗り方（意味的） | 許可済み CLIP 系評価モデル | ⛔ 評価モデル未指定（コード側は差し込み口のみ） |
| ポーズ・人体のバランス | 姿勢推定モデルが必要 | ⛔ 評価モデル未指定（「評価不能」と記録） |
| 改善前後の品質比較 | 指標差分（`vs_first`） | ✅ |

全指標に「根拠」と「限界」を記録し、数値だけで美術的完成度を断定しません。最終判断はユーザー。

## 未採用・代替
- **Stable Diffusion WebUI（A1111/Forge）**: 起動時に既定モデルを自動ダウンロードする挙動があり許可リスト制と衝突、かつ GUI 前提で Actions 向きでないため、**同等機能を Diffusers の CLI 実装で代替**。
- **Stability Matrix**: GUI のモデル管理ツール。**許可リスト＋台帳＋取得/検査/キャッシュ（`studio` CLI）で代替**。
- **Flux / SD3 系**: CPU で 1 枚に数十分〜以上かかり実用外のため未対応。
