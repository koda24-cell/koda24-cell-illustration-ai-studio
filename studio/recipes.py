"""制作目的別レシピ → ステージ列への展開。

レシピは「プリミティブ操作の組み合わせ」の定型であり、新しいモデルを追加しない。
必要なモデル（ControlNet 等）がジョブで指定されていなければ、そのモデルを使わない代替手段を選ぶか、
代替が無い場合は DEPENDENCY_MISSING として止める。
"""
from __future__ import annotations

import copy
from typing import Any

from .util import StudioError

GENERATIVE_OPS = {"txt2img", "img2img", "inpaint", "outpaint", "hires_upscale"}
MODEL_FREE_OPS = {"remove_bg", "replace_bg", "upscale", "upscale_model", "lineart_extract", "control_from"}
ALL_OPS = GENERATIVE_OPS | MODEL_FREE_OPS


def _p(prompt: str, *extra: str) -> str:
    parts = [prompt] + [e for e in extra if e]
    return ", ".join(x.strip(", ") for x in parts if x)


def expand(recipe: dict[str, Any]) -> list[dict[str, Any]]:
    r = copy.deepcopy(recipe)
    kind = r.pop("type")
    prompt = r.get("prompt", "")
    base_ref = r.get("base")  # 既存画像（images:/stage:/run:）から差分を作る場合
    st: list[dict[str, Any]] = []

    def base_stage(extra: str, **kw: Any) -> str:
        if base_ref:
            return base_ref
        st.append({"name": "base", "op": "txt2img", "prompt": _p(prompt, extra), **kw})
        return "stage:base"

    if kind == "character_standing":
        b = base_stage("full body, standing, simple background, white background")
        if r.get("hires_scale"):
            st.append({"name": "hires", "op": "hires_upscale", "init": b, "scale": r["hires_scale"],
                       "denoise": r.get("hires_denoise", 0.3), "prompt": _p(prompt, "full body")})
            b = "stage:hires"
        if r.get("transparent", True):
            st.append({"name": "transparent", "op": "remove_bg", "init": b})
    elif kind == "expression_variants":
        b = base_stage("upper body, portrait, simple background")
        rect = r.get("face_rect") or [0.3, 0.05, 0.4, 0.3]
        for i, ex in enumerate(r.get("expressions") or []):
            st.append({"name": f"expr_{i}", "op": "inpaint", "init": b, "mask": {"rect": rect},
                       "prompt": _p(prompt, ex), "denoise": r.get("denoise", 0.55), "consistency_base": b})
    elif kind == "outfit_variants":
        b = base_stage("full body, standing, simple background")
        rect = r.get("body_rect") or [0.15, 0.25, 0.7, 0.7]
        for i, of in enumerate(r.get("outfits") or []):
            st.append({"name": f"outfit_{i}", "op": "inpaint", "init": b, "mask": {"rect": rect},
                       "prompt": _p(prompt, of), "denoise": r.get("denoise", 0.75), "consistency_base": b})
    elif kind == "pose_variants":
        b = base_stage("full body, standing, simple background")
        for i, pose in enumerate(r.get("poses") or []):
            s: dict[str, Any] = {"name": f"pose_{i}", "prompt": _p(prompt, pose.get("prompt", "")),
                                 "consistency_base": b}
            if pose.get("control_image") and r.get("controlnet"):
                s.update(op="txt2img", controlnet={**r["controlnet"], "image": pose["control_image"]})
                if r.get("ip_adapter"):
                    s["ip_adapter"] = {**r["ip_adapter"], "image": b}
            else:
                # ControlNet 未指定時の代替：元絵から img2img（ポーズ変更の自由度は低い）
                s.update(op="img2img", init=b, denoise=r.get("denoise", 0.65))
            st.append(s)
    elif kind == "turnaround":
        s = {"name": "turnaround", "op": "txt2img",
             "prompt": _p(prompt, "character turnaround, reference sheet, front view, side view, back view, "
                                  "multiple views, same character, full body, white background"),
             "width": r.get("width", 1024), "height": r.get("height", 512)}
        if r.get("controlnet") and r.get("control_image"):
            s["controlnet"] = {**r["controlnet"], "image": r["control_image"]}
        st.append(s)
    elif kind == "lineart":
        st.append({"name": "lineart_gen", "op": "txt2img",
                   "prompt": _p(prompt, "lineart, monochrome, greyscale, white background, clean lines")})
        st.append({"name": "lineart_clean", "op": "lineart_extract", "init": "stage:lineart_gen"})
    elif kind == "colorize":
        src = r.get("lineart") or base_ref
        if not src:
            raise StudioError("BAD_INPUT", "colorize には lineart（images:<id> 等）が必要")
        if r.get("controlnet"):
            st.append({"name": "colorize", "op": "txt2img", "prompt": _p(prompt, "colored, flat colors"),
                       "controlnet": {**r["controlnet"], "image": src}})
        else:
            st.append({"name": "colorize", "op": "img2img", "init": src, "prompt": _p(prompt, "colored"),
                       "denoise": r.get("denoise", 0.75)})
    elif kind == "background":
        st.append({"name": "background", "op": "txt2img", "prompt": _p(prompt, "scenery, no humans, background"),
                   "width": r.get("width", 768), "height": r.get("height", 512)})
    elif kind == "event_still":
        s = {"name": "event", "op": "txt2img", "prompt": _p(prompt, "cinematic composition, detailed background"),
             "width": r.get("width", 768), "height": r.get("height", 512)}
        if r.get("ip_adapter") and r.get("character_ref"):
            s["ip_adapter"] = {**r["ip_adapter"], "image": r["character_ref"]}
        st.append(s)
    elif kind == "replace_background":
        src = base_ref or r.get("image")
        st.append({"name": "cutout", "op": "remove_bg", "init": src})
        if r.get("background"):
            st.append({"name": "composite", "op": "replace_bg", "init": "stage:cutout", "background": r["background"]})
        else:
            st.append({"name": "new_bg", "op": "txt2img", "prompt": _p(r.get("background_prompt", ""),
                                                                       "scenery, no humans")})
            st.append({"name": "composite", "op": "replace_bg", "init": "stage:cutout", "background": "stage:new_bg"})
    else:
        raise StudioError("BAD_INPUT", f"未知のレシピ: {kind}")

    common = r.get("stage_defaults") or {}
    return [{**common, **s} for s in st]
