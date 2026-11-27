#!/usr/bin/env bash
# Stdio server for a Docker host controlled by the MCP client.
set -euo pipefail
engine=${1:?Specify photocraft or vectorcraft}
image=${2:?Specify the published ArtCraft image digest}
workspace=${3:?Specify an absolute workspace path}
case "$engine" in
  photocraft) flags=() ;;
  vectorcraft) flags=(--headless) ;;
  *) exit 2 ;;
esac
[[ "$image" =~ ^ghcr\.io/koda24-cell/illustration-ai-studio-cpu@sha256:[0-9a-f]{64}$ ]]
[[ "$workspace" = /* && -d "$workspace" ]]
exec docker run --rm --init -i --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --user "$(id -u):$(id -g)" \
  --tmpfs /tmp:rw,nosuid,nodev,size=64m -e HOME=/tmp \
  --mount "type=bind,src=$workspace,dst=/project" -w /project "$image" \
  sh -ec '
    binary=$(find "/opt/artcraft/$1" -type f -path "*/bin/$1-cli" -print)
    test -x "$binary"
    shift
    exec "$binary" mcp "$@" --automation-read-root /project --automation-write-root /project
  ' sh "$engine" "${flags[@]}"
