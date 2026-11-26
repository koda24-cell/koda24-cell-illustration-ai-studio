#!/usr/bin/env bash
# 一時ランナー上の未使用ツールチェーンを削除して空き容量を確保（ユーザーデータではない）。
set -eu
df -h / | tail -1
sudo rm -rf /usr/share/dotnet /usr/local/lib/android /opt/ghc /opt/hostedtoolcache/CodeQL /usr/local/share/boost 2>/dev/null || true
sudo docker image prune -af >/dev/null 2>&1 || true
df -h / | tail -1
