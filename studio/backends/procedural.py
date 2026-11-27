"""テスト専用バックエンド（モデル不使用）。出力は抽象的な模様で、イラストではない。"""
from __future__ import annotations

import hashlib
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from ..imageops import to_rgb


def _rng(params: dict[str, Any]) -> np.random.Generator:
    key = f"{params.get('seed', 0)}|{params.get('prompt', '')}".encode()
    return np.random.default_rng(int(hashlib.sha256(key).hexdigest()[:12], 16))


def _pattern(params: dict[str, Any]) -> Image.Image:
    w, h = int(params.get("width", 256)), int(params.get("height", 256))
    rng = _rng(params)
    prompt = str(params.get("prompt", "")).lower()
    sat = 0.35 + (0.4 if "vibrant" in prompt else 0) - (0.25 if "muted" in prompt else 0)
    sat += (float(params.get("cfg", 7)) - 7) * 0.03
    bright = 0.55 + (0.2 if "bright" in prompt else 0) - (0.2 if "dark" in prompt else 0)
    img = Image.new("HSV", (w, h), (int(rng.integers(0, 255)), int(np.clip(sat, 0, 1) * 255), int(bright * 255)))
    d = ImageDraw.Draw(img)
    for _ in range(int(params.get("steps", 20)) // 2 + 4):
        x0, y0 = int(rng.integers(0, w)), int(rng.integers(0, h))
        r = int(rng.integers(w // 16, w // 4))
        col = (int(rng.integers(0, 255)), int(np.clip(sat + rng.normal(0, .1), 0, 1) * 255),
               int(np.clip(bright + rng.normal(0, .2), 0, 1) * 255))
        d.ellipse([x0 - r, y0 - r, x0 + r, y0 + r], fill=col,
                  outline=(0, 0, 20) if "lineart" in prompt or "outline" in prompt else None,
                  width=max(1, w // 128))
    out = img.convert("RGB")
    if "blurry" in str(params.get("negative_prompt", "")):
        out = out.filter(ImageFilter.SHARPEN)
    return out


class ProceduralBackend:
    name = "procedural"

    def describe(self) -> dict[str, Any]:
        return {"backend": "procedural", "warning": "テスト専用。AIモデルは使用していません"}

    def run(self, op: str, params: dict[str, Any], inputs: dict[str, Image.Image]) -> Image.Image:
        if params.get("sleep_seconds"):  # 長時間生成の模擬（引き継ぎ・再開の検証用）
            import time
            time.sleep(min(float(params["sleep_seconds"]), 600))
        gen = _pattern(params)
        if op == "txt2img":
            return gen
        init = to_rgb(inputs["init"]).resize(gen.size)
        if op == "img2img":
            return Image.blend(init, gen, float(params.get("denoise", 0.5)))
        if op == "inpaint":
            mask = inputs["mask"].convert("L").resize(gen.size)
            return Image.composite(gen, init, mask)
        raise ValueError(op)
