"""モデルを使わない画像処理（Pillow + NumPy）。

背景透過（単色背景の色キー / 外周フラッドフィル）、背景合成、Lanczos 拡大、
アウトペイント用の余白追加とマスク、矩形マスク、線画抽出（XDoG）、比較画像。
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps


def to_rgb(img: Image.Image) -> Image.Image:
    if img.mode == "RGBA":
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        return bg
    return img.convert("RGB")


# ---------- 拡大 ----------
def upscale_lanczos(img: Image.Image, scale: float) -> Image.Image:
    w, h = img.size
    return img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)


# ---------- マスク ----------
def rect_mask(size: tuple[int, int], rect: list[float], feather: int = 8) -> Image.Image:
    """rect = [x, y, w, h]（0〜1 の比率）。白=描き直す領域。"""
    W, H = size
    x, y, w, h = rect
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rectangle([int(x * W), int(y * H), int((x + w) * W), int((y + h) * H)], fill=255)
    return m.filter(ImageFilter.GaussianBlur(feather)) if feather else m


def pad_for_outpaint(img: Image.Image, left: int, top: int, right: int, bottom: int,
                     overlap: int = 16) -> tuple[Image.Image, Image.Image]:
    """キャンバスを拡張し、拡張部分（+重なり）を白にしたマスクを返す。
    拡張部は端の色を引き伸ばして初期値にする（何もない灰色より破綻しにくい）。"""
    img = to_rgb(img)
    W, H = img.size
    nw, nh = W + left + right, H + top + bottom
    arr = np.asarray(img)
    padded = np.pad(arr, ((top, bottom), (left, right), (0, 0)), mode="edge")
    canvas = Image.fromarray(padded)
    mask = Image.new("L", (nw, nh), 255)
    ImageDraw.Draw(mask).rectangle(
        [left + (overlap if left else 0), top + (overlap if top else 0),
         left + W - 1 - (overlap if right else 0), top + H - 1 - (overlap if bottom else 0)], fill=0)
    return canvas, mask.filter(ImageFilter.GaussianBlur(overlap // 2 or 1))


# ---------- 背景透過 ----------
def estimate_bg_color(img: Image.Image) -> tuple[int, int, int]:
    arr = np.asarray(to_rgb(img)).astype(np.int32)
    border = np.concatenate([arr[0], arr[-1], arr[:, 0], arr[:, -1]])
    return tuple(int(v) for v in np.median(border, axis=0))


def remove_bg_floodfill(img: Image.Image, tolerance: int = 40, feather: float = 1.5) -> Image.Image:
    """外周から連結した「背景色に近い」画素だけを透明化する。
    生成時に単色背景（例: 'simple white background'）を指定した立ち絵向け。
    複雑な背景・髪と背景の同色には弱い（限界として記録）。"""
    rgb = np.asarray(to_rgb(img)).astype(np.int32)
    bg = np.array(estimate_bg_color(img))
    near = np.abs(rgb - bg).sum(axis=2) <= tolerance
    from scipy import ndimage

    labels, _ = ndimage.label(near)
    border_labels = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    border_labels = border_labels[border_labels != 0]
    visited = np.isin(labels, border_labels)
    alpha = Image.fromarray(np.where(visited, 0, 255).astype(np.uint8))
    if feather:
        alpha = alpha.filter(ImageFilter.GaussianBlur(feather))
    out = to_rgb(img).convert("RGBA")
    out.putalpha(alpha)
    return out


def composite_on_background(fg: Image.Image, bg: Image.Image, scale: float = 1.0,
                            anchor: str = "bottom") -> Image.Image:
    bg = to_rgb(bg).copy()
    fg = fg.convert("RGBA")
    if scale != 1.0:
        fg = upscale_lanczos(fg, scale)
    # 背景に収まるよう縮小
    r = min(bg.width / fg.width, bg.height / fg.height, 1.0)
    if r < 1.0:
        fg = upscale_lanczos(fg, r)
    x = (bg.width - fg.width) // 2
    y = bg.height - fg.height if anchor == "bottom" else (bg.height - fg.height) // 2
    bg.paste(fg, (x, y), fg)
    return bg


# ---------- 線画抽出 ----------
def lineart_xdog(img: Image.Image, sigma: float = 0.8, k: float = 1.6, p: float = 20.0,
                 eps: float = 0.02, phi: float = 10.0) -> Image.Image:
    """XDoG による線画抽出（白地に黒線）。ControlNet 用の入力や線画素材の下書きに使う。"""
    g = np.asarray(ImageOps.grayscale(to_rgb(img))).astype(np.float32) / 255.0
    pil = Image.fromarray((g * 255).astype(np.uint8))
    g1 = np.asarray(pil.filter(ImageFilter.GaussianBlur(sigma))).astype(np.float32) / 255.0
    g2 = np.asarray(pil.filter(ImageFilter.GaussianBlur(sigma * k))).astype(np.float32) / 255.0
    d = (1 + p) * g1 - p * g2
    e = np.where(d >= eps, 1.0, 1.0 + np.tanh(phi * (d - eps)))
    return Image.fromarray((np.clip(e, 0, 1) * 255).astype(np.uint8)).convert("RGB")


def canny_like(img: Image.Image) -> Image.Image:
    """ControlNet(canny系)入力用の簡易エッジ（黒地に白線）。"""
    g = ImageOps.grayscale(to_rgb(img)).filter(ImageFilter.GaussianBlur(1))
    e = g.filter(ImageFilter.FIND_EDGES)
    arr = np.asarray(e)
    thr = max(20, int(np.percentile(arr, 90)))
    return Image.fromarray(np.where(arr >= thr, 255, 0).astype(np.uint8)).convert("RGB")


# ---------- 比較画像 ----------
def side_by_side(images: list[Image.Image], labels: list[str], height: int = 384) -> Image.Image:
    tiles = []
    for im in images:
        im = to_rgb(im)
        r = height / im.height
        tiles.append(im.resize((max(1, int(im.width * r)), height), Image.LANCZOS))
    pad, lab = 8, 22
    W = sum(t.width for t in tiles) + pad * (len(tiles) + 1)
    out = Image.new("RGB", (W, height + lab + pad * 2), (32, 32, 36))
    d = ImageDraw.Draw(out)
    font = ImageFont.load_default()
    x = pad
    for t, l in zip(tiles, labels):
        out.paste(t, (x, pad + lab))
        d.text((x + 2, pad + 2), l, fill=(240, 240, 240), font=font)
        x += t.width + pad
    return out
