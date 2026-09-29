"""
Cameo3D - Image-to-3D API (Flask, deploy on Render)

Backend:
- Accepts a base64 image from the Cameo3D Odoo website
- Submits it to Tencent HY 3D Global (Hunyuan 3D 3.1, international)
- Polls until the GLB is ready, then returns it as base64

Render environment variables required:
    TENCENT_SECRET_ID
    TENCENT_SECRET_KEY
"""

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
# PROTECTION AGAINST MISUSE (protects your Tencent credits)
# ---------------------------------------------------------------
MAX_JOBS_PER_HOUR = 10                                # per visitor IP
app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024   # reject uploads > ~12 MB

_hits = {}


def origin_ok():
    """Only requests coming from your Odoo website are accepted."""
    return request.headers.get("Origin", "") in ALLOWED_ORIGINS


def too_many_jobs():
    ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "?").split(",")[0].strip()
    now = time.time()
    hits = [t for t in _hits.get(ip, []) if now - t < 3600]
    if len(hits) >= MAX_JOBS_PER_HOUR:
        _hits[ip] = hits
        return True
    hits.append(now)
    _hits[ip] = hits
    return False


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
    if too_many_jobs():
        return jsonify({"error": "Too many requests. Please try again later."}), 429
    if not SECRET_ID or not SECRET_KEY:
        return jsonify({"error": "TENCENT_SECRET_ID / TENCENT_SECRET_KEY are not set on Render."}), 500

    data = request.get_json(silent=True) or {}
    image_b64 = data.get("image_base64")
    if not image_b64:
        return jsonify({"error": "No image was provided."}), 400

    # Remove a possible data-URL prefix.
    if "," in image_b64 and image_b64.lstrip().lower().startswith("data:"):
        image_b64 = image_b64.split(",", 1)[1]

    try:
        raw_size = len(base64.b64decode(image_b64, validate=True))
    except Exception:
        return jsonify({"error": "Invalid base64 image data."}), 400

    if raw_size > 6 * 1024 * 1024:
        return jsonify({"error": "Image is larger than 6 MB. Please choose a smaller image."}), 400

    try:
        req = models.SubmitHunyuanTo3DProJobRequest()
        req.from_json_string(json.dumps({
            "Model": HY_MODEL_VERSION,
            "ImageBase64": image_b64,
            "EnablePBR": True,
        }))
        resp = hy_client().SubmitHunyuanTo3DProJob(req)
        return jsonify({"job_id": resp.JobId})
    except TencentCloudSDKException as exc:
        return jsonify({"error": f"Tencent error: {exc}"}), 502
    except Exception as exc:
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
        return jsonify({"error": f"Tencent error: {exc}"}), 502
    except Exception as exc:
        return jsonify({"error": f"Server error: {exc}"}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
