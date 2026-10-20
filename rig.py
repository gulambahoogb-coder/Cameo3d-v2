"""
Cameo3D - Auto-rigging (adds a skeleton to a generated model). Works next to app.py.

What it adds:
    POST /rig/submit          logged-in user sends the job_id of a finished generation
                              -> we convert the GLB to FBX (Tencent Convert3DFormat, 5 credits)
                              -> we send the FBX to Tencent Auto Rigging (10 credits)
                              -> returns rig_job_id
    GET  /rig/status/<id>     poll until COMPLETED -> returns the rigged FBX (base64)
                              and saves a copy in your Supabase "generations" bucket
                              (Tencent's own link dies after 24 hours)
    GET  /rigtest             TEMPORARY admin test page (delete after testing)

Render environment variables (optional):
    RIG_COST     credits charged to the user per rig (default 20; Tencent charges you about 15)

Notes:
    - The character must be in a T-pose (arms straight out). Tencent requires it.
    - Failed Tencent calls are refunded to the user automatically.
"""

import os
import hmac
import threading

import requests
from flask import request, jsonify, Response
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException


def _int_env(name, default):
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


RIG_COST = _int_env("RIG_COST", 20)

# The status action name is tried in this order until Tencent accepts one.
QUERY_ACTIONS = ("QueryAutoRiggingJob", "DescribeAutoRiggingJob")


class RigError(Exception):
    def __init__(self, message, code):
        super().__init__(message)
        self.message = message
        self.code = code


def register_rig(app, cursor, spend, refund, refund_job, current_user, origin_ok,
                 hy_call, pick_glb_url, friendly_tencent_error, get_supabase):
    """Adds the rigging routes to the existing Flask app."""

    def is_admin():
        key = os.environ.get("ADMIN_KEY", "")
        return bool(key) and hmac.compare_digest(request.headers.get("X-Admin-Key", ""), key)

    def query_rig(job_id):
        last = None
        for action in QUERY_ACTIONS:
            try:
                return hy_call(action, {"JobId": job_id})
            except TencentCloudSDKException as exc:
                code = ""
                try:
                    code = (exc.get_code() or "").lower()
                except Exception:
                    pass
                if "invalidaction" in code or "action" in code:
                    last = exc
                    continue
                raise
        raise last

    def start_rig(gen_job_id):
        """GLB of a finished generation -> FBX -> rigging job. Returns the rigging job id."""
        job = hy_call("QueryHunyuanTo3DProJob", {"JobId": gen_job_id})
        if str(job.get("Status") or "").upper() != "DONE":
            raise RigError("This model is not ready or is no longer available.", 409)
        glb_url = pick_glb_url(job.get("ResultFile3Ds"))
        if not glb_url:
            raise RigError("The original model file is no longer available.", 410)

        return rig_from_glb_url(glb_url)

    def rig_from_glb_url(glb_url):
        """GLB url -> FBX (5 credits) -> rigging job. Returns the rigging job id."""
        conv = hy_call("Convert3DFormat", {"File3D": glb_url, "Format": "FBX"})
        fbx_url = conv.get("ResultFile3D")
        if not fbx_url:
            raise RigError("Could not prepare the model for rigging.", 502)
        return rig_from_fbx_url(fbx_url)

    def rig_from_fbx_url(fbx_url):
        """FBX url -> rigging job (10 credits). Returns the rigging job id."""
        resp = hy_call("SubmitAutoRiggingJob", {"File3D": {"Url": fbx_url, "Type": "FBX"}})
        rig_id = resp.get("JobId")
        if not rig_id:
            raise RigError("Tencent returned no rigging job id.", 502)
        return rig_id

    def save_copy(uid, rig_id, content):
        """Background: keep our own copy, because Tencent's link expires in 24 hours."""
        try:
            path = f"{uid}/rig-{rig_id}.fbx"
            get_supabase().storage.from_("generations").upload(
                path, content, {"content-type": "application/octet-stream", "upsert": "true"}
            )
            with cursor() as cur:
                cur.execute("update jobs set file_path=%s, status='saved' where job_id=%s", (path, rig_id))
        except Exception:
            app.logger.exception("save rig copy failed job=%s", rig_id)

    # -----------------------------------------------------------
    @app.route("/rig/submit", methods=["POST", "OPTIONS"])
    def rig_submit():
        if request.method == "OPTIONS":
            return ("", 204)
        admin = is_admin()
        uid = None
        if not admin:
            if not origin_ok():
                return jsonify({"error": "Forbidden."}), 403
            uid = current_user()
            if not uid:
                return jsonify({"error": "Please log in to add a skeleton."}), 401

        data = request.get_json(silent=True) or {}
        gen_job_id = data.get("job_id")
        if not isinstance(gen_job_id, str) or not gen_job_id.strip() or len(gen_job_id) > 100:
            return jsonify({"error": "Missing job id."}), 400
        gen_job_id = gen_job_id.strip()

        cost = RIG_COST
        if uid and cost > 0:
            if not spend(uid, cost, "auto rig"):
                return jsonify({"error": f"Not enough credits. Adding a skeleton needs {cost} credits."}), 402

        try:
            rig_id = start_rig(gen_job_id)
        except RigError as exc:
            if uid and cost > 0:
                refund(uid, cost, "refund: rigging could not start")
            return jsonify({"error": exc.message}), exc.code
        except TencentCloudSDKException as exc:
            if uid and cost > 0:
                refund(uid, cost, "refund: rigging could not start")
            return jsonify({"error": friendly_tencent_error(exc)}), 502
        except Exception as exc:
            if uid and cost > 0:
                refund(uid, cost, "refund: rigging could not start")
            app.logger.exception("rig submit failed")
            return jsonify({"error": f"Server error: {exc}"}), 500

        if uid:
            try:
                with cursor() as cur:
                    cur.execute(
                        "insert into jobs(job_id,user_id,cost) values(%s,%s,%s) on conflict do nothing",
                        (rig_id, uid, cost),
                    )
            except Exception:
                app.logger.exception("could not record rig job %s", rig_id)
        return jsonify({"rig_job_id": rig_id})

    # -----------------------------------------------------------
    @app.route("/rig/status/<rig_id>", methods=["GET", "OPTIONS"])
    def rig_status(rig_id):
        if request.method == "OPTIONS":
            return ("", 204)
        admin = is_admin()
        uid = None
        if not admin:
            if not origin_ok():
                return jsonify({"error": "Forbidden."}), 403
            uid = current_user()
            if not uid:
                return jsonify({"error": "Please log in."}), 401
            with cursor() as cur:
                cur.execute("select 1 from jobs where job_id=%s and user_id=%s", (rig_id, uid))
                if not cur.fetchone():
                    return jsonify({"error": "Job not found."}), 404

        try:
            resp = query_rig(rig_id)
            st = str(resp.get("Status") or "").upper()

            if st == "DONE":
                files = resp.get("ResultFile3Ds") or []
                url = None
                for f in files:
                    if str(f.get("Type", "")).upper() == "FBX":
                        url = f.get("Url")
                        break
                if not url and files:
                    url = files[0].get("Url")
                if not url:
                    if uid:
                        refund_job(rig_id)
                    return jsonify({"status": "FAILED", "error": "Tencent finished but returned no file."})
                r = requests.get(url, timeout=180)
                if not r.ok or not r.content:
                    return jsonify({"status": "FAILED", "error": "Could not download the rigged file."})
                if uid:
                    threading.Thread(target=save_copy, args=(uid, rig_id, r.content), daemon=True).start()
                import base64
                return jsonify({
                    "status": "COMPLETED",
                    "filename": "cameo3d-rigged.fbx",
                    "file_base64": base64.b64encode(r.content).decode("ascii"),
                })

            if st == "FAIL":
                if uid:
                    refund_job(rig_id)
                return jsonify({"status": "FAILED", "error": str(resp.get("ErrorMessage") or "Rigging failed.")})

            return jsonify({"status": "IN_PROGRESS"})

        except TencentCloudSDKException as exc:
            return jsonify({"error": friendly_tencent_error(exc)}), 502
        except Exception as exc:
            app.logger.exception("rig status failed")
            return jsonify({"error": f"Server error: {exc}"}), 500

    # -----------------------------------------------------------
    # ADMIN TEST: rig a file from your own computer (no generation needed).
    # FBX file = 10 Tencent credits. GLB file = 15 (5 to convert + 10 to rig).
    # -----------------------------------------------------------
    @app.post("/rig/submit-file")
    def rig_submit_file():
        if not is_admin():
            return jsonify({"error": "Forbidden."}), 403
        f = request.files.get("file")
        if not f or not f.filename:
            return jsonify({"error": "Choose a .fbx or .glb file."}), 400
        ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
        if ext not in ("fbx", "glb"):
            return jsonify({"error": "Only .fbx or .glb files."}), 400
        content = f.read()
        if not content or len(content) > 30 * 1024 * 1024:
            return jsonify({"error": "File is empty or larger than 30 MB."}), 400
        try:
            import secrets
            path = f"admintest/{secrets.token_hex(8)}.{ext}"
            bucket = get_supabase().storage.from_("generations")
            bucket.upload(path, content, {"content-type": "application/octet-stream", "upsert": "true"})
            res = bucket.create_signed_url(path, 3600)
            url = res.get("signedURL") or res.get("signedUrl")
            if not url:
                return jsonify({"error": "Could not make a link for the uploaded file."}), 502
            rig_id = rig_from_fbx_url(url) if ext == "fbx" else rig_from_glb_url(url)
            return jsonify({"rig_job_id": rig_id})
        except RigError as exc:
            return jsonify({"error": exc.message}), exc.code
        except TencentCloudSDKException as exc:
            return jsonify({"error": friendly_tencent_error(exc)}), 502
        except Exception as exc:
            app.logger.exception("rig submit-file failed")
            return jsonify({"error": f"Server error: {exc}"}), 500

    # -----------------------------------------------------------
    # TEMPORARY ADMIN TEST PAGE. DELETE this section after testing.
    # Needs your ADMIN_KEY. Does not charge any user credits.
    # -----------------------------------------------------------
    RIGTEST_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Rig test</title></head>
<body style="font-family:sans-serif;max-width:560px;margin:40px auto">
<h2>Rig test (admin)</h2>
<p>ADMIN_KEY</p><input id="k" type="password" style="width:100%">
<p>Generation job id (from a finished generation)</p><input id="j" style="width:100%">
<p><button onclick="go()">1. Start rigging</button></p>
<p><b>Or</b> test with a file from your computer (no generation needed):</p>
<input id="f" type="file" accept=".fbx,.glb">
<p><button onclick="goFile()">1b. Start rigging with my file</button></p>
<p>Rig job id</p><input id="r" style="width:100%">
<p><button onclick="check()">2. Check result</button></p>
<pre id="o" style="white-space:pre-wrap"></pre><div id="d"></div>
<script>
function hd(){return {"X-Admin-Key":document.getElementById("k").value.trim(),"Content-Type":"application/json"};}
function out(x){document.getElementById("o").textContent=JSON.stringify(x,null,2);}
async function go(){
  var r=await fetch("/rig/submit",{method:"POST",headers:hd(),body:JSON.stringify({job_id:document.getElementById("j").value.trim()})});
  var d=await r.json(); out(d); if(d.rig_job_id){document.getElementById("r").value=d.rig_job_id;}
}
async function goFile(){
  var file=document.getElementById("f").files[0];
  if(!file){out({error:"Choose a file first."});return;}
  var fd=new FormData(); fd.append("file",file);
  var r=await fetch("/rig/submit-file",{method:"POST",headers:{"X-Admin-Key":document.getElementById("k").value.trim()},body:fd});
  var d=await r.json(); out(d); if(d.rig_job_id){document.getElementById("r").value=d.rig_job_id;}
}
async function check(){
  var id=document.getElementById("r").value.trim();
  var r=await fetch("/rig/status/"+id,{headers:hd()});
  var d=await r.json();
  if(d.file_base64){
    var b=atob(d.file_base64),a=new Uint8Array(b.length);
    for(var i=0;i<b.length;i++){a[i]=b.charCodeAt(i);}
    var u=URL.createObjectURL(new Blob([a]));
    document.getElementById("d").innerHTML='<a href="'+u+'" download="rigged.fbx">Download rigged.fbx</a>';
    d.file_base64="(file received, "+a.length+" bytes)";
  }
  out(d);
}
</script></body></html>"""

    @app.get("/rigtest")
    def rigtest():
        return Response(RIGTEST_HTML, mimetype="text/html")
