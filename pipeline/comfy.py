"""Minimal ComfyUI client with instrumentation.

Runs an API-format workflow and returns the output images plus what it cost:
wall time, per-node time (from websocket 'executing' events), cached nodes,
peak VRAM, and average GPU power (sampled with nvidia-smi).
"""
import json
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import uuid

import websocket


class ComfyError(RuntimeError):
    pass


class GpuSampler(threading.Thread):
    """Samples VRAM used / GPU util / power draw every `period` seconds."""

    def __init__(self, period=0.5):
        super().__init__(daemon=True)
        self.period = period
        self.samples = []
        self._stop = threading.Event()

    def run(self):
        while not self._stop.is_set():
            try:
                out = subprocess.run(
                    ["nvidia-smi", "--query-gpu=memory.used,utilization.gpu,power.draw", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=5,
                ).stdout.strip().split(",")
                self.samples.append((time.time(), float(out[0]), float(out[1]), float(out[2])))
            except Exception:
                pass
            self._stop.wait(self.period)

    def stop(self):
        self._stop.set()
        self.join(timeout=3)
        if not self.samples:
            return {}
        mem = [s[1] for s in self.samples]
        util = [s[2] for s in self.samples]
        power = [s[3] for s in self.samples]
        dur = self.samples[-1][0] - self.samples[0][0]
        return {
            "vram_peak_mb": max(mem),
            "gpu_util_avg": round(sum(util) / len(util), 1),
            "power_avg_w": round(sum(power) / len(power), 1),
            "energy_wh": round(sum(power) / len(power) * dur / 3600, 3),
        }


class Comfy:
    def __init__(self, base="http://127.0.0.1:8000"):
        self.base = base.rstrip("/")
        self.client_id = uuid.uuid4().hex

    # ---- http helpers
    def _get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=60) as r:
            return r.read()

    def _post_json(self, path, payload):
        req = urllib.request.Request(self.base + path, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise ComfyError(f"{path} -> {e.code}: {e.read().decode(errors='replace')[:2000]}") from e

    def system_stats(self):
        return json.loads(self._get("/system_stats"))

    def upload_image(self, data: bytes, name: str, subfolder="casa"):
        boundary = uuid.uuid4().hex
        parts = []
        for key, val in (("overwrite", "true"), ("subfolder", subfolder), ("type", "input")):
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{val}\r\n'.encode())
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{name}"\r\nContent-Type: image/png\r\n\r\n'.encode() + data + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        req = urllib.request.Request(self.base + "/upload/image", data=b"".join(parts), headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(req, timeout=60) as r:
            res = json.loads(r.read())
        return f"{res['subfolder']}/{res['name']}" if res.get("subfolder") else res["name"]

    def history(self, prompt_id, wait_s=30):
        # /history can lag a moment behind the execution_success event
        deadline = time.time() + wait_s
        while True:
            h = json.loads(self._get(f"/history/{prompt_id}"))
            if prompt_id in h:
                return h[prompt_id]
            if time.time() > deadline:
                raise ComfyError(f"no history for {prompt_id}")
            time.sleep(0.25)

    @staticmethod
    def _exec_ms(history):
        # server-side execution time from the status timestamps
        ts = {m[0]: m[1].get("timestamp") for m in history.get("status", {}).get("messages", [])}
        if ts.get("execution_start") and ts.get("execution_success"):
            return ts["execution_success"] - ts["execution_start"]
        return None

    # ---- run a workflow
    def run(self, workflow: dict, timeout=1800):
        ws = websocket.create_connection(f"{self.base.replace('http', 'ws', 1)}/ws?clientId={self.client_id}", timeout=timeout)
        gpu = GpuSampler()
        gpu.start()
        t0 = time.time()
        try:
            prompt_id = self._post_json("/prompt", {"prompt": workflow, "client_id": self.client_id})["prompt_id"]
            node_ms, cached, current, started = {}, [], None, None
            while True:
                msg = ws.recv()
                if not isinstance(msg, str):
                    continue  # binary preview frames
                m = json.loads(msg)
                data = m.get("data", {})
                if data.get("prompt_id") not in (None, prompt_id):
                    continue
                kind = m["type"]
                if kind == "execution_cached":
                    cached = data.get("nodes", [])
                elif kind == "executing":
                    now = time.time()
                    if current is not None:
                        node_ms[current] = round((now - started) * 1000)
                    current, started = data.get("node"), now
                    if current is None:
                        break
                elif kind == "execution_error":
                    raise ComfyError(f"node {data.get('node_id')} ({data.get('node_type')}): {data.get('exception_message')}")
                elif kind == "execution_success":
                    if current is not None:
                        node_ms[current] = round((time.time() - started) * 1000)
                    break
        finally:
            ws.close()
            gpu_stats = gpu.stop()
        total_ms = round((time.time() - t0) * 1000)

        history = self.history(prompt_id)
        exec_ms = self._exec_ms(history)
        images = []
        for node_id, out in history.get("outputs", {}).items():
            for img in out.get("images", []):
                q = urllib.parse.urlencode({"filename": img["filename"], "subfolder": img["subfolder"], "type": img["type"]})
                images.append({"node": node_id, "filename": img["filename"], "data": self._get(f"/view?{q}")})
        titles = {k: v.get("_meta", {}).get("title", v["class_type"]) for k, v in workflow.items()}
        return {
            "prompt_id": prompt_id,
            "images": images,
            "total_ms": total_ms,
            "exec_ms": exec_ms,
            "node_ms": {titles.get(k, k): v for k, v in node_ms.items()},
            "cached_nodes": [titles.get(k, k) for k in cached],
            **gpu_stats,
        }
