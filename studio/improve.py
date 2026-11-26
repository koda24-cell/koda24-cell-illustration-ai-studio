"""評価結果からプロンプトとパラメータを調整する（ルールベース・説明可能）。"""
from __future__ import annotations

import copy
from typing import Any

from .util import REPO_ROOT, load_yaml

RULES_FILE = REPO_ROOT / "config" / "improvement_rules.yaml"


def _tags(prompt: str) -> list[str]:
    return [t.strip() for t in (prompt or "").split(",") if t.strip()]


def _join(tags: list[str]) -> str:
    return ", ".join(tags)


def _add(prompt: str, new: list[str]) -> str:
    tags = _tags(prompt)
    for t in new:
        if t.lower() not in [x.lower() for x in tags]:
            tags.append(t)
    return _join(tags)


def _remove(prompt: str, rm: list[str]) -> str:
    low = {t.lower() for t in rm}
    return _join([t for t in _tags(prompt) if t.lower() not in low])


def _step(params: dict, key: str, direction: int, rules: dict) -> str | None:
    r = rules["params"].get(key)
    if r is None or key not in params:
        return None
    old = float(params[key])
    new = min(r["max"], max(r["min"], old + direction * r["step"]))
    if new == old:
        return None
    params[key] = int(new) if key == "steps" else round(new, 3)
    return f"{key}: {old:g} → {params[key]:g}"


def adjust(params: dict[str, Any], evaluation: dict[str, Any], allowed: list[str],
           round_index: int, op: str, rules: dict | None = None) -> tuple[dict[str, Any], list[str]]:
    """次ラウンドのパラメータと変更理由を返す。allowed: cfg/steps/denoise/prompt から許可されたもの。"""
    rules = rules or load_yaml(RULES_FILE, {})
    th, tags = rules["thresholds"], rules["prompt_tags"]
    p = copy.deepcopy(params)
    changes: list[str] = []
    m = evaluation.get("metrics", {})

    def tagchange(add_key: str, rm_key: str, why: str) -> None:
        if "prompt" not in allowed:
            return
        before = p.get("prompt", "")
        p["prompt"] = _add(_remove(before, tags[rm_key]), tags[add_key])
        if p["prompt"] != before:
            changes.append(f"prompt +{tags[add_key]} ({why})")

    vs = m.get("value_saturation", {}).get("values", {})
    if vs.get("ref_saturation") is not None:
        gap = vs["saturation"] - vs["ref_saturation"]
        if gap < -th["saturation_gap"]:
            tagchange("more_saturation", "less_saturation", f"彩度が参考より低い {gap:+.2f}")
        elif gap > th["saturation_gap"]:
            tagchange("less_saturation", "more_saturation", f"彩度が参考より高い {gap:+.2f}")
    if vs.get("ref_value") is not None:
        gap = vs["value"] - vs["ref_value"]
        if gap < -th["value_gap"]:
            tagchange("brighter", "darker", f"明度が参考より低い {gap:+.2f}")
        elif gap > th["value_gap"]:
            tagchange("darker", "brighter", f"明度が参考より高い {gap:+.2f}")
    la = m.get("lineart", {}).get("values", {})
    if la.get("ref_edge_density") is not None:
        gap = la["edge_density"] - la["ref_edge_density"]
        if gap < -th["edge_gap"]:
            tagchange("stronger_lines", "softer_lines", f"線が参考より少ない {gap:+.3f}")
        elif gap > th["edge_gap"]:
            tagchange("softer_lines", "stronger_lines", f"線が参考より多い {gap:+.3f}")

    art = m.get("artifacts", {})
    if art.get("score") is not None and art["score"] < 0.8:
        if "prompt" in allowed:
            before = p.get("negative_prompt", "")
            p["negative_prompt"] = _add(before, tags["artifact_negative"])
            if p["negative_prompt"] != before:
                changes.append("negative +artifact対策タグ（破綻の兆候）")
        if "steps" in allowed:
            c = _step(p, "steps", +1, rules)
            if c:
                changes.append(c + "（破綻の兆候）")

    sim = m.get("similarity", {}).get("score")
    if op in ("img2img", "inpaint") and "denoise" in allowed and sim is not None:
        if sim < th["similarity_low"]:
            c = _step(p, "denoise", -1, rules)
            if c:
                changes.append(c + "（元画像から離れすぎ）")
        elif sim > th["similarity_high"]:
            c = _step(p, "denoise", +1, rules)
            if c:
                changes.append(c + "（変化が小さすぎ）")

    if not changes and "cfg" in allowed:
        # 明確な手掛かりが無い場合は cfg を交互に探索（範囲内）
        c = _step(p, "cfg", +1 if (round_index // 2) % 2 == 0 else -1, rules)
        if c:
            changes.append(c + "（探索）")
    return p, changes
