# Lab notebook

These notes feed the final case-study page. Every entry covers what was built, why, the numbers, and the open questions. Numbers come from `out/runs.jsonl` and each `meta.json`, never from memory.

## Environment (2026-09-18)

- Windows 11, RTX 2060 Max-Q **6 GB VRAM**, 16 GB RAM (only ~0.5 GB free at the time of the check: close heavy apps before SDXL runs).
- ComfyUI Desktop 0.34.0 on :8000, PyTorch 2.10 + CUDA 13.0, 1,363 nodes.
- Models added for this project (free, local):

| file | folder | size | license | source |
|---|---|---|---|---|
| RealVisXL_V5.0_fp16.safetensors | checkpoints | 6.94 GB | openrail++ | huggingface.co/SG161222/RealVisXL_V5.0 |
| controlnet-union-sdxl-promax.safetensors | controlnet | 2.51 GB | Apache 2.0 | huggingface.co/xinsir/controlnet-union-sdxl-1.0 (`diffusion_pytorch_model_promax`) |
| RealESRGAN_x4plus.pth | upscale_models | 0.07 GB | BSD-3 | github.com/xinntao/Real-ESRGAN v0.1.0 |

**Model choice, first pass:**
- SDXL, not Flux, for local work. With 6 GB, Flux only runs quantized (GGUF) and slowly, and FLUX.1-dev's license is non-commercial. Flux stays as a cloud comparison point.
- Real-ESRGAN, not 4x-UltraSharp, because UltraSharp is CC BY-NC-SA.

## Stage 1: procedural house → render passes

- New generator written from scratch for this repo (no dependency on earlier projects). The house is data (`scene/house.json`), and the builder turns walls with openings into extruded shapes with holes, so there are no seams from stacked boxes.
- **Lines come from the G-buffer, not from Canny on the beauty.** An edge is an ID change, a relative depth jump > 3.5 % or a normal crease > 35°, computed at 2× and box-filtered. Result: clean architectural linework with no texture or shadow noise (the checkerboard floor doesn't produce lines).
- **Depth is encoded as disparity** (like MiDaS, the family ControlNet depth models were trained on). The first version normalized over the full visible range, and the asphalt near the camera ate all the whites while the facade came out flat gray. Fix: 2–98 percentile range by default, with an optional `depthRange` per camera.
- **Street camera:** v1 was tilted, so the verticals converged and the road took a third of the frame. v2 is a level camera plus a 25 % vertical lens shift (`setViewOffset`): straight verticals, like a real estate photographer would shoot it.
- **Cache:** hash of spec + camera + lighting + scene source. The second run gives 3/3 cache hits in ~0 ms.

| camera | render (ms, wall) | triangles | draw calls |
|---|---|---|---|
| street | 1,673 | 11,108 | 600 |
| aerial | 1,510 | 11,376 | 575 |
| patio | 1,605 | 6,284 | 332 |

The export ran headless on the integrated AMD GPU (ANGLE/D3D11). Cost: $0.

**Open questions:**
- How much will SDXL invent in the patio view? The rooms behind the gallery are shallow.
- The aerial neighbors are plain boxes, so check whether ControlNet at low strength fills their roofs believably.

## Stage 2: first CAD → render (SDXL + ControlNet union)

Workflow `workflows/api/cn_depth_lines_sdxl.json`: RealVisXL V5 → two stacked `ControlNetApplyAdvanced` on the same union-promax model (depth 0.65 until 80 % of the steps, lines 0.45 until 60 %) → KSampler dpmpp_2m_sde / karras, 30 steps, CFG 5, 1216×832.

| run | wall | sampler | VRAM peak | GPU power avg | energy |
|---|---|---|---|---|---|
| seed 1, cold start | 206.1 s (server exec) | n/a (client crashed on a /history race, since fixed) | n/a | n/a | n/a |
| seed 2, warm | 212.6 s | 192.9 s (~6.4 s/step) | 5,892 MB of 6,144 | 44.8 W | 2.65 Wh |

**Reading the numbers:**
- Warm and cold cost the same, so the model load isn't the bottleneck; VRAM is. The 5 GB UNet plus the 2.5 GB ControlNet don't fit in 6 GB, so ComfyUI offloads layers every step, and the ControlNet itself is reloaded each run (5.6 s).
- The two stacked ControlNets mean two ControlNet forward passes per step while both are active.

**Quality, first look:** the geometry is respected almost 1:1 (balustrade, pilasters, carved door with fanlight, grilles, shutters). Two problems:
1. **Color is not controlled.** Seed 1 gave an ochre-and-green facade, seed 2 a pale blue one. For a brand, that's a consistency problem.
2. **Low-detail context gets hallucinated.** The right street tree (a simple sphere cluster) became a glass canopy and a yellow blob.

## Stage 2b: speed and color experiments (local, $0)

| config | wall | edge recall | ΔE facade | look |
|---|---|---|---|---|
| SDXL 30 steps (baseline) | 213 s | 0.58–0.67 | 17–23 | photographic, random color |
| SDXL 20 steps | 128 s | 0.59 | 23 | same, −40 % time |
| depth-only ControlNet | 136–171 s | 0.57–0.62 | 21–22 | saves ~20 % at 30 steps, noise at 20 |
| **SDXL + Lightning LoRA, 8 steps, CFG 1** | **63 s** | 0.49–0.70 | 11–33 | photographic, 3.4× faster |
| Lightning img2img from beauty, denoise 0.75 | 64–82 s | 0.87–0.90 | 4.6–5.2 | color-faithful but looks CG |
| standard img2img, 30 steps | 253 s | 0.87 | 5.4 | same as Lightning at 4× the time |

**Takeaways:**
- On a 6 GB card the lever is step count, not the ControlNet. Lightning wins the local tier.
- img2img fixes color and geometry, but it inherits the flat CG look of the source. The metrics liked it and the eye didn't, so we need a realism metric.
- Single runs are noisy on an offloading GPU (E3 was slower than E2). Repeat before quoting numbers.

## Stage 3: Comfy Cloud model bake-off (street camera, 2 seeds)

Creator plan, RTX Pro 6000 (96 GB). Four flat API workflows in `workflows/api/cloud/`, validated with dry runs before spending anything.

| model | approach | GPU s (s1 / s2) | cost per image | edge recall | ΔE facade |
|---|---|---|---|---|---|
| Z-Image Turbo + Fun ControlNet Union (lines) | ControlNet, 8 steps | 8.9 / 3.8 | $0.004–0.009 | **0.90–0.92** | 15–22 |
| FLUX.2 klein 9B | edit from the beauty, 4 steps | 2.7 / 14.3 | $0.003–0.014 | 0.72–0.75 | 16–20 |
| Qwen-Image + InstantX ControlNet (depth) + Lightning | ControlNet, 4 steps | 13.3 / 2.4 | $0.002–0.013 | 0.63–0.68 | 25–28 |
| RealVisXL + ControlNet union (parity with local) | — | failed validation: the catalog lists `controlnet-union-sdxl-1.0` but the executor doesn't have it. No GPU billed. | | | |

- Total: **45.4 GPU seconds ≈ 9.3 credits ≈ $0.044** for 6 images. My estimate was 75–125 credits, because I overestimated model load time.
- The higher number in each pair is the cold start: the first job to load that model.
- vs local: the best local option costs 63 s of wall time and ~0.7 Wh per image. The cloud runs in 2–4 s warm. Quality-wise, all three cloud models look more photographic than SDXL.

**Reading the images:**
- **Z-Image** keeps the geometry best of all and has convincing golden-hour light, but its color follows the prompt, not the model (brown shutters in s1).
- **klein** (edit) gives the richest real-world texture: real trees, weathered plaster, and green shutters carried over from the reference. It adds small details (plinth vents).
- **Qwen** is the most "photographic" and ornate, but it drifts the most: it invented a door on the left.

**Metric caveat:** ΔE is measured against a flat-lit beauty, so golden-hour prompts are penalized even when the paint color is right. Next: compare hue/chroma after white balance, and add a realism score.

## Stage 4: automatic quality gate

`pipeline/gate.py` combines four checks, all local, $0, and ~1 s per image on the 2060 once models are loaded. Thresholds live in `config/qa.json`.

| check | how | threshold v1 | what it catches |
|---|---|---|---|
| geometry | edge recall of the 3D lines in the render, ±2 px, house only | ≥ 0.70 | drift, invented doors |
| brand color | ΔE (Lab) per material region after gray-world white balance | facade ≤ 10 | off-palette paint (without penalizing golden light) |
| reads as photo | CLIP ViT-L/14 zero-shot, photo vs 3D render / CGI | p ≥ 0.5 | the obvious CG cases (img2img d0.6: 0.04) |
| natural texture | NIQE (pyiqa) | ≤ 5.0 | flat, over-clean CG surfaces (beauty: 9.8) |

What each metric turned out to be worth:
- **NIQE** separated photo from CG best (SDXL ~2, klein ~3, img2img 3.5–5.8, beauty 9.8).
- **CLIP p_photo** is saturated (most renders score 0.97–0.99). It's useful as a coarse filter only, and it had one false positive (Z-Image s2 at 0.10).
- **The LAION aesthetic predictor** barely moves on architecture (4.8–5.8), so it's kept as data only and isn't gated.

Gate v1 on the 18 street renders: 7 pass. **Both FLUX.2 klein renders pass.** Qwen fails on geometry and palette, Z-Image on palette, and baseline SDXL on geometry and palette.

`render.py --gate N` re-renders with a new seed (seed + 1000) until the gate passes, up to N times, logging each verdict as `stage: qa_gate`. If nothing passes, the item is flagged for human review. That flag is where the approval checkpoint will plug in.

The thresholds are calibrated by eye on 18 images. They should be recalibrated with a Gemini-as-judge or human labels before scaling.

## Stage 5: winner and the first 3×3 grid (Comfy Cloud)

**A/B, street camera, 2 seeds each** (~6.2 credits):
- **FLUX.2 klein 9B + a second reference (the inverted line drawing):** geometry 0.75 → 0.77, ΔE_wb 2.2–6.8, p_photo 0.98–0.99, NIQE ~2.9. Both seeds pass.
- **Z-Image + brand palette in the prompt:** fixes the color (ΔE_wb 1.5–8.1) but gets a bit more CG-looking (NIQE 4.4–5.1). 1 of 2 passes.
- → The winner is **klein edit + line reference**, with the palette in the prompt for the brand styles.

**Grid: 3 cameras × 3 styles, seed 1** (~7.7 credits): **4.13–4.37 GPU s per image, ≈ $0.004 per image.** Steady because the model stayed warm. Total for A/B + grid: ≈ 13.9 credits (≈ $0.066).

**Gate v1 → v1.1:** reviewing the failures showed two false negatives caused by the metric, not the render:
1. On the aerial camera the facade is 0.37 % of the frame and hidden by a tree, so a facade ΔE is noise. Fix: measure color on the **visible plaster walls** (facade + patio), and only when they cover ≥ 1 % of the frame.
2. Dusk has mixed illuminants (warm interior, blue sky), which breaks gray-world white balance. Fix: a per-style tolerance, **dusk ΔE ≤ 14**.

Gate v1.1 on the grid: **5/9 pass** (all 3 street, patio dusk, patio contemporary). The 4 real failures:
- patio restored: walls painted ochre instead of cream (ΔE 18.6)
- aerial restored and aerial contemporary: geometry 0.65 / 0.69
- aerial dusk: ΔE 16.5

These go to the retry loop (new seed) or human review.

**Incident:** the grid's street/restored output had the same filename as an A/B output and overwrote it. It was restored from its still-valid signed URL, and `cloud_collect.py` now refuses to overwrite. Lesson: output names must encode every axis (model, refs, palette, camera, style, seed).

## Stage 6: retry loop → human review

The 4 grid items that failed gate v1.1 went through the retry loop (≈ 0.8–1.0 credit per try):

| item | try 1 (seed 1001) | try 2 (seed 2001) | result |
|---|---|---|---|
| patio / restored | ΔE 24.1 | ΔE 21.4 (prompt fixed) | → human review |
| aerial / restored | ΔE 13.4 | **edge 0.83, ΔE 10.4** | → human review (0.4 over the limit) |
| aerial / dusk | edge 0.698 | ΔE 19.3 | → human review |
| aerial / contemporary | edge 0.67 | edge 0.694 | → human review (0.006 under the limit) |

**Lessons:**
1. **The same failure twice is a prompt bug, not bad luck.** The "restored" style said "cream **and ochre** plaster", which contradicts the brand palette (cream). Removing it didn't fully fix the patio: under golden-hour sun the walls still read yellow.
2. **Gray-world white balance fails when one color dominates the frame** (the patio walls are 24 % of it). Whether the render shows "cream paint in warm light" or "yellow paint" is a judgment call, better made by a person or a vision-language judge than by a threshold.
3. **After N retries, stop spending and escalate.** The 4 items sit in `out/review/pending.json` with their candidates and gate notes. This is the human approval checkpoint, and later a LangGraph interrupt.

Retries: 8 images, ≈ 6.9 credits. Running total for the day: ≈ 30 credits ≈ $0.14 (Comfy Cloud), $0 local.

## Stage 7: approvals and the asset library

Creative direction reviewed the 4 escalated items: **aerial restored and aerial contemporary approved** (both sit within 0.4 of a threshold), **aerial dusk rejected** (no attempt had both color and geometry), **patio restored rejected** for now (walls read yellow under golden light in all 3 attempts; worth revisiting with different light or a stronger palette instruction). Decisions are recorded in `config/approved.json` with the reason for each.

**7 approved pieces → 28 files.** `pipeline/library.py` upscales 2× with Real-ESRGAN on the local 2060 (79–99 s per piece, ~1.2 Wh, $0) and cuts feed 1:1, story 9:16 and banner 16:9. Crops are framed on the house's bounding box from the material-ID pass, not on the image center, so the facade never gets cut off.

**Cost table (`docs/costs.md`, generated from `out/runs.jsonl`):**

| stage | backend | runs | cache hits | errors | time | $ |
|---|---|---|---|---|---|---|
| export passes | local (Three.js) | 9 | 3 | 0 | 10 s | 0 |
| render | local ComfyUI (2060) | 13 | 1 | 0 | 1,552 s | 0.0015 |
| render | Comfy Cloud | 29 | 0 | 2 | 147 GPU s | 0.1425 |
| upscale + crops | local ComfyUI | 16 | 2 | 0 | 545 s | 0.0008 |

**Total $0.145 for the whole project**, including every benchmark, A/B and rejected render. **$0.021 per approved piece.** Marginal cost of one more approved piece at the current hit rate: ~4.2 GPU s of klein ($0.004) plus ~90 s of local upscale (~$0.0001).

Quality gate: 6 of 18 verdicts passed; 2 more pieces were approved by a human after review.

## Stage 8: brand layer and ad composer (local, $0)

The renders became ads. A **fictional** developer — *form and order* — with a real brand system: cream paper, black mark, Switzer (Fontshare, free for commercial use), terracotta accent, and a voice guide that bans luxury clichés and invented amenities. The visual language is generic modernist; the mark is drawn from code in `pipeline/brand_mark.py`, so there is no external asset and no resemblance to any real studio's logo.

`pipeline/composer.py` lays out three formats in three languages from one approved piece:
- **feed 1:1** — image + paper band with headline, facts and mark
- **story 9:16** — full bleed with a gradient scrim, copy inside the safe zone (250 px top, 320 px bottom for the platform UI)
- **banner 16:9** — image left, paper panel right

**63 ads (7 pieces × 3 formats × 3 languages) in 5.8 s, ~93 ms each, $0.** Transcreation is just another key in `config/copy.json`; adding a language costs 21 more files and about two seconds.

Two rules are enforced in the layout itself, not left to whoever writes the caption:
1. **Every asset carries the AI disclosure** in its language.
2. **The facts come from `config/copy.json`**, one source for m², rooms, patios and price, so no piece can contradict another.

Hypothetical project data (Casa Larga 1408, Villa Crespo, 182 m², USD 265,000) is flagged as invented in the config and in the report.

## Stage 9: a design system, not an overlay

First version of the composer was a band with text on it — creative direction called it what it was: something anyone could do in Paint. Rebuilt as a design system.

**`config/design.json`** holds the tokens: a 12-column grid with a 9 px baseline, a type scale (display / headline / subhead / body / meta / number / caption) with real tracking and leading, the graphic devices (hairlines, index numbers, metadata rails) and the publishing formats. Sizes are authored for 1080 px and scale with canvas width.

**`pipeline/design.py`** is the canvas PIL doesn't give you: letter-spacing, measured type blocks, grid columns, hairlines, cover-fit images, gradient scrims — and image-aware placement that reads the render passes (the ID map knows where the sky is, the lines map knows where the detail is), so copy can be put on the calm part of a photo by data instead of by eye.

**`pipeline/post.py`** builds a *post*, not an image: a 4:5 carousel (cover → two shots with captions → data card → closing card), a story and a link/og image, in every language, plus the caption file and a `manifest.json` with the provenance of every render (which approved file it came from) ready for a scheduler.

**Design QA runs on every slide** and is part of the gate philosophy:
- WCAG contrast of each type block against what is actually behind it
- minimum type size
- safe zones per platform
- **no type block may overlap another** — this one caught a collision between the price and the AI disclosure on the link image that the contrast check could not see

Sequence: first run flagged 2 contrast issues (a caption over a bright aerial, the CTA in brand terracotta on the dark card). Fixes: stronger scrim, and a lighter accent tint reserved for dark backgrounds (`accent_on_dark`). Second run flagged the overlap. Third run: **21 assets (7 × 3 languages) in 4.0 s, QA clean, $0.**

Format note: the feed format is **4:5, not 1:1** — it is the one Instagram gives the most screen to.

## Stage 10: the pipeline becomes a ComfyUI graph

Creative direction's note was that the process was half scripts, half ComfyUI, with me in the middle.
Fixed by packaging the logic as a node pack, `comfy_nodes/casa_accelerator`, loaded into ComfyUI
through a stub in `custom_nodes` that points back at the repo (edit the repo, restart ComfyUI).

| Node | Wraps |
|---|---|
| Casa · passes from 3D | line map from normal discontinuities + silhouette (works on `Load3D`'s normal output) |
| Casa · quality gate | geometry, brand ΔE, CLIP photo-vs-CG, NIQE → `passed` + report + metrics |
| Casa · copy prompt | system + user prompt built from brand, voice and the project fact whitelist |
| Casa · copy check | parses the LLM JSON, enforces character limits, banned phrases, invented numbers |
| Casa · layout | the design system, with the same collision/contrast QA |
| Casa · log run | appends seconds, tokens and cost to the shared `runs.jsonl` |

`Load3D` (core, ships with ComfyUI) accepts GLB/GLTF/FBX/OBJ/STL/USDZ and returns image, mask and
normals — so the "3D model → passes" stage can live inside the graph, which also answers the CAD
question from earlier.

Environment note: `open_clip_torch` and `pyiqa` installed into ComfyUI's own python **with
`--no-deps`**, so its torch 2.10+cu130 build was left untouched; realism scoring runs there on CUDA
(p_photo 0.973, NIQE 2.91 on a known-good render).

Master graph: `workflows/api/graph_master_local.json`, 24 nodes, passes → ControlNet + Lightning →
gate → upscale → copy prompt → Claude Haiku 4.5 (partner node, billed in Comfy credits) → copy
check → layout → save, with the run log at the end.

Report notes live in `docs/report-notes.md` from now on, updated as we go.

## Stage 11 — the graph as a document (2026-09-20)

Two report figures, both exported from the real graph: `docs/images/comfy_graph_master.png`
(3400×1432, the 25-node master graph laid out in seven stage columns) and
`docs/images/comfy_nodes_detail.png` (1900×2677, the casa-accelerator nodes with their inputs and
widgets readable). `scripts/comfy_figure.py` turns a raw canvas export into a labelled figure, so
regenerating them after a graph change is one command, not a screenshot session.

Also added: `CasaRender3D` (renders the passes from the 3D scene inside the graph — `Load3D` renders
in the frontend and returns nothing in a headless run) and `scripts/export-glb.mjs`
(`out/model/casa-chorizo.glb`, 2.19 MB, the same procedural house as a file).

`CasaRender3D` needs a ComfyUI restart to load.

## Stage 12 — the case-study page (2026-09-20)

`docs/report/index.html`: the whole project as a Monks-style case study — problem, pipeline, control
signals, model bake-off, quality gate, copy validator, design system, cost model, rights, and a
plug-and-play section with the step-by-step for someone else to install and run this, plus an honest
table of what is still missing to publish the node pack to the ComfyUI Registry.

Self-contained: brand palette and Switzer, no external requests, inline SVG charts drawn from the
measured numbers. `scripts/report_assets.py` rebuilds its figures from wherever the pipeline wrote
them (4.5 MB of web-sized images), so the page refreshes after new runs instead of drifting.

Two things fixed while assembling it:
- The wordmark on cover and story was drawn straight to the canvas, so the design QA never saw it —
  and it shipped at contrast 2.4 over a bright sky. It now rides on an ink chip (`Canvas.plate`) and
  goes through `qa_text` like every other block. Lesson: **QA only sees what you route through it.**
- The master graph now starts from `CasaRender3D` instead of two `LoadImage` nodes.

Credits, for the record: the Comfy plan's monthly pool is barely touched (41 of 7,400 used). What is
empty is the *additional* pay-as-you-go balance, and that is what partner API nodes draw from when
ComfyUI runs locally — hence "Payment Required" on the copy node while cloud runs of the same model
went through fine.
