# START: CAMEO3D IMAGE LIBRARY + PUBLIC EXPLORE BACKEND (gallery.py) - put this file NEXT TO app.py
"""
Cameo3D - image library (every image a user makes is saved on the server) + public "Explore" area.

Routes:
    GET  /gallery/mine                     the logged-in user's images (newest first)
    GET  /gallery/public?q=&page=          public images, search by prompt (anyone on your website)
    POST /gallery/<id>/visibility          owner: {"visibility": "public" | "private"}
    POST /gallery/<id>/delete              owner: delete the image
    POST /gallery/<id>/report              anyone: report an image (3 reports hide it automatically)
    POST /gallery/<id>/hide                admin only (X-Admin-Key): hide an image
    GET  /galleryadmin                     admin page: see reported / newest public images and hide them

SAFETY RULES (built in, this is what makes automatic publishing correct):
    1. An image made with reference photos is ALWAYS private (it may contain a real person or private photo).
    2. If the prompt contains a blocked word (famous people, copyrighted characters, adult words) the image is
       saved as PRIVATE for its owner and is never shown in Explore.
    3. Anyone can report a public image. 3 reports = hidden automatically.
    4. You (admin) can hide any image from /galleryadmin.
    5. Users can switch an image to Private or delete it at any time.

Render environment variables (optional):
    GALLERY_BLOCKLIST     extra blocked words, separated by commas, e.g.  naruto,one piece,kylian mbappe

Supabase: needs a PRIVATE storage bucket named  images  and the table in GALLERY-STEPS.txt
"""

import os
import re
import base64
import time
import uuid

from flask import request, jsonify, Response

BUCKET = "images"
EXPIRE = 12 * 3600          # picture links stay valid 12 hours
PAGE = 40
REPORTS_TO_HIDE = 3

# Starter list. Whole-word match, not case sensitive. Add more with GALLERY_BLOCKLIST on Render.
DEFAULT_BLOCK = [
    # famous characters / brands
    "spider-man", "spiderman", "spider man", "batman", "superman", "iron man", "captain america", "thor", "hulk",
    "avengers", "marvel", "dc comics", "disney", "pixar", "mickey mouse", "pikachu", "pokemon", "mario", "luigi",
    "zelda", "sonic", "harry potter", "star wars", "darth vader", "yoda", "naruto", "goku", "one piece", "minecraft",
    # famous people
    "ronaldo", "messi", "neymar", "mbappe", "trump", "biden", "obama", "putin", "taylor swift", "elon musk",
    "kim kardashian", "beyonce", "drake", "shah rukh khan", "salman khan", "virat kohli", "imran khan",
    # adult / violent
    "nsfw", "nude", "naked", "porn", "sex", "sexy", "erotic", "gore", "beheaded", "corpse",
]


def _build_block():
    words = list(DEFAULT_BLOCK)
    extra = os.environ.get("GALLERY_BLOCKLIST", "")
    words += [w.strip().lower() for w in extra.split(",") if w.strip()]
    pat = "|".join(re.escape(w) for w in sorted(set(words), key=len, reverse=True))
    return re.compile(r"(?<![a-z0-9])(" + pat + r")(?![a-z0-9])", re.I)


BLOCK_RE = _build_block()
_reports = {}


def register_gallery(app, cursor, current_user, origin_ok, get_supabase):
    """Adds the gallery routes. Returns on_done(...) which imagegen.py calls after every generation."""

    def is_admin():
        import hmac
        key = os.environ.get("ADMIN_KEY", "")
        return bool(key) and hmac.compare_digest(request.headers.get("X-Admin-Key", ""), key)

    def client_ip():
        return (request.headers.get("X-Forwarded-For") or request.remote_addr or "?").split(",")[0].strip()

    def blocked(prompt):
        return bool(BLOCK_RE.search(prompt or ""))

    def sign(paths):
        """One call for many pictures. Returns {path: url}."""
        if not paths:
            return {}
        try:
            res = get_supabase().storage.from_(BUCKET).create_signed_urls(paths, EXPIRE)
        except Exception:
            app.logger.exception("signing image links failed")
            return {}
        out = {}
        for r in res or []:
            p = r.get("path")
            u = r.get("signedURL") or r.get("signedUrl")
            if p and u:
                out[p] = u
        return out

    def rows_to_items(rows):
        urls = sign([r[7] for r in rows])
        items = []
        for r in rows:
            u = urls.get(r[7])
            if not u:
                continue
            items.append({"id": r[0], "prompt": r[1], "style": r[2], "aspect": r[3], "size": r[4],
                          "visibility": r[5], "created": int(r[6] or 0), "url": u})
        return items

    COLS = "id,prompt,style,aspect,size,visibility,extract(epoch from created_at),file_path"

    # ------------------------------------------------------------
    # called by imagegen.py after every generation
    # ------------------------------------------------------------
    def on_done(uid, prompt, style, aspect, size, images, want_private, used_refs):
        out = []
        store = get_supabase().storage.from_(BUCKET)
        for im in images:
            try:
                iid = uuid.uuid4().hex[:16]
                mime = im.get("mime") or "image/png"
                ext = "jpg" if "jpeg" in mime else ("webp" if "webp" in mime else "png")
                path = f"{uid}/{iid}.{ext}"
                store.upload(path, base64.b64decode(im["image_base64"]), {"content-type": mime})
                vis = "private" if (want_private or used_refs or blocked(prompt)) else "public"
                with cursor() as cur:
                    cur.execute(
                        "insert into ai_images(id,user_id,prompt,style,aspect,size,file_path,visibility,with_refs) "
                        "values(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (iid, uid, prompt, style, aspect, size, path, vis, bool(used_refs)))
                out.append({"id": iid, "visibility": vis})
            except Exception:
                app.logger.exception("saving generated image failed")
                out.append({"id": None, "visibility": "private"})
        return out

    # ---------------- routes ----------------
    @app.get("/gallery/mine")
    def gallery_mine():
        if not origin_ok():
            return jsonify({"error": "Forbidden."}), 403
        uid = current_user()
        if not uid:
            return jsonify({"error": "Please log in."}), 401
        with cursor() as cur:
            cur.execute(f"select {COLS} from ai_images where user_id=%s order by created_at desc limit 200", (uid,))
            rows = cur.fetchall()
        return jsonify({"items": rows_to_items(rows)})

    @app.get("/gallery/public")
    def gallery_public():
        if not origin_ok():
            return jsonify({"error": "Forbidden."}), 403
        q = (request.args.get("q") or "").strip()[:80]
        try:
            page = max(0, int(request.args.get("page") or 0))
        except ValueError:
            page = 0
        like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        with cursor() as cur:
            cur.execute(
                f"select {COLS} from ai_images where visibility='public' and prompt ilike %s "
                "order by created_at desc limit %s offset %s", (like, PAGE + 1, page * PAGE))
            rows = cur.fetchall()
        more = len(rows) > PAGE
        return jsonify({"items": rows_to_items(rows[:PAGE]), "more": more})

    @app.post("/gallery/<iid>/visibility")
    def gallery_visibility(iid):
        if not origin_ok():
            return jsonify({"error": "Forbidden."}), 403
        uid = current_user()
        if not uid:
            return jsonify({"error": "Please log in."}), 401
        want = (request.get_json(silent=True) or {}).get("visibility")
        if want not in ("public", "private"):
            return jsonify({"error": "Invalid choice."}), 400
        with cursor() as cur:
            cur.execute("select prompt,visibility,with_refs from ai_images where id=%s and user_id=%s", (iid, uid))
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "Image not found."}), 404
            if want == "public":
                if row[1] == "hidden":
                    return jsonify({"error": "This image was removed from Explore and cannot be made public."}), 403
                if row[2]:
                    return jsonify({"error": "Images made with reference photos always stay private."}), 400
                if blocked(row[0]):
                    return jsonify({"error": "This image cannot be made public (it may show a protected name)."}), 400
            elif row[1] == "hidden":
                return jsonify({"visibility": "hidden"})
            cur.execute("update ai_images set visibility=%s where id=%s", (want, iid))
        return jsonify({"visibility": want})

    @app.post("/gallery/<iid>/delete")
    def gallery_delete(iid):
        if not origin_ok():
            return jsonify({"error": "Forbidden."}), 403
        uid = current_user()
        if not uid:
            return jsonify({"error": "Please log in."}), 401
        with cursor() as cur:
            cur.execute("select file_path from ai_images where id=%s and user_id=%s", (iid, uid))
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "Image not found."}), 404
            cur.execute("delete from ai_images where id=%s", (iid,))
        try:
            get_supabase().storage.from_(BUCKET).remove([row[0]])
        except Exception:
            app.logger.exception("deleting image file failed")
        return jsonify({"ok": True})

    @app.post("/gallery/<iid>/report")
    def gallery_report(iid):
        if not origin_ok():
            return jsonify({"error": "Forbidden."}), 403
        key = (client_ip(), iid)
        if key in _reports and time.time() - _reports[key] < 86400:
            return jsonify({"ok": True})          # same visitor, same image: counted once
        _reports[key] = time.time()
        with cursor() as cur:
            cur.execute("update ai_images set reports=reports+1 where id=%s and visibility='public'", (iid,))
            cur.execute("update ai_images set visibility='hidden' where id=%s and visibility='public' and reports>=%s",
                        (iid, REPORTS_TO_HIDE))
        return jsonify({"ok": True})

    @app.post("/gallery/<iid>/hide")
    def gallery_hide(iid):
        if not is_admin():
            return jsonify({"error": "Forbidden."}), 403
        with cursor() as cur:
            cur.execute("update ai_images set visibility='hidden' where id=%s", (iid,))
        return jsonify({"ok": True})

    @app.get("/gallery/admin/list")
    def gallery_admin_list():
        if not is_admin():
            return jsonify({"error": "Forbidden."}), 403
        with cursor() as cur:
            cur.execute(f"select {COLS},reports from ai_images where visibility in ('public','hidden') "
                        "order by reports desc, created_at desc limit 80")
            rows = cur.fetchall()
        items = rows_to_items([r[:8] for r in rows])
        reps = {r[0]: r[8] for r in rows}
        for it in items:
            it["reports"] = reps.get(it["id"], 0)
        return jsonify({"items": items})

    ADMIN_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Gallery admin</title>
<style>body{font-family:sans-serif;background:#111;color:#eee;margin:20px}img{width:100%;border-radius:8px;display:block}
.g{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:10px}.c{background:#1c1c1c;padding:8px;border-radius:10px;font-size:12px}
button{margin-top:6px;width:100%;padding:6px;border:0;border-radius:6px;background:#c9f45c;font-weight:700;cursor:pointer}</style></head>
<body><h3>Gallery admin (most reported first)</h3>
<input id="k" type="password" placeholder="ADMIN_KEY" style="padding:6px"> <button style="width:auto;padding:6px 14px" onclick="load()">Load</button>
<div class="g" id="g"></div>
<script>
function hd(){return {"X-Admin-Key":document.getElementById("k").value.trim()};}
async function load(){
  var r=await fetch("/gallery/admin/list",{headers:hd()}); var d=await r.json(); var g=document.getElementById("g"); g.textContent="";
  (d.items||[]).forEach(function(it){
    var c=document.createElement("div"); c.className="c";
    var i=document.createElement("img"); i.src=it.url; c.appendChild(i);
    var t=document.createElement("div"); t.textContent=it.visibility+" | reports: "+it.reports+" | "+it.prompt.slice(0,90); c.appendChild(t);
    var b=document.createElement("button"); b.textContent="Hide"; b.onclick=async function(){await fetch("/gallery/"+it.id+"/hide",{method:"POST",headers:hd()}); c.remove();}; c.appendChild(b);
    g.appendChild(c);
  });
}
</script></body></html>"""

    @app.get("/galleryadmin")
    def galleryadmin():
        return Response(ADMIN_HTML, mimetype="text/html")

    return on_done

# END: CAMEO3D IMAGE LIBRARY + PUBLIC EXPLORE BACKEND (gallery.py)
