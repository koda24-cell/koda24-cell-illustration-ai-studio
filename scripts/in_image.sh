#!/usr/bin/env bash
# 共通イメージ内でコマンドを実行する（リポジトリを /work にマウント）。
# 使い方: STUDIO_IMAGE=ghcr.io/...@sha256:... bash scripts/in_image.sh python -m studio doctor
set -euo pipefail
img="${STUDIO_IMAGE:?STUDIO_IMAGE が未設定}"
ws="${GITHUB_WORKSPACE:-$PWD}"
envs=()
for n in GITHUB_TOKEN GITHUB_REPOSITORY GITHUB_OUTPUT_IN GITHUB_RUN_ID GITHUB_SERVER_URL \
         CIVITAI_API_TOKEN HF_TOKEN STUDIO_INPUT_KEY STUDIO_RUNS_REPO STUDIO_RUNS_DIR STUDIO_LEDGER_FILE \
         STUDIO_CHECKPOINT_CMD STUDIO_CHECKPOINT_INTERVAL_SEC STUDIO_ACTIONS_RUN_URL STUDIO_RUNTIME HF_HUB_OFFLINE; do
  [ -n "${!n:-}" ] && envs+=(-e "$n")
done
exec docker run --rm --init -v "$ws:/work" -w /work \
  -e STUDIO_CACHE=/work/.cache/studio -e GITHUB_OUTPUT=/work/.gh_output \
  -e GIT_CONFIG_COUNT=1 -e GIT_CONFIG_KEY_0=safe.directory -e GIT_CONFIG_VALUE_0='*' \
  "${envs[@]}" "$img" "$@"
