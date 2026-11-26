#!/usr/bin/env bash
# ClamAV を導入し定義を更新する。更新できなければ失敗（fail closed）。
# 定義DBは actions/cache で /var/lib/clamav を日次復元し、freshclam は差分更新のみ（配布元への負荷軽減）。
set -euo pipefail
if ! command -v clamscan >/dev/null; then
  sudo apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq clamav clamav-freshclam >/dev/null
fi
sudo systemctl stop clamav-freshclam 2>/dev/null || true
sudo mkdir -p /var/lib/clamav && sudo chown -R clamav:clamav /var/lib/clamav 2>/dev/null || true
ok=0
for i in 1 2 3; do
  set +e; sudo freshclam --stdout; rc=$?; set -e
  # 0=更新成功 1=最新
  if [ "$rc" = "0" ] || [ "$rc" = "1" ]; then ok=1; break; fi
  echo "freshclam failed (rc=$rc), retry $i/3"; sleep $((20 * i))
done
if [ "$ok" != "1" ]; then
  echo "::error::ClamAV definitions could not be updated -> BLOCKED_UNSCANNED"; exit 1
fi
sudo chmod -R a+rX /var/lib/clamav
clamscan --version
