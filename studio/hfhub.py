"""Hugging Face 上の依存ファイル（構成ファイル・画像エンコーダ等）の登録下書き。

ユーザーが承認した repo とファイルだけを、コミット固定・SHA256固定で下書きにする。
ここでのダウンロードは SHA256 計算のためだけ（保存しない）。実使用時は fetch.py が改めて取得・ClamAV 検査する。
"""
from __future__ import annotations

import hashlib
import os
import time
from typing import Any

import requests

from .util import StudioError

UA = "illustration-ai-studio/0.1 (+allowlist-only)"

SDXL_CONFIG_FILES = [
    "model_index.json", "scheduler/scheduler_config.json",
    "text_encoder/config.json", "text_encoder_2/config.json",
    "tokenizer/merges.txt", "tokenizer/special_tokens_map.json", "tokenizer/tokenizer_config.json",
    "tokenizer/vocab.json",
    "tokenizer_2/merges.txt", "tokenizer_2/special_tokens_map.json", "tokenizer_2/tokenizer_config.json",
    "tokenizer_2/vocab.json",
    "unet/config.json", "vae/config.json",
]
SD15_CONFIG_FILES = [
    "model_index.json", "scheduler/scheduler_config.json", "text_encoder/config.json",
    "tokenizer/merges.txt", "tokenizer/special_tokens_map.json", "tokenizer/tokenizer_config.json",
    "tokenizer/vocab.json", "unet/config.json", "vae/config.json",
]
PRESETS = {"sdxl-config": SDXL_CONFIG_FILES, "sd15-config": SD15_CONFIG_FILES}
MAX_DRAFT_FILE = 50 * 1024 * 1024  # 下書き時のハッシュ計算は小さなファイルのみ


def _headers() -> dict[str, str]:
    h = {"User-Agent": UA}
    if os.environ.get("HF_TOKEN"):
        h["Authorization"] = f"Bearer {os.environ['HF_TOKEN']}"
    return h


def resolve_revision(repo: str, revision: str = "main") -> str:
    r = requests.get(f"https://huggingface.co/api/models/{repo}/revision/{revision}", headers=_headers(), timeout=60)
    if r.status_code != 200:
        raise StudioError("NOT_FOUND", f"HF: {repo}@{revision} を解決できません ({r.status_code})")
    return r.json()["sha"]


def file_sha256(repo: str, revision: str, path: str) -> tuple[str, int]:
    url = f"https://huggingface.co/{repo}/resolve/{revision}/{path}"
    h = hashlib.sha256()
    n = 0
    for attempt in range(3):
        try:
            with requests.get(url, headers=_headers(), stream=True, timeout=120) as r:
                r.raise_for_status()
                for chunk in r.iter_content(1024 * 1024):
                    n += len(chunk)
                    if n > MAX_DRAFT_FILE:
                        raise StudioError("BAD_INPUT", f"{path} は大きすぎます（下書きは構成ファイル等の小ファイル用）")
                    h.update(chunk)
            return h.hexdigest(), n
        except StudioError:
            raise
        except Exception as e:  # noqa: BLE001
            if attempt == 2:
                raise StudioError("NETWORK", f"HF 取得失敗 {path}: {e}") from e
            h, n = hashlib.sha256(), 0
            time.sleep(5)
    raise AssertionError


def build_entry_draft(repo: str, files: list[str], kind: str, entry_id: str, instruction: str,
                      revision: str = "main", arch: str | None = None) -> dict[str, Any]:
    rev = revision if len(revision) == 40 else resolve_revision(repo, revision)
    out_files = []
    for fpath in files:
        sha, size = file_sha256(repo, rev, fpath)
        out_files.append({"filename": fpath.replace("/", "__"), "repo_path": fpath, "sha256": sha,
                          "size_bytes": size})
    entry: dict[str, Any] = {
        "id": entry_id, "kind": kind, "source": "huggingface",
        "url": f"https://huggingface.co/{repo}/tree/{rev}",
        "huggingface": {"repo": repo, "revision": rev},
        "name": f"{repo} ({kind})", "files": out_files,
        "added_by_user_instruction": instruction, "added_at": time.strftime("%Y-%m-%d"),
    }
    if arch:
        entry["arch"] = arch
    return entry
