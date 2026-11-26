"""生成バックエンド。

- procedural : テスト専用。モデルを使わず、seed とパラメータから決定的な模様画像を作る。
               パイプライン・評価・保存・再開の動作確認用であり「AI生成」ではない。
- diffusers  : 許可リストのモデルだけを読み込む本番バックエンド（CPU）。
"""
from __future__ import annotations

from typing import Any, Protocol

from PIL import Image

PRIMITIVE_OPS = {"txt2img", "img2img", "inpaint"}


class Backend(Protocol):
    name: str

    def run(self, op: str, params: dict[str, Any], inputs: dict[str, Image.Image]) -> Image.Image: ...

    def describe(self) -> dict[str, Any]: ...


def get_backend(name: str, allowlist: Any = None, job: dict | None = None) -> Backend:
    if name == "procedural":
        from .procedural import ProceduralBackend
        return ProceduralBackend()
    if name == "diffusers":
        from .diffusers_backend import DiffusersBackend
        return DiffusersBackend(allowlist, job or {})
    raise ValueError(f"unknown backend: {name}")
