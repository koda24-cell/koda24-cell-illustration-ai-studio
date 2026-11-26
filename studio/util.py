"""共通ユーティリティ（標準ライブラリ + PyYAML のみ）。"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")


class StudioError(Exception):
    """利用者に見せる想定のエラー。code は ERROR_RUNBOOK.md の分類に対応。"""

    def __init__(self, code: str, message: str):
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def today() -> str:
    return _dt.date.today().isoformat()


def sha256_file(path: str | os.PathLike, chunk: int = 4 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_yaml(path: str | os.PathLike, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    with open(p, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return default if data is None else data


def dump_yaml(path: str | os.PathLike, data: Any) -> None:
    text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120)
    atomic_write_text(path, text)


def load_json(path: str | os.PathLike, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def dump_json(path: str | os.PathLike, data: Any) -> None:
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def atomic_write_text(path: str | os.PathLike, text: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".tmp-", suffix=p.suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, p)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def append_jsonl(path: str | os.PathLike, record: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def cache_dir() -> Path:
    """大容量モデルの置き場所。Git管理外。Actionsでは actions/cache で復元する。"""
    return Path(os.environ.get("STUDIO_CACHE", REPO_ROOT / ".cache" / "studio")).resolve()


def mask_secret(text: str) -> str:
    for key in ("CIVITAI_API_TOKEN", "STUDIO_INPUT_KEY", "GITHUB_TOKEN"):
        val = os.environ.get(key)
        if val and len(val) >= 6:
            text = text.replace(val, "***")
    return re.sub(r"(token=)[^&\s]+", r"\1***", text)
