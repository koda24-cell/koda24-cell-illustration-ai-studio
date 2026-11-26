"""制作指示（ジョブ YAML）の読込・検証・入力画像の解決。

実行前に、ジョブ内の全モデル ID・全画像参照が許可リストにあることを確認する（fail fast）。
"""
from __future__ import annotations

import copy
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image

from . import ledger, recipes
from .allowlist import Allowlist, NotAllowed
from .util import ID_RE, REPO_ROOT, StudioError, load_yaml, sha256_file

MAX_TIME_BUDGET = 345  # 6時間ジョブ上限から、セットアップと保存の余裕を引いた分
DEFAULT_LIMITS = {"max_rounds": 6, "candidates_per_round": 3, "patience": 2, "target_score": 0.8,
                  "max_error_retries": 3}
DEFAULT_PARAMS = {"width": 512, "height": 512, "steps": 20, "cfg": 7.0, "scheduler": "euler_a",
                  "negative_prompt": "", "denoise": 0.5}
MODEL_FIELDS = {"model": {"checkpoint"}, "vae": {"vae"}, "pipeline_config": {"pipeline_config"}}


def load_job(path: str | os.PathLike) -> dict[str, Any]:
    job = load_yaml(path)
    if not isinstance(job, dict):
        raise StudioError("BAD_INPUT", f"ジョブを読めません: {path}")
    return normalize(job)


def normalize(job: dict[str, Any]) -> dict[str, Any]:
    job = copy.deepcopy(job)
    if not ID_RE.match(str(job.get("job_id", ""))):
        raise StudioError("BAD_INPUT", "job_id は英小文字・数字・._- のみ")
    job.setdefault("backend", "diffusers")
    tb = float(job.get("time_budget_minutes", 30))
    if tb > MAX_TIME_BUDGET:
        raise StudioError("BAD_INPUT", f"time_budget_minutes は {MAX_TIME_BUDGET} 以下（GitHub Actions 6時間上限）")
    job["time_budget_minutes"] = tb
    job["limits"] = {**DEFAULT_LIMITS, **(job.get("limits") or {})}
    if job["limits"]["max_error_retries"] > 3:
        raise StudioError("BAD_INPUT", "max_error_retries は 3 以下")
    job["defaults"] = {**DEFAULT_PARAMS, **(job.get("defaults") or {})}
    job.setdefault("evaluation", {})
    job.setdefault("improve", {"enabled": True, "tune": ["cfg", "steps", "denoise", "prompt"]})
    if job.get("recipe"):
        job["stages"] = recipes.expand(job["recipe"]) + list(job.get("stages") or [])
    if not job.get("stages"):
        raise StudioError("BAD_INPUT", "stages か recipe が必要")
    names = set()
    for s in job["stages"]:
        if s.get("op") not in recipes.ALL_OPS:
            raise StudioError("BAD_INPUT", f"stage {s.get('name')}: op は {sorted(recipes.ALL_OPS)}")
        if not ID_RE.match(str(s.get("name", ""))) or s["name"] in names:
            raise StudioError("BAD_INPUT", f"stage 名が不正/重複: {s.get('name')}")
        names.add(s["name"])
    return job


def stage_params(job: dict[str, Any], stage: dict[str, Any]) -> dict[str, Any]:
    keys_skip = {"name", "op", "init", "mask", "background", "consistency_base", "scale", "outpaint"}
    p = copy.deepcopy(job["defaults"])
    for k, v in stage.items():
        if k not in keys_skip:
            p[k] = copy.deepcopy(v)
    return p


def validate_against_allowlist(job: dict[str, Any], al: Allowlist) -> dict[str, Any]:
    """全モデル・画像参照を検査し、model: auto を許可済みモデルから解決する。"""
    used_models: set[str] = set()
    problems: list[str] = []
    backend = job["backend"]
    names_before: set[str] = set()

    def chk_model(mid: str, kinds: set[str]) -> None:
        try:
            al.require_model(mid, kinds)
            used_models.add(mid)
        except NotAllowed as e:
            problems.append(e.message)

    def chk_image(ref: Any, role: str) -> None:
        if isinstance(ref, dict):
            return
        ref = str(ref)
        if ref.startswith("images:"):
            try:
                al.require_image(ref.split(":", 1)[1], role)
            except NotAllowed as e:
                problems.append(e.message)
        elif ref.startswith("stage:"):
            if ref.split(":", 1)[1] not in names_before:
                problems.append(f"{ref} は前のステージにありません")
        elif ref.startswith("run:"):
            pass  # 過去の本リポジトリ生成物（派生物）。実行時に存在確認
        else:
            problems.append(f"画像参照 '{ref}' は images:/stage:/run: のいずれかで指定（URL・任意パスは不可）")

    for ref in job["evaluation"].get("references") or []:
        chk_image(ref, "reference")
    for s in job["stages"]:
        p = stage_params(job, s)
        if s["op"] in recipes.GENERATIVE_OPS and backend == "diffusers":
            if p.get("model") in (None, "auto"):
                try:
                    p["model"] = ledger.select_model(al, "checkpoint", job["defaults"].get("purpose"),
                                                     job["defaults"].get("base_model"))
                except NotAllowed as e:
                    problems.append(e.message)
            s["model"] = p.get("model")
            for f, kinds in MODEL_FIELDS.items():
                if p.get(f) and p[f] != "auto":
                    chk_model(p[f], kinds)
            for l in p.get("loras") or []:
                chk_model(l["id"], {"lora", "lycoris"})
            for e in p.get("embeddings") or []:
                chk_model(e, {"embedding"})
            if p.get("controlnet"):
                chk_model(p["controlnet"]["id"], {"controlnet"})
                chk_image(p["controlnet"].get("image"), "control")
            if p.get("ip_adapter"):
                chk_model(p["ip_adapter"]["id"], {"ip_adapter"})
                if p["ip_adapter"].get("image_encoder"):
                    chk_model(p["ip_adapter"]["image_encoder"], {"image_encoder"})
                chk_image(p["ip_adapter"].get("image"), "reference")
        if s["op"] == "upscale_model":
            chk_model(s.get("upscaler", ""), {"upscaler"})
        for key, role in (("init", "init"), ("background", "background"), ("consistency_base", "init")):
            if s.get(key):
                chk_image(s[key], role)
        if isinstance(s.get("mask"), str):
            chk_image(s["mask"], "mask")
        names_before.add(s["name"])
    for ev in job["evaluation"].get("evaluator_models") or []:
        chk_model(ev, {"evaluator"})
    if problems:
        raise NotAllowed("ジョブが許可リスト外のデータを参照しています:\n- " + "\n- ".join(problems))
    return {"models": sorted(used_models)}


# ---------- 画像読込 ----------
def load_allowed_image(al: Allowlist, image_id: str, role: str | None = None) -> Image.Image:
    e = al.require_image(image_id, role)
    raw = e.raw
    if raw.get("path"):
        p = (REPO_ROOT / raw["path"]).resolve()
        if REPO_ROOT not in p.parents:
            raise StudioError("BAD_INPUT", f"{image_id}: リポジトリ外のパス")
        if sha256_file(p) != raw["sha256"].lower():
            raise StudioError("HASH_MISMATCH", f"{image_id}: 画像の SHA256 が台帳と一致しません")
        return Image.open(p).copy()
    # 非公開画像：暗号化ファイルを Secret STUDIO_INPUT_KEY で復号（平文はリポジトリに置かない）
    key = os.environ.get("STUDIO_INPUT_KEY")
    if not key:
        raise StudioError("SECRET_MISSING", f"{image_id}: 暗号化画像の復号キー STUDIO_INPUT_KEY がありません")
    enc = (REPO_ROOT / raw["encrypted_path"]).resolve()
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "img"
        proc = subprocess.run(["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-iter", "200000",
                               "-in", str(enc), "-out", str(out), "-pass", "env:STUDIO_INPUT_KEY"],
                              capture_output=True, text=True)
        if proc.returncode != 0:
            raise StudioError("DECRYPT_FAILED", f"{image_id}: 復号失敗")
        if sha256_file(out) != raw["sha256"].lower():
            raise StudioError("HASH_MISMATCH", f"{image_id}: 復号後の SHA256 が一致しません")
        return Image.open(out).copy()
