# jobs/queue — プッシュで制作開始

ここに制作指示 YAML（書式は docs/JOB_TEMPLATE.md）を追加・更新して push すると、
`studio-push` ワークフローが共通 Docker イメージでその YAML を実行します（どのブランチでも可）。

- 1回の push で複数ファイルを追加した場合は順番に実行（並列 1）。
- 制作結果は `studio-runs` ブランチと制作確認サイトに保存。main への取り込みは PR。
- 同じ YAML を再実行したいときは、末尾にコメント行を足すなど内容を変更して push。
- README.md や .yaml 以外は実行対象外。
