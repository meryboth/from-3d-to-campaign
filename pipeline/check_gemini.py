"""Free sanity check for the Gemini API key: lists the image/video models the key can see.
No generation, no cost. The key is read from .env and never printed.

    .venv/Scripts/python pipeline/check_gemini.py
"""
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


def main():
    load_env()
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise SystemExit("GEMINI_API_KEY not found: create .env from .env.example")
    print(f"key loaded ({len(key)} chars, ends in ...{key[-4:]})")
    req = urllib.request.Request("https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000", headers={"x-goog-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            models = json.loads(r.read())["models"]
    except urllib.error.HTTPError as e:
        raise SystemExit(f"API error {e.code}: {e.read().decode(errors='replace')[:300]}")
    wanted = [m["name"].removeprefix("models/") for m in models if "image" in m["name"] or "veo" in m["name"]]
    print(f"{len(models)} models visible; image/video ones:")
    for name in sorted(wanted):
        print("  ", name)


if __name__ == "__main__":
    main()
