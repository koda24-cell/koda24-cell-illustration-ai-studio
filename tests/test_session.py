import json

import pytest
from conftest import ROOT, image_entry, write_allowlist
from PIL import Image

from studio import evaluate, improve, jobspec, site
from studio.allowlist import Allowlist
from studio.backends.procedural import ProceduralBackend
from studio.budget import lint_workflows
from studio.session import Session
from studio.util import StudioError, load_json


def job(**over):
    base = {"job_id": "t", "backend": "procedural", "time_budget_minutes": 10,
            "limits": {"max_rounds": 3, "candidates_per_round": 2, "patience": 5, "target_score": 1.5},
            "defaults": {"width": 64, "height": 64, "steps": 8},
            "stages": [{"name": "base", "op": "txt2img", "prompt": "p"}]}
    base.update(over)
    return jobspec.normalize(base)


def test_selftest_job_runs(tmp_path):
    j = jobspec.load_job(ROOT / "jobs" / "examples" / "selftest-procedural.yaml")
    st = Session(j, Allowlist.load(), runs_dir=tmp_path, run_id="r").run()
    assert st["status"] == "completed"
    run = load_json(tmp_path / "r" / "run.json")
    assert run["stages"]["cutout"]["best"]["image"].endswith(".png")
    assert Image.open(tmp_path / "r" / "stages" / "cutout" / "best.png").mode == "RGBA"
    assert (tmp_path / "r" / "plan.md").exists()
    assert (tmp_path / "r" / "comparisons" / "base_latest.png").exists()


class FlakyBackend(ProceduralBackend):
    def __init__(self, fails, exc=RuntimeError("boom")):
        self.fails = fails
        self.exc = exc

    def run(self, op, params, inputs):
        if self.fails > 0:
            self.fails -= 1
            raise self.exc
        return super().run(op, params, inputs)


def test_retry_recovers(tmp_path):
    st = Session(job(), Allowlist.load(), runs_dir=tmp_path, run_id="r", backend=FlakyBackend(2)).run()
    assert st["status"] == "completed" and st["errors_recovered"] == 2


def test_retry_limit_three(tmp_path):
    st = Session(job(), Allowlist.load(), runs_dir=tmp_path, run_id="r", backend=FlakyBackend(10)).run()
    assert st["status"] == "failed" and st["errors_recovered"] == 3
    assert st["fatal_error"]["code"] == "RETRY_EXHAUSTED"


def test_fatal_error_not_retried(tmp_path):
    b = FlakyBackend(1, StudioError("DEPENDENCY_MISSING", "x"))
    st = Session(job(), Allowlist.load(), runs_dir=tmp_path, run_id="r", backend=b).run()
    assert st["status"] == "failed" and st["errors_recovered"] == 0


def test_oom_reduces_size(tmp_path):
    b = FlakyBackend(1, MemoryError())
    st = Session(job(defaults={"width": 512, "height": 512, "steps": 8}), Allowlist.load(), runs_dir=tmp_path,
                 run_id="r", backend=b).run()
    meta = load_json(tmp_path / "r" / "stages" / "base" / "r00_c0.json")
    assert meta["params"]["width"] == 384


def test_time_budget_stop_and_resume(tmp_path):
    t = {"now": 0.0}

    class SlowBackend(ProceduralBackend):
        def run(self, op, params, inputs):
            t["now"] += 120  # 1候補 2分
            return super().run(op, params, inputs)

    j = job(time_budget_minutes=10, limits={"max_rounds": 10, "candidates_per_round": 2, "patience": 99,
                                            "target_score": 1.5})
    st = Session(j, Allowlist.load(), runs_dir=tmp_path, run_id="r", backend=SlowBackend(),
                 clock=lambda: t["now"]).run()
    assert st["status"] == "time_budget_exhausted"
    done = len(st["stages"]["base"]["rounds"])
    assert 1 <= done < 10
    # 再開（新しい時間予算）
    t["now"] = 0.0
    j2 = dict(st["job"])
    j2["time_budget_minutes"] = st["elapsed_total_min"] + 10
    s2 = Session(jobspec.normalize(j2), Allowlist.load(), runs_dir=tmp_path, run_id="r", backend=SlowBackend(),
                 clock=lambda: t["now"])
    assert s2.resumed
    st2 = s2.run()
    assert len(st2["stages"]["base"]["rounds"]) > done
    assert len(st2["sessions"]) == 2


def test_target_score_stops_early(tmp_path):
    j = job(limits={"max_rounds": 10, "candidates_per_round": 1, "patience": 99, "target_score": 0.1},
            evaluation={"metrics": ["artifacts"]})
    st = Session(j, Allowlist.load(), runs_dir=tmp_path, run_id="r").run()
    assert st["stages"]["base"]["stop_reason"] == "target_reached"
    assert len(st["stages"]["base"]["rounds"]) == 1


def test_evaluation_with_reference_and_improvement(test_images):
    vivid = Image.open(test_images["ref_vivid"])
    muted = Image.open(test_images["ref_muted"])
    e = evaluate.evaluate(muted, [vivid])
    assert e["overall"] is not None
    for k in ("color", "value_saturation", "similarity"):
        assert e["metrics"][k]["score"] is not None and e["metrics"][k]["limitations"]
    assert e["metrics"]["pose"]["score"] is None  # 姿勢推定モデル無し
    same = evaluate.evaluate(vivid, [vivid])
    assert same["metrics"]["color"]["score"] > e["metrics"]["color"]["score"]
    p, changes = improve.adjust({"prompt": "girl", "cfg": 7}, e, ["prompt", "cfg"], 0, "txt2img")
    assert "vibrant colors" in p["prompt"] and changes


def test_private_derivatives_not_published(tmp_path, test_images):
    m, i = write_allowlist(tmp_path, [], [image_entry("pub", test_images["ref_vivid"], True),
                                          image_entry("priv", test_images["private_ref"], False)])
    al = Allowlist.load(m, i)
    j = job(stages=[{"name": "a", "op": "img2img", "init": "images:pub", "prompt": "p"},
                    {"name": "b", "op": "img2img", "init": "images:priv", "prompt": "p"},
                    {"name": "c", "op": "upscale", "init": "stage:b"}])
    Session(j, al, runs_dir=tmp_path / "runs", run_id="r").run()
    out = tmp_path / "site"
    site.build(tmp_path / "runs", out, al)
    data = json.loads((out / "data.json").read_text())
    st = {s["name"]: s for s in data["runs"][0]["stages"]}
    assert st["a"]["publishable"] and not st["b"]["publishable"] and not st["c"]["publishable"]
    assert (out / "runs" / "r" / "stages" / "a").exists()
    assert not (out / "runs" / "r" / "stages" / "b").exists()
    assert not (out / "runs" / "r" / "stages" / "c").exists()
    refs = {r["id"] for r in data["references"]}
    assert refs == {"pub"}


def test_workflows_use_free_runners_only():
    assert lint_workflows() == []


def test_stage_level_limits(tmp_path):
    j = job(stages=[{"name": "a", "op": "txt2img", "prompt": "p", "limits": {"max_rounds": 1, "candidates_per_round": 1}},
                    {"name": "b", "op": "txt2img", "prompt": "p"}])
    st = Session(j, Allowlist.load(), runs_dir=tmp_path, run_id="r").run()
    assert len(st["stages"]["a"]["rounds"]) == 1 and len(st["stages"]["a"]["rounds"][0]["candidates"]) == 1
    assert len(st["stages"]["b"]["rounds"]) == 3
