"""Civitai 公式 REST API クライアント（https://civitai.com/api/v1）。

- メタデータ取得は公開APIのみ。トークンは環境変数 CIVITAI_API_TOKEN（GitHub Secret）から。
- 検索・ランキング取得の機能は意図的に持たない（自動収集の禁止）。
- ダウンロードは許可リストに登録済みの version_id / file_id / sha256 に限る（fetch.py 経由）。
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import requests

from .util import StudioError, mask_secret

API = "https://civitai.com/api/v1"
UA = "illustration-ai-studio/0.1 (+allowlist-only)"


def _headers(auth: bool) -> dict[str, str]:
    h = {"User-Agent": UA, "Accept": "application/json"}
    tok = os.environ.get("CIVITAI_API_TOKEN")
    if auth and tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def _get_json(url: str, retries: int = 3) -> dict[str, Any]:
    last: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, headers=_headers(True), timeout=60)
            if r.status_code == 404:
                raise StudioError("NOT_FOUND", f"Civitai: 見つかりません {url}")
            if r.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"HTTP {r.status_code}")
            r.raise_for_status()
            return r.json()
        except StudioError:
            raise
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(min(30, 5 * attempt))
    raise StudioError("NETWORK", mask_secret(f"Civitai API 失敗: {url}: {last}"))


def get_model_version(version_id: int) -> dict[str, Any]:
    return _get_json(f"{API}/model-versions/{int(version_id)}")


def get_model(model_id: int) -> dict[str, Any]:
    return _get_json(f"{API}/models/{int(model_id)}")


def pick_file(version: dict[str, Any], file_id: int | None = None) -> dict[str, Any]:
    files = version.get("files") or []
    if file_id is not None:
        for f in files:
            if int(f.get("id", -1)) == int(file_id):
                return f
        raise StudioError("NOT_FOUND", f"version {version.get('id')} に file_id {file_id} がありません")
    safes = [f for f in files if (f.get("metadata") or {}).get("format") == "SafeTensor"
             and f.get("type") in ("Model", None)]
    prim = [f for f in safes if f.get("primary")] or safes
    if not prim:
        raise StudioError("UNSAFE_FORMAT",
                          "safetensors のファイルが見つかりません。pickle 形式は既定で拒否します（file_id を明示して報告）")
    return prim[0]


def license_summary(model: dict[str, Any]) -> dict[str, Any]:
    acu = model.get("allowCommercialUse")
    if isinstance(acu, str):
        acu = [acu]
    return {
        "allowCommercialUse": acu,
        "allowNoCredit": model.get("allowNoCredit"),
        "allowDerivatives": model.get("allowDerivatives"),
        "allowDifferentLicense": model.get("allowDifferentLicense"),
        "note": "Civitai API の値。最終的な利用可否は配布ページの記載と作品の用途でユーザーが判断する。",
    }


def build_entry_draft(url: str, user_instruction: str, kind: str | None = None,
                      file_id: int | None = None, entry_id: str | None = None) -> dict[str, Any]:
    """ユーザーが指定した URL から、許可リスト登録用の下書きを作る（自動登録はしない）。"""
    from .allowlist import parse_civitai_url

    ids = parse_civitai_url(url)
    if ids["version_id"] is None and ids["model_id"] is not None:
        raise StudioError("BAD_INPUT",
                          "URL にバージョン指定がありません。?modelVersionId= 付きのURLかバージョンIDを指定してください"
                          "（最新版の自動選択はしません）")
    ver = get_model_version(ids["version_id"])
    model = get_model(ver.get("modelId") or ids["model_id"])
    f = pick_file(ver, file_id)
    type_map = {"Checkpoint": "checkpoint", "LORA": "lora", "LoCon": "lycoris", "DoRA": "lora",
                "TextualInversion": "embedding", "VAE": "vae", "Controlnet": "controlnet",
                "Upscaler": "upscaler"}
    mkind = kind or type_map.get(model.get("type", ""), None)
    if mkind is None:
        raise StudioError("BAD_INPUT", f"種類を判定できません（type={model.get('type')}）。kind を指定してください")
    slug = entry_id or f"{model.get('name','model')}-{ver.get('name','v')}"
    slug = "".join(c.lower() if c.isalnum() else "-" for c in slug).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    sha = ((f.get("hashes") or {}).get("SHA256") or "").lower()
    if not sha:
        raise StudioError("NO_HASH", "Civitai が SHA256 を返しませんでした。固定できないため登録不可")
    return {
        "id": slug[:80],
        "kind": mkind,
        "source": "civitai",
        "url": f"https://civitai.com/models/{ver.get('modelId')}?modelVersionId={ver.get('id')}",
        "civitai": {"model_id": ver.get("modelId"), "version_id": ver.get("id"), "file_id": f.get("id")},
        "name": model.get("name"),
        "version_name": ver.get("name"),
        "author": (model.get("creator") or {}).get("username"),
        "base_model": ver.get("baseModel"),
        "filename": f.get("name"),
        "sha256": sha,
        "size_bytes": int(float(f.get("sizeKB") or 0) * 1024),
        "format": (f.get("metadata") or {}).get("format"),
        "trained_words": ver.get("trainedWords") or [],
        "license": license_summary(model),
        "civitai_scan": {"pickle": f.get("pickleScanResult"), "virus": f.get("virusScanResult")},
        "added_by_user_instruction": user_instruction,
        "added_at": time.strftime("%Y-%m-%d"),
    }


def download_file(version_id: int, file_meta: dict[str, Any] | None, dest: Path,
                  file_id: int | None = None) -> Path:
    """Civitai のダウンロードURLから dest に保存（隔離ディレクトリ想定）。"""
    url = f"https://civitai.com/api/download/models/{int(version_id)}"
    if file_id:
        # file_id 固定時は versions API の downloadUrl（ファイル単位）を使う
        if file_meta and file_meta.get("downloadUrl"):
            url = file_meta["downloadUrl"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    # Authorization ヘッダは別ホストへのリダイレクト時に requests が自動で外す
    with requests.get(url, headers=_headers(True), stream=True, timeout=120, allow_redirects=True) as r:
        if r.status_code in (401, 403):
            raise StudioError("AUTH", "Civitai がダウンロードを拒否しました。CIVITAI_API_TOKEN（Secret）を確認してください")
        r.raise_for_status()
        ctype = r.headers.get("content-type", "")
        if "text/html" in ctype:
            raise StudioError("NETWORK", "ファイルではなくHTMLが返りました（ログイン要求等）")
        with open(tmp, "wb") as fo:
            for chunk in r.iter_content(chunk_size=8 * 1024 * 1024):
                if chunk:
                    fo.write(chunk)
    os.replace(tmp, dest)
    return dest
