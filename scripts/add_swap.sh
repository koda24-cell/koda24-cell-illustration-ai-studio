#!/usr/bin/env bash
# SDXL(fp32) は約13GBのメモリを使うため、一時ランナーにスワップを追加して OOM による強制終了を防ぐ。
set -eu
size_gb="${1:-12}"
free -m
if [ ! -f /mnt/studio.swap ]; then
  sudo fallocate -l "${size_gb}G" /mnt/studio.swap
  sudo chmod 600 /mnt/studio.swap
  sudo mkswap /mnt/studio.swap >/dev/null
  sudo swapon /mnt/studio.swap
fi
free -m
