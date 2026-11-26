"""長時間制作セッション：計画 → 候補生成 → 評価 → 改善 → 再生成 …（途中保存・再開つき）。

停止条件（いずれか）:
  - 目標スコア到達 / patience ラウンド改善なし / max_rounds 到達
  - 時間予算（≤345分）切れ：次ラウンドの推定時間が残り時間を超えたら開始しない
  - 致命的エラー（許可リスト外・依存不足・ハッシュ不一致など）
  - 復旧可能エラーの再試行が 3 回を超えた
"""
from __future__ import annotations

import copy
import json
import os
import random
import subprocess
import time
import traceback
from pathlib import Path
from typing import Any

from PIL import Image, PngImagePlugin

from . import evaluate as ev
from . import imageops, improve, jobspec, ledger, recipes
from .allowlist import Allowlist
from .backends import get_backend
from .util import REPO_ROOT, StudioError, append_jsonl, dump_json, load_json, now_iso

FATAL_CODES = {"NOT_ALLOWED", "DEPENDENCY_MISSING", "MODEL_NOT_CACHED", "HASH_MISMATCH", "BLOCKED_UNSCANNED",
               "UNSUPPORTED_ARCH", "BAD_INPUT", "SECRET_MISSING", "DECRYPT_FAILED", "TOOL_MISSING",
               "ALLOWLIST_INVALID", "BUDGET_EXCEEDED"}
RUNS_DIR = Path(os.environ.get("STUDIO_RUNS_DIR", REPO_ROOT / "runs"))


def classify_error(exc: BaseException) -> dict[str, Any]:
    text = f"{type(exc).__name__}: {exc}"
    if isinstance(exc, StudioError):
        return {"code": exc.code, "fatal": exc.code in FATAL_CODES, "analysis": exc.message, "mitigation": None}
    low = text.lower()
    if isinstance(exc, MemoryError) or "out of memory" in low or "defaultcpuallocator" in low \
            or "can't allocate memory" in low:
        return {"code": "OOM", "fatal": False, "analysis": "メモリ不足", "mitigation": "reduce_size"}
    if isinstance(exc, (ImportError, ModuleNotFoundError)):
        return {"code": "TOOL_MISSING", "fatal": True, "analysis": text, "mitigation": None}
    if "connection" in low or "timed out" in low or "offline" in low:
        return {"code": "NETWORK_OR_OFFLINE", "fatal": False,
                "analysis": "通信関連。生成中は外部取得を禁止しているため、構成ファイル不足の可能性", "mitigation": None}
    return {"code": "RUNTIME", "fatal": False, "analysis": text[:500], "mitigation": None}


def _save_png(img: Image.Image, path: Path, meta: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    info = PngImagePlugin.PngInfo()
    info.add_text("studio:params", json.dumps(meta, ensure_ascii=False)[:60000])
    img.save(path, pnginfo=info)


class Session:
    def __init__(self, job: dict[str, Any], al: Allowlist, run_id: str | None = None,
                 runs_dir: Path | None = None, backend: Any = None, clock=time.time):
        self.job = job
        self.al = al
        self.clock = clock
        self.runs_dir = Path(runs_dir or RUNS_DIR)
        self.run_id = run_id or f"{job['job_id']}-{time.strftime('%Y%m%d-%H%M%S')}"
        self.dir = self.runs_dir / self.run_id
        self.state_path = self.dir / "state.json"
        self.state: dict[str, Any] = load_json(self.state_path, None) or {}
        self.resumed = bool(self.state)
        self._backend = backend
        self.t_start = self.clock()
        self._last_ckpt = 0.0
        self._image_cache: dict[str, Image.Image] = {}

    # ---------- 基本 ----------
    @property
    def backend(self):
        if self._backend is None:
            self._backend = get_backend(self.job["backend"], self.al, self.job)
        return self._backend

    def elapsed_min(self) -> float:
        return self.state.get("elapsed_before_min", 0.0) + (self.clock() - self.t_start) / 60

    def remaining_min(self) -> float:
        return self.job["time_budget_minutes"] - self.elapsed_min()

    def log(self, event: str, **kw: Any) -> None:
        append_jsonl(self.dir / "log.jsonl", {"t": now_iso(), "event": event, **kw})

    def save_state(self, force_ckpt: bool = False) -> None:
        self.state["elapsed_total_min"] = round(self.elapsed_min(), 2)
        dump_json(self.state_path, self.state)
        interval = float(os.environ.get("STUDIO_CHECKPOINT_INTERVAL_SEC", "600"))
        cmd = os.environ.get("STUDIO_CHECKPOINT_CMD")
        if cmd and (force_ckpt or self.clock() - self._last_ckpt >= interval):
            self._last_ckpt = self.clock()
            r = subprocess.run([*cmd.split(), str(self.dir)], capture_output=True, text=True)
            self.log("checkpoint", exit_code=r.returncode, stderr=r.stderr[-500:])

    # ---------- 計画 ----------
    def write_plan(self, validation: dict[str, Any]) -> None:
        j = self.job
        lines = [f"# 制作計画: {j.get('title', j['job_id'])}", "",
                 f"- run_id: `{self.run_id}`", f"- backend: `{j['backend']}`",
                 f"- 時間予算: {j['time_budget_minutes']} 分 / 上限ラウンド {j['limits']['max_rounds']}"
                 f" / 候補数 {j['limits']['candidates_per_round']} / 目標スコア {j['limits']['target_score']}",
                 f"- 使用モデル（許可リスト内）: {', '.join(validation['models']) or 'なし'}",
                 f"- 評価用参考画像: {', '.join(map(str, j['evaluation'].get('references') or [])) or 'なし'}",
                 "", "## ステージ"]
        for s in j["stages"]:
            lines.append(f"- **{s['name']}** `{s['op']}` {('入力: ' + str(s.get('init'))) if s.get('init') else ''}")
        lines += ["", "自動評価は改善の参考値であり、最終的な採用判断はユーザーが行う。"]
        (self.dir / "plan.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ---------- 画像参照 ----------
    def resolve_image(self, ref: Any, role: str | None = None) -> Image.Image:
        ref = str(ref)
        if ref in self._image_cache:
            return self._image_cache[ref]
        if ref.startswith("images:"):
            img = jobspec.load_allowed_image(self.al, ref.split(":", 1)[1], role)
        elif ref.startswith("stage:"):
            name = ref.split(":", 1)[1]
            best = self.state["stages"].get(name, {}).get("best")
            if not best:
                raise StudioError("BAD_INPUT", f"{ref} の成果物がありません")
            img = Image.open(self.dir / best["image"]).copy()
        elif ref.startswith("run:"):
            run, name = ref.split(":", 1)[1].split("/", 1)
            st = load_json(self.runs_dir / run / "state.json", {})
            best = st.get("stages", {}).get(name, {}).get("best")
            if not best:
                raise StudioError("BAD_INPUT", f"{ref} が見つかりません")
            img = Image.open(self.runs_dir / run / best["image"]).copy()
        else:
            raise StudioError("BAD_INPUT", f"不正な画像参照 {ref}")
        self._image_cache[ref] = img
        return img

    def private_inputs(self, stage: dict[str, Any]) -> list[str]:
        """非公開（public_ok=false 且つ派生物公開不可）の入力を返す。サイト掲載判定に使う。"""
        out = []
        p = jobspec.stage_params(self.job, stage)
        refs = [stage.get("init"), stage.get("background"), (p.get("controlnet") or {}).get("image"),
                (p.get("ip_adapter") or {}).get("image")]
        if isinstance(stage.get("mask"), str):
            refs.append(stage["mask"])
        for r in refs:
            if isinstance(r, str) and r.startswith("images:"):
                e = self.al.images[r.split(":", 1)[1]]
                if not (e.public_ok or e.derivatives_public_ok):
                    out.append(r)
            elif isinstance(r, str) and r.startswith("stage:"):
                prev = self.state["stages"].get(r.split(":", 1)[1], {})
                out.extend(prev.get("private_inputs", []))
        return sorted(set(out))

    # ---------- 実行 ----------
    def run(self) -> dict[str, Any]:
        self.dir.mkdir(parents=True, exist_ok=True)
        validation = jobspec.validate_against_allowlist(self.job, self.al)
        if not self.state:
            self.state = {"run_id": self.run_id, "job": self.job, "created_at": now_iso(), "status": "running",
                          "stages": {}, "errors_recovered": 0, "elapsed_before_min": 0.0, "sessions": []}
            self.write_plan(validation)
            dump_json(self.dir / "job.json", self.job)
        else:
            self.state["elapsed_before_min"] = self.state.get("elapsed_total_min", 0.0)
            self.state["status"] = "running"
        self.state["sessions"].append({"started_at": now_iso(), "resumed": self.resumed})
        self.log("session_start", resumed=self.resumed, remaining_min=round(self.remaining_min(), 1))
        refs = [self.resolve_image(r, "reference") for r in self.job["evaluation"].get("references") or []]
        self._refs = refs

        final_status = "completed"
        try:
            for stage in self.job["stages"]:
                ss = self.state["stages"].setdefault(stage["name"], {"status": "pending", "rounds": []})
                if ss["status"] == "done":
                    continue
                if self.remaining_min() <= 1:
                    final_status = "time_budget_exhausted"
                    break
                ss["private_inputs"] = self.private_inputs(stage)
                if stage["op"] in recipes.MODEL_FREE_OPS:
                    self._run_model_free(stage, ss)
                else:
                    reason = self._run_generative(stage, ss)
                    if reason == "time_budget":
                        final_status = "time_budget_exhausted"
                        break
                self.save_state()
        except StudioError as e:
            info = classify_error(e)
            final_status = "failed"
            self.state["fatal_error"] = info
            append_jsonl(self.dir / "errors.jsonl", {"t": now_iso(), **info})
        except Exception as e:  # noqa: BLE001  想定外でも状態は保存して再開可能にする
            info = classify_error(e)
            final_status = "failed"
            self.state["fatal_error"] = {**info, "traceback": traceback.format_exc()[-2000:]}
            append_jsonl(self.dir / "errors.jsonl", {"t": now_iso(), **self.state["fatal_error"]})
        self.state["status"] = final_status
        self.state["sessions"][-1]["ended_at"] = now_iso()
        self.state["finished_at"] = now_iso()
        self.save_state(force_ckpt=True)
        self._write_run_summary(validation)
        self.log("session_end", status=final_status)
        return self.state

    def _call_backend(self, op: str, params: dict[str, Any], inputs: dict[str, Image.Image],
                      ss: dict[str, Any]) -> tuple[Image.Image, dict[str, Any]]:
        """最大3回まで復旧・再試行。致命的エラーは即停止。"""
        limit = int(self.job["limits"]["max_error_retries"])
        params = copy.deepcopy(params)
        while True:
            try:
                return self.backend.run(op, params, inputs), params
            except Exception as exc:  # noqa: BLE001
                info = classify_error(exc)
                rec = {"t": now_iso(), "stage": ss.get("name"), "op": op, **info,
                       "traceback": traceback.format_exc()[-2000:]}
                append_jsonl(self.dir / "errors.jsonl", rec)
                if info["fatal"]:
                    raise exc if isinstance(exc, StudioError) else StudioError(info["code"], info["analysis"])
                if self.state["errors_recovered"] >= limit:
                    raise StudioError("RETRY_EXHAUSTED",
                                      f"再試行上限（{limit}回）に達しました。最後のエラー: {info['analysis']}")
                self.state["errors_recovered"] += 1
                if info["mitigation"] == "reduce_size" and op == "txt2img":
                    params["width"] = max(256, int(params["width"] * 0.75) // 8 * 8)
                    params["height"] = max(256, int(params["height"] * 0.75) // 8 * 8)
                self.log("retry", count=self.state["errors_recovered"], code=info["code"],
                         mitigation=info["mitigation"])

    def _inputs_for(self, stage: dict[str, Any], params: dict[str, Any]) -> tuple[str, dict[str, Image.Image]]:
        op = stage["op"]
        inputs: dict[str, Image.Image] = {}
        if stage.get("init"):
            inputs["init"] = imageops.to_rgb(self.resolve_image(stage["init"], "init"))
        if op == "outpaint":
            o = stage.get("outpaint") or {}
            canvas, mask = imageops.pad_for_outpaint(inputs["init"], o.get("left", 0), o.get("top", 0),
                                                     o.get("right", 0), o.get("bottom", 0))
            inputs.update(init=canvas, mask=mask)
            op = "inpaint"
            params.setdefault("denoise", 1.0)
            params["denoise"] = max(float(params["denoise"]), 0.9)
        elif op == "inpaint":
            m = stage.get("mask")
            if isinstance(m, dict) and "rect" in m:
                inputs["mask"] = imageops.rect_mask(inputs["init"].size, m["rect"], m.get("feather", 8))
            elif isinstance(m, str):
                inputs["mask"] = self.resolve_image(m, "mask").convert("L").resize(inputs["init"].size)
            else:
                raise StudioError("BAD_INPUT", f"{stage['name']}: inpaint には mask が必要")
        elif op == "hires_upscale":
            inputs["init"] = imageops.upscale_lanczos(inputs["init"], float(stage.get("scale", 1.5)))
            op = "img2img"
        if params.get("controlnet"):
            src = self.resolve_image(params["controlnet"]["image"], "control")
            pre = params["controlnet"].get("preprocess")
            if pre == "lineart":
                src = imageops.lineart_xdog(src)
            elif pre == "canny":
                src = imageops.canny_like(src)
            inputs["control"] = src
        if params.get("ip_adapter"):
            inputs["ip_image"] = self.resolve_image(params["ip_adapter"]["image"], "reference")
        if op in ("img2img", "inpaint"):
            params["width"], params["height"] = inputs["init"].size
        return op, inputs

    def _run_generative(self, stage: dict[str, Any], ss: dict[str, Any]) -> str:
        lim = self.job["limits"]
        ss["name"] = stage["name"]
        params = ss.get("next_params") or jobspec.stage_params(self.job, stage)
        if params.get("seed") in (None, "random"):
            params["seed"] = random.SystemRandom().randrange(0, 2**31 - 1)
        base_seed = int(ss.setdefault("base_seed", params["seed"]))
        cons_base = self.resolve_image(stage["consistency_base"], "init") if stage.get("consistency_base") else None
        allowed = self.job["improve"].get("tune", []) if self.job["improve"].get("enabled", True) else []
        stop = None
        while True:
            r = len(ss["rounds"])
            if r >= lim["max_rounds"]:
                stop = "max_rounds"
                break
            est = ss.get("sec_per_candidate", 0) * lim["candidates_per_round"] / 60
            if est and est + 2 > self.remaining_min():
                stop = "time_budget"
                break
            run_params = copy.deepcopy(params)
            op, inputs = self._inputs_for(stage, run_params)
            cands = []
            for k in range(lim["candidates_per_round"]):
                cp = copy.deepcopy(run_params)
                # 既定は全ラウンド同じ seed 群（パラメータ変更の効果を比較しやすくする）
                cp["seed"] = base_seed + k + (r * 1000 if lim.get("vary_seeds") else 0)
                t0 = self.clock()
                img, used = self._call_backend(op, cp, inputs, ss)
                secs = self.clock() - t0
                evaluation = ev.evaluate(img, self._refs, base=cons_base,
                                         metrics=self.job["evaluation"].get("metrics"),
                                         weights=self.job["evaluation"].get("weights"), prompt=used.get("prompt"))
                rel = f"stages/{stage['name']}/r{r:02d}_c{k}.png"
                meta = {"run_id": self.run_id, "stage": stage["name"], "round": r, "candidate": k, "op": stage["op"],
                        "params": used, "seconds": round(secs, 2), "evaluation": evaluation, "created_at": now_iso(),
                        "backend": self.job["backend"]}
                _save_png(img, self.dir / rel, {"params": used, "op": stage["op"]})
                dump_json((self.dir / rel).with_suffix(".json"), meta)
                cands.append({"image": rel, "score": evaluation["overall"], "seconds": secs})
                n = ss.get("n_done", 0)
                ss["sec_per_candidate"] = (ss.get("sec_per_candidate", 0) * n + secs) / (n + 1)
                ss["n_done"] = n + 1
            best_c = max(cands, key=lambda c: -1 if c["score"] is None else c["score"])
            round_rec = {"round": r, "params": run_params, "candidates": cands, "best": best_c["image"],
                         "best_score": best_c["score"]}
            prev_best = ss.get("best")
            improved = prev_best is None or (best_c["score"] or 0) > (prev_best["score"] or 0) + 1e-4
            if improved:
                ss["best"] = {"image": best_c["image"], "score": best_c["score"], "round": r, "params": run_params}
                Image.open(self.dir / best_c["image"]).save(self.dir / f"stages/{stage['name']}/best.png")
                ss["no_improve"] = 0
            else:
                ss["no_improve"] = ss.get("no_improve", 0) + 1
            if r > 0 and ss.get("first_best"):
                before = load_json((self.dir / ss["first_best"]).with_suffix(".json"))["evaluation"]
                after = load_json((self.dir / ss["best"]["image"]).with_suffix(".json"))["evaluation"]
                round_rec["vs_first"] = ev.compare(before, after)
                comp = imageops.side_by_side([Image.open(self.dir / ss["first_best"]),
                                              Image.open(self.dir / ss["best"]["image"])],
                                             [f"before r0 {before['overall']}", f"best r{ss['best']['round']} "
                                                                               f"{after['overall']}"])
                comp_rel = f"comparisons/{stage['name']}_latest.png"
                (self.dir / "comparisons").mkdir(exist_ok=True)
                comp.save(self.dir / comp_rel)
                ss["comparison"] = comp_rel
            else:
                ss["first_best"] = best_c["image"]
            # 次ラウンドの改善
            # 次ラウンドは「これまでのベスト」の設定を起点に調整する
            best_eval = load_json((self.dir / ss["best"]["image"]).with_suffix(".json"))["evaluation"]
            params, changes = improve.adjust(ss["best"]["params"], best_eval, allowed, r, stage["op"])
            round_rec["next_changes"] = changes
            ss["rounds"].append(round_rec)
            ss["next_params"] = params
            self.log("round_done", stage=stage["name"], round=r, best_score=best_c["score"], improved=improved,
                     changes=changes)
            self.save_state()
            if ss["best"]["score"] is not None and ss["best"]["score"] >= lim["target_score"]:
                stop = "target_reached"
                break
            if ss["no_improve"] >= lim["patience"]:
                stop = "no_improvement"
                break
            if not allowed:
                stop = "single_pass"
                break
        ss["status"] = "stopped" if stop == "time_budget" else "done"
        ss["stop_reason"] = stop
        if stop != "time_budget":
            ss.pop("next_params", None)
        if self.job["backend"] == "diffusers" and ss.get("best"):
            mid = jobspec.stage_params(self.job, stage).get("model")
            if mid:
                ledger.record_result(mid, self.run_id, ss["best"]["image"], ss["best"]["score"],
                                     ss.get("sec_per_candidate"),
                                     f"{params.get('width')}x{params.get('height')}")
        return stop

    def _run_model_free(self, stage: dict[str, Any], ss: dict[str, Any]) -> None:
        op = stage["op"]
        t0 = self.clock()
        src = self.resolve_image(stage["init"], "init") if stage.get("init") else None
        if op == "remove_bg":
            out = imageops.remove_bg_floodfill(src, int(stage.get("tolerance", 40)))
        elif op == "replace_bg":
            out = imageops.composite_on_background(src, self.resolve_image(stage["background"], "background"),
                                                   float(stage.get("fg_scale", 1.0)))
        elif op == "upscale":
            out = imageops.upscale_lanczos(src, float(stage.get("scale", 2.0)))
        elif op == "upscale_model":
            from .backends.diffusers_backend import upscale_with_model
            out = upscale_with_model(self.al, stage["upscaler"], src)
        elif op == "lineart_extract":
            out = imageops.lineart_xdog(src)
        elif op == "control_from":
            out = imageops.canny_like(src) if stage.get("mode") == "canny" else imageops.lineart_xdog(src)
        else:
            raise StudioError("BAD_INPUT", op)
        rel = f"stages/{stage['name']}/r00_c0.png"
        _save_png(out, self.dir / rel, {"op": op})
        evaluation = ev.evaluate(out.convert("RGB"), self._refs, metrics=["artifacts", "composition"])
        dump_json((self.dir / rel).with_suffix(".json"),
                  {"run_id": self.run_id, "stage": stage["name"], "op": op, "params": {k: v for k, v in stage.items()},
                   "seconds": round(self.clock() - t0, 2), "evaluation": evaluation, "created_at": now_iso(),
                   "backend": "model-free"})
        ss.update(status="done", stop_reason="single_pass", name=stage["name"],
                  best={"image": rel, "score": evaluation["overall"], "round": 0},
                  rounds=[{"round": 0, "candidates": [{"image": rel, "score": evaluation["overall"]}], "best": rel}])
        out.save(self.dir / f"stages/{stage['name']}/best.png")

    def _write_run_summary(self, validation: dict[str, Any]) -> None:
        models = []
        for mid in validation["models"]:
            e = self.al.models[mid]
            models.append({"id": mid, "kind": e.kind, "sha256": e.primary_file.get("sha256"),
                           "name": e.raw.get("name"), "url": e.raw.get("url")})
        private = sorted({p for s in self.state["stages"].values() for p in s.get("private_inputs", [])})
        summary = {
            "run_id": self.run_id, "job_id": self.job["job_id"], "title": self.job.get("title"),
            "status": self.state["status"], "backend": self.job["backend"],
            "backend_info": self._safe_describe(), "created_at": self.state["created_at"],
            "finished_at": self.state.get("finished_at"), "elapsed_min": round(self.elapsed_min(), 2),
            "models": models, "errors_recovered": self.state.get("errors_recovered", 0),
            "fatal_error": self.state.get("fatal_error"),
            "stages": {k: {kk: v.get(kk) for kk in ("status", "stop_reason", "best", "comparison", "private_inputs")}
                       for k, v in self.state["stages"].items()},
            "publish": bool(self.job.get("publish", True)),
            "assign_to": self.job.get("assign_to") or {},
            "approval": "unapproved（approvals/approvals.yaml でユーザーのみ変更）",
            "has_private_inputs": bool(private),
        }
        dump_json(self.dir / "run.json", summary)

    def _safe_describe(self) -> dict[str, Any]:
        try:
            return self.backend.describe() if self._backend is not None else {"backend": self.job["backend"]}
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)[:200]}
