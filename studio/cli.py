"""コマンドライン: python -m studio <command> ..."""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
from pathlib import Path

import yaml

from . import budget, fetch, jobspec, ledger, scan, site
from .allowlist import MODELS_FILE, Allowlist
from .session import RUNS_DIR, Session
from .util import REPO_ROOT, StudioError, dump_json, load_json, load_yaml, mask_secret


def _print(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def cmd_allowlist_check(a) -> int:
    al = Allowlist.load()
    _print({"ok": True, "models": len(al.models), "images": len(al.images),
            "by_kind": {k: len(al.models_of(k)) for k in sorted({m.kind for m in al.models.values()})}})
    return 0


def cmd_allowlist_draft(a) -> int:
    from . import civitai
    if not a.instruction.strip():
        raise StudioError("BAD_INPUT", "--instruction（ユーザー指示の記録）が必須")
    draft = civitai.build_entry_draft(a.url, a.instruction, a.kind, a.file_id, a.id)
    print(yaml.safe_dump([draft], allow_unicode=True, sort_keys=False))
    if a.append:
        data = load_yaml(MODELS_FILE, {"version": 1, "models": []})
        if any(m.get("id") == draft["id"] for m in data.get("models") or []):
            raise StudioError("BAD_INPUT", f"id {draft['id']} は登録済み（自動置換しません）")
        data.setdefault("models", []).append(draft)
        from .util import dump_yaml
        dump_yaml(MODELS_FILE, data)
        Allowlist.load()
        print(f"# allowlist/models.yaml に追記しました: {draft['id']}", file=sys.stderr)
    return 0


def cmd_allowlist_draft_hf(a) -> int:
    from . import hfhub
    from .util import dump_yaml
    if not a.instruction.strip():
        raise StudioError("BAD_INPUT", "--instruction（ユーザー指示の記録）が必須")
    files = hfhub.PRESETS[a.preset] if a.preset else a.files
    if not files:
        raise StudioError("BAD_INPUT", "--files か --preset が必要")
    draft = hfhub.build_entry_draft(a.repo, files, a.kind, a.id, a.instruction, a.revision, a.arch)
    print(yaml.safe_dump([draft], allow_unicode=True, sort_keys=False))
    if a.append:
        data = load_yaml(MODELS_FILE, {"version": 1, "models": []})
        if any(m.get("id") == draft["id"] for m in data.get("models") or []):
            raise StudioError("BAD_INPUT", f"id {draft['id']} は登録済み（自動置換しません）")
        data.setdefault("models", []).append(draft)
        dump_yaml(MODELS_FILE, data)
        Allowlist.load()
    return 0


def cmd_models_fetch(a) -> int:
    al = Allowlist.load()
    if not al.models:
        _print({"ok": True, "note": "許可リストが空のため取得対象なし（勝手に取得しません）"})
        return 0
    res = fetch.fetch_all(al, a.only or None)
    out = Path(a.report)
    dump_json(out, {"results": res})
    _print(res)
    bad = [r for r in res if r.get("status") not in ("SAFETY_CHECK_OK", "CACHED")]
    return 1 if bad else 0


def cmd_models_verify(a) -> int:
    al = Allowlist.load()
    rows = []
    for e in al.models.values():
        try:
            fetch.verify_cached(e)
            rows.append({"id": e.id, "status": "OK"})
        except StudioError as ex:
            rows.append({"id": e.id, "status": ex.code, "message": ex.message})
    _print(rows)
    return 0 if all(r["status"] == "OK" for r in rows) else 1


def cmd_cache_key(a) -> int:
    """必要モデルの SHA256 集合からキャッシュキーを作る（モデルが同じなら同じキー＝再ダウンロード不要）。"""
    import hashlib
    al = Allowlist.load()
    shas = sorted(f["sha256"] for mid in (a.models or []) for f in al.require_model(mid).files)
    key = "models-v2-" + hashlib.sha256("\n".join(shas).encode()).hexdigest()[:20] if shas else "models-v2-none"
    total = sum(int(f.get("size_bytes") or 0) for mid in (a.models or []) for f in al.require_model(mid).files)
    print(json.dumps({"key": key, "files": len(shas), "total_gb": round(total / 1024**3, 2)}))
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a") as f:
            f.write(f"key={key}\n")
    return 0


def cmd_ledger_sync(a) -> int:
    _print({"added": ledger.sync(Allowlist.load())})
    return 0


def cmd_scan(a) -> int:
    res = scan.clamscan([Path(p) for p in a.paths], log_path=Path(a.log) if a.log else None)
    _print(res)
    return 0 if res["status"] == "SAFETY_CHECK_OK" else 1


def cmd_job_validate(a) -> int:
    job = jobspec.load_job(a.job)
    v = jobspec.validate_against_allowlist(job, Allowlist.load())
    _print({"ok": True, "job_id": job["job_id"], "stages": [s["name"] for s in job["stages"]], **v})
    return 0


def cmd_run(a) -> int:
    al = Allowlist.load()
    if a.resume:
        st = load_json(Path(a.runs_dir) / a.resume / "state.json")
        if not st:
            raise StudioError("BAD_INPUT", f"再開元 {a.resume} の state.json がありません")
        job = jobspec.normalize(st["job"])
        run_id = a.resume
    else:
        job = jobspec.load_job(a.job)
        run_id = a.run_id
    if a.backend:
        job["backend"] = a.backend
    if a.time_budget:
        job["time_budget_minutes"] = min(float(a.time_budget), jobspec.MAX_TIME_BUDGET)
    s = Session(job, al, run_id=run_id, runs_dir=Path(a.runs_dir))
    state = s.run()
    summary = {"run_id": s.run_id, "status": state["status"],
               "stages": {k: {"status": v.get("status"), "stop": v.get("stop_reason"),
                              "best": (v.get("best") or {}).get("score")} for k, v in state["stages"].items()},
               "dir": str(s.dir)}
    _print(summary)
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a") as f:
            f.write(f"run_id={s.run_id}\nstatus={state['status']}\n")
    return 0 if state["status"] in ("completed", "time_budget_exhausted") else 1


def cmd_rerun(a) -> int:
    """過去の候補の設定から新しいジョブ YAML を作る（以前の設定の再利用）。"""
    meta = load_json(a.candidate_json)
    st = load_json(Path(a.candidate_json).parents[2] / "state.json")
    job = st["job"]
    stage = next(s for s in job["stages"] if s["name"] == meta["stage"])
    new = {"job_id": a.job_id, "title": f"再利用: {meta['run_id']} {meta['stage']} r{meta['round']}c{meta['candidate']}",
           "backend": job["backend"], "time_budget_minutes": job["time_budget_minutes"],
           "limits": {**job["limits"], "max_rounds": 1, "candidates_per_round": 1},
           "defaults": {**job["defaults"], **meta["params"]}, "evaluation": job.get("evaluation", {}),
           "improve": {"enabled": False, "tune": []},
           "stages": [{k: v for k, v in stage.items() if k in ("name", "op", "init", "mask", "background",
                                                               "consistency_base", "outpaint", "scale")}]}
    Path(a.out).write_text(yaml.safe_dump(new, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(a.out)
    return 0


def cmd_site(a) -> int:
    _print(site.build(Path(a.runs_dir), Path(a.out), Allowlist.load()))
    return 0


def cmd_budget_check(a) -> int:
    _print(budget.check(float(a.minutes)))
    return 0


def cmd_budget_lint(a) -> int:
    probs = budget.lint_workflows()
    _print({"ok": not probs, "problems": probs})
    return 1 if probs else 0


def cmd_doctor(a) -> int:
    import importlib.util as iu
    al = Allowlist.load(strict=False)
    du = shutil.disk_usage(REPO_ROOT)
    _print({
        "python": platform.python_version(), "platform": platform.platform(), "cpus": os.cpu_count(),
        "disk_free_gb": round(du.free / 1e9, 1),
        "packages": {m: bool(iu.find_spec(m)) for m in
                     ("numpy", "PIL", "scipy", "yaml", "requests", "torch", "diffusers", "transformers",
                      "safetensors", "peft", "spandrel")},
        "clamav": scan.clamav_info(), "allowlist": {"models": len(al.models), "images": len(al.images),
                                                    "errors": al.errors},
        "cache_dir": str(fetch.cache_dir()), "hf_offline": os.environ.get("HF_HUB_OFFLINE"),
        "civitai_token_set": bool(os.environ.get("CIVITAI_API_TOKEN")),
    })
    return 0


def cmd_selftest(a) -> int:
    """モデルを使わない総合動作確認（procedural バックエンド）。"""
    job = jobspec.load_job(REPO_ROOT / "jobs" / "examples" / "selftest-procedural.yaml")
    s = Session(job, Allowlist.load(), runs_dir=Path(a.runs_dir), run_id=a.run_id)
    st = s.run()
    _print({"run_id": s.run_id, "status": st["status"],
            "stages": {k: v.get("stop_reason") for k, v in st["stages"].items()}})
    return 0 if st["status"] == "completed" else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="studio", description="GitHub完結型 AIイラスト制作環境")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("allowlist-check"); s.set_defaults(f=cmd_allowlist_check)
    s = sub.add_parser("allowlist-draft", help="ユーザー指定のCivitai URLから登録用下書きを作る")
    s.add_argument("--url", required=True); s.add_argument("--instruction", required=True)
    s.add_argument("--kind"); s.add_argument("--file-id", type=int); s.add_argument("--id")
    s.add_argument("--append", action="store_true", help="models.yaml に追記（ユーザー指示がある場合のみ）")
    s.set_defaults(f=cmd_allowlist_draft)
    s = sub.add_parser("allowlist-draft-hf", help="ユーザー承認済みのHF依存ファイルを登録下書きにする")
    s.add_argument("--repo", required=True); s.add_argument("--revision", default="main")
    s.add_argument("--files", nargs="*"); s.add_argument("--preset", choices=["sdxl-config", "sd15-config"])
    s.add_argument("--kind", default="pipeline_config"); s.add_argument("--arch"); s.add_argument("--id", required=True)
    s.add_argument("--instruction", required=True); s.add_argument("--append", action="store_true")
    s.set_defaults(f=cmd_allowlist_draft_hf)
    s = sub.add_parser("models-fetch"); s.add_argument("--only", nargs="*")
    s.add_argument("--report", default="model_fetch_report.json"); s.set_defaults(f=cmd_models_fetch)
    s = sub.add_parser("models-verify"); s.set_defaults(f=cmd_models_verify)
    s = sub.add_parser("cache-key"); s.add_argument("--models", nargs="*"); s.set_defaults(f=cmd_cache_key)
    s = sub.add_parser("ledger-sync"); s.set_defaults(f=cmd_ledger_sync)
    s = sub.add_parser("scan"); s.add_argument("paths", nargs="+"); s.add_argument("--log"); s.set_defaults(f=cmd_scan)
    s = sub.add_parser("job-validate"); s.add_argument("job"); s.set_defaults(f=cmd_job_validate)
    s = sub.add_parser("run"); s.add_argument("job", nargs="?"); s.add_argument("--run-id")
    s.add_argument("--resume"); s.add_argument("--backend"); s.add_argument("--time-budget", type=float)
    s.add_argument("--runs-dir", default=str(RUNS_DIR)); s.set_defaults(f=cmd_run)
    s = sub.add_parser("rerun"); s.add_argument("candidate_json"); s.add_argument("--job-id", required=True)
    s.add_argument("--out", required=True); s.set_defaults(f=cmd_rerun)
    s = sub.add_parser("site"); s.add_argument("--runs-dir", default=str(RUNS_DIR))
    s.add_argument("--out", default="_site"); s.set_defaults(f=cmd_site)
    s = sub.add_parser("budget-check"); s.add_argument("--minutes", required=True); s.set_defaults(f=cmd_budget_check)
    s = sub.add_parser("budget-lint"); s.set_defaults(f=cmd_budget_lint)
    s = sub.add_parser("doctor"); s.set_defaults(f=cmd_doctor)
    s = sub.add_parser("selftest"); s.add_argument("--runs-dir", default=str(RUNS_DIR))
    s.add_argument("--run-id"); s.set_defaults(f=cmd_selftest)

    a = p.parse_args(argv)
    try:
        return a.f(a)
    except StudioError as e:
        print(mask_secret(str(e)), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
