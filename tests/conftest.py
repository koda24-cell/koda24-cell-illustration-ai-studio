import shutil
import sys
from pathlib import Path

import numpy as np
import pytest
import yaml
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from studio.util import sha256_file  # noqa: E402


@pytest.fixture
def test_images():
    """リポジトリ内の一時フォルダにテスト画像を作る（終了時に削除）。"""
    d = ROOT / "inputs" / "images" / "_pytest_tmp"
    d.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(0)
    paths = {}
    for name, col in (("ref_vivid", (230, 40, 90)), ("ref_muted", (120, 110, 115)), ("private_ref", (20, 160, 60))):
        arr = np.full((96, 96, 3), col, dtype=np.uint8)
        arr[20:76, 30:66] = 255 - np.array(col, dtype=np.uint8)
        arr = np.clip(arr.astype(int) + rng.integers(-8, 8, arr.shape), 0, 255).astype(np.uint8)
        p = d / f"{name}.png"
        Image.fromarray(arr).save(p)
        paths[name] = p
    yield paths
    shutil.rmtree(d, ignore_errors=True)


def write_allowlist(tmp_path, models=None, images=None):
    m = tmp_path / "models.yaml"
    i = tmp_path / "images.yaml"
    m.write_text(yaml.safe_dump({"version": 1, "models": models or []}, allow_unicode=True))
    i.write_text(yaml.safe_dump({"version": 1, "images": images or []}, allow_unicode=True))
    return m, i


def image_entry(iid, path, public_ok=True, roles=("reference", "init")):
    return {"id": iid, "path": str(path.relative_to(ROOT)), "sha256": sha256_file(path), "roles": list(roles),
            "public_ok": public_ok, "added_by_user_instruction": "pytest"}
