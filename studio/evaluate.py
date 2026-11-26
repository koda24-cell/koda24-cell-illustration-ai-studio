"""イラスト自動評価（制作途中の改善用。最終採否はユーザーが判断する）。

既定はモデル不要の画像解析（NumPy）。数値は「参考画像との統計的な近さ」や
「破綻の兆候」を表すだけで、美術的な完成度を断定しない。各指標に根拠と限界を記録する。

評価モデル（CLIP 等）は許可リストに kind: evaluator として登録された場合のみ使用する。
ポーズ・人体バランスの判定は姿勢推定モデルが必要なため、許可モデルが無い間は「評価不能」と記録する。
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
from PIL import Image, ImageFilter, ImageOps

from .imageops import to_rgb

LIMITS = {
    "color": "色ヒストグラムの重なり。配色の雰囲気の近さで、配置や意味は見ていない。",
    "value_saturation": "平均明度・彩度・明度のばらつき。部分的な色の良し悪しは判定しない。",
    "lineart": "エッジ密度と線の濃さ。線の美しさ・強弱の意図は判定できない。",
    "shading": "明度分布（トーン）の近さ。影の位置や光源の正しさは判定しない。",
    "composition": "エッジ量の重心と余白の偏り。主題の認識はしていない。",
    "similarity": "縮小グレースケールのSSIMと知覚ハッシュ。構図・形の近さで、絵柄の近さとは別。",
    "artifacts": "空白・極端な白飛び/黒つぶれ・高周波ノイズの兆候のみ。手指や人体の破綻は検出できない。",
    "consistency": "基準画像との配色・トーンの近さ（同一キャラの代理指標）。顔や体型の同一性は見ていない。",
    "clip": "許可済み CLIP 系モデルの埋め込み類似度。学習データの偏りを含む。",
    "pose": "姿勢推定モデルが必要。",
    "body_balance": "姿勢推定モデルが必要。",
}

DEFAULT_WEIGHTS = {"color": 1.0, "value_saturation": 1.0, "lineart": 0.7, "shading": 0.7,
                   "composition": 0.5, "similarity": 0.5, "artifacts": 1.5, "consistency": 1.0, "clip": 1.5}


def _small(img: Image.Image, side: int = 256) -> Image.Image:
    img = to_rgb(img)
    r = side / max(img.size)
    return img.resize((max(8, int(img.width * r)), max(8, int(img.height * r))), Image.BILINEAR)


def _hsv(img: Image.Image) -> np.ndarray:
    return np.asarray(_small(img).convert("HSV")).astype(np.float32) / 255.0


def _hist_intersection(a: np.ndarray, b: np.ndarray) -> float:
    a = a / (a.sum() + 1e-9)
    b = b / (b.sum() + 1e-9)
    return float(np.minimum(a, b).sum())


def _rgb_hist(img: Image.Image) -> np.ndarray:
    arr = (np.asarray(_small(img)) // 32).reshape(-1, 3)
    idx = arr[:, 0] * 64 + arr[:, 1] * 8 + arr[:, 2]
    return np.bincount(idx, minlength=512).astype(np.float64)


def _hue_hist(img: Image.Image) -> np.ndarray:
    hsv = _hsv(img)
    h, s = hsv[..., 0].ravel(), hsv[..., 1].ravel()
    return np.histogram(h, bins=36, range=(0, 1), weights=s + 1e-3)[0]


def _gray(img: Image.Image, side: int = 256) -> np.ndarray:
    return np.asarray(ImageOps.grayscale(_small(img, side))).astype(np.float32)


def _edges(img: Image.Image) -> np.ndarray:
    g = ImageOps.grayscale(_small(img)).filter(ImageFilter.FIND_EDGES)
    return np.asarray(g).astype(np.float32)


def _closeness(a: float, b: float, scale: float) -> float:
    return float(math.exp(-abs(a - b) / scale))


def ssim(a: np.ndarray, b: np.ndarray) -> float:
    """全体SSIM（グローバル統計版の簡易実装）。"""
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    ma, mb = a.mean(), b.mean()
    va, vb = a.var(), b.var()
    cov = ((a - ma) * (b - mb)).mean()
    return float(((2 * ma * mb + c1) * (2 * cov + c2)) / ((ma**2 + mb**2 + c1) * (va + vb + c2)))


def windowed_ssim(img_a: Image.Image, img_b: Image.Image, side: int = 128, win: int = 16) -> float:
    a = np.asarray(ImageOps.grayscale(to_rgb(img_a)).resize((side, side), Image.BILINEAR)).astype(np.float32)
    b = np.asarray(ImageOps.grayscale(to_rgb(img_b)).resize((side, side), Image.BILINEAR)).astype(np.float32)
    vals = [ssim(a[y:y + win, x:x + win], b[y:y + win, x:x + win])
            for y in range(0, side, win) for x in range(0, side, win)]
    return float(np.mean(vals))


def dhash(img: Image.Image, size: int = 8) -> int:
    g = np.asarray(ImageOps.grayscale(to_rgb(img)).resize((size + 1, size), Image.BILINEAR)).astype(np.int32)
    bits = (g[:, 1:] > g[:, :-1]).ravel()
    return int("".join("1" if b else "0" for b in bits), 2)


def stats(img: Image.Image) -> dict[str, float]:
    hsv = _hsv(img)
    e = _edges(img)
    g = _gray(img)
    ys, xs = np.mgrid[0:e.shape[0], 0:e.shape[1]]
    w = e + 1e-6
    cx, cy = float((xs * w).sum() / w.sum() / e.shape[1]), float((ys * w).sum() / w.sum() / e.shape[0])
    lap = np.asarray(ImageOps.grayscale(_small(img)).filter(
        ImageFilter.Kernel((3, 3), [0, 1, 0, 1, -4, 1, 0, 1, 0], 1, 128))).astype(np.float32) - 128
    return {
        "mean_value": float(hsv[..., 2].mean()), "mean_saturation": float(hsv[..., 1].mean()),
        "value_std": float(hsv[..., 2].std()), "edge_density": float((e > 40).mean()),
        "edge_strength": float(e.mean() / 255), "gray_std": float(g.std()),
        "clipped_white": float((g >= 254).mean()), "clipped_black": float((g <= 1).mean()),
        "hf_energy": float(np.abs(lap).mean() / 255), "mass_cx": cx, "mass_cy": cy,
    }


def _metric(score: float | None, rationale: str, key: str, **values: Any) -> dict[str, Any]:
    return {"score": None if score is None else round(float(score), 4), "rationale": rationale,
            "limitations": LIMITS[key], "values": {k: (round(v, 4) if isinstance(v, float) else v)
                                                  for k, v in values.items()}}


def evaluate(img: Image.Image, refs: list[Image.Image] | None = None,
             base: Image.Image | None = None, metrics: list[str] | None = None,
             weights: dict[str, float] | None = None,
             clip_scorer: Any = None, prompt: str | None = None) -> dict[str, Any]:
    refs = refs or []
    metrics = metrics or ["color", "value_saturation", "lineart", "shading", "composition",
                          "similarity", "artifacts", "consistency", "clip", "pose", "body_balance"]
    weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    s = stats(img)
    rs = [stats(r) for r in refs]
    out: dict[str, Any] = {}

    if "color" in metrics:
        if refs:
            vals = [0.5 * _hist_intersection(_rgb_hist(img), _rgb_hist(r))
                    + 0.5 * _hist_intersection(_hue_hist(img), _hue_hist(r)) for r in refs]
            out["color"] = _metric(max(vals), f"参考画像との配色ヒストグラム重なり（最大 {max(vals):.2f}）", "color",
                                   per_reference=[round(v, 3) for v in vals])
        else:
            out["color"] = _metric(None, "参考画像なしのため比較不可", "color")

    if "value_saturation" in metrics:
        if rs:
            mv = float(np.mean([r["mean_value"] for r in rs]))
            ms = float(np.mean([r["mean_saturation"] for r in rs]))
            sd = float(np.mean([r["value_std"] for r in rs]))
            sc = (_closeness(s["mean_value"], mv, 0.15) + _closeness(s["mean_saturation"], ms, 0.15)
                  + _closeness(s["value_std"], sd, 0.1)) / 3
            out["value_saturation"] = _metric(
                sc, f"明度 {s['mean_value']:.2f}(参考{mv:.2f}) 彩度 {s['mean_saturation']:.2f}(参考{ms:.2f})",
                "value_saturation", value=s["mean_value"], saturation=s["mean_saturation"],
                ref_value=mv, ref_saturation=ms, value_std=s["value_std"], ref_value_std=sd)
        else:
            out["value_saturation"] = _metric(None, "参考画像なし（数値のみ記録）", "value_saturation",
                                              value=s["mean_value"], saturation=s["mean_saturation"])

    if "lineart" in metrics:
        if rs:
            ed = float(np.mean([r["edge_density"] for r in rs]))
            es = float(np.mean([r["edge_strength"] for r in rs]))
            sc = 0.5 * _closeness(s["edge_density"], ed, 0.05) + 0.5 * _closeness(s["edge_strength"], es, 0.05)
            out["lineart"] = _metric(sc, f"エッジ密度 {s['edge_density']:.3f}(参考{ed:.3f})", "lineart",
                                     edge_density=s["edge_density"], ref_edge_density=ed,
                                     edge_strength=s["edge_strength"], ref_edge_strength=es)
        else:
            out["lineart"] = _metric(None, "参考画像なし", "lineart", edge_density=s["edge_density"])

    if "shading" in metrics:
        if refs:
            hv = np.histogram(_gray(img), bins=16, range=(0, 255))[0]
            vals = [_hist_intersection(hv, np.histogram(_gray(r), bins=16, range=(0, 255))[0]) for r in refs]
            out["shading"] = _metric(max(vals), "明度ヒストグラム（16段）の重なり", "shading",
                                     gray_std=s["gray_std"])
        else:
            out["shading"] = _metric(None, "参考画像なし", "shading", gray_std=s["gray_std"])

    if "composition" in metrics:
        cx, cy = s["mass_cx"], s["mass_cy"]
        if rs:
            rcx = float(np.mean([r["mass_cx"] for r in rs]))
            rcy = float(np.mean([r["mass_cy"] for r in rs]))
            d = math.hypot(cx - rcx, cy - rcy)
            sc = math.exp(-d / 0.15)
            why = f"視覚的重心 ({cx:.2f},{cy:.2f}) 参考 ({rcx:.2f},{rcy:.2f})"
        else:
            off = max(0.0, abs(cx - 0.5) - 0.2) + max(0.0, abs(cy - 0.5) - 0.25)
            sc = math.exp(-off / 0.1)
            why = f"視覚的重心 ({cx:.2f},{cy:.2f})。極端な偏りのみ減点"
        out["composition"] = _metric(sc, why, "composition", cx=cx, cy=cy)

    if "similarity" in metrics:
        if refs:
            vals = []
            for r in refs:
                ham = bin(dhash(img) ^ dhash(r)).count("1")
                vals.append(0.6 * max(0.0, windowed_ssim(img, r)) + 0.4 * (1 - ham / 64))
            out["similarity"] = _metric(max(vals), "SSIM(128px)とdHashの合成", "similarity",
                                        per_reference=[round(v, 3) for v in vals])
        else:
            out["similarity"] = _metric(None, "参考画像なし", "similarity")

    if "artifacts" in metrics:
        issues = []
        pen = 0.0
        if s["gray_std"] < 6:
            issues.append("ほぼ単色（生成失敗の可能性）")
            pen += 0.8
        if s["clipped_white"] > 0.6 or s["clipped_black"] > 0.4:
            issues.append("白飛び/黒つぶれが広い")
            pen += 0.3
        base_hf = float(np.mean([r["hf_energy"] for r in rs])) if rs else 0.06
        if s["hf_energy"] > max(0.12, base_hf * 2.0):
            issues.append(f"高周波ノイズが多い（{s['hf_energy']:.3f}）")
            pen += 0.4
        out["artifacts"] = _metric(max(0.0, 1 - pen), "兆候: " + ("、".join(issues) if issues else "検出なし"),
                                   "artifacts", issues=issues, hf_energy=s["hf_energy"],
                                   clipped_white=s["clipped_white"], clipped_black=s["clipped_black"])

    if "consistency" in metrics:
        if base is not None:
            c = 0.5 * _hist_intersection(_hue_hist(img), _hue_hist(base)) + \
                0.5 * _hist_intersection(_rgb_hist(img), _rgb_hist(base))
            out["consistency"] = _metric(c, "基準画像（差分元）との配色の近さ", "consistency")
        else:
            out["consistency"] = _metric(None, "基準画像なし", "consistency")

    if "clip" in metrics:
        if clip_scorer is not None:
            res = clip_scorer(img, refs, prompt)
            out["clip"] = _metric(res.get("score"), res.get("rationale", "CLIP類似度"), "clip",
                                  **{k: v for k, v in res.items() if k not in ("score", "rationale")})
        else:
            out["clip"] = _metric(None, "許可済み評価モデルなし（使用しない）", "clip")

    for k in ("pose", "body_balance"):
        if k in metrics:
            out[k] = _metric(None, "評価不能：姿勢推定モデルが許可リストにありません", k)

    used = {k: v["score"] for k, v in out.items() if v["score"] is not None and weights.get(k, 0) > 0}
    total_w = sum(weights[k] for k in used)
    overall = sum(used[k] * weights[k] for k in used) / total_w if total_w else None
    return {
        "overall": None if overall is None else round(overall, 4),
        "metrics": out,
        "weights_used": {k: weights[k] for k in used},
        "note": "自動評価は制作途中の改善用の参考値。美術的な完成度の判定や採用判断ではない。",
    }


def compare(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """改善前後の指標差分。"""
    diff = {}
    for k, v in after["metrics"].items():
        b = before["metrics"].get(k, {}).get("score")
        a = v.get("score")
        if a is not None and b is not None:
            diff[k] = round(a - b, 4)
    ob, oa = before.get("overall"), after.get("overall")
    return {"overall_delta": None if ob is None or oa is None else round(oa - ob, 4), "metric_delta": diff}
