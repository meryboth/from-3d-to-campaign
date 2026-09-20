"""Approved render -> campaign asset library.

Upscales 2x with Real-ESRGAN on the local GPU (free) and cuts the formats the
campaign needs, framing each crop on the house (from the material-ID pass) instead
of the image center. Every step is logged to out/runs.jsonl.

    .venv/Scripts/python pipeline/library.py out/renders/cloud/street/foo.png --cam street --piece street_restored
"""
import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from comfy import Comfy  # noqa: E402
from qa import HOUSE_KEYS, mask_for  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FORMATS = {"feed": (1, 1), "story": (9, 16), "banner": (16, 9)}


def log(entry):
    with (ROOT / "out" / "runs.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(), **entry}) + "\n")


def upscale(path, comfy):
    """2x via Real-ESRGAN x4 then lanczos 0.5, on the local ComfyUI."""
    wf = json.loads((ROOT / "workflows" / "api" / "upscale_realesrgan_2x.json").read_text())
    data = Path(path).read_bytes()
    name = f"lib_{hashlib.sha256(data).hexdigest()[:16]}.png"
    wf["1"]["inputs"]["image"] = comfy.upload_image(data, name)
    wf["5"]["inputs"]["filename_prefix"] = f"casa/upscaled_{Path(path).stem}"
    res = comfy.run(wf)
    return res["images"][0]["data"], res


def house_box(cam, shape):
    """Bounding box of the house in the ID pass, scaled to the target image size."""
    ids = np.asarray(Image.open(ROOT / "out" / "passes" / cam / "ids.png").convert("RGB"))
    m = mask_for(ids, HOUSE_KEYS)
    ys, xs = np.where(m)
    sy, sx = shape[0] / ids.shape[0], shape[1] / ids.shape[1]
    return xs.min() * sx, ys.min() * sy, xs.max() * sx, ys.max() * sy


def crop(img, ratio, box):
    """Largest crop with the given aspect ratio that still fits the frame, centered on the house."""
    W, H = img.size
    cx = (box[0] + box[2]) / 2
    cy = (box[1] + box[3]) / 2
    rw, rh = ratio
    w = min(W, H * rw / rh)
    h = w * rh / rw
    x = min(max(cx - w / 2, 0), W - w)
    y = min(max(cy - h / 2, 0), H - h)
    return img.crop((round(x), round(y), round(x + w), round(y + h)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("render")
    ap.add_argument("--cam", required=True)
    ap.add_argument("--piece", required=True, help="asset name, e.g. street_restored")
    args = ap.parse_args()

    out_dir = ROOT / "out" / "library" / args.piece
    out_dir.mkdir(parents=True, exist_ok=True)
    master = out_dir / "master_2x.png"

    if master.exists():
        log({"stage": "library_upscale", "item": args.piece, "cache_hit": True, "ms": 0, "cost_usd": 0})
        print(f"cache hit  {master.relative_to(ROOT)}")
    else:
        t0 = time.time()
        data, res = upscale(args.render, Comfy())
        master.write_bytes(data)
        log({"stage": "library_upscale", "item": args.piece, "backend": "local_comfyui", "model": "RealESRGAN_x4plus",
             "source": Path(args.render).resolve().relative_to(ROOT).as_posix(), "cache_hit": False,
             "ms": res["total_ms"], "node_ms": res["node_ms"], "vram_peak_mb": res.get("vram_peak_mb"),
             "energy_wh": res.get("energy_wh"), "cost_usd": 0, "output": master.relative_to(ROOT).as_posix()})
        print(f"upscaled   {master.relative_to(ROOT)}  {res['total_ms'] / 1000:.1f}s")

    img = Image.open(master).convert("RGB")
    box = house_box(args.cam, (img.size[1], img.size[0]))
    t0 = time.time()
    for name, ratio in FORMATS.items():
        out = out_dir / f"{name}.jpg"
        crop(img, ratio, box).save(out, quality=92)
        print(f"  {name:7} {Image.open(out).size}")
    log({"stage": "library_crops", "item": args.piece, "formats": list(FORMATS), "cache_hit": False,
         "ms": round((time.time() - t0) * 1000), "cost_usd": 0})


if __name__ == "__main__":
    main()
