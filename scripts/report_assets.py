# Collects the figures the case-study page uses into docs/report/assets, web-sized.
#
# Nothing here is decorative: every file is an artefact of a run, copied from where the
# pipeline wrote it. Re-run after new renders to refresh the page.
#
#   python scripts/report_assets.py
import shutil
import sys
from pathlib import Path

from PIL import Image

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "report" / "assets"

# source -> (published name, max width, quality). JPEG for photos, PNG for graphs and diagrams.
FIGURES = [
    ("docs/images/comfy_graph_master.png", "graph-master.png", 2200, None),
    ("docs/images/comfy_nodes_detail.png", "graph-nodes.png", 1300, None),
    ("out/sheets/passes.png", "passes.jpg", 2000, 86),
    ("out/sheets/street_before_after.png", "before-after.jpg", 1600, 88),
    ("out/sheets/model_bakeoff_street.png", "bakeoff.jpg", 1600, 88),
    ("out/sheets/ab_klein_lines_vs_zimage_palette.png", "ab-lines-palette.jpg", 1600, 88),
    ("out/sheets/graph_i2i.png", "i2i-strip.jpg", 2000, 86),
    ("out/sheets/retry_review.png", "retry-review.jpg", 1600, 88),
    ("out/sheets/library_v1.png", "library.jpg", 1000, 86),
    ("out/sheets/post_carousel.png", "post-carousel.jpg", 2200, 86),
    ("out/sheets/post_story_link.png", "post-story-link.jpg", 1600, 88),
    ("out/graph3d_street_restored.png", "hero.jpg", 2200, 88),
    ("out/posts/casa-larga-1408/es/01_cover.jpg", "asset-cover.jpg", 900, 90),
    ("out/posts/casa-larga-1408/es/04_data.jpg", "asset-data.jpg", 900, 90),
    ("out/posts/casa-larga-1408/es/05_end.jpg", "asset-end.jpg", 900, 90),
    ("out/posts/casa-larga-1408/es/story.jpg", "asset-story.jpg", 700, 90),
]
FONTS = [("assets/fonts/Switzer_Complete/Fonts/TTF/Switzer-Variable.ttf", "Switzer-Variable.ttf")]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "fonts").mkdir(exist_ok=True)
    total = 0
    for src, name, max_w, quality in FIGURES:
        p = ROOT / src
        if not p.exists():
            print(f"missing   {src}")
            continue
        im = Image.open(p)
        if im.width > max_w:
            im = im.resize((max_w, round(im.height * max_w / im.width)), Image.LANCZOS)
        dst = OUT / name
        if quality:
            im.convert("RGB").save(dst, quality=quality, subsampling=1, optimize=True)
        else:
            im.save(dst, optimize=True)
        kb = dst.stat().st_size / 1024
        total += kb
        print(f"{name:24s} {im.width}x{im.height}  {kb:6.0f} kB")
    for src, name in FONTS:
        shutil.copy(ROOT / src, OUT / "fonts" / name)
        print(f"{name:24s} font")
    print(f"total {total/1024:.1f} MB")


if __name__ == "__main__":
    main()
