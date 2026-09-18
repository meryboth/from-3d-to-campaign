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
    from realism import score as realism
    for r in rows:
        r["qa"] = evaluate(ROOT / r["output"])
        r["realism"] = realism(ROOT / r["output"])
    out = ROOT / "out" / "benchmarks"
    out.mkdir(parents=True, exist_ok=True)
    (out / "renders.json").write_text(json.dumps(rows, indent=1))

    print("| tag | item | backend | time s | $ | edge recall | ΔE facade (wb) | ΔE shutters (wb) | p_photo | aesthetic | niqe |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        de = r["qa"]["delta_e_wb"]
        rl = r["realism"]
        backend = "cloud GPU" if r.get("backend") == "comfy_cloud" else "local 2060"
        print(f"| {r.get('tag') or '-'} | {r['item']} | {backend} | {r['ms'] / 1000:.1f} | {r.get('cost_usd', 0):.4f} | "
              f"{r['qa']['edge_recall']:.3f} | {de.get('facade_plaster', '-')} | {de.get('wood_shutter', '-')} | "
              f"{rl['p_photo']:.2f} | {rl['aesthetic']:.2f} | {rl['niqe']:.2f} |")

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
