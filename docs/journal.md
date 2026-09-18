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
