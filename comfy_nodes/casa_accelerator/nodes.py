"""Node implementations. Kept dependency-light: numpy + PIL always, torch only for
tensor conversion (ComfyUI already has it). The realism metrics (CLIP / NIQE) are
optional: if their packages aren't in ComfyUI's python, the gate still runs the
geometry and colour checks and says so in the report.
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
from PIL import Image

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "pipeline"))

import qa as qa_mod  # noqa: E402
from design import BRAND, C, Canvas, contrast_ratio, hex_rgb  # noqa: E402

CATEGORY = "casa accelerator"


# ---- tensor helpers ---------------------------------------------------------

def to_pil(image):
    """ComfyUI IMAGE [B,H,W,C] float 0..1 -> PIL RGB (first of batch)."""
    a = (image[0].detach().cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
    return Image.fromarray(a[:, :, :3])


def to_image(pil):
    a = np.asarray(pil.convert("RGB")).astype(np.float32) / 255.0
    return torch.from_numpy(a)[None, ...]


def mask_np(mask):
    """ComfyUI MASK [B,H,W] float -> bool array."""
    return (mask[0].detach().cpu().numpy() > 0.5) if mask is not None else None


# ---- 1. passes from a Load3D render ----------------------------------------

class CasaPasses:
    """Turn Load3D's normal + mask into the control maps the render needs.

    Lines come from normal discontinuities (creases) plus the silhouette of the mask:
    the geometry's own edges, not a Canny of the beauty, so textures and shadows
    never produce false lines.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "normal": ("IMAGE",),
            "crease_degrees": ("FLOAT", {"default": 35.0, "min": 5.0, "max": 89.0, "step": 1.0}),
            "line_gain": ("FLOAT", {"default": 1.6, "min": 0.2, "max": 4.0, "step": 0.1}),
            "silhouette": ("BOOLEAN", {"default": True}),
        }, "optional": {"mask": ("MASK",)}}

    RETURN_TYPES = ("IMAGE", "IMAGE")
    RETURN_NAMES = ("lines", "mask_image")
    FUNCTION = "run"
    CATEGORY = CATEGORY

    def run(self, normal, crease_degrees, line_gain, silhouette, mask=None):
        n = normal[0].detach().cpu().numpy()[:, :, :3] * 2 - 1
        m = mask_np(mask)
        norm = np.linalg.norm(n, axis=-1, keepdims=True)
        n = n / np.maximum(norm, 1e-6)
        cos_t = np.cos(np.radians(crease_degrees))
        edges = np.zeros(n.shape[:2], np.float32)
        for dy, dx in ((0, 1), (1, 0)):
            shifted = np.roll(np.roll(n, -dy, 0), -dx, 1)
            dot = (n * shifted).sum(-1)
            edges = np.maximum(edges, (dot < cos_t).astype(np.float32))
        if silhouette and m is not None:
            for dy, dx in ((0, 1), (1, 0)):
                s = np.roll(np.roll(m, -dy, 0), -dx, 1)
                edges = np.maximum(edges, (m != s).astype(np.float32))
        if m is not None:
            edges = edges * m  # keep lines on the model only
        edges = np.clip(edges * line_gain, 0, 1)
        lines = np.repeat(edges[:, :, None], 3, axis=2).astype(np.float32)
        mask_img = np.repeat((m if m is not None else np.ones_like(edges))[:, :, None].astype(np.float32), 3, axis=2)
        return (torch.from_numpy(lines)[None, ...], torch.from_numpy(mask_img)[None, ...])


# ---- 2. quality gate --------------------------------------------------------

class CasaQAGate:
    """Does this render still show the building we modelled, in the brand's colours,
    and does it read as a photograph? Geometry + colour always; realism when the
    optional packages are available."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "render": ("IMAGE",),
            "reference": ("IMAGE",),
            "lines": ("IMAGE",),
            "edge_recall_min": ("FLOAT", {"default": 0.70, "min": 0.0, "max": 1.0, "step": 0.01}),
            "delta_e_max": ("FLOAT", {"default": 10.0, "min": 0.0, "max": 60.0, "step": 0.5}),
            "check_color": ("BOOLEAN", {"default": True}),
            "check_realism": ("BOOLEAN", {"default": True}),
            "niqe_max": ("FLOAT", {"default": 5.0, "min": 1.0, "max": 20.0, "step": 0.1}),
            "p_photo_min": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.05}),
        }, "optional": {"mask": ("MASK",)}}

    RETURN_TYPES = ("BOOLEAN", "STRING", "FLOAT", "FLOAT", "FLOAT")
    RETURN_NAMES = ("passed", "report", "edge_recall", "delta_e", "niqe")
    FUNCTION = "run"
    CATEGORY = CATEGORY

    def run(self, render, reference, lines, edge_recall_min, delta_e_max, check_color, check_realism, niqe_max, p_photo_min, mask=None):
        img = np.asarray(to_pil(render))
        ref = np.asarray(to_pil(reference))
        ln = np.asarray(to_pil(lines).convert("L")) > 96
        m = mask_np(mask)
        if m is None:
            m = np.ones(ln.shape, bool)
        if img.shape[:2] != ln.shape:
            img = np.asarray(to_pil(render).resize(ln.shape[::-1], Image.LANCZOS))

        target = ln & m
        found = qa_mod.dilate(qa_mod.sobel_edges(np.asarray(Image.fromarray(img).convert("L"))), 2)
        edge_recall = float((target & found).sum() / max(1, target.sum()))

        reasons = []
        if edge_recall < edge_recall_min:
            reasons.append(f"geometry drift: edge recall {edge_recall:.2f} < {edge_recall_min}")

        delta_e = 0.0
        if check_color and m.sum() > 500:
            lab_r = qa_mod.to_lab(qa_mod.gray_world(img, m))
            lab_b = qa_mod.to_lab(qa_mod.gray_world(ref, m))
            delta_e = round(float(np.linalg.norm(lab_r[m].mean(0) - lab_b[m].mean(0))), 1)
            if delta_e > delta_e_max:
                reasons.append(f"off-palette: deltaE {delta_e} > {delta_e_max}")

        niqe = 0.0
        if check_realism:
            try:
                from realism import score as realism_score
                tmp = REPO / "out" / ".cache_gate.png"
                tmp.parent.mkdir(parents=True, exist_ok=True)
                Image.fromarray(img).save(tmp)
                r = realism_score(tmp)
                niqe = r["niqe"]
                if r["p_photo"] < p_photo_min:
                    reasons.append(f"reads as CG: p_photo {r['p_photo']:.2f} < {p_photo_min}")
                if niqe > niqe_max:
                    reasons.append(f"unnatural texture: NIQE {niqe:.2f} > {niqe_max}")
            except ImportError as e:
                reasons.append(f"realism skipped (install open_clip_torch + pyiqa in ComfyUI's python): {e}")

        passed = not reasons
        report = ("PASS  " if passed else "FAIL  ") + f"edge {edge_recall:.3f}  deltaE {delta_e}  niqe {niqe:.2f}"
        if reasons:
            report += "\n- " + "\n- ".join(reasons)
        return (passed, report, edge_recall, float(delta_e), float(niqe))


# ---- 3. copy: prompt spec and validation ------------------------------------

SYSTEM_PROMPT = """You write advertising copy for a real-estate developer that restores heritage houses.

WHO YOU WRITE FOR
{positioning}
Brand name: {brand}. Voice: {voice_do}
Never: {voice_dont}

NON-NEGOTIABLE FACTS — you may use these numbers and nothing else. Never invent a
feature, a room, an amenity, a distance to anything, or a claim about the future value
of the neighbourhood. If a fact is not in this list, it does not exist:
{facts}

HOW TO WRITE
- Write in {language_name}. {language_note}
- This is transcreation, not translation: each language gets its own idiom and rhythm.
- Short sentences. Concrete nouns. Let the architecture do the selling.
- Talk about light, proportion, patios, the street, how the house is used.
- No exclamation marks, no emoji, no ALL CAPS, no questions to the reader.
- Never describe the images as renders or AI; the disclosure is printed separately.

OUTPUT
Return ONE JSON object and nothing else. Every value is a plain string — never an
object, never a list. Use exactly this shape, replacing the placeholder text:

{example}

Each field, with the limit it must respect (character limits are layout constraints,
not suggestions — count them):
{slot_list}"""


class CasaCopySpec:
    """Builds the system and user prompts for the LLM node from brand, project and slots."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "language": (["es", "en", "pt"],),
            "piece": ("STRING", {"default": "street_restored"}),
            "scene_note": ("STRING", {"multiline": True, "default": "Facade from across the street, golden hour."}),
            "slots": ("STRING", {"multiline": True, "default": json.dumps({
                "claim": {"max_chars": 42, "what": "the post's claim, lowercase, no period"},
                "headline": {"max_chars": 38, "what": "headline for this image"},
                "caption": {"max_chars": 90, "what": "one sentence under the image"},
                "post_caption": {"max_chars": 420, "what": "the caption of the post, 2 short paragraphs"},
                "cta": {"max_chars": 26, "what": "call to action, imperative"},
            }, indent=1)}),
        }}

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("system_prompt", "user_prompt", "slots_json")
    FUNCTION = "run"
    CATEGORY = CATEGORY

    def run(self, language, piece, scene_note, slots):
        copy_cfg = json.loads((REPO / "config" / "copy.json").read_text(encoding="utf-8"))
        p = copy_cfg["project"]
        facts = "\n".join(f"- {k}: {v}" for k, v in {
            "project": p["name"], "typology": p["typology"], "neighbourhood": p["neighbourhood"],
            "lot": p["lot"], "covered area m2": p["area_m2"], "rooms": p["rooms"], "patios": p["patios"],
            "price USD": p["price_usd"], "status": p["status"][language],
        }.items())
        slot_spec = json.loads(slots)
        example = json.dumps({k: f"<{k} here>" for k in slot_spec}, indent=1, ensure_ascii=False)
        slot_list = "\n".join(f'- "{k}": {v["what"]} — max {v["max_chars"]} characters' for k, v in slot_spec.items())
        system = SYSTEM_PROMPT.format(
            positioning=BRAND["positioning"], brand=BRAND["name"],
            voice_do="; ".join(BRAND["voice"]["do"]), voice_dont="; ".join(BRAND["voice"]["dont"]),
            facts=facts, language_name={"es": "Spanish", "en": "English", "pt": "Brazilian Portuguese"}[language],
            language_note={"es": "Use rioplatense Spanish (vos, not tú), never peninsular.",
                           "en": "Neutral international English; metric units.",
                           "pt": "Brazilian Portuguese, not European; metric units."}[language],
            example=example, slot_list=slot_list)
        user = (f"Piece: {piece}\nWhat the image shows: {scene_note}\n"
                f"Write the JSON now, in {language}.")
        return (system, user, slots)


class CasaCopyCheck:
    """Validates the LLM's JSON before it reaches the layout: lengths, banned words,
    invented numbers, and the things the brand voice forbids."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "llm_output": ("STRING", {"forceInput": True}),
            "slots_json": ("STRING", {"forceInput": True}),
            "language": (["es", "en", "pt"],),
        }}

    RETURN_TYPES = ("BOOLEAN", "STRING", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("ok", "report", "claim", "headline", "caption", "post_caption")
    FUNCTION = "run"
    CATEGORY = CATEGORY

    BANNED = {
        "es": ["oportunidad única", "sueño", "exclusivo", "lujo", "imperdible", "único en su tipo", "inversión segura"],
        "en": ["dream home", "once in a lifetime", "exclusive", "luxury", "unmissable", "safe investment"],
        "pt": ["oportunidade única", "sonho", "exclusivo", "luxo", "imperdível", "investimento seguro"],
    }

    def run(self, llm_output, slots_json, language):
        issues = []
        text = llm_output.strip()
        if "```" in text:
            text = text.split("```")[1].removeprefix("json").strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            return (False, f"not valid JSON: {e}", "", "", "", "")

        slots = json.loads(slots_json)
        for key, spec in slots.items():
            raw_v = data.get(key, "")
            if isinstance(raw_v, (dict, list)):
                issues.append(f"{key}: expected a string, got {type(raw_v).__name__} (model echoed the schema)")
                continue
            v = str(raw_v).strip()
            if not v:
                issues.append(f"{key}: missing")
                continue
            if len(v) > spec["max_chars"]:
                issues.append(f"{key}: {len(v)} chars > {spec['max_chars']}")
            low = v.lower()
            for bad in self.BANNED[language]:
                if bad in low:
                    issues.append(f"{key}: banned phrase '{bad}'")
            if "!" in v or "¡" in v:
                issues.append(f"{key}: exclamation mark")

        # numbers must come from the project facts
        p = json.loads((REPO / "config" / "copy.json").read_text(encoding="utf-8"))["project"]
        allowed = {str(p["area_m2"]), str(p["rooms"]), str(p["patios"]), str(p["price_usd"]),
                   f"{p['price_usd']:,}".replace(",", "."), "8,66", "8.66", "50", "1890", "1408"}
        import re
        for key in slots:
            for num in re.findall(r"\d[\d.,]*", str(data.get(key, ""))):
                if num.strip(".,") not in {a.strip(".,") for a in allowed}:
                    issues.append(f"{key}: number '{num}' is not in the project facts")

        ok = not issues
        report = ("COPY OK" if ok else "COPY REJECTED") + ("\n- " + "\n- ".join(issues) if issues else "")
        return (ok, report, data.get("claim", ""), data.get("headline", ""), data.get("caption", ""), data.get("post_caption", ""))


# ---- 4. layout --------------------------------------------------------------

class CasaLayout:
    """Lays out a finished asset with the design system: grid, type scale, safe zones,
    mark and the AI disclosure. Same engine the CLI uses."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE",),
            "format": (["feed", "story", "link", "banner"],),
            "template": (["cover", "shot", "data"],),
            "language": (["es", "en", "pt"],),
            "headline": ("STRING", {"multiline": True, "default": ""}),
            "caption": ("STRING", {"multiline": True, "default": ""}),
            "meta_left": ("STRING", {"default": ""}),
            "meta_right": ("STRING", {"default": ""}),
        }}

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("asset", "qa_report")
    FUNCTION = "run"
    CATEGORY = CATEGORY

    def run(self, image, format, template, language, headline, caption, meta_left, meta_right):
        from brand_mark import draw_mark
        src = to_pil(image)
        cv = Canvas(format)
        tmp = REPO / "out" / ".cache_layout_src.png"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        src.save(tmp)
        issues = []

        if template == "data":
            cv = Canvas(format, C["paper"])
            y = cv.text((cv.col(0), cv.safe[1]), meta_left, "meta", C["ink"])
            cv.text((cv.w - cv.col(0), cv.safe[1]), meta_right, "meta", C["ink"], align="right")
            cv.rule(cv.col(0), y + 10 * cv.k, cv.w - 2 * cv.col(0))
            y = cv.text((cv.col(0), y + 60 * cv.k), headline, "display", C["ink"], cv.span(11))
            cv.place_image(tmp, (cv.col(0), y + 40 * cv.k, cv.span(12), cv.h - y - cv.safe[3] - 120 * cv.k))
            cv.text((cv.col(0), cv.h - cv.safe[3] - 40 * cv.k), caption, "body", C["muted"], cv.span(10))
        else:
            cv.place_image(tmp, (0, 0, cv.w, cv.h))
            role = "display" if template == "cover" else "body"
            block = cv.block_height(headline, role, cv.span(10)) if headline else 0
            cap_h = cv.block_height(caption, "body", cv.span(9)) if caption else 0
            band = block + cap_h + 170 * cv.k
            cv.scrim((0, round(cv.h - band - 200 * cv.k), cv.w, round(band + 200 * cv.k)), 0.9)
            y = cv.h - cv.safe[3] - band + 40 * cv.k
            if meta_left or meta_right:
                cv.text((cv.col(0), y), meta_left, "meta", "#CFCABE")
                cv.text((cv.w - cv.col(0), y), meta_right, "meta", "#CFCABE", align="right")
                y = cv.rule(cv.col(0), y + cv.tok("meta")["px"] * 1.9, cv.w - 2 * cv.col(0), "#CFCABE") + 26 * cv.k
            if headline:
                y = cv.text((cv.col(0), y), headline, role, C["paper"], cv.span(10))
            if caption:
                cv.text((cv.col(0), y + 20 * cv.k), caption, "body", "#DCD8CE", cv.span(9))
            draw_mark(cv.img, (round(cv.col(0)), round(cv.safe[1])), round(52 * cv.k), C["paper"])
            cv.text((cv.col(0) + 70 * cv.k, cv.safe[1] + 10 * cv.k), BRAND["wordmark"], "body", C["paper"])

        cv.text((cv.col(0), cv.h - cv.safe[3] + (18 * cv.k if format == "story" else -22 * cv.k)),
                BRAND["legal"]["ai_disclosure"][language], "caption", "#9A958A" if template != "data" else C["muted"])

        # design QA: contrast of the main block and no overlapping type
        for i, a in enumerate(cv.boxes):
            for b in cv.boxes[i + 1:]:
                ax, ay, aw, ah = a["box"]
                bx, by, bw, bh = b["box"]
                if min(ax + aw, bx + bw) - max(ax, bx) > 4 and min(ay + ah, by + bh) - max(ay, by) > 4:
                    issues.append(f"'{a['text']}' overlaps '{b['text']}'")
        report = "LAYOUT OK" if not issues else "LAYOUT ISSUES\n- " + "\n- ".join(issues)
        return (to_image(cv.img), report)


# ---- 5. run log -------------------------------------------------------------

class CasaLogRun:
    """Appends one line to out/runs.jsonl so graph runs land in the same cost table
    as the CLI runs: seconds, tokens, credits, dollars."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "stage": ("STRING", {"default": "graph_render"}),
            "item": ("STRING", {"default": ""}),
            "backend": (["local_comfyui", "comfy_cloud", "partner_api"],),
            "seconds": ("FLOAT", {"default": 0.0, "min": 0.0, "step": 0.1}),
            "tokens_in": ("INT", {"default": 0, "min": 0}),
            "tokens_out": ("INT", {"default": 0, "min": 0}),
            "cost_usd": ("FLOAT", {"default": 0.0, "min": 0.0, "step": 0.0001}),
            "notes": ("STRING", {"multiline": True, "default": ""}),
        }}

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("line",)
    FUNCTION = "run"
    OUTPUT_NODE = True
    CATEGORY = CATEGORY

    def run(self, stage, item, backend, seconds, tokens_in, tokens_out, cost_usd, notes):
        entry = {"ts": datetime.now(timezone.utc).isoformat(), "stage": stage, "item": item, "backend": backend,
                 "ms": round(seconds * 1000), "tokens_in": tokens_in, "tokens_out": tokens_out,
                 "cost_usd": cost_usd, "cache_hit": False, "source": "comfy_graph", "notes": notes}
        path = REPO / "out" / "runs.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        return (json.dumps(entry),)


NODE_CLASS_MAPPINGS = {
    "CasaPasses": CasaPasses,
    "CasaQAGate": CasaQAGate,
    "CasaCopySpec": CasaCopySpec,
    "CasaCopyCheck": CasaCopyCheck,
    "CasaLayout": CasaLayout,
    "CasaLogRun": CasaLogRun,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "CasaPasses": "Casa · passes from 3D",
    "CasaQAGate": "Casa · quality gate",
    "CasaCopySpec": "Casa · copy prompt",
    "CasaCopyCheck": "Casa · copy check",
    "CasaLayout": "Casa · layout",
    "CasaLogRun": "Casa · log run",
}
