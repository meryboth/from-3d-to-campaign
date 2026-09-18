"""Quality gate: geometry + brand color + realism, thresholds in config/qa.json.

    from gate import check
    ok, scores, reasons = check("out/renders/street/x.png", cam="street")
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from qa import evaluate  # noqa: E402
from realism import score as realism  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def thresholds():
    return json.loads((ROOT / "config" / "qa.json").read_text())


def check(path, cam=None):
    t = thresholds()
    qa = evaluate(path, cam)
    rl = realism(path)
    de = qa["delta_e_wb"].get("facade_plaster")
    reasons = []
    if qa["edge_recall"] < t["edge_recall_min"]:
        reasons.append(f"geometry drift: edge recall {qa['edge_recall']:.2f} < {t['edge_recall_min']}")
    if de is not None and de > t["delta_e_wb_facade_max"]:
        reasons.append(f"off-palette facade: ΔE {de} > {t['delta_e_wb_facade_max']}")
    if rl["p_photo"] < t["p_photo_min"]:
        reasons.append(f"reads as CG: p_photo {rl['p_photo']:.2f} < {t['p_photo_min']}")
    if rl["niqe"] > t["niqe_max"]:
        reasons.append(f"unnatural texture: NIQE {rl['niqe']:.2f} > {t['niqe_max']}")
    return not reasons, {**qa, **rl}, reasons


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    for p in sys.argv[1:]:
        ok, _, reasons = check(p)
        print(("PASS " if ok else "FAIL ") + Path(p).name, "; ".join(reasons))
