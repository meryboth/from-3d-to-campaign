# Turns a raw ComfyUI canvas export into a report figure.
#
# The canvas is exported from the browser with `canvas.toDataURL()` and POSTed to
# ComfyUI's /api/userdata as base64 text (that is the only way to get the graph at
# print resolution, without window chrome and without the viewport cropping it).
# This script decodes that text and draws the brand furniture on top: a title bar
# and the stage labels, positioned with the pixel coordinates the browser reported.
#
#   python scripts/comfy_figure.py casa_shot_graph.txt docs/images/comfy_graph_master.png \
#       --title "Master graph" --subtitle "..." --labels '[{"title":"1 - in","px":68}]'
import argparse, base64, json, sys
from io import BytesIO
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
USERDATA = Path.home() / "Documents" / "ComfyUI" / "user" / "default"
FONTS = ROOT / "assets" / "fonts" / "Switzer_Complete" / "Fonts" / "OTF"
BRAND = json.loads((ROOT / "config" / "brand.json").read_text(encoding="utf-8"))
INK, PAPER, ACCENT = "#0C0C0E", "#EFECE3", BRAND["palette"]["accent_on_dark"]


def font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / f"Switzer-{weight}.otf"), size)


def tracked(draw, xy, text, fnt, fill, tracking=0.0):
    """PIL has no letter-spacing, so draw glyph by glyph."""
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=fnt, fill=fill)
        x += draw.textlength(ch, font=fnt) + tracking
    return x


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("shot")  # file name inside ComfyUI's userdata, or a path
    ap.add_argument("out")
    ap.add_argument("--title", default="")
    ap.add_argument("--subtitle", default="")
    ap.add_argument("--labels", default="[]")  # [{"title": str, "px": int}]
    ap.add_argument("--band", type=int, default=0, help="extra top band in px (0 = reuse the export's own padding)")
    a = ap.parse_args()

    src = Path(a.shot)
    if not src.exists():
        src = USERDATA / a.shot
    raw = src.read_text(encoding="utf-8").strip().strip('"')
    shot = Image.open(BytesIO(base64.b64decode(raw))).convert("RGBA")
    # the canvas is exported without its background layer, so the figure gets one flat
    # ink field instead of LiteGraph's two-tone viewport
    img = Image.new("RGB", shot.size, INK)
    img.paste(shot, (0, 0), shot)

    band = a.band
    if band:
        canvas = Image.new("RGB", (img.width, img.height + band), INK)
        canvas.paste(img, (0, band))
        img = canvas
    d = ImageDraw.Draw(img)

    if a.title:
        tracked(d, (68, 34), a.title.upper(), font("Semibold", 34), PAPER, 2.4)
    if a.subtitle:
        d.text((68, 82), a.subtitle, font=font("Regular", 26), fill="#8A8A8F")

    for lab in json.loads(a.labels):
        x, y = lab["px"], lab.get("py", 118)
        end = tracked(d, (x, y), lab["title"].upper(), font("Medium", 24), ACCENT, 1.8)
        d.line([(x, y + 38), (max(end, x + 120), y + 38)], fill="#2E2E33", width=2)

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    print(f"{out}  {img.width}x{img.height}")


if __name__ == "__main__":
    main()
