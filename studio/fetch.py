"""許可リスト登録済みモデルだけを取得・検査・キャッシュする。

流れ（fail closed）:
  1. 許可リストのエントリを確認（無ければ NOT_ALLOWED）
  2. 隔離ディレクトリ quarantine/ に取得
  3. 直後に ClamAV 検査 → 圧縮なら構造検査・隔離展開・再スキャン
  4. SHA256 を許可リストの固定値と照合（不一致は破棄・報告。自動置換しない）
  5. safetensors ヘッダ検査
  6. 合格したものだけ cache/models/<sha256>/<filename> へ移動し scan_manifest.json を記録
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

import requests

from . import civitai, scan
from .allowlist import Allowlist, ModelEntry
from .util import StudioError, cache_dir, dump_json, load_json, now_iso, sha256_file


def model_dir(sha: str) -> Path:
    return cache_dir() / "models" / sha.lower()


def cached_path(entry: ModelEntry, file_meta: dict[str, Any] | None = None) -> Path:
    f = file_meta or entry.primary_file
    return model_dir(f["sha256"]) / Path(f["filename"]).name


def is_cached(entry: ModelEntry) -> bool:
    for f in entry.files:
        p = cached_path(entry, f)
        man = load_json(p.parent / "scan_manifest.json", {})
        if not p.exists() or man.get("status") != "SAFETY_CHECK_OK":
            return False
    return True


def verify_cached(entry: ModelEntry) -> list[Path]:
    """使用直前の検証：存在・検査合格・SHA256一致。1つでも外れたら使わない。"""
    paths = []
    for f in entry.files:
        p = cached_path(entry, f)
        man = load_json(p.parent / "scan_manifest.json", {})
        if not p.exists():
            raise StudioError("MODEL_NOT_CACHED", f"{entry.id}: {f['filename']} が未取得です（fetch-models を実行）")
        if man.get("status") != "SAFETY_CHECK_OK":
            raise StudioError("BLOCKED_UNSCANNED", f"{entry.id}: 安全検査が未完了です")
        stamp = f"{p.stat().st_size}:{int(p.stat().st_mtime)}"
        marker = p.parent / ".verified"
        if not (marker.exists() and marker.read_text() == stamp):
            actual = sha256_file(p)
            if actual != f["sha256"].lower():
                raise StudioError("HASH_MISMATCH", f"{entry.id}: SHA256 不一致（{actual}）。使用しません")
            marker.write_text(stamp)
        paths.append(p)
    return paths


def _download_hf(entry: ModelEntry, f: dict[str, Any], dest: Path) -> Path:
    hf = entry.raw["huggingface"]
    url = f"https://huggingface.co/{hf['repo']}/resolve/{hf['revision']}/{f.get('repo_path', f['filename'])}"
    headers = {"User-Agent": civitai.UA}
    tok = os.environ.get("HF_TOKEN")
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, headers=headers, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(tmp, "wb") as fo:
            for chunk in r.iter_content(8 * 1024 * 1024):
                fo.write(chunk)
    os.replace(tmp, dest)
    return dest


def fetch_entry(entry: ModelEntry, work: Path | None = None) -> list[dict[str, Any]]:
    results = []
    work = work or (cache_dir() / "quarantine")
    for f in entry.files:
        final = cached_path(entry, f)
        if is_cached(entry) and final.exists():
            verify_cached(entry)
            results.append({"id": entry.id, "file": f["filename"], "status": "CACHED"})
            continue
        q = work / entry.id
        if q.exists():
            shutil.rmtree(q)
        q.mkdir(parents=True)
        target = q / Path(f["filename"]).name
        record: dict[str, Any] = {"id": entry.id, "file": f["filename"], "started_at": now_iso(),
                                  "expected_sha256": f["sha256"].lower()}
        try:
            if entry.raw["source"] == "civitai":
                c = entry.raw["civitai"]
                meta = None
                if c.get("file_id"):
                    ver = civitai.get_model_version(c["version_id"])
                    meta = civitai.pick_file(ver, c["file_id"])
                civitai.download_file(c["version_id"], meta, target, file_id=c.get("file_id"))
            else:
                _download_hf(entry, f, target)
        except StudioError as e:
            record.update(status="NOT_DOWNLOADED", error=e.message)
            results.append(record)
            continue
        except Exception as e:  # noqa: BLE001
            record.update(status="NOT_DOWNLOADED", error=str(e)[:300])
            results.append(record)
            continue

        # 2) ダウンロード直後のスキャン
        s1 = scan.clamscan([target], log_path=q / "clamscan_1.log")
        record["scan_primary"] = s1
        if s1["status"] != "SAFETY_CHECK_OK":
            record["status"] = s1["status"]
            results.append(record)
            continue
        # 3) 圧縮ファイル（モデルは通常非圧縮。来た場合のみ）
        if scan.is_archive(target):
            ext = q / "extracted"
            files = scan.safe_extract(target, ext)
            s2 = scan.clamscan([ext], log_path=q / "clamscan_2.log")
            record["scan_secondary"] = s2
            record["status"] = "ARCHIVE_NEEDS_REVIEW" if s2["status"] == "SAFETY_CHECK_OK" else s2["status"]
            record["extracted"] = [str(p.relative_to(ext)) for p in files]
            results.append(record)  # 展開物のどれを使うかはユーザー指定が必要
            continue
        # 4) ハッシュ照合
        actual = sha256_file(target)
        record["actual_sha256"] = actual
        if actual != f["sha256"].lower():
            record["status"] = "HASH_MISMATCH"
            target.unlink()
            results.append(record)
            continue
        # 5) 形式検査
        if target.suffix.lower() == ".safetensors":
            record["format_check"] = scan.inspect_safetensors(target)
        elif target.suffix.lower() in {".json", ".txt", ".model"}:
            record["format_check"] = {"format": target.suffix.lower().lstrip("."), "size": target.stat().st_size}
        elif entry.raw.get("allow_pickle"):
            record["format_check"] = {"format": "pickle", "note": "allow_pickle 明示。torch weights_only=True で読込"}
        else:
            record["status"] = "UNSAFE_FORMAT"
            results.append(record)
            continue
        # 6) 昇格
        final.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(target), final)
        record.update(status="SAFETY_CHECK_OK", finished_at=now_iso(), path=str(final))
        dump_json(final.parent / "scan_manifest.json", record)
        shutil.copy(q / "clamscan_1.log", final.parent / "clamscan_1.log")
        shutil.rmtree(q, ignore_errors=True)
        results.append(record)
    return results


def fetch_all(al: Allowlist, only: list[str] | None = None) -> list[dict[str, Any]]:
    out = []
    targets = [al.require_model(i) for i in only] if only else list(al.models.values())
    for e in targets:
        out.extend(fetch_entry(e))
    return out


def materialize_dir(entry: ModelEntry) -> Path:
    """複数ファイルのエントリ（Diffusers形式の構成・ControlNet・画像エンコーダ等）を
    repo_path どおりのディレクトリに並べる（検証済みファイルへのシンボリックリンク）。"""
    paths = verify_cached(entry)
    root = cache_dir() / "materialized" / entry.id
    for f, p in zip(entry.files, paths):
        rel = Path(f.get("repo_path") or f["filename"])
        if ".." in rel.parts or rel.is_absolute():
            raise StudioError("BAD_INPUT", f"{entry.id}: repo_path が不正")
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.is_symlink() or dst.exists():
            dst.unlink()
        dst.symlink_to(p)
    return root
