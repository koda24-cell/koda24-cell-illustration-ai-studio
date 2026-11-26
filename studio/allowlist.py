"""使用許可リスト（最重要）。

- allowlist/models.yaml : 生成・評価に使うモデル（Checkpoint / LoRA / VAE / ...）
- allowlist/images.yaml : 参照画像・学習用画像・評価用画像

ここに無いものは取得も使用もできない。登録はユーザーの明示指示がある場合のみ
（`added_by_user_instruction` 必須）。自動収集・自動更新・自動置換は実装しない。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .util import ID_RE, REPO_ROOT, SHA256_RE, StudioError, load_yaml

MODEL_KINDS = {
    "checkpoint",
    "lora",
    "lycoris",
    "vae",
    "embedding",
    "controlnet",
    "ip_adapter",
    "image_encoder",   # IP-Adapter の必須依存（CLIP Vision 等）
    "upscaler",
    "evaluator",       # 評価用モデル（CLIP 等）
    "pipeline_config", # Diffusers の構成ファイル（重みなし: json/txt）
}
IMAGE_ROLES = {"reference", "training", "evaluation", "init", "mask", "control", "background"}
SOURCES = {"civitai", "huggingface"}
SAFE_FORMATS = {"safetensors"}
PICKLE_SUFFIXES = {".ckpt", ".pt", ".pth", ".bin", ".pkl"}

MODELS_FILE = REPO_ROOT / "allowlist" / "models.yaml"
IMAGES_FILE = REPO_ROOT / "allowlist" / "images.yaml"


class NotAllowed(StudioError):
    def __init__(self, message: str):
        super().__init__("NOT_ALLOWED", message)


def parse_civitai_url(url: str) -> dict[str, int | None]:
    """https://civitai.com/models/<modelId>[/slug][?modelVersionId=<id>] を分解する。"""
    u = urlparse(url)
    if not u.netloc.endswith(("civitai.com", "civitai.green")):
        raise StudioError("BAD_INPUT", f"Civitai のURLではありません: {url}")
    m = re.search(r"/models/(\d+)", u.path)
    q = parse_qs(u.query)
    version = q.get("modelVersionId", [None])[0]
    dl = re.search(r"/api/download/models/(\d+)", u.path)
    return {
        "model_id": int(m.group(1)) if m else None,
        "version_id": int(version) if version else (int(dl.group(1)) if dl else None),
    }


@dataclass
class ModelEntry:
    raw: dict[str, Any]

    @property
    def id(self) -> str:
        return self.raw["id"]

    @property
    def kind(self) -> str:
        return self.raw["kind"]

    @property
    def files(self) -> list[dict[str, Any]]:
        """取得対象ファイル（各要素に filename / sha256 / size_bytes）。"""
        if "files" in self.raw:
            return list(self.raw["files"])
        return [{k: self.raw.get(k) for k in ("filename", "sha256", "size_bytes", "file_id")}]

    @property
    def primary_file(self) -> dict[str, Any]:
        return self.files[0]


@dataclass
class ImageEntry:
    raw: dict[str, Any]

    @property
    def id(self) -> str:
        return self.raw["id"]

    @property
    def public_ok(self) -> bool:
        return bool(self.raw.get("public_ok", False))

    @property
    def derivatives_public_ok(self) -> bool:
        return bool(self.raw.get("derivatives_public_ok", False))


@dataclass
class Allowlist:
    models: dict[str, ModelEntry] = field(default_factory=dict)
    images: dict[str, ImageEntry] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    # ---------- 読み込み・検証 ----------
    @classmethod
    def load(cls, models_file: Path = MODELS_FILE, images_file: Path = IMAGES_FILE,
             strict: bool = True) -> "Allowlist":
        al = cls()
        mdata = load_yaml(models_file, {"version": 1, "models": []})
        idata = load_yaml(images_file, {"version": 1, "images": []})
        for raw in mdata.get("models") or []:
            al._add_model(raw)
        for raw in idata.get("images") or []:
            al._add_image(raw)
        if strict and al.errors:
            raise StudioError("ALLOWLIST_INVALID", "許可リストに不備があります:\n- " + "\n- ".join(al.errors))
        return al

    def _add_model(self, raw: dict[str, Any]) -> None:
        mid = str(raw.get("id", ""))
        where = f"models[{mid or '?'}]"
        if not ID_RE.match(mid):
            self.errors.append(f"{where}: id は英小文字・数字・._- のみ")
        if mid in self.models:
            self.errors.append(f"{where}: id が重複")
        if raw.get("kind") not in MODEL_KINDS:
            self.errors.append(f"{where}: kind が不正 ({raw.get('kind')})")
        if raw.get("source") not in SOURCES:
            self.errors.append(f"{where}: source は civitai / huggingface")
        if not str(raw.get("added_by_user_instruction", "")).strip():
            self.errors.append(f"{where}: added_by_user_instruction（ユーザー指示の記録）が必須")
        if raw.get("source") == "civitai":
            c = raw.get("civitai") or {}
            if not c.get("version_id"):
                self.errors.append(f"{where}: civitai.version_id（バージョン固定）が必須")
        if raw.get("source") == "huggingface":
            hf = raw.get("huggingface") or {}
            if not hf.get("repo") or not re.fullmatch(r"[0-9a-f]{40}", str(hf.get("revision", ""))):
                self.errors.append(f"{where}: huggingface.repo と 40桁のコミット revision が必須")
        entry = ModelEntry(raw)
        for f in entry.files:
            fn = str(f.get("filename") or "")
            if not fn:
                self.errors.append(f"{where}: filename が必須")
            if ".." in Path(fn).parts or fn.startswith(("/", "\\")):
                self.errors.append(f"{where}: filename にパス移動は不可")
            sha = str(f.get("sha256") or "").lower()
            if not SHA256_RE.match(sha):
                self.errors.append(f"{where}: {fn} の sha256（64桁）が必須（ファイル固定のため）")
            suffix = Path(fn).suffix.lower()
            if suffix in PICKLE_SUFFIXES and not raw.get("allow_pickle"):
                self.errors.append(
                    f"{where}: {fn} は pickle 形式。safetensors を優先。どうしても必要なら allow_pickle: true と理由を明記")
        self.models[mid] = entry

    def _add_image(self, raw: dict[str, Any]) -> None:
        iid = str(raw.get("id", ""))
        where = f"images[{iid or '?'}]"
        if not ID_RE.match(iid):
            self.errors.append(f"{where}: id が不正")
        if iid in self.images:
            self.errors.append(f"{where}: id が重複")
        roles = raw.get("roles") or []
        if not roles or any(r not in IMAGE_ROLES for r in roles):
            self.errors.append(f"{where}: roles は {sorted(IMAGE_ROLES)} から")
        if not (raw.get("path") or raw.get("encrypted_path")):
            self.errors.append(f"{where}: path か encrypted_path が必須")
        if not SHA256_RE.match(str(raw.get("sha256", "")).lower()):
            self.errors.append(f"{where}: sha256（平文画像）が必須")
        if not str(raw.get("added_by_user_instruction", "")).strip():
            self.errors.append(f"{where}: added_by_user_instruction が必須")
        if "public_ok" not in raw:
            self.errors.append(f"{where}: public_ok（公開可否）を明記すること")
        self.images[iid] = ImageEntry(raw)

    # ---------- 参照 ----------
    def require_model(self, model_id: str, kinds: set[str] | None = None) -> ModelEntry:
        entry = self.models.get(model_id)
        if entry is None:
            raise NotAllowed(f"モデル '{model_id}' は許可リストにありません（勝手に追加しません）")
        if kinds and entry.kind not in kinds:
            raise NotAllowed(f"モデル '{model_id}' は {entry.kind}。ここでは {sorted(kinds)} が必要")
        return entry

    def require_image(self, image_id: str, role: str | None = None) -> ImageEntry:
        entry = self.images.get(image_id)
        if entry is None:
            raise NotAllowed(f"画像 '{image_id}' は許可リストにありません")
        if role and role not in entry.raw.get("roles", []):
            raise NotAllowed(f"画像 '{image_id}' は役割 '{role}' での使用が許可されていません")
        return entry

    def models_of(self, *kinds: str) -> list[ModelEntry]:
        return [m for m in self.models.values() if m.kind in kinds]

    def is_empty(self) -> bool:
        return not self.models and not self.images
