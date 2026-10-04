"""
Cameo3D - Image / Text / Multi-view to 3D API  +  Credits system  (Flask, deploy on Render)

What this file does:
- Everything your old app.py did (Tencent HY 3D: /submit, /status, /convert)
- Accounts:        /register  /login  /me
- Model library:   /library  /library/<id>  /library/<id>/download  (full file is locked)
- Credits:         one balance per user, spent on generations, conversions and paid downloads
- Admin:           /admin/grant  (give test credits by hand, before billing exists)
- Billing (later): /checkout/<variant>  and  /webhook/payment  (Lemon Squeezy, switched off until configured)

Render environment variables:
    TENCENT_SECRET_ID          (already set)
    TENCENT_SECRET_KEY         (already set)
    DATABASE_URL               Supabase "Session pooler" connection string
    SUPABASE_URL               https://zpnokntlfjjayzttjuzv.supabase.co
    SUPABASE_SERVICE_KEY       Supabase secret key
    JWT_SECRET                 any long random text
    ADMIN_KEY                  any other long random text

Optional environment variables:
    GEN_COST                   credits per generation   (default 0 = free, login not required)
    CONVERT_COST               credits per conversion   (default 0 = free, login not required)
    LS_WEBHOOK_SECRET          Lemon Squeezy signing secret (only when billing is turned on)

Render start command:  gunicorn app:app --timeout 120

requirements.txt must contain:
    flask, gunicorn, requests, tencentcloud-sdk-python,
    psycopg2-binary, PyJWT, supabase      (and optionally Pillow)
"""

import io
import os
import json
import time
import base64
import hmac
import hashlib
import secrets
import datetime
from contextlib import contextmanager

import jwt
import psycopg2
import psycopg2.errors
import requests
from flask import Flask, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

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


@app.before_request
def handle_preflight():
    # Browsers send an OPTIONS request first when a page sends a login header.
    if request.method == "OPTIONS":
        return ("", 204)


@app.after_request
def add_cors_headers(response):
    origin = request.headers.get("Origin")
    if origin in ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Admin-Key"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


# ---------------------------------------------------------------
# LIMITS (protect your Tencent credits)
# ---------------------------------------------------------------
MAX_JOBS_PER_HOUR = 10                                # per visitor IP
MAX_CONVERSIONS_PER_HOUR = 20                         # per visitor IP (each conversion costs 5 Tencent credits)
MAX_AUTH_PER_HOUR = 30                                # login / register attempts per visitor IP
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
_auth_hits = {}


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


def auth_limited():
    """Counts every login / register attempt and blocks guessing."""
    ip = client_ip()
    now = time.time()
    hits = [t for t in _auth_hits.get(ip, []) if now - t < 3600]
    hits.append(now)
    _auth_hits[ip] = hits
    return len(hits) > MAX_AUTH_PER_HOUR


# ---------------------------------------------------------------
# CREDITS: DATABASE + ACCOUNTS
# ---------------------------------------------------------------
def _int_env(name, default):
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


GEN_COST = _int_env("GEN_COST", 0)          # credits per generation (0 = free)
CONVERT_COST = _int_env("CONVERT_COST", 0)  # credits per conversion (0 = free)
SIGNUP_CREDITS = _int_env("SIGNUP_CREDITS", 100)  # free credits for every new account
ODOO_URL = os.environ.get("ODOO_URL", "https://cameo3d.odoo.com").rstrip("/")
GEN_COST_PBR = _int_env("GEN_COST_PBR", 0)      # extra credits when PBR textures are switched on
GEN_COST_FACES = _int_env("GEN_COST_FACES", 0)  # extra credits when a custom polygon count is chosen


@contextmanager
def cursor():
    """Open a database cursor. Saves on success, undoes everything on error, always closes."""
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        with conn:
            with conn.cursor() as cur:
                yield cur
    finally:
        conn.close()


def add_credits(cur, uid, amount, reason):
    cur.execute("update users set credits = credits + %s where id=%s", (amount, uid))
    cur.execute("insert into credit_ledger(user_id,amount,reason) values(%s,%s,%s)", (uid, amount, reason))


def spend_credits(cur, uid, cost, reason):
    """Takes credits only if the user has enough. One statement, so no double spending."""
    cur.execute("update users set credits = credits - %s where id=%s and credits >= %s", (cost, uid, cost))
    if cur.rowcount == 0:
        return False
    cur.execute("insert into credit_ledger(user_id,amount,reason) values(%s,%s,%s)", (uid, -cost, reason))
    return True


def spend(uid, cost, reason):
    with cursor() as cur:
        return spend_credits(cur, uid, cost, reason)


def refund(uid, cost, reason):
    try:
        with cursor() as cur:
            add_credits(cur, uid, cost, reason)
    except Exception:
        app.logger.exception("refund failed uid=%s cost=%s", uid, cost)


def refund_job(job_id):
    """Give the credits back once if a generation failed on Tencent's side."""
    try:
        with cursor() as cur:
            cur.execute("select user_id,cost,refunded from jobs where job_id=%s for update", (job_id,))
            row = cur.fetchone()
            if row and not row[2]:
                add_credits(cur, row[0], row[1], f"refund failed job {job_id}")
                cur.execute("update jobs set refunded=true where job_id=%s", (job_id,))
    except Exception:
        app.logger.exception("refund_job failed job=%s", job_id)


def make_jwt(uid):
    secret = os.environ.get("JWT_SECRET", "")
    if not secret:
        raise RuntimeError("JWT_SECRET is not set on Render.")
    payload = {"uid": uid, "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=30)}
    return jwt.encode(payload, secret, algorithm="HS256")


def current_user():
    """Returns the logged-in user id from the Authorization header, or None."""
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    secret = os.environ.get("JWT_SECRET", "")
    if not secret:
        return None
    try:
        data = jwt.decode(header[7:], secret, algorithms=["HS256"])
        return int(data["uid"])
    except Exception:
        return None


def login_required(f):
    from functools import wraps

    @wraps(f)
    def wrap(*args, **kwargs):
        uid = current_user()
        if not uid:
            return jsonify({"error": "Please log in."}), 401
        request.uid = uid
        return f(*args, **kwargs)

    return wrap


def get_supabase():
    from supabase import create_client
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])


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
# ROUTES: HOME
# ---------------------------------------------------------------
@app.route("/")
def index():
    # Standalone page is off. Visitors use the Odoo website.
    # This reply also lets the Odoo page wake the free server up.
    return "Cameo3D API is running.", 200


# ---------------------------------------------------------------
# ROUTES: ACCOUNTS
# ---------------------------------------------------------------
@app.post("/register")
def register():
    if os.environ.get("ALLOW_LOCAL_LOGIN") != "1":
        return jsonify({"error": "Please sign in on the website."}), 403
    if auth_limited():
        return jsonify({"error": "Too many attempts. Please try again later."}), 429
    d = request.get_json(silent=True) or {}
    email = str(d.get("email", "")).strip().lower()
    password = str(d.get("password", ""))
    if "@" not in email or len(email) > 200:
        return jsonify({"error": "Please enter a valid email."}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters."}), 400
    try:
        with cursor() as cur:
            cur.execute("select 1 from users where email=%s", (email,))
            if cur.fetchone():
                return jsonify({"error": "This email is already used."}), 400
            cur.execute(
                "insert into users(email,password_hash) values(%s,%s) returning id",
                (email, generate_password_hash(password)),
            )
            uid = cur.fetchone()[0]
    except psycopg2.errors.UniqueViolation:
        return jsonify({"error": "This email is already used."}), 400
    return jsonify({"token": make_jwt(uid)})


@app.post("/login")
def login():
    if os.environ.get("ALLOW_LOCAL_LOGIN") != "1":
        return jsonify({"error": "Please sign in on the website."}), 403
    if auth_limited():
        return jsonify({"error": "Too many attempts. Please try again later."}), 429
    d = request.get_json(silent=True) or {}
    email = str(d.get("email", "")).strip().lower()
    password = str(d.get("password", ""))
    with cursor() as cur:
        cur.execute("select id,password_hash from users where email=%s", (email,))
        row = cur.fetchone()
    if not row or not check_password_hash(row[1], password):
        return jsonify({"error": "Wrong email or password."}), 401
    return jsonify({"token": make_jwt(row[0])})


@app.get("/me")
@login_required
def me():
    with cursor() as cur:
        cur.execute("select email,credits from users where id=%s", (request.uid,))
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "Please log in."}), 401
        cur.execute("select model_id from downloads where user_id=%s", (request.uid,))
        owned = [r[0] for r in cur.fetchall()]
    return jsonify({"id": request.uid, "email": row[0], "credits": row[1], "owned": owned})

# ---------------------------------------------------------------
# ROUTES: SIGN IN WITH YOUR ODOO WEBSITE ACCOUNT (no second login)
# The page sends the visitor's Odoo session id. We ask Odoo if it is a real
# signed-in user, then give back a credits token for that same person.
# ---------------------------------------------------------------
def verify_odoo_session(sid):
    """Returns the Odoo login of the signed-in visitor, or None."""
    if not sid or not isinstance(sid, str) or len(sid) > 200:
        return None
    try:
        r = requests.post(
            ODOO_URL + "/web/session/get_session_info",
            json={"jsonrpc": "2.0", "method": "call", "params": {}},
            cookies={"session_id": sid},
            timeout=15,
        )
        info = (r.json() or {}).get("result") or {}
    except Exception:
        app.logger.exception("odoo session check failed")
        return None
    login = str(info.get("username") or "").strip().lower()
    if not info.get("uid") or info.get("is_website_user") or not login or login == "public":
        return None
    return login


def get_or_create_user(login):
    """Finds the credits account for this Odoo user, or creates it with the signup bonus."""
    for _ in range(2):
        try:
            with cursor() as cur:
                cur.execute("select id from users where email=%s", (login,))
                row = cur.fetchone()
                if row:
                    return row[0]
                cur.execute(
                    "insert into users(email,password_hash) values(%s,%s) returning id",
                    (login, generate_password_hash(secrets.token_hex(24))),
                )
                uid = cur.fetchone()[0]
                if SIGNUP_CREDITS > 0:
                    add_credits(cur, uid, SIGNUP_CREDITS, "signup bonus")
                return uid
        except psycopg2.errors.UniqueViolation:
            continue
    return None


@app.post("/auth/odoo")
def auth_odoo():
    d = request.get_json(silent=True) or {}
    login = verify_odoo_session(d.get("sid"))
    if not login:
        return jsonify({"error": "Please sign in to your Cameo3D account."}), 401
    uid = get_or_create_user(login)
    if not uid:
        return jsonify({"error": "Could not open your account. Please try again."}), 500
    return jsonify({"token": make_jwt(uid)})



# ---------------------------------------------------------------
# ROUTES: MODEL LIBRARY (preview is public, full file is locked)
# ---------------------------------------------------------------
@app.get("/library")
def library():
    with cursor() as cur:
        cur.execute("select id,title,preview_url,price_credits,category from models order by id desc")
        rows = cur.fetchall()
    return jsonify([{"id": r[0], "title": r[1], "preview": r[2], "price": r[3], "category": r[4]} for r in rows])


@app.get("/library/<int:mid>")
def library_one(mid):
    with cursor() as cur:
        cur.execute("select id,title,preview_url,price_credits,category,description from models where id=%s", (mid,))
        r = cur.fetchone()
    if not r:
        return jsonify({"error": "Model not found."}), 404
    return jsonify({"id": r[0], "title": r[1], "preview": r[2], "price": r[3], "category": r[4], "description": r[5]})


@app.post("/library/<int:mid>/download")
@login_required
def library_download(mid):
    with cursor() as cur:
        cur.execute("select file_path,price_credits from models where id=%s", (mid,))
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "Model not found."}), 404
        path, price = row
        # Every download is charged again: there is no "owned forever" access.
        if price > 0 and not spend_credits(cur, request.uid, price, f"download model {mid}"):
            return jsonify({"error": "Not enough credits."}), 402
        cur.execute(
            "insert into downloads(user_id,model_id) values(%s,%s) on conflict do nothing",
            (request.uid, mid),
        )
    # If the link cannot be made, the credits are given back below.
    try:
        res = get_supabase().storage.from_("models").create_signed_url(path, 60)
        url = res.get("signedURL") or res.get("signedUrl")
    except Exception:
        app.logger.exception("signed url failed model=%s", mid)
        url = None
    if not url:
        if price > 0:
            refund(request.uid, price, f"refund: download link failed model {mid}")
        return jsonify({"error": "Could not create the download link. Your credits were returned. Please try again."}), 502
    return jsonify({"url": url})


# ---------------------------------------------------------------
# ROUTES: ADMIN (give test credits by hand)
# ---------------------------------------------------------------
@app.post("/admin/grant")
def admin_grant():
    admin_key = os.environ.get("ADMIN_KEY", "")
    if not admin_key or not hmac.compare_digest(request.headers.get("X-Admin-Key", ""), admin_key):
        return jsonify({"error": "Forbidden."}), 403
    d = request.get_json(silent=True) or {}
    email = str(d.get("email", "")).strip().lower()
    try:
        amount = int(d.get("amount"))
    except (TypeError, ValueError):
        return jsonify({"error": "amount must be a number."}), 400
    with cursor() as cur:
        cur.execute("select id from users where email=%s", (email,))
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "User not found."}), 404
        add_credits(cur, row[0], amount, "manual grant")
    return jsonify({"ok": True})


# ---------------------------------------------------------------
# ROUTES: 3D GENERATION  (costs GEN_COST credits when GEN_COST > 0)
# ---------------------------------------------------------------
def generation_cost(payload):
    """Credits for one generation: base price plus the extras the user switched on."""
    cost = GEN_COST
    if payload.get("EnablePBR"):
        cost += GEN_COST_PBR
    if payload.get("FaceCount"):
        cost += GEN_COST_FACES
    return cost


@app.get("/costs")
def costs():
    """Public price list, so the workspace page can show the cost before the user clicks."""
    return jsonify({"generate": GEN_COST, "pbr": GEN_COST_PBR, "faces": GEN_COST_FACES, "convert": CONVERT_COST})


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

    uid = None
    if GEN_COST > 0:
        uid = current_user()
        if not uid:
            return jsonify({"error": "Please log in to generate a model."}), 401

    data = request.get_json(silent=True) or {}
    try:
        payload = build_payload(data)
    except BadInput as exc:
        return jsonify({"error": str(exc)}), 400

    cost = generation_cost(payload)

    # Charge only after the request is valid, so mistakes never cost credits.
    if uid:
        if not spend(uid, cost, "generation"):
            return jsonify({"error": "Not enough credits."}), 402

    record_job()  # only valid requests use up the visitor's hourly allowance

    try:
        req = models.SubmitHunyuanTo3DProJobRequest()
        req.from_json_string(json.dumps(payload))
        resp = hy_client().SubmitHunyuanTo3DProJob(req)
        if uid:
            try:
                with cursor() as cur:
                    cur.execute(
                        "insert into jobs(job_id,user_id,cost) values(%s,%s,%s) on conflict do nothing",
                        (resp.JobId, uid, cost),
                    )
            except Exception:
                app.logger.exception("could not record job %s", resp.JobId)
        return jsonify({"job_id": resp.JobId})
    except TencentCloudSDKException as exc:
        if uid:
            refund(uid, cost, "refund: generation could not start")
        return jsonify({"error": friendly_tencent_error(exc)}), 502
    except Exception as exc:
        if uid:
            refund(uid, cost, "refund: generation could not start")
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
                if GEN_COST > 0:
                    refund_job(job_id)
                return jsonify({"status": "FAILED", "error": "Tencent finished but returned no GLB URL."})

            r = requests.get(glb_url, timeout=120)
            if not r.ok or not r.content:
                return jsonify({"status": "FAILED", "error": "Could not download the GLB file."})

            return jsonify({
                "status": "COMPLETED",
                "model_base64": base64.b64encode(r.content).decode("ascii"),
            })

        if st == "FAIL":
            if GEN_COST > 0:
                refund_job(job_id)  # credits go back once, automatically
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


# ---------------------------------------------------------------
# ROUTES: FORMAT CONVERSION  (costs CONVERT_COST credits when CONVERT_COST > 0)
# ---------------------------------------------------------------
class ConvertError(Exception):
    def __init__(self, message, code):
        super().__init__(message)
        self.message = message
        self.code = code


def run_conversion(job_id, fmt):
    """Convert a finished model. Returns the JSON result or raises ConvertError."""
    client = hy_client()

    q = models.QueryHunyuanTo3DProJobRequest()
    q.from_json_string(json.dumps({"JobId": job_id}))
    job = client.QueryHunyuanTo3DProJob(q)
    if str(job.Status or "").upper() != "DONE":
        raise ConvertError("This model is not ready or is no longer available.", 409)

    files = job.ResultFile3Ds or []
    glb_url = None
    for f in files:
        if str(getattr(f, "Type", "")).upper() == "GLB":
            glb_url = getattr(f, "Url", None)
            break
    if not glb_url and files:
        glb_url = getattr(files[0], "Url", None)
    if not glb_url:
        raise ConvertError("The original model file is no longer available.", 410)

    c = models.Convert3DFormatRequest()
    c.from_json_string(json.dumps({"File3D": glb_url, "Format": fmt}))
    out = client.Convert3DFormat(c)
    result_url = out.ResultFile3D
    if not result_url:
        raise ConvertError(f"Tencent returned no file for {fmt}.", 502)

    r = requests.get(result_url, timeout=180)
    if not r.ok or not r.content:
        raise ConvertError("Could not download the converted file.", 502)

    return {
        "format": fmt,
        "filename": "cameo3d-model." + fmt.lower(),
        "file_base64": base64.b64encode(r.content).decode("ascii"),
    }


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
    job_id = job_id.strip()

    uid = None
    if CONVERT_COST > 0:
        uid = current_user()
        if not uid:
            return jsonify({"error": "Please log in to download this format."}), 401
        if not spend(uid, CONVERT_COST, f"convert {fmt}"):
            return jsonify({"error": "Not enough credits."}), 402

    record_conversion()  # only valid requests use up the visitor's hourly allowance

    try:
        return jsonify(run_conversion(job_id, fmt))
    except ConvertError as exc:
        if uid:
            refund(uid, CONVERT_COST, f"refund: convert {fmt} failed")
        return jsonify({"error": exc.message}), exc.code
    except TencentCloudSDKException as exc:
        if uid:
            refund(uid, CONVERT_COST, f"refund: convert {fmt} failed")
        return jsonify({"error": friendly_tencent_error(exc)}), 502
    except Exception as exc:
        if uid:
            refund(uid, CONVERT_COST, f"refund: convert {fmt} failed")
        app.logger.exception("convert failed")
        return jsonify({"error": f"Server error: {exc}"}), 500


# ---------------------------------------------------------------
# BILLING (LATER): Lemon Squeezy buys credits automatically.
# Switched off until LS_WEBHOOK_SECRET is set on Render.
# Fill in PACKS and CHECKOUT_LINKS with your real Lemon Squeezy values.
# ---------------------------------------------------------------
PACKS = {
    # "variant id from Lemon Squeezy": credits given
    "111111": 100,
    "222222": 300,
}
CHECKOUT_LINKS = {
    "111111": "https://YOURSTORE.lemonsqueezy.com/buy/AAAA",
    "222222": "https://YOURSTORE.lemonsqueezy.com/buy/BBBB",
}


@app.get("/checkout/<variant>")
@login_required
def checkout(variant):
    base = CHECKOUT_LINKS.get(variant)
    if not base or "YOURSTORE" in base:
        return jsonify({"error": "This pack is not available yet."}), 404
    return jsonify({"url": f"{base}?checkout[custom][user_id]={request.uid}"})


@app.post("/webhook/payment")
def payment_webhook():
    secret = os.environ.get("LS_WEBHOOK_SECRET", "")
    if not secret:
        return "billing not enabled", 503

    raw = request.get_data()
    sent = request.headers.get("X-Signature", "")
    good = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sent, good):
        return "bad signature", 401

    d = request.get_json(silent=True) or {}
    try:
        if d["meta"]["event_name"] != "order_created":
            return "ignored", 200
        attrs = d["data"]["attributes"]
        if attrs.get("status") != "paid":
            return "not paid", 200
        order_id = str(d["data"]["id"])
        uid = int(d["meta"]["custom_data"]["user_id"])
        variant = str(attrs["first_order_item"]["variant_id"])
    except (KeyError, TypeError, ValueError):
        return "bad payload", 400

    credits = PACKS.get(variant)
    if not credits:
        return "unknown pack", 200

    with cursor() as cur:
        cur.execute("select 1 from processed_orders where order_id=%s", (order_id,))
        if cur.fetchone():
            return "already done", 200  # the gateway retried: never add credits twice
        cur.execute("insert into processed_orders(order_id) values(%s)", (order_id,))
        add_credits(cur, uid, credits, f"purchase order {order_id}")
    return "ok", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
