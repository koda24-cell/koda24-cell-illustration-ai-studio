"""外部ファイルの安全検査ゲート（fail closed）。

- ClamAV（clamscan）でダウンロード直後に検査。未導入・定義未更新・エラーは BLOCKED_UNSCANNED。
- 圧縮ファイルは展開前に構造検査（パストラバーサル / symlink / 暗号化 / 圧縮率 / 総サイズ）、
  隔離領域へ展開後に再スキャン。
- safetensors はテンソルを読み込まずにヘッダ(JSON)だけ検査する。
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import shutil
import struct
import subprocess
import tarfile
import zipfile
from pathlib import Path
from typing import Any

from .util import StudioError, now_iso, sha256_file

MAX_DB_AGE_HOURS = int(os.environ.get("STUDIO_CLAMAV_MAX_DB_AGE_HOURS", "96"))
MAX_ARCHIVE_TOTAL = 20 * 1024**3
MAX_ARCHIVE_RATIO = 200
MAX_ARCHIVE_MEMBERS = 10000


def clamav_info() -> dict[str, Any]:
    exe = shutil.which("clamscan")
    if not exe:
        return {"available": False, "reason": "clamscan が見つかりません"}
    out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=60)
    ver = out.stdout.strip()
    info: dict[str, Any] = {"available": out.returncode == 0, "version_string": ver}
    # 例: "ClamAV 1.0.7/27470/Tue Nov 25 08:35:01 2026"
    m = re.match(r"ClamAV ([^/]+)/(\d+)/(.+)$", ver)
    if m:
        info.update(engine=m.group(1), db_version=int(m.group(2)), db_date=m.group(3).strip())
        try:
            dt = _dt.datetime.strptime(m.group(3).strip(), "%a %b %d %H:%M:%S %Y")
            age = (_dt.datetime.utcnow() - dt).total_seconds() / 3600
            info["db_age_hours"] = round(age, 1)
        except ValueError:
            info["db_age_hours"] = None
    else:
        info["db_age_hours"] = None
    return info


def require_clamav() -> dict[str, Any]:
    info = clamav_info()
    if not info.get("available"):
        raise StudioError("BLOCKED_UNSCANNED", f"ClamAV が使えません: {info.get('reason', info)}")
    age = info.get("db_age_hours")
    if age is None or age > MAX_DB_AGE_HOURS:
        raise StudioError("BLOCKED_UNSCANNED",
                          f"ClamAV 定義が古いか不明です（{age} 時間, 上限 {MAX_DB_AGE_HOURS}h）。freshclam で更新してください")
    return info


# ClamAV は 1 ファイル約 4GB を超えると全体を検査できない（上限超過を「検査済み」と誤認しない）。
CHUNK_THRESHOLD = int(os.environ.get("STUDIO_SCAN_CHUNK_THRESHOLD", str(3 * 1024**3)))
CHUNK_SIZE = int(os.environ.get("STUDIO_SCAN_CHUNK_SIZE", str(1024**3)))
CHUNK_OVERLAP = 4 * 1024 * 1024
CLAM_LIMITS = ["--max-filesize=4000M", "--max-scansize=4000M", "--alert-exceeds-max=yes"]


def _run_clamscan(paths: list[Path]) -> subprocess.CompletedProcess:
    cmd = ["clamscan", "--recursive", "--stdout", "--no-summary", "--infected", "--scan-archive=yes",
           *CLAM_LIMITS, *[str(p) for p in paths]]
    return subprocess.run(cmd, capture_output=True, text=True)


def _chunks(path: Path, workdir: Path):
    """大きなファイルを重なり付きの分割片として順に書き出す（1片ずつ生成・削除）。"""
    size = path.stat().st_size
    workdir.mkdir(parents=True, exist_ok=True)
    start, idx = 0, 0
    with open(path, "rb") as f:
        while start < size:
            f.seek(start)
            length = min(CHUNK_SIZE + CHUNK_OVERLAP, size - start)
            cp = workdir / f"{path.name}.part{idx:04d}"
            with open(cp, "wb") as o:
                remaining = length
                while remaining:
                    b = f.read(min(remaining, 16 * 1024 * 1024))
                    if not b:
                        break
                    o.write(b)
                    remaining -= len(b)
            yield idx, start, length, cp
            start += CHUNK_SIZE
            idx += 1


def clamscan(paths: list[Path], log_path: Path | None = None) -> dict[str, Any]:
    """clamscan を実行。exit 0=感染なし, 1=検出, 2=エラー。0 以外は全て失敗扱い。
    約3GB超のファイルは 1GB（4MB重なり）単位の分割片をすべて検査する（method=chunked として記録）。"""
    info = require_clamav()
    small = [p for p in paths if not (p.is_file() and p.stat().st_size > CHUNK_THRESHOLD)]
    large = [p for p in paths if p not in small]
    out_log: list[str] = []
    detections: list[str] = []
    codes: list[int] = []
    methods: list[dict[str, Any]] = []
    if small:
        proc = _run_clamscan(small)
        codes.append(proc.returncode)
        out_log.append(proc.stdout + "\n--- stderr ---\n" + proc.stderr)
        detections += [ln for ln in proc.stdout.splitlines() if ln.rstrip().endswith("FOUND")]
        methods += [{"path": str(p), "method": "whole"} for p in small]
    for p in large:
        wd = p.parent / f".scan-chunks-{p.name}"
        n = 0
        for idx, start, length, cp in _chunks(p, wd):
            proc = _run_clamscan([cp])
            codes.append(proc.returncode)
            out_log.append(f"[chunk {idx} offset={start} len={length}] rc={proc.returncode}\n{proc.stdout}{proc.stderr}")
            detections += [ln for ln in proc.stdout.splitlines() if ln.rstrip().endswith("FOUND")]
            cp.unlink()
            n += 1
            if proc.returncode != 0:
                break
        shutil.rmtree(wd, ignore_errors=True)
        methods.append({"path": str(p), "method": "chunked", "chunks": n, "chunk_size": CHUNK_SIZE,
                        "overlap": CHUNK_OVERLAP,
                        "note": "ClamAV の1ファイル上限(約4GB)のため分割検査。分割片をまたぐシグネチャは重なり分のみ考慮"})
    result = {
        "scanner": "clamscan",
        "scanner_version": info.get("version_string"),
        "db_age_hours": info.get("db_age_hours"),
        "options": CLAM_LIMITS,
        "exit_codes": sorted(set(codes)),
        "exit_code": max(codes) if codes else 2,
        "detections": detections,
        "detection_count": len(detections),
        "methods": methods,
        "scanned_at": now_iso(),
        "targets": [{"path": str(p), "sha256": sha256_file(p) if p.is_file() else None} for p in paths],
    }
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("\n".join(out_log), encoding="utf-8")
    if detections or 1 in codes:
        result["status"] = "QUARANTINED_DETECTION"
    elif not codes or any(c != 0 for c in codes):
        result["status"] = "BLOCKED_UNSCANNED"
    else:
        result["status"] = "SAFETY_CHECK_OK"
    return result


# ---------------- safetensors ----------------
def inspect_safetensors(path: Path, max_header: int = 100 * 1024 * 1024) -> dict[str, Any]:
    """ヘッダのみ検査（重みはデコードしない）。"""
    size = path.stat().st_size
    with open(path, "rb") as f:
        head = f.read(8)
        if len(head) != 8:
            raise StudioError("BAD_FILE", f"{path.name}: safetensors として短すぎます")
        (n,) = struct.unpack("<Q", head)
        if n <= 0 or n > max_header or n + 8 > size:
            raise StudioError("BAD_FILE", f"{path.name}: safetensors ヘッダ長が不正 ({n})")
        raw = f.read(n)
    try:
        header = json.loads(raw.decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        raise StudioError("BAD_FILE", f"{path.name}: safetensors ヘッダが JSON ではありません: {e}") from e
    meta = header.pop("__metadata__", {}) or {}
    max_end = 0
    for name, t in header.items():
        if not isinstance(t, dict) or "data_offsets" not in t:
            raise StudioError("BAD_FILE", f"{path.name}: テンソル {name} の記述が不正")
        s, e = t["data_offsets"]
        if not (0 <= s <= e):
            raise StudioError("BAD_FILE", f"{path.name}: data_offsets が不正")
        max_end = max(max_end, e)
    if 8 + n + max_end > size:
        raise StudioError("BAD_FILE", f"{path.name}: ファイルが途中で切れています")
    markers = sorted(k for k in ("v_pred", "ztsnr") if k in header)  # v-prediction 系チェックポイントの目印
    return {"format": "safetensors", "tensor_count": len(header), "special_keys": markers,
            "metadata_keys": sorted(meta.keys())[:50],
            "metadata_sample": {k: str(v)[:200] for k, v in list(meta.items())[:10]}}


# ---------------- archives ----------------
def inspect_archive(path: Path) -> dict[str, Any]:
    comp = path.stat().st_size or 1
    total = 0
    members: list[str] = []
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            if len(infos) > MAX_ARCHIVE_MEMBERS:
                raise StudioError("ARCHIVE_REJECTED", "メンバー数が多すぎます")
            for i in infos:
                if i.flag_bits & 0x1:
                    raise StudioError("ARCHIVE_REJECTED", f"暗号化メンバー: {i.filename}")
                _check_member_name(i.filename)
                if (i.external_attr >> 16) & 0o170000 == 0o120000:
                    raise StudioError("ARCHIVE_REJECTED", f"symlink: {i.filename}")
                total += i.file_size
                members.append(i.filename)
        kind = "zip"
    elif tarfile.is_tarfile(path):
        with tarfile.open(path) as t:
            for i in t.getmembers():
                _check_member_name(i.name)
                if i.issym() or i.islnk() or i.isdev():
                    raise StudioError("ARCHIVE_REJECTED", f"リンク/デバイス: {i.name}")
                total += i.size
                members.append(i.name)
                if len(members) > MAX_ARCHIVE_MEMBERS:
                    raise StudioError("ARCHIVE_REJECTED", "メンバー数が多すぎます")
        kind = "tar"
    else:
        raise StudioError("ARCHIVE_REJECTED", f"未対応の圧縮形式: {path.name}")
    if total > MAX_ARCHIVE_TOTAL or total / comp > MAX_ARCHIVE_RATIO:
        raise StudioError("ARCHIVE_REJECTED", f"展開後サイズ/圧縮率が異常（{total} bytes, 比 {total/comp:.0f}）")
    return {"kind": kind, "members": members, "total_uncompressed": total}


def _check_member_name(name: str) -> None:
    p = Path(name)
    if name.startswith(("/", "\\")) or ".." in p.parts or re.match(r"^[A-Za-z]:", name):
        raise StudioError("ARCHIVE_REJECTED", f"パストラバーサル: {name}")


def safe_extract(path: Path, dest: Path) -> list[Path]:
    """inspect_archive を通過したものだけ展開する。展開後は必ず再スキャンすること。"""
    info = inspect_archive(path)
    dest.mkdir(parents=True, exist_ok=True)
    if info["kind"] == "zip":
        with zipfile.ZipFile(path) as z:
            z.extractall(dest)
    else:
        with tarfile.open(path) as t:
            t.extractall(dest, filter="data")
    return [p for p in dest.rglob("*") if p.is_file()]


def is_archive(path: Path) -> bool:
    return path.suffix.lower() in {".zip", ".tar", ".gz", ".tgz", ".xz", ".bz2", ".7z", ".rar"}
