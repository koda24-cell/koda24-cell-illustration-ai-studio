import pytest
from conftest import ROOT, image_entry, write_allowlist

from studio import jobspec
from studio.allowlist import Allowlist, NotAllowed, parse_civitai_url
from studio.util import StudioError

GOOD = {"id": "test-ckpt", "kind": "checkpoint", "source": "civitai",
        "civitai": {"model_id": 1, "version_id": 2, "file_id": 3}, "filename": "a.safetensors",
        "sha256": "a" * 64, "base_model": "SD 1.5", "added_by_user_instruction": "pytest"}


def test_repository_allowlist_is_empty_initially():
    al = Allowlist.load()
    assert al.is_empty(), "初期状態の許可リストは空であること"


def test_valid_entry(tmp_path):
    m, i = write_allowlist(tmp_path, [GOOD])
    al = Allowlist.load(m, i)
    assert al.require_model("test-ckpt", {"checkpoint"}).id == "test-ckpt"


@pytest.mark.parametrize("patch,needle", [
    ({"sha256": ""}, "sha256"),
    ({"added_by_user_instruction": ""}, "added_by_user_instruction"),
    ({"filename": "x.ckpt"}, "pickle"),
    ({"civitai": {"model_id": 1}}, "version_id"),
    ({"kind": "magic"}, "kind"),
    ({"filename": "../evil.safetensors"}, "パス移動"),
])
def test_invalid_entries_rejected(tmp_path, patch, needle):
    m, i = write_allowlist(tmp_path, [{**GOOD, **patch}])
    with pytest.raises(StudioError) as e:
        Allowlist.load(m, i)
    assert needle in str(e.value)


def test_not_allowed(tmp_path):
    m, i = write_allowlist(tmp_path, [GOOD])
    al = Allowlist.load(m, i)
    with pytest.raises(NotAllowed):
        al.require_model("unknown")
    with pytest.raises(NotAllowed):
        al.require_model("test-ckpt", {"lora"})


def test_parse_civitai_url():
    assert parse_civitai_url("https://civitai.com/models/123/foo?modelVersionId=456") == {"model_id": 123, "version_id": 456}
    assert parse_civitai_url("https://civitai.com/api/download/models/789")["version_id"] == 789
    with pytest.raises(StudioError):
        parse_civitai_url("https://example.com/models/1")


def _job(**stage):
    return jobspec.normalize({"job_id": "t", "backend": "diffusers",
                              "stages": [{"name": "a", "op": "txt2img", "prompt": "x", **stage}]})


def test_job_rejects_unlisted_models(tmp_path):
    m, i = write_allowlist(tmp_path, [GOOD])
    al = Allowlist.load(m, i)
    jobspec.validate_against_allowlist(_job(model="test-ckpt"), al)
    with pytest.raises(NotAllowed):
        jobspec.validate_against_allowlist(_job(model="popular-model"), al)
    with pytest.raises(NotAllowed):
        jobspec.validate_against_allowlist(_job(model="test-ckpt", loras=[{"id": "x", "weight": 1}]), al)


def test_job_auto_model_picks_only_allowed(tmp_path):
    m, i = write_allowlist(tmp_path, [GOOD])
    job = _job(model="auto")
    jobspec.validate_against_allowlist(job, Allowlist.load(m, i))
    assert job["stages"][0]["model"] == "test-ckpt"
    sub = tmp_path / "empty"
    sub.mkdir()
    m2, i2 = write_allowlist(sub, [])
    with pytest.raises(NotAllowed):
        jobspec.validate_against_allowlist(_job(model="auto"), Allowlist.load(m2, i2))


def test_job_rejects_url_and_unlisted_images(tmp_path, test_images):
    m, i = write_allowlist(tmp_path, [GOOD], [image_entry("ref1", test_images["ref_vivid"])])
    al = Allowlist.load(m, i)
    ok = _job(model="test-ckpt")
    ok["evaluation"]["references"] = ["images:ref1"]
    jobspec.validate_against_allowlist(ok, al)
    for bad in ("https://example.com/a.png", "images:nope", "/etc/passwd"):
        j = _job(model="test-ckpt")
        j["evaluation"]["references"] = [bad]
        with pytest.raises(NotAllowed):
            jobspec.validate_against_allowlist(j, al)


def test_image_hash_checked(tmp_path, test_images):
    e = image_entry("ref1", test_images["ref_vivid"])
    e["sha256"] = "0" * 64
    m, i = write_allowlist(tmp_path, [], [e])
    with pytest.raises(StudioError) as ex:
        jobspec.load_allowed_image(Allowlist.load(m, i), "ref1")
    assert ex.value.code == "HASH_MISMATCH"


def test_time_budget_and_retry_limits():
    with pytest.raises(StudioError):
        jobspec.normalize({"job_id": "t", "time_budget_minutes": 400, "stages": [{"name": "a", "op": "txt2img"}]})
    with pytest.raises(StudioError):
        jobspec.normalize({"job_id": "t", "limits": {"max_error_retries": 5}, "stages": [{"name": "a", "op": "txt2img"}]})
