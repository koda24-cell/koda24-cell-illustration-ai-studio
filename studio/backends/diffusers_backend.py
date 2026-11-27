"""Diffusers による CPU 生成バックエンド。

許可リスト外のファイルを読まないための対策:
  - モデルは許可リストの ID でのみ指定。パスや URL は受け付けない。
  - 読込前に SHA256・安全検査記録を照合（fetch.verify_cached）。
  - HF_HUB_OFFLINE=1 / local_files_only=True で、Diffusers が裏で構成ファイルや
    セーフティチェッカー等をダウンロードするのを禁止する。
  - 単一ファイルの Checkpoint を読むには、アーキテクチャの構成ファイル（重みなし）が必要。
    許可リストに kind: pipeline_config が無ければ DEPENDENCY_MISSING として報告し、勝手に取得しない。
"""
from __future__ import annotations

import os
import time
from typing import Any

from PIL import Image

from .. import fetch
from ..allowlist import Allowlist
from ..util import StudioError

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("DIFFUSERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

SDXL_MARKERS = ("xl", "pony", "illustrious", "noobai", "noob")


def arch_of(base_model: str | None) -> str:
    b = (base_model or "").lower()
    if any(m in b for m in SDXL_MARKERS):
        return "sdxl"
    if b.startswith("sd 1") or b.startswith("sd1") or "1.5" in b:
        return "sd15"
    raise StudioError("UNSUPPORTED_ARCH",
                      f"base_model '{base_model}' は未対応（対応: SD1.x / SDXL系）。Flux/SD3 等は CPU では実用外のため未実装")


SCHEDULERS = {
    "euler_a": ("EulerAncestralDiscreteScheduler", {}),
    "euler": ("EulerDiscreteScheduler", {}),
    "dpmpp_2m": ("DPMSolverMultistepScheduler", {}),
    "dpmpp_2m_karras": ("DPMSolverMultistepScheduler", {"use_karras_sigmas": True}),
    "ddim": ("DDIMScheduler", {}),
    "unipc": ("UniPCMultistepScheduler", {}),
}


class DiffusersBackend:
    name = "diffusers"

    def __init__(self, allowlist: Allowlist, job: dict[str, Any]):
        import torch  # noqa: F401  遅延 import（テスト環境では不要）

        self.al = allowlist
        self.job = job
        self._base = None
        self._base_key = None
        self._loaded_loras: dict[str, float] = {}
        self._ip_loaded = None
        self._controlnets: dict[str, Any] = {}
        self.load_seconds = 0.0
        torch.set_num_threads(max(1, os.cpu_count() or 1))

    def describe(self) -> dict[str, Any]:
        import diffusers
        import torch
        cpu = ""
        try:
            cpu = next((l.split(":", 1)[1].strip() for l in open("/proc/cpuinfo") if l.startswith("model name")), "")
        except Exception:  # noqa: BLE001
            pass
        return {"backend": "diffusers", "diffusers": diffusers.__version__, "torch": torch.__version__, "cpu_model": cpu,
                "device": "cpu", "threads": torch.get_num_threads(),
                "model_load_seconds": round(self.load_seconds, 1)}

    # ---------- 読込 ----------
    def _config_dir(self, arch: str, explicit: str | None) -> str:
        if explicit:
            e = self.al.require_model(explicit, {"pipeline_config"})
        else:
            cands = [m for m in self.al.models_of("pipeline_config") if m.raw.get("arch") == arch]
            if not cands:
                raise StudioError(
                    "DEPENDENCY_MISSING",
                    f"{arch} の Checkpoint を読むための構成ファイル（pipeline_config, 重みなし）が許可リストにありません。"
                    f"勝手に追加しません。docs/MODEL_REGISTRATION.md の『必須依存』を参照し、指定してください")
            e = cands[0]
        return str(fetch.materialize_dir(e))

    def _load_base(self, p: dict[str, Any]):
        import torch
        from diffusers import StableDiffusionPipeline, StableDiffusionXLPipeline

        ckpt = self.al.require_model(p["model"], {"checkpoint"})
        key = (ckpt.id, p.get("vae"), p.get("pipeline_config"), p.get("dtype"), p.get("attention_slicing", False),
               p.get("channels_last", True))
        if self._base is not None and self._base_key == key:
            return self._base
        t0 = time.time()
        arch = arch_of(ckpt.raw.get("base_model"))
        cfg = self._config_dir(arch, p.get("pipeline_config"))
        (path,) = fetch.verify_cached(ckpt)
        cls = StableDiffusionXLPipeline if arch == "sdxl" else StableDiffusionPipeline
        dtype = {"float32": torch.float32, "bfloat16": torch.bfloat16}[p.get("dtype") or "float32"]
        self._dtype = dtype
        kw: dict[str, Any] = dict(config=cfg, local_files_only=True, torch_dtype=dtype)
        if arch == "sd15":
            kw.update(safety_checker=None, requires_safety_checker=False, load_safety_checker=False)
        if p.get("vae"):
            from diffusers import AutoencoderKL
            ve = self.al.require_model(p["vae"], {"vae"})
            (vpath,) = fetch.verify_cached(ve)
            kw["vae"] = AutoencoderKL.from_single_file(str(vpath), config=cfg, subfolder="vae",
                                                       local_files_only=True, torch_dtype=dtype)
        pipe = cls.from_single_file(str(path), **kw)
        pipe.set_progress_bar_config(disable=True)
        try:
            # 既定は実測で最速だった設定（2026-11-27, Obsession: 出力は同一で約9%高速）:
            #   attention_slicing=False（PyTorch SDPA）, channels_last=True
            if p.get("attention_slicing", False):
                pipe.enable_attention_slicing()
            if p.get("channels_last", True):
                pipe.unet.to(memory_format=torch.channels_last)
            if arch == "sdxl" and p.get("vae_tiling", True):
                pipe.enable_vae_tiling()  # CPU メモリ節約
        except Exception:  # noqa: BLE001
            pass
        # v-prediction / zero terminal SNR（Illustrious v-pred 系など）。台帳・許可リストの記載かジョブ指定に従う
        self._pred = {
            "prediction_type": p.get("prediction_type") or ckpt.raw.get("prediction_type"),
            "zero_snr": p.get("zero_terminal_snr", ckpt.raw.get("zero_terminal_snr")),
        }
        self._base, self._base_key, self._arch = pipe, key, arch
        self._loaded_loras, self._ip_loaded = {}, None
        for emb in p.get("embeddings") or []:
            self._load_embedding(pipe, emb)
        self.load_seconds += time.time() - t0
        return pipe

    def _load_embedding(self, pipe, emb_id: str) -> None:
        e = self.al.require_model(emb_id, {"embedding"})
        (path,) = fetch.verify_cached(e)
        token = e.raw.get("token") or (e.raw.get("trained_words") or [emb_id])[0]
        if self._arch == "sdxl":
            from safetensors.torch import load_file
            sd = load_file(str(path))
            pipe.load_textual_inversion(sd["clip_g"], token=token, text_encoder=pipe.text_encoder_2,
                                        tokenizer=pipe.tokenizer_2)
            pipe.load_textual_inversion(sd["clip_l"], token=token, text_encoder=pipe.text_encoder,
                                        tokenizer=pipe.tokenizer)
        else:
            pipe.load_textual_inversion(str(path), token=token)

    def _apply_loras(self, pipe, loras: list[dict[str, Any]]) -> None:
        want = {l["id"]: float(l.get("weight", 0.8)) for l in loras or []}
        for lid in want:
            if lid not in self._loaded_loras:
                e = self.al.require_model(lid, {"lora", "lycoris"})
                (path,) = fetch.verify_cached(e)
                pipe.load_lora_weights(str(path.parent), weight_name=path.name, adapter_name=lid.replace(".", "_"))
                self._loaded_loras[lid] = want[lid]
        names = [k.replace(".", "_") for k in want]
        if names:
            pipe.set_adapters(names, adapter_weights=list(want.values()))
        elif self._loaded_loras:
            pipe.disable_lora()
        if names:
            pipe.enable_lora()

    def _controlnet(self, cn_id: str):
        if cn_id in self._controlnets:
            return self._controlnets[cn_id]
        import torch
        from diffusers import ControlNetModel
        e = self.al.require_model(cn_id, {"controlnet"})
        if len(e.files) > 1:  # Diffusers 形式（config.json + 重み）
            m = ControlNetModel.from_pretrained(str(fetch.materialize_dir(e)), local_files_only=True,
                                                torch_dtype=getattr(self, "_dtype", torch.float32))
        else:
            (path,) = fetch.verify_cached(e)
            cfg_id = e.raw.get("config_entry")
            if not cfg_id:
                raise StudioError("DEPENDENCY_MISSING",
                                  f"ControlNet {cn_id} の構成ファイル（config_entry）が未指定。勝手に取得しません")
            cfg = str(fetch.materialize_dir(self.al.require_model(cfg_id, {"pipeline_config"})))
            m = ControlNetModel.from_single_file(str(path), config=cfg, local_files_only=True,
                                                 torch_dtype=torch.float32)
        self._controlnets[cn_id] = m
        return m

    def _ip_adapter(self, pipe, ip: dict[str, Any]) -> None:
        key = (ip["id"], ip.get("image_encoder"))
        if self._ip_loaded == key:
            pipe.set_ip_adapter_scale(float(ip.get("scale", 0.6)))
            return
        e = self.al.require_model(ip["id"], {"ip_adapter"})
        (path,) = fetch.verify_cached(e)
        enc_id = ip.get("image_encoder") or e.raw.get("image_encoder")
        if not enc_id:
            raise StudioError("DEPENDENCY_MISSING",
                              f"IP-Adapter {ip['id']} には画像エンコーダ（kind: image_encoder）が必要です。勝手に取得しません")
        enc_dir = fetch.materialize_dir(self.al.require_model(enc_id, {"image_encoder"}))
        import torch
        from transformers import CLIPVisionModelWithProjection
        pipe.image_encoder = CLIPVisionModelWithProjection.from_pretrained(
            str(enc_dir), local_files_only=True, torch_dtype=torch.float32)
        pipe.load_ip_adapter(str(path.parent), subfolder="", weight_name=path.name, image_encoder_folder=None)
        pipe.set_ip_adapter_scale(float(ip.get("scale", 0.6)))
        self._ip_loaded = key

    def _scheduler(self, pipe, name: str | None):
        import diffusers
        extra: dict[str, Any] = {}
        pred = getattr(self, "_pred", {}) or {}
        if pred.get("prediction_type"):
            extra["prediction_type"] = pred["prediction_type"]
        if pred.get("zero_snr"):
            extra.update(rescale_betas_zero_snr=True, timestep_spacing="trailing")
        if name:
            if name not in SCHEDULERS:
                raise StudioError("BAD_INPUT", f"scheduler は {sorted(SCHEDULERS)}")
            cls_name, sx = SCHEDULERS[name]
            cls = getattr(diffusers, cls_name)
            extra = {**sx, **extra}
        else:
            cls = type(pipe.scheduler)
        if extra or name:
            pipe.scheduler = cls.from_config(pipe.scheduler.config, **extra)

    # ---------- 実行 ----------
    def run(self, op: str, params: dict[str, Any], inputs: dict[str, Image.Image]) -> Image.Image:
        import torch
        from diffusers import AutoPipelineForImage2Image, AutoPipelineForInpainting

        base = self._load_base(params)
        self._apply_loras(base, params.get("loras") or [])
        cn = params.get("controlnet")
        if cn:
            from diffusers import (StableDiffusionControlNetImg2ImgPipeline, StableDiffusionControlNetInpaintPipeline,
                                   StableDiffusionControlNetPipeline, StableDiffusionXLControlNetImg2ImgPipeline,
                                   StableDiffusionXLControlNetInpaintPipeline, StableDiffusionXLControlNetPipeline)
            xl = self._arch == "sdxl"
            cls = {
                "txt2img": StableDiffusionXLControlNetPipeline if xl else StableDiffusionControlNetPipeline,
                "img2img": StableDiffusionXLControlNetImg2ImgPipeline if xl else StableDiffusionControlNetImg2ImgPipeline,
                "inpaint": StableDiffusionXLControlNetInpaintPipeline if xl else StableDiffusionControlNetInpaintPipeline,
            }[op]
            pipe = cls.from_pipe(base, controlnet=self._controlnet(cn["id"]))
        elif op == "txt2img":
            pipe = base
        elif op == "img2img":
            pipe = AutoPipelineForImage2Image.from_pipe(base)
        else:
            pipe = AutoPipelineForInpainting.from_pipe(base)
        self._scheduler(pipe, params.get("scheduler"))
        if params.get("ip_adapter"):
            self._ip_adapter(pipe, params["ip_adapter"])
        if cn and getattr(self, "_dtype", None) is not None:
            pipe.controlnet.to(self._dtype)

        g = torch.Generator("cpu").manual_seed(int(params["seed"]))
        kw: dict[str, Any] = dict(prompt=params.get("prompt", ""), negative_prompt=params.get("negative_prompt") or None,
                                  num_inference_steps=int(params.get("steps", 20)),
                                  guidance_scale=float(params.get("cfg", 7.0)), generator=g)
        if params.get("guidance_rescale") is not None:
            kw["guidance_rescale"] = float(params["guidance_rescale"])
        if params.get("clip_skip"):
            kw["clip_skip"] = int(params["clip_skip"])
        if op == "txt2img":
            kw.update(width=int(params["width"]), height=int(params["height"]))
        else:
            kw["image"] = inputs["init"].convert("RGB")
            kw["strength"] = float(params.get("denoise", 0.5))
        if op == "inpaint":
            kw["mask_image"] = inputs["mask"].convert("L")
            kw.update(width=inputs["init"].width, height=inputs["init"].height)
        if cn:
            ctrl = inputs["control"].convert("RGB")
            if op == "txt2img":
                kw["image"] = ctrl
            else:
                kw["control_image"] = ctrl
            kw["controlnet_conditioning_scale"] = float(cn.get("scale", 0.8))
        if params.get("ip_adapter"):
            kw["ip_adapter_image"] = inputs["ip_image"].convert("RGB")
        with torch.inference_mode():
            img = pipe(**kw).images[0]
        del pipe
        import gc
        gc.collect()
        import numpy as np
        if not np.isfinite(np.asarray(img, dtype=np.float32)).all() or np.asarray(img).std() < 1:
            raise StudioError("BAD_OUTPUT", "生成結果が空/単色（設定不整合の可能性: v-pred 指定や dtype を確認）")
        return img


def upscale_with_model(al: Allowlist, model_id: str, img: Image.Image) -> Image.Image:
    """許可済みアップスケーラ（ESRGAN 系 safetensors）を spandrel で読み込んで拡大。未検証。"""
    import numpy as np
    import torch
    try:
        import spandrel
    except ImportError as e:
        raise StudioError("TOOL_MISSING", "spandrel が未導入（requirements/gen.txt）") from e
    e = al.require_model(model_id, {"upscaler"})
    (path,) = fetch.verify_cached(e)
    model = spandrel.ModelLoader().load_from_file(str(path)).eval()
    x = torch.from_numpy(np.asarray(img.convert("RGB")).astype("float32") / 255).permute(2, 0, 1)[None]
    with torch.inference_mode():
        y = model(x)[0].clamp(0, 1).permute(1, 2, 0).numpy()
    return Image.fromarray((y * 255).round().astype("uint8"))
