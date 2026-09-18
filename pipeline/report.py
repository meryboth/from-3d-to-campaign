"""Benchmark report: every tagged render in out/runs.jsonl, joined with its QA scores.

    .venv/Scripts/python pipeline/report.py            -> prints a markdown table,
                                                          writes out/benchmarks/renders.json
                                                          and out/sheets/benchmark.png
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).parent))
from qa import evaluate  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def runs():
    rows = []
    for line in (ROOT / "out" / "runs.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r.get("stage") == "render" and not r.get("cache_hit") and r.get("output") and not r.get("error"):
            rows.append(r)
    return rows


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    rows = runs()
    for r in rows:
        r["qa"] = evaluate(ROOT / r["output"])
    out = ROOT / "out" / "benchmarks"
    out.mkdir(parents=True, exist_ok=True)
    (out / "renders.json").write_text(json.dumps(rows, indent=1))

    print("| tag | workflow | steps | cfg | wall s | sampler s | VRAM GB | Wh | edge recall | ΔE facade | ΔE shutters |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        sampler = r.get("node_ms", {}).get("sampler")
        de = r["qa"]["delta_e"]
        steps = next((o.split("=")[1] for o in r.get("overrides", []) if o.startswith("sampler.steps=")), r.get("steps"))
        print(f"| {r.get('tag') or '-'} | {r['workflow']} | {steps} | {r.get('cfg')} | {r['ms'] / 1000:.1f} | "
              f"{sampler / 1000 if sampler else float('nan'):.1f} | {(r.get('vram_peak_mb') or 0) / 1024:.2f} | {r.get('energy_wh') or '-'} | "
              f"{r['qa']['edge_recall']:.3f} | {de.get('facade_plaster', '-')} | {de.get('wood_shutter', '-')} |")

    # comparison sheet: beauty reference first, then every render labeled with its tag and key numbers
    tiles = [(ROOT / "out" / "passes" / "street" / "beauty.png", "reference: Three.js beauty")]
    for r in rows:
        if r["item"].startswith("street/"):
            tiles.append((ROOT / r["output"], f"{r.get('tag') or r['item']} · {r['ms'] / 1000:.0f}s · edge {r['qa']['edge_recall']:.2f} · ΔE {r['qa']['delta_e'].get('facade_plaster', '-')}"))
    tw, cols, pad, lab = 480, 4, 10, 26
    th = round(832 * tw / 1216)
    rows_n = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (pad + cols * (tw + pad), pad + rows_n * (th + lab + pad)), "#141414")
    d = ImageDraw.Draw(sheet)
    try:
        f = ImageFont.truetype("segoeui.ttf", 15)
    except OSError:
        f = ImageFont.load_default()
    for i, (p, t) in enumerate(tiles):
        x = pad + (i % cols) * (tw + pad)
        y = pad + (i // cols) * (th + lab + pad)
        d.text((x, y + 3), t, fill="#e0e0e0", font=f)
        sheet.paste(Image.open(p).convert("RGB").resize((tw, th), Image.LANCZOS), (x, y + lab))
    sheet.save(ROOT / "out" / "sheets" / "benchmark.png")


if __name__ == "__main__":
    main()
