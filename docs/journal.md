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
