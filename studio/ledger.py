"""モデル台帳（catalog/model_ledger.yaml）。

許可リストは「使ってよいか」、台帳は「どんなモデルか・どう使うと良いか」を管理する。
台帳にあっても許可リストに無いモデルは使えない（台帳は許可の根拠にならない）。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .allowlist import Allowlist, NotAllowed
from .util import REPO_ROOT, dump_yaml, load_yaml, today

# Actions では実績の書込先を studio-runs ブランチ側に向ける（main は PR でのみ更新）
LEDGER_FILE = Path(os.environ.get("STUDIO_LEDGER_FILE", REPO_ROOT / "catalog" / "model_ledger.yaml"))

# 台帳の項目（依頼書 3. の一覧に対応）
TEMPLATE: dict[str, Any] = {
    "name": None,
    "version": None,
    "source_url": None,
    "author": None,
    "kind": None,
    "base_model": None,
    "file_format": None,
    "size_bytes": None,
    "sha256": None,
    "license": {"commercial_use": None, "notes": "未確認（配布ページで要確認）"},
    "strengths": {"styles": [], "content": [], "source": "未記入（配布元記載 or 実生成結果から追記）"},
    "recommended_settings": {"sampler": None, "steps": None, "cfg": None, "width": None, "height": None,
                             "clip_skip": None, "notes": None},
    "trigger_words": [],
    "compatible_with": [],      # 対応する LoRA / VAE / ControlNet 等の許可済みID
    "required_dependencies": [],  # 必須依存（未登録なら報告用。勝手に追加しない）
    "cpu_status": {"status": "未検証", "seconds_per_image": None, "resolution": None, "run": None},
    "results": [],              # 実際の生成結果 {run, candidate, score, date}
}


def load() -> dict[str, Any]:
    return load_yaml(LEDGER_FILE, {"version": 1, "models": {}})


def save(data: dict[str, Any]) -> None:
    dump_yaml(LEDGER_FILE, data)


def sync(al: Allowlist) -> list[str]:
    """許可リストの各モデルに台帳の枠を用意する。既存の記入内容は上書きしない。"""
    data = load()
    models = data.setdefault("models", {})
    added = []
    for e in al.models.values():
        r = e.raw
        cur = models.get(e.id)
        if cur is None:
            cur = {k: (v.copy() if isinstance(v, (dict, list)) else v) for k, v in TEMPLATE.items()}
            models[e.id] = cur
            added.append(e.id)
        facts = {
            "name": r.get("name"), "version": r.get("version_name"), "source_url": r.get("url"),
            "author": r.get("author"), "kind": e.kind, "base_model": r.get("base_model"),
            "file_format": r.get("format") or (e.primary_file.get("filename") or "").rsplit(".", 1)[-1],
            "size_bytes": e.primary_file.get("size_bytes"), "sha256": e.primary_file.get("sha256"),
        }
        for k, v in facts.items():
            if v is not None and cur.get(k) in (None, ""):
                cur[k] = v
        if r.get("license") and cur["license"].get("commercial_use") is None:
            cur["license"] = {"commercial_use": r["license"].get("allowCommercialUse"),
                              "civitai_flags": r["license"],
                              "notes": "Civitai API の値。用途ごとの最終判断はユーザー"}
        if r.get("trained_words") and not cur.get("trigger_words"):
            cur["trigger_words"] = r["trained_words"]
    # 許可リストから外れたモデルは削除せず「許可取消」と明記（履歴保持）
    for mid, cur in models.items():
        cur["allowed"] = mid in al.models
    save(data)
    return added


def record_result(model_id: str, run_id: str, candidate: str, score: float | None,
                  seconds: float | None = None, resolution: str | None = None) -> None:
    data = load()
    m = data.setdefault("models", {}).get(model_id)
    if m is None:
        return
    m.setdefault("results", []).append({"run": run_id, "candidate": candidate,
                                        "score": None if score is None else round(score, 4), "date": today()})
    m["results"] = m["results"][-50:]
    if seconds is not None:
        cs = m.setdefault("cpu_status", {})
        cs.update(status="実動作確認済み", seconds_per_image=round(seconds, 1), resolution=resolution, run=run_id)
    save(data)


def select_model(al: Allowlist, kind: str, purpose: list[str] | None = None,
                 base_model: str | None = None) -> str:
    """許可済みモデルの中から用途に合うものを選ぶ（許可外からは選ばない）。"""
    cands = al.models_of(kind)
    if base_model:
        cands = [c for c in cands if (c.raw.get("base_model") or "") == base_model] or cands
    if not cands:
        raise NotAllowed(f"種類 {kind} の許可済みモデルがありません。モデルの指定をお願いします")
    led = load().get("models", {})
    purpose = [p.lower() for p in (purpose or [])]

    def score(c) -> tuple:
        s = led.get(c.id, {}).get("strengths", {})
        tags = [t.lower() for t in (s.get("styles", []) + s.get("content", []))]
        hit = sum(1 for p in purpose if any(p in t for t in tags))
        res = led.get(c.id, {}).get("results", [])
        best = max([r["score"] or 0 for r in res], default=0)
        return (hit, best, c.id)

    return sorted(cands, key=score, reverse=True)[0].id
