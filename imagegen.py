# START: CAMEO3D AI IMAGE GENERATOR BACKEND (imagegen.py) - put this file NEXT TO app.py
"""
Cameo3D - AI image generator (Google Gemini "Nano Banana"). Works next to app.py, rig.py and tools.py.

Routes:
    GET  /image/options     public: styles, aspect ratios, sizes, poses, prices (for the website page)
    POST /image/generate    logged-in users: makes 1-4 images, takes credits, refunds failed images

The server adds a hidden prompt to every request (clean plain background, one object, centered),
so the 3D generator always receives a good input image. Edit the text in the "HIDDEN PROMPT" part.

Render environment variables:
    GEMINI_API_KEY        (required, unless test mode)  your key from Google AI Studio
    GEMINI_IMAGE_MODEL    model name (default gemini-2.5-flash-image). Change it here to use another model.
    IMAGE_TEST_MODE       set to 1 = NO call to Google, returns sample pictures (free, for testing the page)
    IMAGE_COST            credits per image at 1K   (default 9)
    IMAGE_COST_2K         credits per image at 2K   (default 14)
    IMAGE_COST_4K         credits per image at 4K   (default 25)
    IMAGE_MAX_PER_HOUR    images per visitor IP per hour (default 24)
    IMAGE_PRIVATE_EXTRA   extra credits per image when the user chooses Private (default 0 = free)

Nothing new in requirements.txt (uses requests, already there).
"""

import os
import io
import time
import zlib
import base64
import struct
import concurrent.futures

import requests
from flask import request, jsonify


def _int_env(name, default):
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


# ---------------------------------------------------------------
# WHAT THE WEBSITE PAGE CAN CHOOSE (edit here to add/remove choices)
# ---------------------------------------------------------------
ASPECTS = ["1:1", "16:9", "9:16", "4:3", "3:4"]
SIZES = ["1K", "2K", "4K"]
POSES = {"none": "", "a-pose": "standing in an A-pose, arms relaxed and angled down", "t-pose": "standing in a T-pose, arms stretched straight out to the sides, legs slightly apart"}
MAX_IMAGES = 4
MAX_REFS = 5
MAX_PROMPT = 800
MAX_REF_BYTES = 6 * 1024 * 1024

STYLES = {   # label shown on the page -> style words added to the prompt
    "default":   "",
    "realistic": "photorealistic, detailed materials",
    "cartoon":   "stylized cartoon look, bold clean shapes, bright colors",
    "anime":     "anime style, clean line art, cel shading",
    "lowpoly":   "low-poly game asset look, simple faceted shapes",
    "clay":      "soft clay figurine look, matte material",
    "toy":       "cute vinyl toy figurine look, glossy plastic",
    "handpaint": "hand-painted game texture look, stylized fantasy",
}

# ---------------------------------------------------------------
# HIDDEN PROMPT (added to every request, the user never sees it)
# ---------------------------------------------------------------
BASE_RULES = (
    "Single object only, centered in the frame, the whole object fully visible and not cropped, "
    "clear 3/4 front view, plain solid light-gray background, soft even studio lighting, "
    "no floor shadow, no text, no watermark, no frame, no other objects, clean sharp edges, "
    "reference image for 3D modeling."
)
MULTIVIEW_RULES = (
    "Character turnaround sheet: the same object shown from the front, the side and the back, side by side, "
    "same scale, plain solid light-gray background."
)

_hits = {}


class ImgError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


def _png(color):
    """A small plain PNG made without any library. Used by free test mode."""
    w = h = 384
    raw = b"".join(b"\x00" + bytes(color) * w for _ in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def register_imagegen(app, cursor, spend, refund, current_user, origin_ok, on_done=None):
    """Adds the image routes to the existing Flask app."""

    def costs():
        return {"1K": _int_env("IMAGE_COST", 9), "2K": _int_env("IMAGE_COST_2K", 14), "4K": _int_env("IMAGE_COST_4K", 25)}

    def client_ip():
        return (request.headers.get("X-Forwarded-For") or request.remote_addr or "?").split(",")[0].strip()

    def over_limit(n):
        ip, now = client_ip(), time.time()
        hits = [t for t in _hits.get(ip, []) if now - t < 3600]
        _hits[ip] = hits
        return len(hits) + n > _int_env("IMAGE_MAX_PER_HOUR", 24)

    def read_ref(value, i):
        if not isinstance(value, str) or not value.strip():
            raise ImgError(f"Reference image {i}: no data.")
        value = value.strip()
        if value.lower().startswith("data:") and "," in value:
            value = value.split(",", 1)[1]
        try:
            raw = base64.b64decode(value, validate=True)
        except Exception:
            raise ImgError(f"Reference image {i}: invalid data.")
        if len(raw) > MAX_REF_BYTES:
            raise ImgError(f"Reference image {i} is larger than 6 MB.")
        if raw[:8] == b"\x89PNG\r\n\x1a\n":
            mime = "image/png"
        elif raw[:3] == b"\xff\xd8\xff":
            mime = "image/jpeg"
        elif raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
            mime = "image/webp"
        else:
            raise ImgError(f"Reference image {i} must be PNG, JPG or WebP.")
        return {"inline_data": {"mime_type": mime, "data": value}}

    def build_text(prompt, style, pose, multiview, has_refs):
        """User text + hidden rules = the real prompt sent to Google."""
        parts = [prompt]
        if STYLES.get(style):
            parts.append(STYLES[style] + ".")
        if POSES.get(pose):
            parts.append("The character is " + POSES[pose] + ".")
        parts.append(MULTIVIEW_RULES if multiview else BASE_RULES)
        if has_refs:
            parts.append("Use the attached reference image(s) for the look of the subject.")
        return " ".join(parts)

    def call_gemini(parts, aspect, size):
        key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not key:
            raise ImgError("The image service is not set up yet.")
        model = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image").strip()
        cfg = {"aspectRatio": aspect}
        if "2.5" not in model:                 # the first Nano Banana has no size option
            cfg["imageSize"] = size
        body = {"contents": [{"parts": parts}],
                "generationConfig": {"responseModalities": ["TEXT", "IMAGE"], "imageConfig": cfg}}
        try:
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": key, "Content-Type": "application/json"}, json=body, timeout=100)
        except requests.RequestException:
            raise ImgError("The image service did not answer. Please try again.")
        if r.status_code != 200:
            app.logger.error("Gemini error %s: %s", r.status_code, r.text[:600])
            low = r.text.lower()
            if r.status_code == 429 or "quota" in low or "rate" in low:
                raise ImgError("The image service is busy right now. Please try again in a minute.")
            if r.status_code in (400, 403, 404):
                raise ImgError("The image service is temporarily unavailable. Please try again later.")
            raise ImgError("The image service had a problem. Please try again.")
        try:
            data = r.json()
            for cand in data.get("candidates", []):
                for part in (cand.get("content") or {}).get("parts", []):
                    inl = part.get("inlineData") or part.get("inline_data")
                    if inl and inl.get("data"):
                        return inl["data"], inl.get("mimeType") or inl.get("mime_type") or "image/png"
        except Exception:
            app.logger.exception("Gemini answer could not be read")
        app.logger.error("Gemini returned no image: %s", r.text[:600])
        raise ImgError("This description was rejected by the content check. Please try different words.")

    # ---------------- routes ----------------
    @app.get("/image/options")
    def image_options():
        return jsonify({
            "styles": list(STYLES.keys()), "aspects": ASPECTS, "sizes": SIZES, "poses": list(POSES.keys()),
            "max_images": MAX_IMAGES, "max_refs": MAX_REFS, "max_prompt": MAX_PROMPT,
            "costs": costs(), "private_extra": _int_env("IMAGE_PRIVATE_EXTRA", 0),
            "test_mode": os.environ.get("IMAGE_TEST_MODE") == "1",
        })

    @app.route("/image/generate", methods=["POST", "OPTIONS"])
    def image_generate():
        if request.method == "OPTIONS":
            return ("", 204)
        if not origin_ok():
            return jsonify({"error": "Forbidden."}), 403
        uid = current_user()
        if not uid:
            return jsonify({"error": "Please log in to create images."}), 401

        d = request.get_json(silent=True) or {}
        prompt = d.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            return jsonify({"error": "Please describe the image you want."}), 400
        prompt = prompt.strip()
        if len(prompt) > MAX_PROMPT:
            return jsonify({"error": f"Description is too long (max {MAX_PROMPT} characters)."}), 400

        style = d.get("style") if d.get("style") in STYLES else "default"
        pose = d.get("pose") if d.get("pose") in POSES else "none"
        aspect = d.get("aspect") if d.get("aspect") in ASPECTS else "1:1"
        size = d.get("size") if d.get("size") in SIZES else "1K"
        multiview = d.get("multiview") is True
        want_private = d.get("visibility") == "private"
        try:
            count = max(1, min(MAX_IMAGES, int(d.get("count") or 1)))
        except (TypeError, ValueError):
            count = 1

        try:
            refs_in = d.get("references") or []
            if not isinstance(refs_in, list) or len(refs_in) > MAX_REFS:
                raise ImgError(f"You can add up to {MAX_REFS} reference images.")
            refs = [read_ref(v, i + 1) for i, v in enumerate(refs_in)]
        except ImgError as exc:
            return jsonify({"error": exc.message}), 400

        if over_limit(count):
            return jsonify({"error": "Too many images this hour. Please try again later."}), 429

        each = costs()[size] + (_int_env("IMAGE_PRIVATE_EXTRA", 0) if want_private else 0)
        total = each * count
        if total > 0 and not spend(uid, total, f"image x{count} {size}"):
            return jsonify({"error": f"Not enough credits. This needs {total} credits."}), 402
        _hits.setdefault(client_ip(), []).extend([time.time()] * count)

        text = build_text(prompt, style, pose, multiview, bool(refs))
        parts = [{"text": text}] + refs
        test = os.environ.get("IMAGE_TEST_MODE") == "1"
        colors = [(90, 120, 200), (200, 120, 90), (110, 190, 120), (190, 160, 90)]

        def one(i):
            if test:
                time.sleep(1)
                return base64.b64encode(_png(colors[i % 4])).decode("ascii"), "image/png"
            return call_gemini(parts, aspect, size)

        images, errors = [], []
        with concurrent.futures.ThreadPoolExecutor(max_workers=count) as pool:
            for f in [pool.submit(one, i) for i in range(count)]:
                try:
                    b, mime = f.result()
                    images.append({"image_base64": b, "mime": mime})
                except ImgError as exc:
                    errors.append(exc.message)
                except Exception:
                    app.logger.exception("image job failed")
                    errors.append("Something went wrong. Please try again.")

        meta = []
        if on_done and images:
            try:
                meta = on_done(uid, prompt, style, aspect, size, images, want_private, bool(refs))
            except Exception:
                app.logger.exception("saving to the gallery failed")
        for i, im in enumerate(images):
            m = meta[i] if len(meta) > i else {}
            im["id"] = m.get("id")
            im["visibility"] = m.get("visibility") or ("private" if want_private else "public")

        failed = count - len(images)
        if failed and total > 0:
            refund(uid, each * failed, f"refund: {failed} image(s) failed")
        if not images:
            return jsonify({"error": errors[0] if errors else "No image was made. Your credits were returned."}), 502
        return jsonify({"images": images, "failed": failed, "charged": each * len(images)})

# END: CAMEO3D AI IMAGE GENERATOR BACKEND (imagegen.py)
