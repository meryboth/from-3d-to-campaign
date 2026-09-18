"""Build Comfy Cloud batch items (API-format workflows) from the same presets the local
pipeline uses. Output is a JSON list ready for submit_batch.

    .venv/Scripts/python pipeline/cloud_batch.py --workflow klein9b_edit_lines --cams street --styles restored --seeds 1 2 --palette

Cloud input names come from config/cloud_inputs.json (local content hash -> uploaded name);
a stale hash means the pass changed and must be re-uploaded.
"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

EDIT_PREFIX = ("Turn this 3D render into a real photograph. Keep the exact architecture, proportions and camera angle: "
               "every window, door, pilaster, cornice and balustrade stays exactly where it is. ")
EDIT_LINES = "The second image is the exact line drawing of the same view; follow its lines precisely. "
MATERIALS = ("Real materials: lime plaster with subtle weathering, carved stone mouldings, painted wood shutters, "
             "wrought iron, real leafy trees, natural sky.")


def cloud_name(cam, p):
    reg = json.loads((ROOT / "config" / "cloud_inputs.json").read_text())
    entry = reg[f"{cam}/{p}"]
    local = hashlib.sha256((ROOT / "out" / "passes" / cam / f"{p}.png").read_bytes()).hexdigest()[:16]
    if local != entry["local_sha"]:
        raise SystemExit(f"{cam}/{p} changed since upload: re-upload it and update config/cloud_inputs.json")
    return entry["cloud_name"]


def prompt(workflow, cam, style, palette):
    s = json.loads((ROOT / "config" / "styles.json").read_text())
    body = f"{s['subject'][cam]}, {s['styles'][style]}" + (f", {s['palette']}" if palette else "")
    if "edit" in workflow:
        return EDIT_PREFIX + (EDIT_LINES if "lines" in workflow else "") + f"Make it a {body}. " + MATERIALS
    return body


def build(workflow, cam, style, seed, palette):
    wf = json.loads((ROOT / "workflows" / "api" / "cloud" / f"{workflow}.json").read_text())
    for n in wf.values():
        t, i = n["_meta"]["title"], n["inputs"]
        if n["class_type"] == "LoadImage":
            i["image"] = cloud_name(cam, t[: -len("_image")])
        elif t == "positive":
            i["text"] = prompt(workflow, cam, style, palette)
        elif t == "sampler":
            i["seed" if "seed" in i else "noise_seed"] = seed
        elif t == "save":
            i["filename_prefix"] = f"casa/{workflow}_{cam}_{style}_s{seed}"
    label = f"{workflow}{'_pal' if palette else ''}_{cam}_{style}_s{seed}"
    return {"tool": "submit_workflow", "description": label, "workflow": wf}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workflow", required=True)
    ap.add_argument("--cams", nargs="+", default=["street"])
    ap.add_argument("--styles", nargs="+", default=["restored"])
    ap.add_argument("--seeds", nargs="+", type=int, default=[1])
    ap.add_argument("--palette", action="store_true", help="append the brand palette to the prompt")
    ap.add_argument("--out", default=str(ROOT / "out" / "cloud_items.json"))
    args = ap.parse_args()
    items = [build(args.workflow, c, st, sd, args.palette) for c in args.cams for st in args.styles for sd in args.seeds]
    Path(args.out).write_text(json.dumps(items))
    print(len(items), "items ->", args.out)


if __name__ == "__main__":
    main()
