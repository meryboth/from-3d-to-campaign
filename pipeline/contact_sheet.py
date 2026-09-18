"""Contact sheet: one row per camera, one column per pass.

    py pipeline/contact_sheet.py            -> out/sheets/passes.png
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
PASSES = ["beauty", "depth", "normal", "lines", "ids"]
THUMB_W = 480
PAD = 12
LABEL_H = 28


def font(size):
    for name in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def main(out_path=ROOT / "out" / "sheets" / "passes.png"):
    cams = json.loads((ROOT / "config" / "cameras.json").read_text())["cameras"]
    first = Image.open(ROOT / "out" / "passes" / cams[0]["id"] / "beauty.png")
    th = round(first.height * THUMB_W / first.width)
    sheet = Image.new("RGB", (PAD + len(PASSES) * (THUMB_W + PAD), LABEL_H + PAD + len(cams) * (th + LABEL_H + PAD)), "#141414")
    draw = ImageDraw.Draw(sheet)
    f = font(18)
    for c, name in enumerate(PASSES):
        draw.text((PAD + c * (THUMB_W + PAD), 6), name, fill="#e8e8e8", font=f)
    for r, cam in enumerate(cams):
        y = LABEL_H + PAD + r * (th + LABEL_H + PAD)
        draw.text((PAD, y), f"{cam['id']} · {cam['label']}", fill="#a0a0a0", font=f)
        for c, name in enumerate(PASSES):
            img = Image.open(ROOT / "out" / "passes" / cam["id"] / f"{name}.png").convert("RGB")
            img = img.resize((THUMB_W, th), Image.NEAREST if name == "ids" else Image.LANCZOS)
            sheet.paste(img, (PAD + c * (THUMB_W + PAD), y + LABEL_H))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    print(out_path)


if __name__ == "__main__":
    main(*sys.argv[1:])
