"""No-reference realism / quality scores for a render (local GPU, $0).

- p_photo: CLIP ViT-L/14 zero-shot probability that the image is a real photograph rather
  than a 3D render / CGI. Targets the exact failure we saw with img2img ("looks CG").
- aesthetic: LAION improved aesthetic predictor (MLP on CLIP ViT-L/14 embeddings), ~1-10.
- niqe: natural image quality evaluator (pyiqa); lower = more natural, flags blur/noise.

    .venv/Scripts/python pipeline/realism.py out/renders/street/*.png
"""
import json
import sys
import urllib.request
from functools import lru_cache
from pathlib import Path

import torch
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache"
AESTHETIC_URL = "https://github.com/christophschuhmann/improved-aesthetic-predictor/raw/main/sac+logos+ava1-l14-linearMSE.pth"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

PHOTO = ["a real photograph of a house", "a professional real estate photograph", "a DSLR photo of a building facade",
         "an architectural photograph taken with a camera"]
RENDER = ["a 3D render of a house", "a CGI rendering of a building", "a computer graphics image",
          "a video game screenshot", "an untextured 3D model"]


class AestheticMLP(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.layers = torch.nn.Sequential(
            torch.nn.Linear(768, 1024), torch.nn.Dropout(0.2), torch.nn.Linear(1024, 128), torch.nn.Dropout(0.2),
            torch.nn.Linear(128, 64), torch.nn.Dropout(0.1), torch.nn.Linear(64, 16), torch.nn.Linear(16, 1))

    def forward(self, x):
        return self.layers(x)


@lru_cache(maxsize=1)
def models():
    import open_clip
    import pyiqa

    clip, _, preprocess = open_clip.create_model_and_transforms("ViT-L-14", pretrained="openai", device=DEVICE)
    clip.eval()
    tok = open_clip.get_tokenizer("ViT-L-14")
    with torch.no_grad():
        def embed(texts):
            t = clip.encode_text(tok(texts).to(DEVICE)).float()
            t = t / t.norm(dim=-1, keepdim=True)
            m = t.mean(0)
            return m / m.norm()
        text = torch.stack([embed(PHOTO), embed(RENDER)])

    CACHE.mkdir(exist_ok=True)
    wpath = CACHE / "aesthetic_l14_mlp.pth"
    if not wpath.exists():
        urllib.request.urlretrieve(AESTHETIC_URL, wpath)
    mlp = AestheticMLP().to(DEVICE)
    mlp.load_state_dict(torch.load(wpath, map_location=DEVICE))
    mlp.eval()

    niqe = pyiqa.create_metric("niqe", device=DEVICE)
    return clip, preprocess, text, mlp, niqe


@torch.no_grad()
def score(path):
    clip, preprocess, text, mlp, niqe = models()
    img = Image.open(path).convert("RGB")
    e = clip.encode_image(preprocess(img).unsqueeze(0).to(DEVICE)).float()
    e = e / e.norm(dim=-1, keepdim=True)
    probs = (100.0 * e @ text.T).softmax(dim=-1)[0]
    aesthetic = mlp(e).item()
    n = niqe(str(path)).item()
    return {"p_photo": round(probs[0].item(), 3), "aesthetic": round(aesthetic, 2), "niqe": round(n, 2)}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    for p in sys.argv[1:]:
        print(Path(p).name, json.dumps(score(p)))
