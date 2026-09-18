"""Collect a Comfy Cloud batch into the repo and log what it cost.

Input: a JSON list of {label, job, gpu_s, model, steps, url?, error?} built from the batch
output (download URLs) and the billing feed (gpu_seconds per job).

    .venv/Scripts/python pipeline/cloud_collect.py batch.json --tag cloud-bakeoff-1 --cam street
"""
import argparse
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Comfy Cloud developer pricing (2026-09-18): RTX 6000 Pro = $3.49/h = 736.39 credits/h
CREDITS_PER_S = 736.39 / 3600
USD_PER_S = 3.49 / 3600


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("batch")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--cam", default="street")
    args = ap.parse_args()

    runs = ROOT / "out" / "runs.jsonl"
    for it in json.loads(Path(args.batch).read_text()):
        cam = it.get("cam", args.cam)
        out_dir = ROOT / "out" / "renders" / "cloud" / cam
        out_dir.mkdir(parents=True, exist_ok=True)
        entry = {"ts": datetime.now(timezone.utc).isoformat(), "stage": "render", "backend": "comfy_cloud", "gpu": "rtx_pro_6000",
                 "item": f"{cam}/{it['label']}", "style": it.get("style"), "workflow": "cloud/" + it["label"].rsplit("_", 2)[0], "tag": args.tag,
                 "model": it.get("model"), "steps": it.get("steps"), "cache_hit": False, "attempt": 1, "job_id": it.get("job")}
        if it.get("error"):
            entry.update(error=it["error"], gpu_seconds=0, credits=0, cost_usd=0, ms=0)
        else:
            out = out_dir / f"{it['label']}.png"
            if out.exists():
                raise SystemExit(f"{out} already exists: labels must be unique per render (include palette/cam/style)")
            if it.get("url"):
                with urllib.request.urlopen(it["url"], timeout=60) as r:
                    out.write_bytes(r.read())
            gs = it["gpu_s"]
            entry.update(gpu_seconds=gs, credits=round(gs * CREDITS_PER_S, 3), cost_usd=round(gs * USD_PER_S, 5),
                         ms=round(gs * 1000), output=str(out.relative_to(ROOT)).replace("\\", "/"))
        with runs.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        print(f"{it['label']:28} gpu {entry['gpu_seconds']:6.2f}s  credits {entry['credits']:6.3f}  usd {entry['cost_usd']:.5f}  {entry.get('error', '')[:60]}")


if __name__ == "__main__":
    main()
