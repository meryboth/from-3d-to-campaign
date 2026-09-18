"""CAD -> photoreal render through ComfyUI (SDXL + ControlNet union: depth + lines).

    .venv/Scripts/python pipeline/render.py --cam street --style restored --seed 1
    .venv/Scripts/python pipeline/render.py --cam street --style restored --set cn_depth.strength=0.8

Content-addressed cache: the key hashes the patched workflow with the control images
replaced by their content hashes, so the same inputs never hit the GPU twice.
Every attempt is logged to out/runs.jsonl.
"""
import argparse
import copy
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from comfy import Comfy, ComfyError  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "out" / "runs.jsonl"


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:16]


def by_title(wf, title):
    for node in wf.values():
        if node.get("_meta", {}).get("title") == title:
            return node["inputs"]
    raise KeyError(f"no node titled {title!r}")


def coerce(v: str):
    for cast in (int, float):
        try:
            return cast(v)
        except ValueError:
            pass
    return v


def log(entry):
    RUNS.parent.mkdir(parents=True, exist_ok=True)
    with RUNS.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(), **entry}) + "\n")


def build(args):
    wf = json.loads((ROOT / "workflows" / "api" / f"{args.workflow}.json").read_text())
    styles = json.loads((ROOT / "config" / "styles.json").read_text())
    passes = ROOT / "out" / "passes" / args.cam
    # every LoadImage titled "<pass>_image" gets that render pass (depth, lines, beauty, ...)
    names = [n["_meta"]["title"][:-6] for n in wf.values() if n["class_type"] == "LoadImage" and n["_meta"]["title"].endswith("_image")]
    controls = {name: (passes / f"{name}.png").read_bytes() for name in names}

    by_title(wf, "positive")["text"] = f"{styles['subject'][args.cam]}, {styles['styles'][args.style]}"
    by_title(wf, "negative")["text"] = styles["negative"]
    by_title(wf, "sampler")["seed"] = args.seed
    for s in args.set:
        key, val = s.split("=", 1)
        title, field = key.split(".", 1)
        by_title(wf, title)[field] = coerce(val)

    # cache key: workflow with image names replaced by content hashes
    keyed = copy.deepcopy(wf)
    for name, data in controls.items():
        by_title(keyed, f"{name}_image")["image"] = sha(data)
    by_title(keyed, "save")["filename_prefix"] = ""
    key = sha(json.dumps(keyed, sort_keys=True).encode())
    return wf, controls, key


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cam", default="street")
    ap.add_argument("--style", default="restored")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--workflow", default="cn_depth_lines_sdxl")
    ap.add_argument("--set", action="append", default=[], help="title.field=value overrides")
    ap.add_argument("--tag", default="", help="free label for experiments (A/B tests)")
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--gate", type=int, default=0, metavar="N",
                    help="quality gate (config/qa.json): on fail, retry up to N times with a new seed")
    args = ap.parse_args()

    for gate_try in range(args.gate + 1):
        out_png = render_once(args)
        if not args.gate:
            return
        from gate import check
        ok, scores, reasons = check(out_png, args.cam)
        log({"stage": "qa_gate", "item": f"{args.cam}/{args.style}/s{args.seed}", "output": str(out_png.relative_to(ROOT)),
             "passed": ok, "reasons": reasons, "scores": {k: v for k, v in scores.items() if k != "house_px"}, "gate_try": gate_try})
        print(("QA PASS " if ok else "QA FAIL ") + "; ".join(reasons))
        if ok:
            return
        args.seed += 1000  # new seed, same everything else
    print(f"gate: no render passed after {args.gate + 1} tries; flag for human review")


def render_once(args):
    wf, controls, key = build(args)
    out_dir = ROOT / "out" / "renders" / args.cam
    out_dir.mkdir(parents=True, exist_ok=True)
    out_png = out_dir / f"{args.style}_s{args.seed}_{key}.png"
    base = {"stage": "render", "item": f"{args.cam}/{args.style}/s{args.seed}", "hash": key, "workflow": args.workflow,
            "tag": args.tag, "overrides": args.set, "model": by_title(wf, "ckpt")["ckpt_name"],
            "steps": by_title(wf, "sampler")["steps"], "cfg": by_title(wf, "sampler")["cfg"], "cost_usd": 0}

    if out_png.exists() and not args.force:
        log({**base, "cache_hit": True, "ms": 0, "attempt": 0})
        print(f"cache hit  {out_png.relative_to(ROOT)}")
        return out_png

    comfy = Comfy()
    for name, data in controls.items():
        by_title(wf, f"{name}_image")["image"] = comfy.upload_image(data, f"{args.cam}_{name}_{sha(data)}.png")
    by_title(wf, "save")["filename_prefix"] = f"casa/{args.cam}_{args.style}_s{args.seed}"

    for attempt in range(1, args.retries + 2):
        try:
            t0 = time.time()
            res = comfy.run(wf)
            break
        except (ComfyError, OSError) as e:
            log({**base, "cache_hit": False, "ms": round((time.time() - t0) * 1000), "attempt": attempt, "error": str(e)[:500]})
            print(f"attempt {attempt} failed: {e}")
            if attempt > args.retries:
                raise
            time.sleep(3 * attempt)

    out_png.write_bytes(res["images"][0]["data"])
    meta = {**base, "cache_hit": False, "attempt": attempt, "ms": res["total_ms"], "node_ms": res["node_ms"],
            "cached_nodes": res["cached_nodes"], "vram_peak_mb": res.get("vram_peak_mb"), "gpu_util_avg": res.get("gpu_util_avg"),
            "power_avg_w": res.get("power_avg_w"), "energy_wh": res.get("energy_wh"), "output": str(out_png.relative_to(ROOT))}
    out_png.with_suffix(".json").write_text(json.dumps({**meta, "workflow": wf}, indent=2))
    log(meta)
    print(json.dumps({k: meta[k] for k in ("item", "ms", "node_ms", "cached_nodes", "vram_peak_mb", "power_avg_w", "energy_wh")}, indent=1))
    print(out_png.relative_to(ROOT))
    return out_png


if __name__ == "__main__":
    main()
