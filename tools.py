# START: CAMEO3D PRO TOOLS BACKEND (tools.py) - put this file NEXT TO app.py and rig.py
"""
Cameo3D - Pro tools (every extra Tencent Hunyuan 3D feature). Works next to app.py and rig.py.

What it adds (all use your credits system, refund automatically if Tencent fails):
    POST /tool/submit                      tool = topology | uv | retexture | parts | rapid
    GET  /tool/status/<tool>/<job_id>      poll until COMPLETED -> returns the result as GLB (base64)
    GET  /tool/costs                       public price list (for the website buttons)
    GET  /toolstest                        TEMPORARY admin test page (delete after testing)

Source model for topology / uv / retexture / parts:
    {"kind": "gen",  "ref": <job_id of a finished generation>}
    {"kind": "tool", "ref": <job_id of an earlier tool result>}     <- lets users chain tools
    {"kind": "url",  "ref": "https://...glb"}                        <- admin test page only

Render environment variables (all optional, number of credits charged to the USER):
    TOOL_COST_TOPOLOGY (20)   TOOL_COST_UV (10)   TOOL_COST_RETEXTURE (20)
    TOOL_COST_PARTS (25)      TOOL_COST_RAPID (10)

IMPORTANT: Tencent's own price per call differs per tool. Check your Tencent billing page once and
set these numbers so you keep a margin.
"""

import os
import re
import base64
import hmac
import time

import requests
from flask import request, jsonify, Response
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException


def _int_env(name, default):
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


# ---------------------------------------------------------------
# THE TOOL LIST. One line per Tencent feature. Add/remove tools here.
# ---------------------------------------------------------------
TOOLS = {
    "topology":  {"submit": "Submit3DSmartTopologyJob",       "query": "Describe3DSmartTopologyJob",    "field": "File3D", "cost": _int_env("TOOL_COST_TOPOLOGY", 20)},
    "uv":        {"submit": "SubmitHunyuanTo3DUVJob",         "query": "DescribeHunyuanTo3DUVJob",      "field": "File",   "cost": _int_env("TOOL_COST_UV", 10)},
    "retexture": {"submit": "SubmitHunyuanTo3DTextureEditJob", "query": "QueryHunyuanTo3DTextureEditJob", "field": "File3D", "cost": _int_env("TOOL_COST_RETEXTURE", 20)},
    "parts":     {"submit": "SubmitHunyuan3DPartJob",         "query": "QueryHunyuan3DPartJob",         "field": "File3D", "cost": _int_env("TOOL_COST_PARTS", 25)},
    "rapid":     {"submit": "SubmitHunyuanTo3DRapidJob",      "query": "QueryHunyuanTo3DRapidJob",      "field": None,     "cost": _int_env("TOOL_COST_RAPID", 10)},
}

MAX_TOOLS_PER_HOUR = 20      # per visitor IP
MAX_IMAGE_BYTES = 6 * 1024 * 1024
_hits = {}
_WORD = re.compile(r"^[A-Za-z_]{1,24}$")


class ToolError(Exception):
    def __init__(self, message, code=400):
        super().__init__(message)
        self.message = message
        self.code = code


def register_tools(app, cursor, spend, refund, refund_job, current_user, origin_ok,
                   hy_call, pick_glb_url, friendly_tencent_error, get_supabase):
    """Adds the tool routes to the existing Flask app."""

    # ---------------- small helpers ----------------
    def client_ip():
        return (request.headers.get("X-Forwarded-For") or request.remote_addr or "?").split(",")[0].strip()

    def limited():
        ip, now = client_ip(), time.time()
        hits = [t for t in _hits.get(ip, []) if now - t < 3600]
        _hits[ip] = hits
        return len(hits) >= MAX_TOOLS_PER_HOUR

    def is_admin():
        key = os.environ.get("ADMIN_KEY", "")
        return bool(key) and hmac.compare_digest(request.headers.get("X-Admin-Key", ""), key)

    def read_b64_image(value, label):
        if not isinstance(value, str) or not value.strip():
            raise ToolError(f"{label}: no image was provided.")
        value = value.strip()
        if value.lower().startswith("data:") and "," in value:
            value = value.split(",", 1)[1]
        try:
            raw = base64.b64decode(value, validate=True)
        except Exception:
            raise ToolError(f"{label}: invalid image data.")
        if len(raw) > MAX_IMAGE_BYTES:
            raise ToolError(f"{label} is larger than 6 MB.")
        ok = raw[:8] == b"\x89PNG\r\n\x1a\n" or raw[:3] == b"\xff\xd8\xff" or (raw[:4] == b"RIFF" and raw[8:12] == b"WEBP")
        if not ok:
            raise ToolError(f"{label} must be a PNG, JPG or WebP image.")
        return value

    def files_of(resp):
        """Collect result files from any response shape Tencent uses. Returns [{'Type','Url'}]."""
        out = []
        for f in (resp.get("ResultFile3Ds") or []):
            if isinstance(f, dict) and f.get("Url"):
                out.append({"Type": str(f.get("Type") or "").upper(), "Url": f["Url"]})
        single = resp.get("ResultFile3D")
        if isinstance(single, str) and single:
            out.append({"Type": "", "Url": single})
        elif isinstance(single, dict) and single.get("Url"):
            out.append({"Type": str(single.get("Type") or "").upper(), "Url": single["Url"]})
        for key in ("ResultUrl", "ResultImage", "ResultImageUrl"):
            if isinstance(resp.get(key), str) and resp.get(key):
                out.append({"Type": "", "Url": resp[key]})
        return out

    def source_url(src, uid, admin):
        """Turns the website's {'kind','ref'} into a link Tencent can download (a GLB)."""
        if not isinstance(src, dict):
            raise ToolError("Missing source model.")
        kind, ref = src.get("kind"), str(src.get("ref") or "").strip()
        if not ref or len(ref) > 600:
            raise ToolError("Missing source model.")
        if kind == "gen":
            job = hy_call("QueryHunyuanTo3DProJob", {"JobId": ref})
            if str(job.get("Status") or "").upper() != "DONE":
                raise ToolError("This model is not ready or is no longer available.", 409)
            url = pick_glb_url(job.get("ResultFile3Ds"))
            if not url:
                raise ToolError("The original model file is no longer available.", 410)
            return url
        if kind == "tool":
            with cursor() as cur:
                if admin:
                    cur.execute("select file_path from jobs where job_id=%s", (ref,))
                else:
                    cur.execute("select file_path from jobs where job_id=%s and user_id=%s", (ref, uid))
                row = cur.fetchone()
            if not row or not row[0]:
                raise ToolError("That earlier result is not available any more.", 404)
            res = get_supabase().storage.from_("generations").create_signed_url(row[0], 3600)
            url = res.get("signedURL") or res.get("signedUrl")
            if not url:
                raise ToolError("Could not open the earlier result.", 502)
            return url
        if kind == "url" and admin and ref.startswith("https://"):
            return ref
        raise ToolError("Unknown source.")

    def build_params(tool, data, src_url):
        """Builds the Tencent request for one tool. Only validated values are sent."""
        opts = data.get("options") or {}
        if not isinstance(opts, dict):
            opts = {}
        spec = TOOLS[tool]

        if tool == "rapid":
            prompt, image = data.get("prompt"), data.get("image_base64")
            p = {}
            if isinstance(prompt, str) and prompt.strip():
                if len(prompt.strip()) > 1000:
                    raise ToolError("Description is too long (max 1000 characters).")
                p["Prompt"] = prompt.strip()
            elif image:
                p["ImageBase64"] = read_b64_image(image, "Image")
            else:
                raise ToolError("Send a text description or an image.")
            if opts.get("pbr") is True:
                p["EnablePBR"] = True
            return p

        f = {"Url": src_url, "Type": "GLB"}
        p = {spec["field"]: f}

        if tool == "topology":
            for key, name in (("polygon_type", "PolygonType"), ("face_level", "FaceLevel")):
                v = opts.get(key)
                if isinstance(v, str) and v and v.lower() != "auto":
                    if not _WORD.match(v):
                        raise ToolError("Invalid option.")
                    p[name] = v
        elif tool == "retexture":
            prompt, image = opts.get("prompt"), opts.get("image_base64")
            has_prompt = isinstance(prompt, str) and prompt.strip()
            if not has_prompt and not image:
                raise ToolError("Describe the new texture or add a reference image.")
            if has_prompt:
                if len(prompt.strip()) > 1000:
                    raise ToolError("Description is too long (max 1000 characters).")
                p["Prompt"] = prompt.strip()
                if opts.get("pbr") is True:
                    p["EnablePBR"] = True          # Tencent: PBR only works together with a prompt
            if image:
                p["Image"] = {"Base64": read_b64_image(image, "Reference image")}
        return p

    def submit_tencent(tool, params):
        """Sends the job. If Tencent dislikes the 'Type' field it retries once without it."""
        spec = TOOLS[tool]
        try:
            return hy_call(spec["submit"], params)
        except TencentCloudSDKException as exc:
            code = ""
            try:
                code = (exc.get_code() or "").lower()
            except Exception:
                pass
            fld = spec["field"]
            if fld and "invalidparameter" in code and isinstance(params.get(fld), dict) and "Type" in params[fld]:
                p2 = dict(params)
                p2[fld] = {"Url": params[fld]["Url"]}
                return hy_call(spec["submit"], p2)
            raise

    def to_glb(files):
        """Returns (glb_bytes, None) or (None, (bytes, filename)) when only another format exists."""
        if not files:
            return None, None
        pick = next((f for f in files if f["Type"] == "GLB"), None) or next((f for f in files if f["Url"].lower().split("?")[0].endswith(".glb")), None)
        if pick:
            r = requests.get(pick["Url"], timeout=180)
            return (r.content, None) if r.ok and r.content else (None, None)
        first = files[0]
        try:
            out = hy_call("Convert3DFormat", {"File3D": first["Url"], "Format": "GLB"})
            url = out.get("ResultFile3D")
            if isinstance(url, str) and url:
                r = requests.get(url, timeout=180)
                if r.ok and r.content:
                    return r.content, None
        except Exception:
            app.logger.warning("convert to GLB failed for %s", first["Url"])
        r = requests.get(first["Url"], timeout=180)
        if r.ok and r.content:
            ext = (first["Type"] or first["Url"].split("?")[0].rsplit(".", 1)[-1] or "bin").lower()
            return None, (r.content, "cameo3d-result." + ext)
        return None, None

    # ---------------- routes ----------------
    @app.get("/tool/costs")
    def tool_costs():
        return jsonify({k: v["cost"] for k, v in TOOLS.items()})

    @app.route("/tool/submit", methods=["POST", "OPTIONS"])
    def tool_submit():
        if request.method == "OPTIONS":
            return ("", 204)
        admin = is_admin()
        uid = None
        if not admin:
            if not origin_ok():
                return jsonify({"error": "Forbidden."}), 403
            uid = current_user()
            if not uid:
                return jsonify({"error": "Please log in to use this tool."}), 401
            if limited():
                return jsonify({"error": "Too many requests. Please try again later."}), 429

        data = request.get_json(silent=True) or {}
        tool = data.get("tool")
        if tool not in TOOLS:
            return jsonify({"error": "Unknown tool."}), 400
        cost = TOOLS[tool]["cost"]

        try:
            src_url = None if tool == "rapid" else source_url(data.get("source"), uid, admin)
            params = build_params(tool, data, src_url)
        except ToolError as exc:
            return jsonify({"error": exc.message}), exc.code
        except TencentCloudSDKException as exc:
            return jsonify({"error": friendly_tencent_error(exc)}), 502
        except Exception as exc:
            app.logger.exception("tool prepare failed")
            return jsonify({"error": f"Server error: {exc}"}), 500

        charged = bool(uid and cost > 0)
        if charged and not spend(uid, cost, f"tool {tool}"):
            return jsonify({"error": f"Not enough credits. This tool needs {cost} credits."}), 402
        _hits.setdefault(client_ip(), []).append(time.time())

        try:
            resp = submit_tencent(tool, params)
            job_id = resp.get("JobId")
            if not job_id:
                raise ToolError("Tencent returned no job id.", 502)
        except ToolError as exc:
            if charged:
                refund(uid, cost, f"refund: {tool} could not start")
            return jsonify({"error": exc.message}), exc.code
        except TencentCloudSDKException as exc:
            if charged:
                refund(uid, cost, f"refund: {tool} could not start")
            return jsonify({"error": friendly_tencent_error(exc)}), 502
        except Exception as exc:
            if charged:
                refund(uid, cost, f"refund: {tool} could not start")
            app.logger.exception("tool submit failed")
            return jsonify({"error": f"Server error: {exc}"}), 500

        if uid:
            try:
                with cursor() as cur:
                    cur.execute("insert into jobs(job_id,user_id,cost) values(%s,%s,%s) on conflict do nothing",
                                (job_id, uid, cost if charged else 0))
            except Exception:
                app.logger.exception("could not record tool job %s", job_id)
        return jsonify({"job_id": job_id, "tool": tool})

    @app.route("/tool/status/<tool>/<job_id>", methods=["GET", "OPTIONS"])
    def tool_status(tool, job_id):
        if request.method == "OPTIONS":
            return ("", 204)
        if tool not in TOOLS:
            return jsonify({"error": "Unknown tool."}), 400
        admin = is_admin()
        uid = None
        if not admin:
            if not origin_ok():
                return jsonify({"error": "Forbidden."}), 403
            uid = current_user()
            if not uid:
                return jsonify({"error": "Please log in."}), 401
            with cursor() as cur:
                cur.execute("select 1 from jobs where job_id=%s and user_id=%s", (job_id, uid))
                if not cur.fetchone():
                    return jsonify({"error": "Job not found."}), 404

        try:
            resp = hy_call(TOOLS[tool]["query"], {"JobId": job_id})
            st = str(resp.get("Status") or "").upper()

            if st == "DONE":
                files = files_of(resp)
                glb, other = to_glb(files)
                if glb is None and other is None:
                    app.logger.error("tool %s finished without a usable file: %s", tool, resp)
                    if uid:
                        refund_job(job_id)
                    out = {"status": "FAILED", "error": "Tencent finished but returned no model file."}
                    if admin:
                        out["raw"] = resp
                    return jsonify(out)
                out = {"status": "COMPLETED"}
                if glb is not None:
                    out["model_base64"] = base64.b64encode(glb).decode("ascii")
                    if uid:      # keep our own copy so the result can be chained into another tool
                        try:
                            path = f"{uid}/tool-{job_id}.glb"
                            get_supabase().storage.from_("generations").upload(
                                path, glb, {"content-type": "model/gltf-binary", "upsert": "true"})
                            with cursor() as cur:
                                cur.execute("update jobs set file_path=%s, status='saved' where job_id=%s", (path, job_id))
                        except Exception:
                            app.logger.exception("save tool result failed job=%s", job_id)
                else:
                    out["filename"] = other[1]
                    out["file_base64"] = base64.b64encode(other[0]).decode("ascii")
                if admin:
                    out["raw"] = resp
                return jsonify(out)

            if st == "FAIL":
                if uid:
                    refund_job(job_id)
                out = {"status": "FAILED", "error": str(resp.get("ErrorMessage") or "The tool failed.")}
                if admin:
                    out["raw"] = resp
                return jsonify(out)

            return jsonify({"status": "IN_PROGRESS"})

        except TencentCloudSDKException as exc:
            return jsonify({"error": friendly_tencent_error(exc)}), 502
        except Exception as exc:
            app.logger.exception("tool status failed")
            return jsonify({"error": f"Server error: {exc}"}), 500

    # ---------------------------------------------------------------
    # TEMPORARY ADMIN TEST PAGE. DELETE this section after testing.
    # Open /toolstest, type your ADMIN_KEY, test every tool. Shows Tencent's raw answer.
    # ---------------------------------------------------------------
    TEST_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Tool test</title></head>
<body style="font-family:sans-serif;max-width:620px;margin:40px auto">
<h2>Pro tools test (admin)</h2>
<p>ADMIN_KEY</p><input id="k" type="password" style="width:100%">
<p>Tool</p><select id="t"><option>topology</option><option>uv</option><option>retexture</option><option>parts</option><option>rapid</option></select>
<p>Source kind</p><select id="sk"><option>gen</option><option>tool</option><option>url</option></select>
<p>Source (job id, or https link to a .glb)</p><input id="sr" style="width:100%">
<p>Extra fields as JSON (optional). Examples:<br>
topology: <code>{"options":{"polygon_type":"quadrilateral"}}</code><br>
retexture: <code>{"options":{"prompt":"rusty gold metal","pbr":true}}</code><br>
rapid: <code>{"prompt":"a red dragon figurine"}</code></p>
<textarea id="x" style="width:100%;height:70px">{}</textarea>
<p><button onclick="go()">1. Start</button></p>
<p>Job id</p><input id="j" style="width:100%">
<p><button onclick="check()">2. Check result</button></p>
<pre id="o" style="white-space:pre-wrap"></pre><div id="d"></div>
<script>
function hd(){return {"X-Admin-Key":document.getElementById("k").value.trim(),"Content-Type":"application/json"};}
function out(x){document.getElementById("o").textContent=JSON.stringify(x,null,2);}
async function go(){
  var body={}; try{body=JSON.parse(document.getElementById("x").value||"{}");}catch(e){out({error:"Extra JSON is not valid"});return;}
  body.tool=document.getElementById("t").value;
  body.source={kind:document.getElementById("sk").value,ref:document.getElementById("sr").value.trim()};
  var r=await fetch("/tool/submit",{method:"POST",headers:hd(),body:JSON.stringify(body)});
  var d=await r.json(); out(d); if(d.job_id){document.getElementById("j").value=d.job_id;}
}
async function check(){
  var r=await fetch("/tool/status/"+document.getElementById("t").value+"/"+document.getElementById("j").value.trim(),{headers:hd()});
  var d=await r.json(); var f=d.model_base64||d.file_base64;
  if(f){var b=atob(f),a=new Uint8Array(b.length);for(var i=0;i<b.length;i++){a[i]=b.charCodeAt(i);}
    var u=URL.createObjectURL(new Blob([a]));
    document.getElementById("d").innerHTML='<a href="'+u+'" download="'+(d.filename||"result.glb")+'">Download result</a>';
    d.model_base64=d.file_base64="(file received, "+a.length+" bytes)";}
  out(d);
}
</script></body></html>"""

    @app.get("/toolstest")
    def toolstest():
        return Response(TEST_HTML, mimetype="text/html")

# END: CAMEO3D PRO TOOLS BACKEND (tools.py)
