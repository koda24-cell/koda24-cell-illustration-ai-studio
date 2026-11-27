#!/usr/bin/env bash
# 途中保存：studio-runs ブランチの作業ツリー（STUDIO_RUNS_REPO）をコミットして push する。
# 既存データは削除・強制上書きしない（--force 不使用）。競合時は rebase して再試行（最大3回）。
set -u
repo="${STUDIO_RUNS_REPO:?}"
run_dir="${1:-}"
cd "$repo" || exit 1
# コンテナ内でも rebase/commit できるよう識別情報を環境変数で与える
export GIT_AUTHOR_NAME="studio-bot" GIT_COMMITTER_NAME="studio-bot"
export GIT_AUTHOR_EMAIL="41898282+github-actions[bot]@users.noreply.github.com" GIT_COMMITTER_EMAIL="41898282+github-actions[bot]@users.noreply.github.com"
git add -A
if git diff --cached --quiet; then exit 0; fi
git -c user.name="studio-bot" -c user.email="41898282+github-actions[bot]@users.noreply.github.com" \
  commit -q -m "checkpoint: $(basename "${run_dir:-run}") $(date -u +%FT%TZ)" || exit 1
for i in 1 2 3; do
  if git push -q origin HEAD:studio-runs; then exit 0; fi
  git pull -q --rebase origin studio-runs || true
  sleep $((5 * i))
done
echo "checkpoint push failed" >&2
exit 1
