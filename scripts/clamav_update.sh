#!/usr/bin/env bash
# コンテナ内で ClamAV 定義を更新（イメージに初期DBあり→差分更新）。失敗したら停止（fail closed）。
set -uo pipefail
for i in 1 2 3; do
  freshclam --stdout; rc=$?
  if [ "$rc" = "0" ] || [ "$rc" = "1" ]; then clamscan --version; exit 0; fi
  echo "freshclam failed (rc=$rc), retry $i/3"; sleep $((20 * i))
done
echo "ClamAV definitions could not be updated -> BLOCKED_UNSCANNED"; exit 1
