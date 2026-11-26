import io
import json
import struct
import tarfile
import zipfile

import pytest
from conftest import write_allowlist

from studio import fetch, scan
from studio.allowlist import Allowlist
from studio.util import StudioError, sha256_bytes


def make_safetensors(n=4) -> bytes:
    header = {"w": {"dtype": "F32", "shape": [n], "data_offsets": [0, 4 * n]}, "__metadata__": {"a": "b"}}
    h = json.dumps(header).encode()
    return struct.pack("<Q", len(h)) + h + b"\0" * (4 * n)


def test_safetensors_header(tmp_path):
    p = tmp_path / "m.safetensors"
    p.write_bytes(make_safetensors())
    assert scan.inspect_safetensors(p)["tensor_count"] == 1
    p.write_bytes(make_safetensors()[:-4])
    with pytest.raises(StudioError):
        scan.inspect_safetensors(p)
    p.write_bytes(b"\x80\x02pickle")
    with pytest.raises(StudioError):
        scan.inspect_safetensors(p)


def test_archive_traversal_rejected(tmp_path):
    z = tmp_path / "a.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("../../evil.txt", "x")
    with pytest.raises(StudioError):
        scan.inspect_archive(z)
    t = tmp_path / "b.tar"
    with tarfile.open(t, "w") as f:
        info = tarfile.TarInfo("link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        f.addfile(info)
    with pytest.raises(StudioError):
        scan.inspect_archive(t)


def test_zip_bomb_ratio_rejected(tmp_path):
    z = tmp_path / "bomb.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as f:
        f.writestr("zeros.bin", b"\0" * 50_000_000)
    with pytest.raises(StudioError):
        scan.inspect_archive(z)


def test_clamav_missing_blocks(monkeypatch, tmp_path):
    monkeypatch.setattr(scan.shutil, "which", lambda _: None)
    p = tmp_path / "x"
    p.write_text("x")
    with pytest.raises(StudioError) as e:
        scan.clamscan([p])
    assert e.value.code == "BLOCKED_UNSCANNED"


@pytest.fixture
def fake_env(tmp_path, monkeypatch):
    data = make_safetensors()
    entry = {"id": "m1", "kind": "lora", "source": "civitai", "civitai": {"model_id": 1, "version_id": 2},
             "filename": "m1.safetensors", "sha256": sha256_bytes(data), "added_by_user_instruction": "pytest"}
    m, i = write_allowlist(tmp_path, [entry])
    monkeypatch.setenv("STUDIO_CACHE", str(tmp_path / "cache"))
    payload = {"data": data}

    def fake_download(version_id, meta, dest, file_id=None):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(payload["data"])
        return dest

    scan_result = {"status": "SAFETY_CHECK_OK"}

    def fake_clamscan(paths, log_path=None):
        if log_path:
            log_path.write_text("fake")
        return {"status": scan_result["status"], "exit_code": 0, "detections": []}

    monkeypatch.setattr(fetch.civitai, "download_file", fake_download)
    monkeypatch.setattr(fetch.scan, "clamscan", fake_clamscan)
    return Allowlist.load(m, i), payload, scan_result


def test_fetch_ok_and_cached(fake_env):
    al, _, _ = fake_env
    r = fetch.fetch_all(al)
    assert r[0]["status"] == "SAFETY_CHECK_OK"
    assert fetch.verify_cached(al.models["m1"])
    assert fetch.fetch_all(al)[0]["status"] == "CACHED"


def test_fetch_hash_mismatch_not_cached(fake_env):
    al, payload, _ = fake_env
    payload["data"] = make_safetensors(8)
    r = fetch.fetch_all(al)
    assert r[0]["status"] == "HASH_MISMATCH"
    with pytest.raises(StudioError):
        fetch.verify_cached(al.models["m1"])


def test_fetch_detection_quarantined(fake_env):
    al, _, sr = fake_env
    sr["status"] = "QUARANTINED_DETECTION"
    assert fetch.fetch_all(al)[0]["status"] == "QUARANTINED_DETECTION"
    assert not fetch.is_cached(al.models["m1"])


def test_fetch_unlisted_refused(fake_env):
    al, _, _ = fake_env
    with pytest.raises(StudioError):
        fetch.fetch_all(al, ["not-listed"])


def test_large_file_scanned_in_chunks(monkeypatch, tmp_path):
    import subprocess as sp
    monkeypatch.setattr(scan, "require_clamav", lambda: {"version_string": "fake", "db_age_hours": 1})
    monkeypatch.setattr(scan, "CHUNK_THRESHOLD", 1000)
    monkeypatch.setattr(scan, "CHUNK_SIZE", 400)
    monkeypatch.setattr(scan, "CHUNK_OVERLAP", 10)
    seen = []

    def fake_run(paths):
        seen.append(paths[0].stat().st_size)
        return sp.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(scan, "_run_clamscan", fake_run)
    p = tmp_path / "big.safetensors"
    p.write_bytes(b"x" * 1500)
    r = scan.clamscan([p])
    assert r["status"] == "SAFETY_CHECK_OK"
    assert r["methods"][0]["method"] == "chunked" and r["methods"][0]["chunks"] == 4
    assert seen == [410, 410, 410, 300]
    assert not any(x.name.startswith(".scan-chunks") for x in tmp_path.iterdir())

    def detect(paths):
        return sp.CompletedProcess([], 1, f"{paths[0]}: Eicar FOUND\n", "")

    monkeypatch.setattr(scan, "_run_clamscan", detect)
    assert scan.clamscan([p])["status"] == "QUARANTINED_DETECTION"
