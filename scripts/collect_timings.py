#!/usr/bin/env python3
"""Actions のステップ所要時間とセッション内の計時をまとめて timings.json に書く（標準ライブラリのみ）。
使い方: collect_timings.py <run_dir>   環境変数: GITHUB_TOKEN GITHUB_REPOSITORY GITHUB_RUN_ID RUNNER_NAME"""
import datetime as dt
import json
import os
import sys
import urllib.request
from pathlib import Path


def gh(path):
    req = urllib.request.Request(f"https://api.github.com{path}", headers={
        "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def secs(a, b):
    if not a or not b:
        return None
    f = lambda x: dt.datetime.fromisoformat(x.replace("Z", "+00:00"))
    return round((f(b) - f(a)).total_seconds(), 1)


def main():
    run_dir = Path(sys.argv[1])
    out = {"collected_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "actions_run": f"{os.environ.get('GITHUB_SERVER_URL','https://github.com')}/{os.environ.get('GITHUB_REPOSITORY')}/actions/runs/{os.environ.get('GITHUB_RUN_ID')}",
           "runtime": os.environ.get("STUDIO_RUNTIME", "native"), "steps": []}
    try:
        jobs = gh(f"/repos/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}/jobs?per_page=50")["jobs"]
        job = next((j for j in jobs if j.get("runner_name") == os.environ.get("RUNNER_NAME")), jobs[0])
        out["job"] = {"name": job["name"], "started_at": job["started_at"]}
        for s in job.get("steps", []):
            out["steps"].append({"name": s["name"], "status": s["status"], "conclusion": s.get("conclusion"),
                                 "seconds": secs(s.get("started_at"), s.get("completed_at"))})
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        out["job_elapsed_seconds_so_far"] = secs(job["started_at"], now)
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)[:300]
    extra = os.environ.get("STUDIO_TIMING_MARKS")
    if extra and Path(extra).exists():
        out["marks"] = [json.loads(l) for l in Path(extra).read_text().splitlines() if l.strip()]
    rj = run_dir / "run.json"
    if rj.exists():
        out["session"] = json.loads(rj.read_text()).get("timing")
    name = f"timings-{os.environ.get('GITHUB_RUN_ID','local')}.json"
    (run_dir / name).write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
