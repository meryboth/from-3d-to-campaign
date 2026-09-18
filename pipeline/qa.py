"""Automatic QA for a render against its source passes.

Two scores, both computed only where the material-ID pass says "our house":
- edge_recall: share of the 3D model's lines (lines.png) that show up as image edges in
  the render within +-2 px. Measures how faithful the render is to the geometry.
- delta_e: CIE76 color distance (Lab) between the render and the reference beauty,
  per material region (facade plaster, shutters). Measures palette/brand adherence.
  Rule of thumb: < 10 close, 10-25 noticeably different, > 25 a different color.

    .venv/Scripts/python pipeline/qa.py out/renders/street/*.png
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
MATERIALS = None
HOUSE_KEYS = ["facade_plaster", "facade_molding", "facade_plinth", "patio_plaster", "party_wall", "interior_wall", "roof",
              "gallery_roof", "wood_door", "wood_shutter", "glass", "iron", "floor_tile", "planter"]
COLOR_KEYS = ["facade_plaster", "wood_shutter"]


def material_ids():
    # parse the id table out of scene/src/materials.js so there is a single source of truth
    global MATERIALS
    if MATERIALS is None:
        import re
        src = (ROOT / "scene" / "src" / "materials.js").read_text()
        MATERIALS = {k: tuple(map(int, v.split(","))) for k, v in re.findall(r"(\w+): \{ id: \[([\d, ]+)\]", src)}
    return MATERIALS


def mask_for(ids, keys):
    table = material_ids()
    m = np.zeros(ids.shape[:2], bool)
    for k in keys:
        m |= np.all(ids == np.array(table[k], np.uint8), axis=-1)
    return m


def to_lab(rgb):
    c = rgb.astype(np.float64) / 255
    c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    xyz = c @ np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]]).T
    xyz /= np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def sobel_edges(gray, keep=0.12):
    g = gray.astype(np.float64)
    p = np.pad(g, 1, mode="edge")
    gx = (p[:-2, 2:] + 2 * p[1:-1, 2:] + p[2:, 2:]) - (p[:-2, :-2] + 2 * p[1:-1, :-2] + p[2:, :-2])
    gy = (p[2:, :-2] + 2 * p[2:, 1:-1] + p[2:, 2:]) - (p[:-2, :-2] + 2 * p[:-2, 1:-1] + p[:-2, 2:])
    mag = np.hypot(gx, gy)
    return mag >= np.quantile(mag, 1 - keep)


def dilate(m, r=2):
    out = m.copy()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            out |= np.roll(np.roll(m, dy, 0), dx, 1)
    return out


def evaluate(render_path, cam=None):
    render_path = Path(render_path)
    cam = cam or render_path.parent.name
    passes = ROOT / "out" / "passes" / cam
    img = np.asarray(Image.open(render_path).convert("RGB"))
    ids = np.asarray(Image.open(passes / "ids.png").convert("RGB"))
    beauty = np.asarray(Image.open(passes / "beauty.png").convert("RGB"))
    lines = np.asarray(Image.open(passes / "lines.png").convert("L")) > 96
    if img.shape != ids.shape:
        img = np.asarray(Image.fromarray(img).resize(ids.shape[1::-1], Image.LANCZOS))

    house = mask_for(ids, HOUSE_KEYS)
    target = lines & house
    found = dilate(sobel_edges(np.asarray(Image.fromarray(img).convert("L"))), 2)
    edge_recall = float((target & found).sum() / max(1, target.sum()))

    lab_r, lab_b = to_lab(img), to_lab(beauty)
    # white-balanced variant: gray-world over the house region, so warm golden-hour light
    # isn't counted as "wrong paint" (a golden facade that is the right paint under that light)
    lab_rw, lab_bw = to_lab(gray_world(img, house)), to_lab(gray_world(beauty, house))
    delta_e, delta_e_wb = {}, {}
    for k in COLOR_KEYS:
        m = mask_for(ids, [k])
        if m.sum() > 200:
            delta_e[k] = round(float(np.linalg.norm(lab_r[m].mean(0) - lab_b[m].mean(0))), 1)
            delta_e_wb[k] = round(float(np.linalg.norm(lab_rw[m].mean(0) - lab_bw[m].mean(0))), 1)
    return {"edge_recall": round(edge_recall, 3), "delta_e": delta_e, "delta_e_wb": delta_e_wb, "house_px": int(house.sum())}


def gray_world(rgb, mask):
    """Scale channels so the masked region averages to neutral gray (keeps its luminance)."""
    c = rgb.astype(np.float64)
    mean = c[mask].mean(0)
    return np.clip(c * (mean.mean() / np.maximum(mean, 1e-6)), 0, 255).astype(np.uint8)


if __name__ == "__main__":
    for p in sys.argv[1:]:
        print(Path(p).name, json.dumps(evaluate(p)))
