"""無料枠ガード。超える可能性があれば実行を止める（fail closed）。"""
from __future__ import annotations

import datetime as _dt
import os
import re
from pathlib import Path
from typing import Any

import requests
import yaml

from .util import REPO_ROOT, StudioError, load_yaml

BUDGET_FILE = REPO_ROOT / "config" / "budget.yaml"


def _gh(path: str, params: dict | None = None) -> Any:
    tok = os.environ.get("GITHUB_TOKEN")
    if not tok:
        raise StudioError("BUDGET_UNKNOWN", "GITHUB_TOKEN が無く使用量を確認できません")
    r = requests.get(f"https://api.github.com{path}", params=params, timeout=30,
                     headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"})
    r.raise_for_status()
    return r.json()


def check(requested_minutes: float, repo: str | None = None) -> dict[str, Any]:
    cfg = load_yaml(BUDGET_FILE, {})
    if requested_minutes > cfg.get("max_job_minutes", 355):
        raise StudioError("BUDGET_EXCEEDED", f"1ジョブ {requested_minutes} 分は上限 {cfg['max_job_minutes']} 分を超えます")
    repo = repo or os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        raise StudioError("BUDGET_UNKNOWN", "GITHUB_REPOSITORY が不明")
    info = _gh(f"/repos/{repo}")
    if not info.get("private"):
        return {"visibility": "public", "ok": True,
                "note": "Public リポジトリの標準ランナーは無料。上限はジョブ時間のみ適用"}
    # Private：今月の本リポジトリの実行時間（壁時計）を合算して保守的に見積もる
    start = _dt.date.today().replace(day=1).isoformat()
    used_ms, page = 0, 1
    while True:
        data = _gh(f"/repos/{repo}/actions/runs", {"created": f">={start}", "per_page": 100, "page": page})
        for run in data.get("workflow_runs", []):
            try:
                t0 = _dt.datetime.fromisoformat(run["run_started_at"].replace("Z", "+00:00"))
                t1 = _dt.datetime.fromisoformat(run["updated_at"].replace("Z", "+00:00"))
                used_ms += max(0, (t1 - t0).total_seconds() * 1000)
            except Exception:  # noqa: BLE001
                continue
        if len(data.get("workflow_runs", [])) < 100:
            break
        page += 1
    used = used_ms / 60000
    cap = cfg.get("private_monthly_minutes_cap", 1200)
    ok = used + requested_minutes <= cap
    result = {"visibility": "private", "used_minutes_estimate": round(used, 1), "requested": requested_minutes,
              "cap": cap, "ok": ok,
              "note": "アカウント全体の無料枠は他リポジトリと共有。ここは本リポジトリの自主上限による保守的判定"}
    if not ok:
        raise StudioError("BUDGET_EXCEEDED", f"今月の推定使用 {used:.0f} 分 + 要求 {requested_minutes} 分 > 上限 {cap} 分")
    return result


def lint_workflows(root: Path = REPO_ROOT) -> list[str]:
    """ワークフローが無料の標準ランナーだけを使っているか静的に確認する。"""
    cfg = load_yaml(BUDGET_FILE, {})
    allowed = set(cfg.get("allowed_runner_labels", []))
    problems = []
    for wf in sorted((root / ".github" / "workflows").glob("*.y*ml")):
        data = yaml.safe_load(wf.read_text(encoding="utf-8")) or {}
        for name, job in (data.get("jobs") or {}).items():
            ro = job.get("runs-on")
            labels = ro if isinstance(ro, list) else [ro]
            for l in labels:
                if l not in allowed:
                    problems.append(f"{wf.name}:{name}: runs-on '{l}' は許可されていません")
            tm = job.get("timeout-minutes")
            if tm is None or int(tm) > 360:
                problems.append(f"{wf.name}:{name}: timeout-minutes（≤360）が必要")
        text = wf.read_text(encoding="utf-8")
        if re.search(r"api\.openai\.com|OPENAI_API_KEY|anthropic\.com/v1|ANTHROPIC_API_KEY", text):
            problems.append(f"{wf.name}: 従量課金APIの参照は禁止")
    return problems
