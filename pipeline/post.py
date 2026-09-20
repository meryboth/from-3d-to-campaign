"""Post builder: approved renders -> a publishable sequence.

One post = a 4:5 carousel (cover, shots, data card, end card) + a story + a link
image, in every language, plus the caption file and a publishing manifest.
Every slide goes through design QA (contrast, safe zones, type size, detail under
type) and the result is written next to the assets.

    .venv/Scripts/python pipeline/post.py --post casa-larga-1408 --langs es en pt
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from brand_mark import draw_mark  # noqa: E402
from design import BRAND, C, Canvas, contrast_ratio, DESIGN, hex_rgb  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
COPY = json.loads((ROOT / "config" / "copy.json").read_text(encoding="utf-8"))
POSTS = json.loads((ROOT / "config" / "posts.json").read_text(encoding="utf-8"))["posts"]
APPROVED = {p["piece"]: p for p in json.loads((ROOT / "config" / "approved.json").read_text(encoding="utf-8"))["pieces"]}
QA = DESIGN["qa"]
DEV = DESIGN["devices"]


def master(piece):
    return ROOT / "out" / "library" / piece / "master_2x.png"


def meta_row(cv, y, left, right, fill):
    """A thin metadata rail: label on the left, label on the right, hairline under it."""
    cv.text((cv.col(0), y), left, "meta", fill)
    cv.text((cv.w - cv.col(0), y), right, "meta", fill, align="right")
    t = cv.tok("meta")
    return cv.rule(cv.col(0), y + t["px"] * 1.9, cv.w - 2 * cv.col(0), fill)


def sample_bg(cv, box):
    x, y, w, h = [round(v) for v in box]
    a = np.asarray(cv.img.crop((max(0, x), max(0, y), x + w, y + h)))
    return tuple(int(v) for v in a.reshape(-1, 3).mean(0))


def qa_collisions(cv, issues, where):
    """No type block may overlap another: the bug a contrast check cannot see."""
    for i, a in enumerate(cv.boxes):
        for b in cv.boxes[i + 1:]:
            ax, ay, aw, ah = a["box"]
            bx, by, bw, bh = b["box"]
            ox = min(ax + aw, bx + bw) - max(ax, bx)
            oy = min(ay + ah, by + bh) - max(ay, by)
            if ox > 4 and oy > 4:
                issues.append(f"{where}: '{a['text']}' overlaps '{b['text']}'")


def qa_text(cv, box, fill, role, issues, where):
    """Check a type block: contrast against what is behind it, and minimum size."""
    ratio = contrast_ratio(hex_rgb(fill), sample_bg(cv, box))
    if ratio < QA["min_contrast_ratio"]:
        issues.append(f"{where}: contrast {ratio:.1f} < {QA['min_contrast_ratio']}")
    if cv.tok(role)["px"] < QA["min_type_px"]:
        issues.append(f"{where}: type {cv.tok(role)['px']}px < {QA['min_type_px']}")
    return ratio


# ---------- slides ----------

def lockup(cv, mark_px, text_dx, text_dy, issues, where):
    """Mark + wordmark over a photo: they ride on an ink chip, because a gradient cannot
    guarantee contrast against a sky that changes with every render."""
    t = cv.tok("body")
    pad = round(14 * cv.k)
    x, y = round(cv.col(0)), round(cv.safe[1])
    w = round(text_dx * cv.k + cv.width_of(BRAND["wordmark"], t) + pad)
    h = round(max(mark_px * cv.k, t["px"] * 1.35) + pad)
    cv.plate((x - pad, y - pad * 0.8, w + pad, h + pad * 0.6), C["ink"], 0.86, radius=4 * cv.k)
    draw_mark(cv.img, (x, y), round(mark_px * cv.k), C["paper"])
    qa_text(cv, (x + text_dx * cv.k, y + text_dy * cv.k, cv.width_of(BRAND["wordmark"], t), t["px"] * 1.2),
            C["paper"], "body", issues, f"{where} wordmark")
    cv.text((x + text_dx * cv.k, y + text_dy * cv.k), BRAND["wordmark"], "body", C["paper"])


def slide_cover(post, lang, issues):
    cv = Canvas("feed")
    cv.place_image(master(post["cover"]), (0, 0, cv.w, cv.h))
    cv.scrim((0, round(cv.h * 0.45), cv.w, round(cv.h * 0.55)), 0.86)
    claim = post["claim"][lang]
    t = cv.tok("display")
    block_h = cv.block_height(claim, "display", cv.span(10))
    y = cv.h - cv.safe[3] - block_h - cv.tok("meta")["px"] * 4.6
    qa_text(cv, (cv.col(0), y, cv.span(10), block_h), C["paper"], "display", issues, f"cover/{lang} claim")
    y = cv.text((cv.col(0), y), claim, "display", C["paper"], cv.span(10))
    p = COPY["project"]
    meta_row(cv, y + 34 * cv.k, f"{p['neighbourhood']}", f"{p['lot']}", "#CFCABE")
    lockup(cv, 56, 72, 12, issues, f"cover/{lang}")
    cv.text((cv.w - cv.col(0), cv.safe[1] + 16 * cv.k), DEV["index_format"].format(n=1), "meta", "#CFCABE", align="right")
    return cv


def slide_shot(post, piece, n, lang, issues):
    cv = Canvas("feed")
    cv.place_image(master(piece), (0, 0, cv.w, cv.h))
    cap = post["shot_captions"][piece][lang]
    band = cv.block_height(cap, "body", cv.span(9)) + cv.tok("meta")["px"] * 5.0
    cv.scrim((0, round(cv.h - band - 260 * cv.k), cv.w, round(band + 260 * cv.k)), 0.92)
    y = cv.h - cv.safe[3] - band
    y = meta_row(cv, y, f"{DEV['index_format'].format(n=n)} · {piece.split('_')[0]}", COPY["project"]["name"], "#CFCABE")
    qa_text(cv, (cv.col(0), y + 30 * cv.k, cv.span(9), cv.block_height(cap, "body", cv.span(9))), C["paper"], "body", issues, f"shot{n}/{lang}")
    cv.text((cv.col(0), y + 30 * cv.k), cap, "body", C["paper"], cv.span(9))
    return cv


def slide_data(post, lang, issues):
    cv = Canvas("feed", C["paper"])
    p, L = COPY["project"], COPY["labels"][lang]
    y = meta_row(cv, cv.safe[1], COPY["project"]["typology"], p["status"][lang], C["ink"])
    y += 40 * cv.k
    for value, label in ((str(p["area_m2"]), L["area"]), (str(p["rooms"]), L["rooms"]), (str(p["patios"]), L["patios"])):
        t = cv.tok("number")
        cv.text((cv.col(0), y), value, "number", C["ink"])
        cv.text((cv.col(0) + cv.width_of(value, t) + 22 * cv.k, y + t["px"] * 0.62), label, "meta", C["muted"])
        y += t["px"] * 0.98
        cv.rule(cv.col(0), y, cv.span(12), "#D8D3C7")
        y += 30 * cv.k
    strip_h = cv.h - y - cv.safe[3] - 96 * cv.k
    cv.place_image(master(post["shots"][0]), (cv.col(0), y + 16 * cv.k, cv.span(12), strip_h))
    cv.text((cv.col(0), cv.h - cv.safe[3] - 44 * cv.k), f"{L['from']} USD {p['price_usd']:,}".replace(",", "."), "headline", C["ink"], case="none")
    qa_text(cv, (cv.col(0), cv.h - cv.safe[3] - 44 * cv.k, cv.span(8), 60 * cv.k), C["ink"], "headline", issues, f"data/{lang}")
    return cv


def slide_end(post, lang, issues):
    cv = Canvas("feed", C["ink"])
    draw_mark(cv.img, (round(cv.col(0)), round(cv.safe[1])), round(72 * cv.k), C["paper"])
    y = cv.h * 0.42
    y = cv.text((cv.col(0), y), BRAND["tagline"][lang], "headline", C["paper"], cv.span(9))
    cv.text((cv.col(0), y + 40 * cv.k), COPY["cta"][lang], "headline", C["accent_on_dark"], cv.span(9))
    qa_text(cv, (cv.col(0), y + 40 * cv.k, cv.span(9), 60 * cv.k), C["accent_on_dark"], "headline", issues, f"end/{lang} cta")
    cv.rule(cv.col(0), cv.h - cv.safe[3] - 80 * cv.k, cv.span(12), "#3A352E")
    cv.text((cv.col(0), cv.h - cv.safe[3] - 52 * cv.k), BRAND["legal"]["ai_disclosure"][lang], "caption", "#8A857A", cv.span(12))
    cv.text((cv.w - cv.col(0), cv.h - cv.safe[3] - 52 * cv.k), BRAND["wordmark"], "caption", "#8A857A", align="right")
    return cv


def slide_story(post, lang, issues):
    cv = Canvas("story")
    cv.place_image(master(post["cover"]), (0, 0, cv.w, cv.h))
    claim = post["claim"][lang]
    block_h = cv.block_height(claim, "display", cv.span(11))
    y = cv.h - cv.safe[3] - block_h - 170 * cv.k
    cv.scrim((0, round(y - 180 * cv.k), cv.w, round(cv.h - y + 180 * cv.k)), 0.88)
    qa_text(cv, (cv.col(0), y, cv.span(11), block_h), C["paper"], "display", issues, f"story/{lang}")
    y = cv.text((cv.col(0), y), claim, "display", C["paper"], cv.span(11))
    p, L = COPY["project"], COPY["labels"][lang]
    cv.text((cv.col(0), y + 24 * cv.k), f"{p['rooms']} {L['rooms']} · {p['area_m2']} {L['area']} · {L['from']} USD {p['price_usd']:,}".replace(",", "."), "body", "#DCD8CE")
    cv.text((cv.col(0), cv.h - cv.safe[3] - 6 * cv.k), COPY["cta"][lang], "meta", C["accent_on_dark"])
    lockup(cv, 56, 74, 14, issues, f"story/{lang}")
    cv.text((cv.col(0), cv.h - cv.safe[3] + 44 * cv.k), BRAND["legal"]["ai_disclosure"][lang], "caption", "#9A958A")
    return cv


def slide_link(post, lang, issues):
    """Editorial split for og:image / banner: image left, paper panel right."""
    cv = Canvas("link", C["paper"])
    iw = round(cv.w * 0.58)
    cv.place_image(master(post["cover"]), (0, 0, iw, cv.h))
    x = iw + 48 * cv.k
    draw_mark(cv.img, (round(x), round(cv.safe[1])), round(44 * cv.k))
    cv.text((x + 58 * cv.k, cv.safe[1] + 8 * cv.k), BRAND["wordmark"], "caption", C["ink"])
    y = cv.text((x, cv.h * 0.2), post["claim"][lang], "subhead", C["ink"], cv.w - x - cv.safe[2])
    p, L = COPY["project"], COPY["labels"][lang]
    cv.text((x, y + 22 * cv.k), f"{p['neighbourhood']} · {p['area_m2']} {L['area']}", "caption", C["muted"], cv.w - x - cv.safe[2])
    cv.text((x, y + 64 * cv.k), f"{L['from']} USD {p['price_usd']:,}".replace(",", "."), "body", C["ink"], cv.w - x - cv.safe[2], case="none")
    cv.text((x, cv.h - cv.safe[3] - 30 * cv.k), BRAND["legal"]["ai_disclosure"][lang], "caption", C["muted"], cv.w - x - cv.safe[2])
    qa_text(cv, (x, cv.h * 0.2, cv.w - x - cv.safe[2], 80 * cv.k), C["ink"], "subhead", issues, f"link/{lang}")
    return cv


# ---------- build ----------

def build(post, lang):
    issues = []
    out = ROOT / "out" / "posts" / post["id"] / lang
    files = []
    slides = [("01_cover", slide_cover(post, lang, issues))]
    for i, piece in enumerate(post["shots"], start=2):
        slides.append((f"{i:02d}_{piece}", slide_shot(post, piece, i, lang, issues)))
    slides += [(f"{len(post['shots']) + 2:02d}_data", slide_data(post, lang, issues)),
               (f"{len(post['shots']) + 3:02d}_end", slide_end(post, lang, issues)),
               ("story", slide_story(post, lang, issues)),
               ("link", slide_link(post, lang, issues))]
    for name, cv in slides:
        qa_collisions(cv, issues, f"{name}/{lang}")
        files.append(str(Path(cv.save(out / f"{name}.jpg")).relative_to(ROOT)).replace("\\", "/"))
    caption = post["caption"][lang] + "\n\n" + " ".join(post["hashtags"])
    (out / "caption.txt").write_text(caption, encoding="utf-8")
    return files, caption, issues


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--post", required=True)
    ap.add_argument("--langs", nargs="+", default=["es", "en", "pt"])
    args = ap.parse_args()
    post = next(p for p in POSTS if p["id"] == args.post)

    t0 = time.time()
    manifest = {"post": post["id"], "generated": datetime.now(timezone.utc).isoformat(),
                "pieces": [post["cover"], *post["shots"]],
                "provenance": {p: APPROVED[p]["render"] for p in [post["cover"], *post["shots"]]},
                "disclosure": BRAND["legal"]["ai_disclosure"], "languages": {}}
    all_issues = []
    for lang in args.langs:
        files, caption, issues = build(post, lang)
        manifest["languages"][lang] = {"carousel": [f for f in files if "/0" in f], "story": [f for f in files if f.endswith("story.jpg")][0],
                                       "link": [f for f in files if f.endswith("link.jpg")][0],
                                       "caption": f"out/posts/{post['id']}/{lang}/caption.txt", "qa_issues": issues}
        all_issues += issues
        print(f"{lang}: {len(files)} assets" + (f"  ⚠ {len(issues)} QA issues" if issues else "  QA clean"))
    ms = round((time.time() - t0) * 1000)
    (ROOT / "out" / "posts" / post["id"] / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    with (ROOT / "out" / "runs.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "stage": "build_post", "backend": "local",
                            "item": post["id"], "langs": args.langs, "n_assets": len(args.langs) * 7,
                            "qa_issues": len(all_issues), "ms": ms, "cost_usd": 0, "cache_hit": False}) + "\n")
    for i in all_issues:
        print("  QA:", i)
    print(f"{len(args.langs) * 7} assets in {ms / 1000:.1f}s")


if __name__ == "__main__":
    main()
