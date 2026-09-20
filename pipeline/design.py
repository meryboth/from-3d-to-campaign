"""Design system: tokens, a typographic canvas, and image-aware placement.

The canvas gives what PIL doesn't: letter-spacing, a baseline grid, hairlines and
type blocks measured before they are drawn. Placement uses the render passes — the
ID map tells us where the sky is, the lines map tells us where the detail is — so
copy lands on calm areas instead of on a balustrade.
"""
import json
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
DESIGN = json.loads((ROOT / "config" / "design.json").read_text(encoding="utf-8"))
BRAND = json.loads((ROOT / "config" / "brand.json").read_text(encoding="utf-8"))
C = BRAND["palette"]


@lru_cache(maxsize=1)
def font_paths():
    d = ROOT / "assets" / "fonts"
    found = [p for p in sorted(d.rglob("*.otf")) + sorted(d.rglob("*.ttf")) if "WEB" not in p.parts] if d.exists() else []
    def pick(*keys, default):
        for k in keys:
            for p in found:
                if k in p.stem.lower():
                    return str(p)
        return default
    fb = BRAND.get("typography_fallback_files", {"regular": "C:/Windows/Fonts/arial.ttf", "bold": "C:/Windows/Fonts/arialbd.ttf"})
    return {"regular": pick("switzer-regular", "inter-regular", default=fb["regular"]),
            "medium": pick("switzer-medium", "inter-medium", default=fb["regular"]),
            "bold": pick("switzer-semibold", "switzer-bold", "inter-semibold", default=fb["bold"])}


@lru_cache(maxsize=64)
def font(weight, size):
    return ImageFont.truetype(font_paths()[weight], size)


def luminance(rgb):
    c = [v / 255 for v in rgb[:3]]
    c = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contrast_ratio(fg, bg):
    a, b = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


class Canvas:
    """A format-aware canvas: tokens scale with width, text is set with tracking."""

    def __init__(self, fmt, bg=None):
        spec = DESIGN["formats"][fmt]
        self.fmt = fmt
        self.w, self.h = spec["w"], spec["h"]
        self.safe = spec["safe"]
        self.k = self.w / 1080  # token scale
        self.img = Image.new("RGB", (self.w, self.h), bg or C["paper"])
        self.d = ImageDraw.Draw(self.img)
        self.boxes = []  # every type block, for the collision check

    # ---- grid
    def col(self, n):
        g = DESIGN["grid"]
        m, gut = g["margin"] * self.k, g["gutter"] * self.k
        cw = (self.w - 2 * m - gut * (g["cols"] - 1)) / g["cols"]
        return m + n * (cw + gut)

    def span(self, n):
        g = DESIGN["grid"]
        m, gut = g["margin"] * self.k, g["gutter"] * self.k
        cw = (self.w - 2 * m - gut * (g["cols"] - 1)) / g["cols"]
        return n * cw + (n - 1) * gut

    def tok(self, role):
        t = dict(DESIGN["type"][role])
        t["px"] = round(t["size"] * self.k)
        t["font"] = font(t["weight"], t["px"])
        return t

    # ---- text
    def _case(self, text, case):
        return text.upper() if case == "upper" else text.lower() if case == "lower" else text

    def width_of(self, text, t):
        tr = t["tracking"] * t["px"]
        return sum(self.d.textlength(ch, font=t["font"]) + tr for ch in text) - tr if text else 0

    def wrap(self, text, t, max_w):
        words, lines, cur = text.split(), [], ""
        for w in words:
            trial = f"{cur} {w}".strip()
            if self.width_of(trial, t) <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines

    def text(self, xy, text, role, fill, max_w=None, align="left", case=None):
        """Draw text with tracking; returns the y after the block."""
        t = self.tok(role)
        text = self._case(text, case or t["case"])
        lines = self.wrap(text, t, max_w) if max_w else [text]
        x0, y = xy
        y0, wmax = y, 0
        for line in lines:
            x = x0 if align == "left" else x0 - self.width_of(line, t)
            tr = t["tracking"] * t["px"]
            for ch in line:
                self.d.text((x, y), ch, font=t["font"], fill=fill)
                x += self.d.textlength(ch, font=t["font"]) + tr
            wmax = max(wmax, self.width_of(line, t))
            y += t["px"] * t["leading"]
        left = x0 if align == "left" else x0 - wmax
        self.boxes.append({"role": role, "box": (left, y0, wmax, y - y0), "text": text[:40]})
        return y

    def block_height(self, text, role, max_w):
        t = self.tok(role)
        return len(self.wrap(self._case(text, t["case"]), t, max_w)) * t["px"] * t["leading"]

    # ---- devices
    def rule(self, x, y, w, fill=None):
        h = max(1, round(DESIGN["devices"]["hairline"] * self.k))
        self.d.rectangle([x, y, x + w, y + h], fill=fill or C["ink"])
        return y + h

    def place_image(self, path, box):
        """Cover-fit an image into box=(x, y, w, h)."""
        x, y, w, h = [round(v) for v in box]
        im = Image.open(path).convert("RGB")
        s = max(w / im.width, h / im.height)
        im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
        ox, oy = (im.width - w) // 2, (im.height - h) // 2
        self.img.paste(im.crop((ox, oy, ox + w, oy + h)), (x, y))
        return (x, y, w, h)

    def scrim(self, box, strength=0.82, direction="up"):
        """Soft dark gradient so type stays readable over a photo."""
        x, y, w, h = [round(v) for v in box]
        g = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        gd = ImageDraw.Draw(g)
        for i in range(h):
            p = (i / h) if direction == "up" else 1 - (i / h)
            gd.line([(0, i), (w, i)], fill=(14, 12, 10, int(255 * strength * p ** 1.25)))
        self.img.paste(g, (x, y), g)

    def save(self, path, quality=93):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.img.save(path, quality=quality, subsampling=0)
        return path


# ---- image-aware placement -------------------------------------------------

@lru_cache(maxsize=8)
def passes(cam):
    p = ROOT / "out" / "passes" / cam
    ids = np.asarray(Image.open(p / "ids.png").convert("RGB"))
    lines = np.asarray(Image.open(p / "lines.png").convert("L"))
    sky = np.all(ids == 0, axis=-1)  # sky has ID (0,0,0)
    return sky, lines


def calm_band(cam, crop_box, canvas_box, bands=("bottom", "top")):
    """Pick the calmer horizontal band (less geometric detail, more sky) for a type block.

    crop_box: (left, top, w, h) of the render crop inside the original pass, in pass pixels.
    Returns the band name and its detail score (0 = empty, 1 = all edges).
    """
    sky, lines = passes(cam)
    x, y, w, h = [round(v) for v in crop_box]
    sub_l = lines[y:y + h, x:x + w]
    sub_s = sky[y:y + h, x:x + w]
    scores = {}
    for band in bands:
        part_l = sub_l[: h // 3] if band == "top" else sub_l[-h // 3:]
        part_s = sub_s[: h // 3] if band == "top" else sub_s[-h // 3:]
        detail = float((part_l > 96).mean())
        scores[band] = detail - 0.25 * float(part_s.mean())  # sky is a bonus
    best = min(scores, key=scores.get)
    return best, scores[best]


def detail_under(cam, region):
    """Share of edge pixels under a region (x, y, w, h) in pass pixels."""
    _, lines = passes(cam)
    x, y, w, h = [round(v) for v in region]
    x, y = max(0, x), max(0, y)
    sub = lines[y:y + h, x:x + w]
    return float((sub > 96).mean()) if sub.size else 0.0
