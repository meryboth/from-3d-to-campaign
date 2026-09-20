"""The 'form and order' mark, drawn from code (no external asset).

2x2 grid: two solid squares and two quarter-discs arranged as a pinwheel.
Order = the grid; form = the curves.

    draw_mark(img, (x, y), size, color)      # on a PIL image
    mark_svg(size, color)                    # standalone SVG string
"""
from PIL import Image, ImageDraw


def draw_mark(img, xy, size, color="#12100E"):
    """Draw the mark with its top-left corner at xy, occupying size x size px."""
    ss = 4  # supersample so the curves stay clean at small sizes
    m = Image.new("RGBA", (size * ss, size * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(m)
    h = size * ss // 2
    box = [0, 0, 2 * h, 2 * h]                     # circle centred on the middle of the grid
    d.rectangle([0, 0, h, h], fill=color)          # top-left: square
    d.pieslice(box, 270, 360, fill=color)          # top-right: quarter disc
    d.pieslice(box, 90, 180, fill=color)           # bottom-left: quarter disc
    d.rectangle([h, h, 2 * h, 2 * h], fill=color)  # bottom-right: square
    img.paste(m.resize((size, size), Image.LANCZOS), xy, m.resize((size, size), Image.LANCZOS))
    return img


def mark_svg(size=100, color="#12100E"):
    h = size / 2
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" width="{size}" height="{size}">'
            f'<rect x="0" y="0" width="{h}" height="{h}" fill="{color}"/>'
            f'<path d="M{h} 0 A {h} {h} 0 0 1 {size} {h} L {h} {h} Z" fill="{color}"/>'
            f'<path d="M{h} {size} A {h} {h} 0 0 1 0 {h} L {h} {h} Z" fill="{color}"/>'
            f'<rect x="{h}" y="{h}" width="{h}" height="{h}" fill="{color}"/></svg>')


if __name__ == "__main__":
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    out = root / "assets" / "brand"
    out.mkdir(parents=True, exist_ok=True)
    (out / "mark.svg").write_text(mark_svg(200), encoding="utf-8")
    img = Image.new("RGB", (600, 260), "#EFECE3")
    draw_mark(img, (60, 60), 140)
    from PIL import ImageFont
    f = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 54)
    ImageDraw.Draw(img).text((240, 118), "form and order", font=f, fill="#12100E")
    img.save(out / "lockup.png")
    print(out / "lockup.png")
