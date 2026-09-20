# Casa Accelerator

A generative-AI production pipeline for architecture and real estate: from a house generated in code to a library of campaign assets (stills, video, copy in several languages), with every step measured (time, cost, retries, cache hits).

It's a personal R&D project inspired by agentic content accelerators. The real-estate developer and its brand guidelines are fictional.

> Status: **stage 1 — render passes done**, ControlNet workflow next.

## Pipeline (target)

```
house.json ──► Three.js scene ──► render passes ──► ComfyUI (SDXL + ControlNet) ──► upscale ──► QA ──► approval
  (spec)        (procedural)      beauty/depth/       photoreal stills, 3 styles                    (human
                                  normal/lines/ids                                                  checkpoint)
brief + brand book ──► vector KB ──► LangGraph agents (concept → script → storyboard → prompts)
                                     ──► Nano Banana variants · Veo clip · ES/EN copy ──► asset library + cost table
```

## Stage 1: render passes

The house is a data spec (`scene/house.json`, meters) turned into geometry by `scene/src/house.js`: a casa chorizo on a 10-vara lot, with an Italianate facade, a cast-iron gallery, a checkerboard patio, neighbors and the street. Every mesh carries a semantic material key, and that key feeds both the look and the material-ID pass.

For each camera in `config/cameras.json`, `npm run export` renders:

| pass | how | used for |
|---|---|---|
| `beauty.png` | shadows, ACES tone mapping | reference, before/after, img2img |
| `depth.png` + `depth.npy` | linear view depth → disparity (near = white), float32 kept for QA | ControlNet depth, geometry-similarity score |
| `normal.png` | view-space normals (OpenGL convention) | ControlNet normal, QA |
| `lines.png` | edges from G-buffer discontinuities (ID / depth / normal crease), 2× supersampled | ControlNet lineart/canny |
| `ids.png` + coverage | flat semantic colors, exact (no AA) | masks for inpainting / region edits, per-material QA |

- Cameras use a vertical lens shift instead of tilting, so the verticals stay straight (the architectural-photography way).
- The exporter uses a content-addressed cache: the hash covers the spec, the camera, the lighting and the scene source. Every run appends a line to `out/runs.jsonl`.

```bash
npm install
npm run export                 # all cameras (cached)
npm run export -- street       # one camera
npm run scene                  # interactive preview: /?cam=street, press "p" to log the pose
py pipeline/contact_sheet.py   # out/sheets/passes.png
```

Headless rendering uses the system's Microsoft Edge through `playwright-core`, so there's no browser download.

## Docs

- [`docs/journal.md`](docs/journal.md): the lab notebook, with decisions, numbers and what I learned at each stage.

## The case study

The full write-up — pipeline, control signals, model bake-off, quality gate, cost model, rights and a
plug-and-play guide — is a page in this repo: [`docs/report/index.html`](docs/report/index.html).

```bash
python scripts/report_assets.py      # rebuild its figures from the latest runs
python -m http.server 8010 -d docs/report
```
