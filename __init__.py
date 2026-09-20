"""from-3d-to-campaign — the pipeline as ComfyUI nodes.

Entry point for ComfyUI: clone this repo into `ComfyUI/custom_nodes/` (or install it
from the Registry) and the nodes load from here. The implementations live in
`comfy_nodes/casa_accelerator`, and they call the same `pipeline/` modules the command
line uses, so the graph and the batch scripts cannot drift apart.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "comfy_nodes"))

from casa_accelerator import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS  # noqa: E402

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
