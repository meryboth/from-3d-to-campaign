"""Render -> finished ad: brand, copy, formats and languages.

Takes a piece from the asset library and lays out feed / story / banner in every
language, respecting each format's safe zones (story: 250 px top, 320 px bottom).
Everything is local and free; each run is logged to out/runs.jsonl.

    .venv/Scripts/python pipeline/composer.py --piece street_restored --langs es en pt
    .venv/Scripts/python pipeline/composer.py --all
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).parent))
from brand_mark import draw_mark  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BRAND = json.loads((ROOT / "config" / "brand.json").read_text(encoding="utf-8"))
COPY = json.loads((ROOT / "config" / "copy.json").read_text(encoding="utf-8"))
C = BRAND["palette"]


def font_files():
    """Prefer a downloaded grotesk in assets/fonts (Inter, Switzer...); fall back to Arial."""
    d = ROOT / "assets" / "fonts"
    # desktop OTF/TTF only; skip the WEB folder's hinted subset
    found = [p for p in sorted(d.rglob("*.otf")) + sorted(d.rglob("*.ttf")) if "WEB" not in p.parts]
    files = {p.stem.lower(): p for p in found} if d.exists() else {}
    def pick(*keys, default):
        for k in keys:
            for stem, p in files.items():
                if k in stem:
                    return str(p)
        return default
    return {
        "regular": pick("switzer-regular", "inter-regular", "inter_18pt-regular", default=BRAND["typography"]["files"]["regular"]),
        "bold": pick("switzer-semibold", "switzer-bold", "inter-semibold", "inter-bold", default=BRAND["typography"]["files"]["bold"]),
        "medium": pick("switzer-medium", "inter-medium", default=BRAND["typography"]["files"]["regular"]),
    }


FONTS = font_files()
fnt = lambda w, s: ImageFont.truetype(FONTS[w], s)


def wrap(draw, text, font, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = f"{cur} {w}".strip()
        if draw.textlength(t, font=font) <= max_w:
            cur = t
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


def text_block(d, xy, lines, font, fill, leading=1.18):
    x, y = xy
    for line in lines:
        d.text((x, y), line, font=font, fill=fill)
        y += round(font.size * leading)
    return y


def facts(lang):
    p = COPY["project"]
    L = COPY["labels"][lang]
    return f"{p['rooms']} {L['rooms']}  ·  {p['area_m2']} {L['area']}  ·  {p['patios']} {L['patios']}  ·  {L['from']} USD {p['price_usd']:,}".replace(",", ".")


def compose(piece, fmt, lang):
    spec = BRAND["formats"][fmt]
    W, H = spec["w"], spec["h"]
    sl, st, sr, sb = spec["safe"]
    copy = COPY["pieces"][piece][lang]
    img = Image.new("RGB", (W, H), C["paper"])
    src = Image.open(ROOT / "out" / "library" / piece / f"{fmt}.jpg").convert("RGB")

    if fmt == "feed":
        band = 300
        ih = H - band
        img.paste(src.resize((W, ih), Image.LANCZOS), (0, 0))
        d = ImageDraw.Draw(img)
        y = ih + 46
        head = fnt("bold", 58)
        y = text_block(d, (sl + 16, y), wrap(d, copy["head"], head, W - 2 * sl - 220), head, C["ink"])
        text_block(d, (sl + 16, y + 10), wrap(d, facts(lang), fnt("regular", 27), W - 2 * sl - 32), fnt("regular", 27), C["muted"], 1.35)
        draw_mark(img, (W - sl - 16 - 54, ih + 52), 54)
        d.text((W - sl - 16, ih + 118), BRAND["wordmark"], font=fnt("regular", 21), fill=C["ink"], anchor="ra")
        d.text((sl + 16, H - 44), BRAND["legal"]["ai_disclosure"][lang], font=fnt("regular", 19), fill=C["muted"])

    elif fmt == "story":
        img.paste(src.resize((W, H), Image.LANCZOS), (0, 0))
        d = ImageDraw.Draw(img)
        head, sub, small = fnt("bold", 72), fnt("regular", 32), fnt("regular", 26)
        maxw = W - 2 * sl - 40
        lines, subl = wrap(d, copy["head"], head, maxw), wrap(d, copy["sub"], sub, maxw)
        block = len(lines) * head.size * 1.15 + 16 + len(subl) * sub.size * 1.3 + 26 + small.size + 70 + 34
        bottom = H - sb            # nothing below this: the platform UI lives there
        top = bottom - block
        scrim_h = round(H - top + 200)
        scrim = Image.new("RGBA", (W, scrim_h), (0, 0, 0, 0))
        sd = ImageDraw.Draw(scrim)
        for i in range(scrim_h):   # gradient so copy stays readable over any photo
            # ramp to full opacity by the time the copy starts, then hold
            sd.line([(0, i), (W, i)], fill=(18, 16, 14, int(225 * min(1.0, (i / (scrim_h * 0.42)) ** 1.1))))
        img.paste(scrim, (0, H - scrim_h), scrim)
        d = ImageDraw.Draw(img)
        y = text_block(d, (sl + 20, top), lines, head, C["paper"], 1.15)
        y = text_block(d, (sl + 20, y + 16), subl, sub, "#DCD8CE", 1.3)
        d.text((sl + 20, y + 26), facts(lang), font=small, fill="#BDB8AC")
        d.text((sl + 20, y + 26 + small.size + 34), COPY["cta"][lang].upper(), font=fnt("bold", 30), fill=C["accent"])
        d.text((sl + 20, bottom - 30), BRAND["legal"]["ai_disclosure"][lang], font=fnt("regular", 18), fill="#9A958A")
        draw_mark(img, (sl + 20, st + 20), 56, C["paper"])
        d.text((sl + 88, st + 28), BRAND["wordmark"], font=fnt("regular", 30), fill=C["paper"])

    else:  # banner: image left, paper panel right
        pw = round(W * 0.38)
        iw = W - pw
        img.paste(src.resize((iw, H), Image.LANCZOS), (0, 0))
        d = ImageDraw.Draw(img)
        x = iw + 56
        draw_mark(img, (x, 64), 52)
        d.text((x + 68, 74), BRAND["wordmark"], font=fnt("regular", 28), fill=C["ink"])
        head = fnt("bold", 52)
        y = text_block(d, (x, 260), wrap(d, copy["head"], head, pw - 112), head, C["ink"])
        sub = fnt("regular", 27)
        y = text_block(d, (x, y + 18), wrap(d, copy["sub"], sub, pw - 112), sub, C["muted"], 1.35)
        text_block(d, (x, y + 40), wrap(d, facts(lang), fnt("regular", 24), pw - 112), fnt("regular", 24), C["ink"], 1.5)
        d.text((x, H - 150), COPY["cta"][lang].upper(), font=fnt("bold", 30), fill=C["accent"])
        d.text((x, H - 70), BRAND["legal"]["ai_disclosure"][lang], font=fnt("regular", 18), fill=C["muted"])

    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--piece")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--langs", nargs="+", default=["es", "en", "pt"])
    ap.add_argument("--formats", nargs="+", default=list(BRAND["formats"]))
    args = ap.parse_args()
    pieces = [p["piece"] for p in json.loads((ROOT / "config" / "approved.json").read_text(encoding="utf-8"))["pieces"]] if args.all else [args.piece]

    t0 = time.time()
    n = 0
    for piece in pieces:
        out_dir = ROOT / "out" / "ads" / piece
        out_dir.mkdir(parents=True, exist_ok=True)
        for fmt in args.formats:
            for lang in args.langs:
                compose(piece, fmt, lang).save(out_dir / f"{fmt}_{lang}.jpg", quality=92)
                n += 1
        print(f"{piece}: {len(args.formats) * len(args.langs)} ads")
    ms = round((time.time() - t0) * 1000)
    with (ROOT / "out" / "runs.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "stage": "compose_ads", "backend": "local",
                            "item": ",".join(pieces), "n_assets": n, "langs": args.langs, "formats": args.formats,
                            "ms": ms, "cost_usd": 0, "cache_hit": False}) + "\n")
    print(f"{n} ads in {ms / 1000:.1f}s  ({ms / max(n, 1):.0f} ms each)")


if __name__ == "__main__":
    main()
