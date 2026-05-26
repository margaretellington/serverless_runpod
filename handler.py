"""
RunPod Serverless Worker for ComfyUI WAN 2.2 S2V Audio-to-Video.

Expects ComfyUI to already be running on localhost:8188 (started by start-comfy.sh).
"""

import os
import json
import time
import uuid
import base64
import logging
from pathlib import Path
from urllib.parse import urlparse

import runpod
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
COMFY_URL = os.getenv("COMFYUI_URL", "http://127.0.0.1:8188")
COMFY_INPUT_DIR = Path("/app/ComfyUI/input")
COMFY_OUTPUT_DIR = Path("/app/ComfyUI/output")
WORKFLOW_PATH = Path("/app/wan_audio_workflow.json")
S3_BUCKET = os.getenv("S3_BUCKET", "comfyui-wan-outputs")
S3_ENDPOINT = os.getenv("S3_ENDPOINT", "https://s3api-us-il-1.runpod.io")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_workflow() -> dict:
    """Load the WAN audio workflow template from disk."""
    if not WORKFLOW_PATH.exists():
        raise FileNotFoundError(f"Workflow not found: {WORKFLOW_PATH}")
    return json.loads(WORKFLOW_PATH.read_text())


def _download_file(url: str, dest: Path) -> Path:
    """Download a file from a URL to a local path. Handles data URIs too."""
    dest.parent.mkdir(parents=True, exist_ok=True)

    if url.startswith("data:"):
        header, b64 = url.split(",", 1)
        data = base64.b64decode(b64)
        dest.write_bytes(data)
    else:
        r = requests.get(url, stream=True, timeout=120)
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)

    log.info(f"Downloaded {dest} ({dest.stat().st_size:,} bytes)")
    return dest


def _wait_for_comfyui(timeout: int = 10) -> bool:
    """Block until ComfyUI answers on its HTTP port."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"{COMFY_URL}/system_stats", timeout=3)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def _comfy_post(endpoint: str, payload: dict) -> dict:
    """POST JSON to the ComfyUI API and return the parsed response."""
    r = requests.post(f"{COMFY_URL}{endpoint}", json=payload, timeout=30)
    r.raise_for_status()
    return r.json()


def _comfy_get(endpoint: str) -> dict:
    """GET JSON from the ComfyUI API."""
    r = requests.get(f"{COMFY_URL}{endpoint}", timeout=30)
    r.raise_for_status()
    return r.json()


def _upload_image(filename: str) -> None:
    """Tell ComfyUI about an image we placed in the input directory."""
    _comfy_post("/upload/image", {"image": filename, "overwrite": True})


def _submit_workflow(workflow: dict) -> str:
    """Submit a workflow and return the prompt_id."""
    payload = {
        "prompt": workflow,
        "client_id": f"runpod-worker-{uuid.uuid4().hex[:8]}",
    }
    resp = _comfy_post("/prompt", payload)
    if "prompt_id" not in resp:
        raise RuntimeError(f"ComfyUI rejected prompt: {resp}")
    log.info(f"Workflow submitted → prompt_id={resp['prompt_id']}")
    return resp["prompt_id"]


def _poll_execution(prompt_id: str, poll_interval: float = 2.0, timeout: int = 600) -> dict:
    """Poll until a prompt execution completes or times out."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        history = _comfy_get(f"/history/{prompt_id}")
        entry = history.get(prompt_id)
        if entry is not None:
            status = entry.get("status", {})
            if status.get("completed") is True:
                log.info(f"Execution {prompt_id} completed.")
                return entry
            if status.get("status_str") == "error":
                raise RuntimeError(f"Execution {prompt_id} failed: {entry}")
        time.sleep(poll_interval)

    raise TimeoutError(f"Execution {prompt_id} timed out after {timeout}s")


def _collect_outputs(history_entry: dict) -> list[dict]:
    """Walk the execution outputs and collect file paths for 'SaveVideo' nodes."""
    outputs = []
    for node_id, node_output in history_entry.get("outputs", {}).items():
        for ext_type, ext_data in node_output.items():
            if ext_type in ("videos", "images", "files"):
                for item in ext_data:
                    fname = item.get("filename") or item.get("name")
                    subfolder = item.get("subfolder", "")
                    ftype = item.get("type", "output")
                    outputs.append({
                        "filename": fname,
                        "subfolder": subfolder,
                        "type": ftype,
                    })
    return outputs


def _locate_output_files(outputs: list[dict]) -> list[Path]:
    """Resolve output entries to absolute file paths on disk."""
    paths = []
    for o in outputs:
        candidate = COMFY_OUTPUT_DIR / o["subfolder"] / o["filename"]
        if candidate.exists():
            paths.append(candidate)
        else:
            log.warning(f"Output file not found on disk: {candidate}")
    return paths


def _upload_to_s3(local_path: Path) -> str | None:
    """Upload a file to RunPod S3-compatible storage. Returns the public URL."""
    if not S3_BUCKET:
        return None
    import boto3

    s3 = boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT or None,
        config=boto3.session.Config(s3={"addressing_style": "path"}),
    )
    key = f"wan-audio-outputs/{uuid.uuid4().hex}/{local_path.name}"
    s3.upload_file(str(local_path), S3_BUCKET, key)
    url = f"{S3_ENDPOINT.rstrip('/')}/{S3_BUCKET}/{key}"
    log.info(f"Uploaded {local_path} → {url}")
    return url


# ---------------------------------------------------------------------------
# Workflow patching
# ---------------------------------------------------------------------------

def _patch_workflow(wf: dict, job: dict) -> dict:
    """Patch the WAN audio workflow template with the user's input values."""
    nodes_by_id = {n["id"]: n for n in wf["nodes"]}

    patches: dict[int, dict] = {}

    def _p(node_id: int, widget_name: str, value):
        if node_id not in patches:
            patches[node_id] = {}
        patches[node_id][widget_name] = value

    # Positive prompt → node 6 (CLIPTextEncode)
    if job.get("positive_prompt"):
        _p(6, "text", job["positive_prompt"])

    # Negative prompt → node 7 (CLIPTextEncode)
    if job.get("negative_prompt"):
        _p(7, "text", job["negative_prompt"])

    # Seed → KSampler (node 3)
    if job.get("seed") is not None:
        _p(3, "seed", int(job["seed"]))

    # Steps → KSampler (node 3)
    if job.get("steps"):
        _p(3, "steps", int(job["steps"]))

    # CFG → KSampler (node 3)
    if job.get("cfg"):
        _p(3, "cfg", float(job["cfg"]))

    # WanSoundImageToVideo params → node 93
    if job.get("width"):
        _p(93, "width", int(job["width"]))
    if job.get("height"):
        _p(93, "height", int(job["height"]))
    if job.get("num_frames"):
        _p(93, "length", int(job["num_frames"]))
    if job.get("batch_size"):
        _p(93, "batch_size", int(job["batch_size"]))

    # Chunk length → node 104 (PrimitiveInt)
    if job.get("chunk_length"):
        _p(104, "value", int(job["chunk_length"]))

    # Steps primitive → node 103
    if job.get("steps"):
        _p(103, "value", int(job["steps"]))

    # CFG primitive → node 105
    if job.get("cfg"):
        _p(105, "value", float(job["cfg"]))

    # Frame multiplier → node 16:9
    if job.get("frame_multiplier"):
        _p("16:9", "value", int(job["frame_multiplier"]))

    # Apply patches
    for node_id, widget_values in patches.items():
        node = nodes_by_id.get(node_id)
        if node is not None:
            for widget_name, value in widget_values.items():
                if "widgets_values" not in node:
                    node["widgets_values"] = []
                # Find the widget index
                inputs = node.get("inputs", [])
                for i, inp in enumerate(inputs):
                    if inp.get("widget", {}).get("name") == widget_name:
                        while len(node["widgets_values"]) <= i:
                            node["widgets_values"].append(None)
                        node["widgets_values"][i] = value
                        break

    return wf


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

def handler(job: dict) -> dict:
    """Main RunPod serverless handler — called once per invocation."""
    job_input = job.get("input", {})

    log.info(f"Job received: {json.dumps({k: v for k, v in job_input.items() if 'url' not in k}, default=str)[:500]}")

    # --- Download inputs ---------------------------------------------------
    image_url = job_input.get("image_url")
    audio_url = job_input.get("audio_url")
    image_filename: str | None = None
    audio_filename: str | None = None

    if image_url:
        ext = os.path.splitext(urlparse(image_url).path)[1] or ".png"
        image_filename = f"input_ref_{uuid.uuid4().hex[:8]}{ext}"
        _download_file(image_url, COMFY_INPUT_DIR / image_filename)
        # Notify ComfyUI about the new file in the input directory
        try:
            _comfy_post("/upload/image", {"image": image_filename, "overwrite": True})
        except Exception:
            pass

    if audio_url:
        ext = os.path.splitext(urlparse(audio_url).path)[1] or ".mp3"
        audio_filename = f"input_audio_{uuid.uuid4().hex[:8]}{ext}"
        _download_file(audio_url, COMFY_INPUT_DIR / audio_filename)

    # --- Patch and submit workflow -----------------------------------------
    wf = _load_workflow()

    # Set the input filenames in the workflow
    if image_filename:
        for node in wf["nodes"]:
            if node["id"] == 52:  # LoadImage node
                node.setdefault("widgets_values", ["image", None])[0] = image_filename
    if audio_filename:
        for node in wf["nodes"]:
            if node["id"] == 58:  # LoadAudio node
                node.setdefault("widgets_values", ["audio", None, None])[0] = audio_filename

    wf = _patch_workflow(wf, job_input)

    prompt_id = _submit_workflow(wf)

    # --- Wait for completion -----------------------------------------------
    history = _poll_execution(prompt_id, timeout=job_input.get("timeout", 600))

    # --- Collect outputs ---------------------------------------------------
    output_entries = _collect_outputs(history)
    output_files = _locate_output_files(output_entries)

    if not output_files:
        return {
            "status": "error",
            "message": f"Execution {prompt_id} completed but no output files found.",
            "history": history,
        }

    # --- Upload ------------------------------------------------------------
    result_urls = []
    for fp in output_files:
        s3_url = _upload_to_s3(fp)
        result_urls.append({
            "filename": fp.name,
            "size_bytes": fp.stat().st_size,
            "url": s3_url or str(fp),
            "comfy_output": f"{COMFY_URL}/view?filename={fp.name}&type=output&subfolder={fp.parent.relative_to(COMFY_OUTPUT_DIR)}",
        })

    return {
        "status": "completed",
        "prompt_id": prompt_id,
        "outputs": result_urls,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if not _wait_for_comfyui(timeout=60):
        log.error("ComfyUI did not become ready. Exiting.")
        raise SystemExit(1)

    log.info("ComfyUI is ready. Starting RunPod serverless handler.")
    runpod.serverless.start({"handler": handler})
