import pytest

from studio import jobspec, recipes
from studio.util import StudioError


@pytest.mark.parametrize("r", [
    {"type": "character_standing", "prompt": "girl", "hires_scale": 1.5},
    {"type": "expression_variants", "prompt": "girl", "expressions": ["smile", "angry"]},
    {"type": "outfit_variants", "prompt": "girl", "outfits": ["armor"]},
    {"type": "pose_variants", "prompt": "girl", "poses": [{"prompt": "sitting"}]},
    {"type": "turnaround", "prompt": "girl"},
    {"type": "lineart", "prompt": "girl"},
    {"type": "colorize", "prompt": "girl", "lineart": "images:la"},
    {"type": "background", "prompt": "forest"},
    {"type": "event_still", "prompt": "battle"},
    {"type": "replace_background", "image": "images:x", "background_prompt": "beach"},
])
def test_recipes_expand_to_valid_jobs(r):
    stages = recipes.expand(r)
    assert stages
    jobspec.normalize({"job_id": "t", "recipe": r})


def test_unknown_recipe():
    with pytest.raises(StudioError):
        recipes.expand({"type": "nope"})


def test_pose_without_controlnet_falls_back_to_img2img():
    st = recipes.expand({"type": "pose_variants", "prompt": "g", "poses": [{"prompt": "run"}]})
    assert st[-1]["op"] == "img2img"
    st = recipes.expand({"type": "pose_variants", "prompt": "g", "controlnet": {"id": "cn"},
                         "poses": [{"prompt": "run", "control_image": "images:p"}]})
    assert st[-1]["op"] == "txt2img" and st[-1]["controlnet"]["image"] == "images:p"


def test_templates_are_structurally_valid():
    from conftest import ROOT
    files = sorted((ROOT / "jobs" / "templates").glob("*.yaml"))
    assert len(files) >= 10
    for f in files:
        jobspec.load_job(f)
