"""casa-accelerator: the pipeline as ComfyUI nodes.

3D model -> passes -> render -> quality gate -> copy -> laid-out asset, all in one graph.
The heavy logic lives in the repo's `pipeline/` modules; these nodes are thin wrappers
so the same code runs from the graph and from the command line.
"""
from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
WEB_DIRECTORY = None
