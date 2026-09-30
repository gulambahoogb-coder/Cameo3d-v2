"""
Cameo3D - Image / Text / Multi-view to 3D API (Flask, deploy on Render)

Backend:
- Accepts requests from the Cameo3D Odoo website in three modes:
    1. Image -> 3D      : image_base64
    2. Text  -> 3D      : prompt
    3. Multi-view -> 3D : image_base64 (front) + multi_view [{view, image_base64}]
- Options from the page: pbr, generate_type, face_count
- Submits to Tencent HY 3D Global (Hunyuan 3D 3.1, international)
- Polls until the GLB is ready, then returns it as base64
- /convert turns a finished model into FBX / OBJ / STL / USDZ (Tencent Convert3DFormat, 5 credits)

Render environment variables required:
    TENCENT_SECRET_ID
    TENCENT_SECRET_KEY

Render start command:  gunicorn app:app --timeout 120

Optional: add "Pillow" to requirements.txt to also check image resolution
(128-5000 px per side) before spending Tencent credits.
"""

import io
import os
import json
import time
import base64
import requests
from flask import Flask, request, jsonify

from tencentcloud.common import credential
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
from tencentcloud.hunyuan.v20230901 import hunyuan_client, models

try:  # optional: resolution check
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None

app = Flask(__name__)

# ---------------------------------------------------------------
# PERMISSION FOR YOUR ODOO WEBSITE (CORS)
# ---------------------------------------------------------------
ALLOWED_ORIGINS = [
    "https://cameo3d.odoo.com",
    "https://www.cameo3d.odoo.com",
]


@app.after_request
def add_cors_headers(response):
    origin = request.headers.get("Origin")
    if origin in ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


# ---------------------------------------------------------------
# LIMITS (protect your Tencent credits)
# ---------------------------------------------------------------
MAX_JOBS_PER_HOUR = 10                                # per visitor IP
MAX_CONVERSIONS_PER_HOUR = 20                         # per visitor IP (each conversion costs 5 Tencent credits)
app.config["MAX_CONTENT_LENGTH"] = 36 * 1024 * 1024   # up to 4 images of 6 MB each (base64 adds ~33%)

MAX_PROMPT_CHARS = 1000               # Tencent allows 1024; the page limits to 1000
MAX_IMAGE_BYTES = 6 * 1024 * 1024     # Tencent recommends <= 6 MB per image
MIN_SIDE, MAX_SIDE = 128, 5000        # Tencent resolution limits per side

# Only these values are accepted, so nobody can send odd options to Tencent.
ALLOWED_TYPES = {"Normal", "Geometry"}                                   # textured / white model
ALLOWED_FACE_COUNTS = {50000, 100000, 200000, 500000, 1000000, 1500000}  # matches the page dropdown
VIEW_NAMES = ("left", "back", "right")                                   # extra views (front = main image)
CONVERT_FORMATS = {"FBX", "OBJ", "STL", "USDZ"}                          # formats the download menu can request

_hits = {}
_conv_hits = {}


def client_ip():
    return (request.headers.get("X-Forwarded-For") or request.remote_addr or "?").split(",")[0].strip()


def origin_ok():
    """Only requests coming from your Odoo website are accepted."""
    return request.headers.get("Origin", "") in ALLOWED_ORIGINS


def rate_limited():
    """True if this visitor already used all jobs this hour. Does NOT count a job."""
    ip = client_ip()
    now = time.time()
    hits = [t for t in _hits.get(ip, []) if now - t < 3600]
    _hits[ip] = hits
    return len(hits) >= MAX_JOBS_PER_HOUR


def record_job():
    """Count one job. Called only after the request passed validation."""
    _hits.setdefault(client_ip(), []).append(time.time())


def conversion_limited():
    """True if this visitor already used all conversions this hour. Does NOT count one."""
    ip = client_ip()
    now = time.time()
    hits = [t for t in _conv_hits.get(ip, []) if now - t < 3600]
    _conv_hits[ip] = hits
    return len(hits) >= MAX_CONVERSIONS_PER_HOUR


def record_conversion():
    _conv_hits.setdefault(client_ip(), []).append(time.time())


# ---------------------------------------------------------------
# TENCENT HY 3D GLOBAL (Hunyuan 3D 3.1)
# Keys live only in Render Environment Variables.
# ---------------------------------------------------------------
SECRET_ID = os.environ.get("TENCENT_SECRET_ID", "").strip()
SECRET_KEY = os.environ.get("TENCENT_SECRET_KEY", "").strip()
HY_MODEL_VERSION = "3.1"


def hy_client():
    cred = credential.Credential(SECRET_ID, SECRET_KEY)
    http = HttpProfile()
    http.endpoint = "hunyuan.intl.tencentcloudapi.com"
    prof = ClientProfile()
    prof.httpProfile = http
    return hunyuan_client.HunyuanClient(cred, "ap-singapore", prof)


def friendly_tencent_error(exc):
    """Log the real error on Render, show visitors a short clear message."""
    code = ""
    msg = str(exc)
    try:
        code = exc.get_code() or ""
        msg = exc.get_message() or msg
    except Exception:
        pass
    app.logger.error("Tencent error code=%s message=%s", code, msg)
    low = (code + " " + msg).lower()
    if "limit" in low or "concurren" in low:
        return "The 3D service is busy right now. Please try again in a minute."
    if any(w in low for w in ("balance", "arrear", "insufficient", "resource")):
        return "The 3D service is temporarily unavailable. Please try again later."
    if any(w in low for w in ("risk", "moderat", "sensitive", "illegal", "audit")):
        return "This input was rejected by the content check. Please try a different image or description."
    return f"Tencent error: {msg}"


# ---------------------------------------------------------------
# INPUT CHECKS
# ---------------------------------------------------------------
class BadInput(Exception):
    pass


def sniff(raw):
    """Detect the real image type from the file's first bytes."""
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if raw[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "webp"
    return None


def read_image(value, label, allowed):
    """Validate one base64 image. Returns clean base64 text (no data: prefix)."""
    if not isinstance(value, str) or not value.strip():
        raise BadInput(f"{label}: no image was provided.")
    value = value.strip()
    if value.lower().startswith("data:") and "," in value:
        value = value.split(",", 1)[1]
    try:
        raw = base64.b64decode(value, validate=True)
    except Exception:
        raise BadInput(f"{label}: invalid image data.")
    if len(raw) > MAX_IMAGE_BYTES:
        raise BadInput(f"{label} is larger than 6 MB. Please choose a smaller image.")
    kind = sniff(raw)
    if kind not in allowed:
        names = ["JPG" if k == "jpeg" else k.upper() for k in sorted(allowed)]
        kinds = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " or " + names[-1]
        raise BadInput(f"{label} must be a {kinds} image.")
    if Image is not None:
        try:
            w, h = Image.open(io.BytesIO(raw)).size
        except Exception:
            raise BadInput(f"{label} could not be read as an image.")
        if min(w, h) < MIN_SIDE or max(w, h) > MAX_SIDE:
            raise BadInput(f"{label} must be between {MIN_SIDE} and {MAX_SIDE} pixels on each side (yours is {w}x{h}).")
    return value


def parse_options(data):
    gen = data.get("generate_type") or "Normal"
    if gen not in ALLOWED_TYPES:
        raise BadInput("Unknown model type.")

    pbr = data.get("pbr") is True
    if gen == "Geometry":
        pbr = False  # white models have no textures, so PBR does not apply

    face = data.get("face_count")
    if face in (None, "", 0):
        face = None
    else:
        try:
            face = int(face)
        except (TypeError, ValueError):
            raise BadInput("Unsupported polygon count.")
        if face not in ALLOWED_FACE_COUNTS:
            raise BadInput("Unsupported polygon count.")
    return gen, pbr, face


def build_payload(data):
    """Turn the page's request into the Tencent request. Raises BadInput on any problem."""
    gen, pbr, face = parse_options(data)
    payload = {"Model": HY_MODEL_VERSION, "GenerateType": gen}
    if gen == "Normal":
        payload["EnablePBR"] = pbr
    if face:
        payload["FaceCount"] = face

    prompt = data.get("prompt")
    image = data.get("image_base64")
    views = data.get("multi_view")

    if prompt is not None and not isinstance(prompt, str):
        raise BadInput("Invalid text description.")
    has_prompt = bool(prompt and prompt.strip())

    # ---- Text -> 3D ----
    if has_prompt:
        if image or views:
            raise BadInput("Send either a text description or images, not both.")
        prompt = prompt.strip()
        if len(prompt) > MAX_PROMPT_CHARS:
            raise BadInput(f"Description is too long (max {MAX_PROMPT_CHARS} characters).")
        payload["Prompt"] = prompt
        return payload

    # ---- Image -> 3D  and  Multi-view -> 3D ----
    if not image:
        raise BadInput("No image was provided.")
    payload["ImageBase64"] = read_image(image, "Image", {"png", "jpeg", "webp"})

    if views:
        if not isinstance(views, list) or len(views) > len(VIEW_NAMES):
            raise BadInput("Invalid multi-view data.")
        seen, out = set(), []
        for v in views:
            name = v.get("view") if isinstance(v, dict) else None
            if name not in VIEW_NAMES or name in seen:
                raise BadInput("Each extra view must be left, back or right, used once.")
            seen.add(name)
            b64 = read_image(v.get("image_base64"), f"{name.capitalize()} view", {"png", "jpeg"})
            out.append({"ViewType": name, "ViewImageBase64": b64})
        payload["MultiViewImages"] = out
    return payload


# ---------------------------------------------------------------
# ROUTES
# ---------------------------------------------------------------
@app.route("/")
def index():
    # Standalone page is off. Visitors use the Odoo website.
    # This reply also lets the Odoo page wake the free server up.
    return "Cameo3D API is running.", 200


@app.route("/submit", methods=["POST", "OPTIONS"])
def submit():
    if request.method == "OPTIONS":
        return ("", 204)
    if not origin_ok():
        return jsonify({"error": "Forbidden."}), 403
    if rate_limited():
        return jsonify({"error": "Too many requests. Please try again later."}), 429
    if not SECRET_ID or not SECRET_KEY:
        return jsonify({"error": "TENCENT_SECRET_ID / TENCENT_SECRET_KEY are not set on Render."}), 500

    data = request.get_json(silent=True) or {}
    try:
        payload = build_payload(data)
    except BadInput as exc:
        return jsonify({"error": str(exc)}), 400

    record_job()  # only valid requests use up the visitor's hourly allowance

    try:
        req = models.SubmitHunyuanTo3DProJobRequest()
        req.from_json_string(json.dumps(payload))
        resp = hy_client().SubmitHunyuanTo3DProJob(req)
        return jsonify({"job_id": resp.JobId})
    except TencentCloudSDKException as exc:
        return jsonify({"error": friendly_tencent_error(exc)}), 502
    except Exception as exc:
        app.logger.exception("submit failed")
        return jsonify({"error": f"Server error: {exc}"}), 500


@app.route("/status/<job_id>", methods=["GET", "OPTIONS"])
def status(job_id):
    if request.method == "OPTIONS":
        return ("", 204)
    if not origin_ok():
        return jsonify({"error": "Forbidden."}), 403
    if not SECRET_ID or not SECRET_KEY:
        return jsonify({"error": "TENCENT_SECRET_ID / TENCENT_SECRET_KEY are not set on Render."}), 500

    try:
        req = models.QueryHunyuanTo3DProJobRequest()
        req.from_json_string(json.dumps({"JobId": job_id}))
        resp = hy_client().QueryHunyuanTo3DProJob(req)
        st = str(resp.Status or "").upper()

        if st == "DONE":
            files = resp.ResultFile3Ds or []
            glb_url = None
            for f in files:
                if str(getattr(f, "Type", "")).upper() == "GLB":
                    glb_url = getattr(f, "Url", None)
                    break
            if not glb_url and files:
                glb_url = getattr(files[0], "Url", None)
            if not glb_url:
                return jsonify({"status": "FAILED", "error": "Tencent finished but returned no GLB URL."})

            r = requests.get(glb_url, timeout=120)
            if not r.ok or not r.content:
                return jsonify({"status": "FAILED", "error": "Could not download the GLB file."})

            return jsonify({
                "status": "COMPLETED",
                "model_base64": base64.b64encode(r.content).decode("ascii"),
            })

        if st == "FAIL":
            return jsonify({
                "status": "FAILED",
                "error": str(getattr(resp, "ErrorMessage", None) or "Generation failed."),
            })

        # WAIT or RUN
        return jsonify({"status": "IN_PROGRESS"})

    except TencentCloudSDKException as exc:
        return jsonify({"error": friendly_tencent_error(exc)}), 502
    except Exception as exc:
        app.logger.exception("status failed")
        return jsonify({"error": f"Server error: {exc}"}), 500


@app.route("/convert", methods=["POST", "OPTIONS"])
def convert():
    """Convert a finished model to FBX / OBJ / STL / USDZ (Tencent Convert3DFormat, 5 credits)."""
    if request.method == "OPTIONS":
        return ("", 204)
    if not origin_ok():
        return jsonify({"error": "Forbidden."}), 403
    if conversion_limited():
        return jsonify({"error": "Too many conversions. Please try again later."}), 429
    if not SECRET_ID or not SECRET_KEY:
        return jsonify({"error": "TENCENT_SECRET_ID / TENCENT_SECRET_KEY are not set on Render."}), 500

    data = request.get_json(silent=True) or {}
    job_id = data.get("job_id")
    fmt = str(data.get("format", "")).upper()

    if fmt not in CONVERT_FORMATS:
        return jsonify({"error": "Unsupported format."}), 400
    if not isinstance(job_id, str) or not job_id.strip() or len(job_id) > 100:
        return jsonify({"error": "Missing job id."}), 400

    record_conversion()  # only valid requests use up the visitor's hourly allowance

    try:
        client = hy_client()

        q = models.QueryHunyuanTo3DProJobRequest()
        q.from_json_string(json.dumps({"JobId": job_id.strip()}))
        job = client.QueryHunyuanTo3DProJob(q)
        if str(job.Status or "").upper() != "DONE":
            return jsonify({"error": "This model is not ready or is no longer available."}), 409

        files = job.ResultFile3Ds or []
        glb_url = None
        for f in files:
            if str(getattr(f, "Type", "")).upper() == "GLB":
                glb_url = getattr(f, "Url", None)
                break
        if not glb_url and files:
            glb_url = getattr(files[0], "Url", None)
        if not glb_url:
            return jsonify({"error": "The original model file is no longer available."}), 410

        c = models.Convert3DFormatRequest()
        c.from_json_string(json.dumps({"File3D": glb_url, "Format": fmt}))
        out = client.Convert3DFormat(c)
        result_url = out.ResultFile3D
        if not result_url:
            return jsonify({"error": f"Tencent returned no file for {fmt}."}), 502

        r = requests.get(result_url, timeout=180)
        if not r.ok or not r.content:
            return jsonify({"error": "Could not download the converted file."}), 502

        return jsonify({
            "format": fmt,
            "filename": "cameo3d-model." + fmt.lower(),
            "file_base64": base64.b64encode(r.content).decode("ascii"),
        })

    except TencentCloudSDKException as exc:
        return jsonify({"error": friendly_tencent_error(exc)}), 502
    except Exception as exc:
        app.logger.exception("convert failed")
        return jsonify({"error": f"Server error: {exc}"}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
