# START: ADMIN MODELS PAGE v3 (add / edit / delete library models from one form page)
#
# What this file does:
#   - Opens a form page at  /admin/models  on your Render service
#   - ADD:    pick the files, fill the boxes, click Save. The server puts the files in Cloudflare R2.
#   - EDIT:   click Edit in the list, change the text (or pick new files), click Save.
#   - DELETE: click Delete in the list. It removes the library row AND its files in Cloudflare.
#   - THUMBNAIL STYLE per model:
#         "Rotating 3D model"  = the card shows the viewer .glb turning (use for light files only)
#         "Picture only"       = the card shows the thumbnail picture, and the white picture on hover
#   - Uploads go through your Render server, so there is NO Cloudflare CORS setup needed.
#   - Files bigger than about 80 MB: the page tells you the exact name to upload by hand in Cloudflare.
#   - It creates the new columns by itself (viewer_url, slug, tags, white_url, thumb_mode).
#
# Needs these Render variables (you already have them):
#   ADMIN_KEY, R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET
# Optional Render variables (defaults are already your values):
#   R2_PREVIEW_BUCKET   (default: cameo-previews)
#   R2_PREVIEW_BASE_URL (default: your pub-....r2.dev address)

import os
import re
import hmac

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from flask import jsonify, request, Response

PREVIEW_BUCKET = os.environ.get("R2_PREVIEW_BUCKET", "cameo-previews")
PREVIEW_BASE = os.environ.get(
    "R2_PREVIEW_BASE_URL", "https://pub-5b01e64ba08c4a6eafb3de4a956cd45a.r2.dev"
).rstrip("/")

MAX_UPLOAD = 120 * 1024 * 1024                        # biggest file the form accepts
SLUG_OK = re.compile(r"^[a-z0-9][a-z0-9-]{0,59}$")   # short name: lowercase letters, numbers, dashes
EXT_OK = re.compile(r"^[a-z0-9]{2,5}$")              # file ending like glb, stl, webp
IMAGE_ENDINGS = (".jpg", ".jpeg", ".png", ".webp")
_columns_ready = [False]


def ensure_model_columns(cur):
    """Adds the extra columns the library needs. Safe to call many times; app.py uses it too."""
    if _columns_ready[0]:
        return
    for col in ("viewer_url text", "slug text", "tags text", "white_url text", "thumb_mode text"):
        cur.execute("alter table models add column if not exists " + col)
    _columns_ready[0] = True


def r2_client():
    return boto3.client(
        "s3",
        endpoint_url="https://%s.r2.cloudflarestorage.com" % os.environ["R2_ACCOUNT_ID"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
        config=Config(
            signature_version="s3v4",
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )


def target(slug, kind, ext):
    """Where each file lives: which bucket and which path."""
    if kind == "full":
        return os.environ["R2_BUCKET"], "%s.%s" % (slug, ext)
    if kind == "thumb":
        return PREVIEW_BUCKET, "thumbs/%s.%s" % (slug, ext)
    if kind == "white":
        return PREVIEW_BUCKET, "thumbs/%s-white.%s" % (slug, ext)
    if kind == "viewer":
        return PREVIEW_BUCKET, "viewer/%s.glb" % slug
    return None, None


def key_matches(slug, kind, key):
    """True if a path looks exactly like what this form would have made."""
    if kind == "viewer":
        return key == "viewer/%s.glb" % slug
    if kind == "full":
        prefix = "%s." % slug
    elif kind == "white":
        prefix = "thumbs/%s-white." % slug
    else:
        prefix = "thumbs/%s." % slug
    return key.startswith(prefix) and EXT_OK.match(key[len(prefix):]) is not None


def register_models_admin(app, cursor):
    def key_ok():
        key = os.environ.get("ADMIN_KEY", "")
        return bool(key) and hmac.compare_digest(request.headers.get("X-Admin-Key", ""), key)

    # Lets the upload route accept big files (the rest of the site keeps its smaller limit).
    @app.before_request
    def admin_models_upload_limit():
        if request.path == "/admin/models/upload":
            try:
                request.max_content_length = MAX_UPLOAD
            except Exception:
                pass

    @app.get("/admin/models")
    def admin_models_page():
        return Response(PAGE_HTML, mimetype="text/html")

    # Receives one file from the page and puts it into Cloudflare R2.
    @app.post("/admin/models/upload")
    def admin_models_upload():
        if not key_ok():
            return jsonify({"error": "Wrong admin key."}), 403
        slug = request.form.get("slug", "")
        kind = request.form.get("kind", "")
        ext = request.form.get("ext", "").lower().lstrip(".")
        f = request.files.get("file")
        if not SLUG_OK.match(slug) or kind not in ("thumb", "white", "viewer", "full") or not EXT_OK.match(ext) or not f:
            return jsonify({"error": "Bad upload request."}), 400
        bucket, key = target(slug, kind, ext)
        if kind == "viewer":
            ctype = "model/gltf-binary"
        elif kind in ("thumb", "white"):
            ctype = f.mimetype or "image/webp"
        else:
            ctype = "application/octet-stream"
        try:
            r2_client().upload_fileobj(f.stream, bucket, key, ExtraArgs={"ContentType": ctype})
        except Exception as exc:
            app.logger.exception("r2 upload failed %s/%s", bucket, key)
            return jsonify({"error": "Cloudflare upload failed: %s" % str(exc)[:160]}), 502
        return jsonify({"key": key})

    # After the files are in R2, write (or update) the row in the models table.
    @app.post("/admin/models/save")
    def admin_models_save():
        if not key_ok():
            return jsonify({"error": "Wrong admin key."}), 403
        d = request.get_json(silent=True) or {}
        slug = str(d.get("slug", ""))
        title = str(d.get("title", "")).strip()[:120]
        category = str(d.get("category", "")).strip()[:40]
        tags = str(d.get("tags", "")).strip()[:300]
        description = str(d.get("description", "")).strip()[:1000]
        mode = "model" if d.get("mode") == "model" else "image"
        try:
            price = int(d.get("price"))
        except (TypeError, ValueError):
            return jsonify({"error": "Credits must be a number (0 = free)."}), 400
        if not SLUG_OK.match(slug) or not title or not category or price < 0 or price > 100000:
            return jsonify({"error": "Title, URL name, category and credits are needed."}), 400

        keys = {
            "thumb": str(d.get("thumb_key") or ""),
            "white": str(d.get("white_key") or ""),
            "viewer": str(d.get("viewer_key") or ""),
            "full": str(d.get("full_key") or ""),
        }
        client = r2_client()
        for kind, key in keys.items():
            if not key:
                continue
            if not key_matches(slug, kind, key):
                return jsonify({"error": "File names do not match the URL name."}), 400
            bucket = os.environ["R2_BUCKET"] if kind == "full" else PREVIEW_BUCKET
            try:
                client.head_object(Bucket=bucket, Key=key)
            except ClientError:
                return jsonify({"error": "File not found in Cloudflare: %s/%s . Upload it there with exactly this name, then click Save again." % (bucket, key)}), 400

        with cursor() as cur:
            ensure_model_columns(cur)
            cur.execute("select id,preview_url,viewer_url,file_path,white_url from models where slug=%s", (slug,))
            row = cur.fetchone()
            if not row and not (keys["full"] and keys["viewer"]):
                return jsonify({"error": "A new model needs the viewer .glb and the full model file."}), 400
            viewer_url = PREVIEW_BASE + "/" + keys["viewer"] if keys["viewer"] else row[2]
            if keys["thumb"]:
                preview_url = PREVIEW_BASE + "/" + keys["thumb"]
            elif row and row[1]:
                preview_url = row[1]
            else:
                preview_url = viewer_url
            if mode == "image" and not preview_url.lower().split("?")[0].endswith(IMAGE_ENDINGS):
                return jsonify({"error": "Picture style needs a thumbnail picture. Choose one in box 1."}), 400
            white_url = PREVIEW_BASE + "/" + keys["white"] if keys["white"] else (row[4] if row else None)
            file_path = keys["full"] or row[3]
            if row:
                cur.execute(
                    "update models set title=%s, category=%s, price_credits=%s, tags=%s, description=%s,"
                    " preview_url=%s, viewer_url=%s, file_path=%s, white_url=%s, thumb_mode=%s where id=%s",
                    (title, category, price, tags, description, preview_url, viewer_url, file_path, white_url, mode, row[0]),
                )
                mid = row[0]
            else:
                cur.execute(
                    "insert into models(title,slug,category,price_credits,tags,description,preview_url,viewer_url,file_path,white_url,thumb_mode)"
                    " values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id",
                    (title, slug, category, price, tags, description, preview_url, viewer_url, file_path, white_url, mode),
                )
                mid = cur.fetchone()[0]
        return jsonify({"ok": True, "id": mid})

    @app.get("/admin/models/list")
    def admin_models_list():
        if not key_ok():
            return jsonify({"error": "Wrong admin key."}), 403
        with cursor() as cur:
            ensure_model_columns(cur)
            cur.execute("select id,title,slug,category,price_credits,tags,description,thumb_mode from models order by id desc")
            rows = cur.fetchall()
        return jsonify([
            {"id": r[0], "title": r[1], "slug": r[2], "category": r[3], "price": r[4],
             "tags": r[5] or "", "description": r[6] or "", "mode": r[7] or "image"} for r in rows
        ])

    # Removes the library row and the model's files in Cloudflare.
    @app.post("/admin/models/delete")
    def admin_models_delete():
        if not key_ok():
            return jsonify({"error": "Wrong admin key."}), 403
        try:
            mid = int((request.get_json(silent=True) or {}).get("id"))
        except (TypeError, ValueError):
            return jsonify({"error": "Bad id."}), 400
        with cursor() as cur:
            ensure_model_columns(cur)
            cur.execute("select preview_url,viewer_url,white_url,file_path from models where id=%s", (mid,))
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "Model not found."}), 404
            cur.execute("delete from downloads where model_id=%s", (mid,))
            cur.execute("delete from models where id=%s", (mid,))
        client = r2_client()
        base = PREVIEW_BASE + "/"
        jobs = []
        for url in (row[0], row[1], row[2]):
            if url and url.startswith(base):
                jobs.append((PREVIEW_BUCKET, url[len(base):]))
        if row[3]:
            jobs.append((os.environ["R2_BUCKET"], row[3]))
        for bucket, key in set(jobs):
            try:
                client.delete_object(Bucket=bucket, Key=key)
            except Exception:
                app.logger.exception("r2 delete failed %s/%s", bucket, key)
        return jsonify({"ok": True})


PAGE_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cameo3D - Models admin</title>
<style>
:root{--bg:#101012;--card:#19191d;--line:#2c2c33;--text:#f2f2f4;--dim:#9a9aa6;--lime:#c9f23b;--pink:#f58cb4}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:16px/1.5 system-ui,Segoe UI,Arial,sans-serif}
main{max-width:780px;margin:0 auto;padding:28px 18px 80px}
h1{font-size:28px;margin:0 0 4px}
h2{font-size:19px;margin:34px 0 10px}
p.sub{color:var(--dim);margin:0 0 22px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px}
label{display:block;font-weight:600;margin:14px 0 5px}
.hint{font-weight:400;color:var(--dim);font-size:14px}
input,textarea,select{width:100%;background:#0e0e10;color:var(--text);border:1px solid var(--line);border-radius:9px;padding:10px 12px;font:inherit}
input:focus,textarea:focus,select:focus,button:focus-visible{outline:2px solid var(--lime);outline-offset:1px}
input[type=file]{padding:9px}
.row{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:560px){.row{grid-template-columns:1fr}}
button{font:inherit;font-weight:700;border:0;border-radius:10px;padding:12px 20px;cursor:pointer;background:var(--lime);color:#14160a}
button:disabled{opacity:.5;cursor:wait}
button.small{padding:6px 12px;font-size:14px;background:#2a2a31;color:var(--text);margin-right:6px}
button.danger{background:#4a2233;color:var(--pink)}
#status{margin-top:14px;min-height:24px;font-weight:600}
#status.err{color:var(--pink)}
#mode_note{color:var(--lime);font-weight:600;margin:0 0 6px;min-height:24px}
table{width:100%;border-collapse:collapse}
td,th{text-align:left;padding:9px 6px;border-bottom:1px solid var(--line);font-size:15px}
th{color:var(--dim);font-weight:600}
td.act{white-space:nowrap;text-align:right}
</style></head>
<body><main>
<!-- START: ADMIN FORM - ADD OR EDIT MODEL -->
<h1>Models admin</h1>
<p class="sub">Add a model, or click Edit in the list below to change one.</p>

<div class="card">
  <label for="key">Admin key <span class="hint">(the ADMIN_KEY from Render)</span></label>
  <input id="key" type="password" autocomplete="off">

  <p id="mode_note"></p>

  <label for="title">Title</label>
  <input id="title" maxlength="120" placeholder="Modern chair">

  <div class="row">
    <div>
      <label for="slug">URL name <span class="hint">(made from the title; the same name edits that model)</span></label>
      <input id="slug" maxlength="60" placeholder="modern-chair">
    </div>
    <div>
      <label for="price">Credits <span class="hint">(0 = free, more than 0 = premium)</span></label>
      <input id="price" type="number" min="0" value="0">
    </div>
  </div>

  <label for="mode">Thumbnail style <span class="hint">(how the card looks in the library)</span></label>
  <select id="mode">
    <option value="image">Picture only (heavy files): picture, white picture on hover</option>
    <option value="model">Rotating 3D model (light files only): the viewer .glb turns in the card</option>
  </select>

  <label for="category">Category</label>
  <input id="category" list="cats" placeholder="Furniture">
  <datalist id="cats"><option>Characters</option><option>Props</option><option>Vehicles</option><option>Furniture</option></datalist>

  <label for="tags">Search words <span class="hint">(separate with commas)</span></label>
  <input id="tags" maxlength="300" placeholder="chair, seat, furniture, home, modern">

  <label for="description">Description</label>
  <textarea id="description" rows="3" maxlength="1000"></textarea>

  <label for="thumb">1. Thumbnail picture <span class="hint">(needed for Picture style; webp, png or jpg)</span></label>
  <input id="thumb" type="file" accept="image/*">

  <label for="white">2. White model picture <span class="hint">(optional; same size as the thumbnail; shows when the mouse is over the card)</span></label>
  <input id="white" type="file" accept="image/*">

  <label for="viewer">3. Viewer model <span class="hint">(.glb, opens when someone clicks the card; leave empty to use the full file when it is a .glb)</span></label>
  <input id="viewer" type="file" accept=".glb">

  <label for="full">4. Full model for download <span class="hint">(private; .glb, .stl, .zip, .3mf, .fbx)</span></label>
  <input id="full" type="file">

  <p class="hint" style="margin:14px 0 0">When editing, leave the file boxes empty to keep the current files.</p>
  <p style="margin:16px 0 0"><button id="go">Save model</button> <button class="small" id="clear" type="button">Clear form</button></p>
  <div id="status"></div>
</div>
<!-- END: ADMIN FORM - ADD OR EDIT MODEL -->

<!-- START: ADMIN LIST - MODELS IN LIBRARY -->
<h2>Models in the library</h2>
<div class="card">
  <p style="margin:0 0 10px"><button class="small" id="refresh">Show list</button></p>
  <table><thead><tr><th>Title</th><th>Category</th><th>Credits</th><th></th></tr></thead><tbody id="rows"></tbody></table>
</div>
<!-- END: ADMIN LIST - MODELS IN LIBRARY -->

<script>
// START: ADMIN PAGE SCRIPT
const $ = id => document.getElementById(id);
const BIG = 80 * 1024 * 1024;       // bigger files are uploaded by hand in Cloudflare
let known = new Set();              // URL names that already exist

function say(text, bad){ const s=$("status"); s.textContent=text; s.className = bad ? "err" : ""; }
function extOf(f){ const m=/\.([A-Za-z0-9]+)$/.exec(f.name); return m ? m[1].toLowerCase() : ""; }
function keyFor(kind, slug, ext){
  return kind==="thumb" ? "thumbs/"+slug+"."+ext : kind==="white" ? "thumbs/"+slug+"-white."+ext : kind==="viewer" ? "viewer/"+slug+".glb" : slug+"."+ext;
}

async function api(path, method, body){
  const r = await fetch(path, {method, headers:{"Content-Type":"application/json","X-Admin-Key":$("key").value.trim()}, body: body ? JSON.stringify(body) : undefined});
  const j = await r.json().catch(()=>({}));
  if(!r.ok) throw new Error(j.error || ("Server error " + r.status));
  return j;
}

// Sends one file to the server. Files over 80 MB are skipped here and must be put in Cloudflare by hand.
function up(kind, file, slug, ext, label){
  if(file.size > BIG) return Promise.resolve(keyFor(kind, slug, ext));
  return new Promise((ok, fail) => {
    const fd = new FormData();
    fd.append("slug", slug); fd.append("kind", kind); fd.append("ext", ext); fd.append("file", file);
    const x = new XMLHttpRequest();
    x.open("POST", "/admin/models/upload");
    x.setRequestHeader("X-Admin-Key", $("key").value.trim());
    x.upload.onprogress = e => { if(e.lengthComputable) say(label + ": " + Math.round(e.loaded/e.total*100) + "%"); };
    x.onload = () => {
      let j = {}; try{ j = JSON.parse(x.responseText); }catch(e){}
      if(x.status < 300) ok(j.key);
      else fail(new Error(j.error || (x.status === 413 ? label + " is too large for the form." : label + " upload failed (" + x.status + ").")));
    };
    x.onerror = () => fail(new Error(label + ": no answer from the server. Wait a minute (it may be waking up) and try again."));
    x.send(fd);
  });
}

$("title").addEventListener("input", () => {
  if(!$("slug").dataset.touched) $("slug").value = $("title").value.toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/^-+|-+$/g,"").slice(0,60);
});
$("slug").addEventListener("input", () => { $("slug").dataset.touched = "1"; });

function clearForm(){
  ["title","slug","tags","description","category","thumb","white","viewer","full"].forEach(i => { $(i).value = ""; });
  $("price").value = "0";
  $("mode").value = "image";
  delete $("slug").dataset.touched;
  $("mode_note").textContent = "";
}
$("clear").onclick = () => { clearForm(); say(""); };

$("go").onclick = async () => {
  try{
    const slug=$("slug").value.trim(), title=$("title").value.trim(), mode=$("mode").value;
    const thumb=$("thumb").files[0], white=$("white").files[0], viewer=$("viewer").files[0], full=$("full").files[0];
    if(!title || !slug) throw new Error("Write a title first.");
    if(!$("category").value.trim()) throw new Error("Write a category.");
    const isNew = !known.has(slug);
    if(isNew && !full) throw new Error("A new model needs the full model file (box 4).");
    if(isNew && mode === "image" && !thumb) throw new Error("Picture style needs a thumbnail picture (box 1).");
    for(const f of [thumb, white, viewer, full]) if(f && !extOf(f)) throw new Error("Every file needs an ending like .glb or .webp.");
    $("go").disabled = true;
    const body = {slug, title, mode, category:$("category").value, price:$("price").value, tags:$("tags").value, description:$("description").value};
    const manual = [];
    if(thumb){ body.thumb_key = await up("thumb", thumb, slug, extOf(thumb), "Thumbnail"); if(thumb.size > BIG) manual.push("cameo-previews/" + body.thumb_key); }
    if(white){ body.white_key = await up("white", white, slug, extOf(white), "White picture"); if(white.size > BIG) manual.push("cameo-previews/" + body.white_key); }
    const viewerFile = viewer || (full && extOf(full) === "glb" ? full : null);
    if(viewerFile){ body.viewer_key = await up("viewer", viewerFile, slug, "glb", "Viewer model"); if(viewerFile.size > BIG) manual.push("cameo-previews/" + body.viewer_key); }
    else if(isNew) throw new Error("The viewer needs a .glb file. Choose one in box 3.");
    if(full){ body.full_key = await up("full", full, slug, extOf(full), "Full model"); if(full.size > BIG) manual.push("cameo-models/" + body.full_key); }
    if(manual.length) say("Big file: upload it in Cloudflare with this exact name (bucket/name): " + manual.join("  and  ") + " . Then click Save again.", true);
    await api("/admin/models/save", "POST", body);
    say("Saved. The model is in the library.");
    clearForm();
    loadList();
  }catch(e){ say(e.message, true); }
  finally{ $("go").disabled = false; }
};

async function loadList(){
  try{
    const rows = await api("/admin/models/list", "GET");
    known = new Set(rows.map(m => m.slug).filter(Boolean));
    const body = $("rows"); body.innerHTML = "";
    rows.forEach(m => {
      const tr = document.createElement("tr");
      [m.title, m.category || "", m.price === 0 ? "Free" : String(m.price)].forEach(t => {
        const td = document.createElement("td"); td.textContent = t; tr.appendChild(td);
      });
      const td = document.createElement("td"); td.className = "act";
      if(m.slug){
        const e = document.createElement("button"); e.className = "small"; e.textContent = "Edit";
        e.onclick = () => {
          clearForm();
          $("title").value = m.title; $("slug").value = m.slug; $("slug").dataset.touched = "1";
          $("price").value = m.price; $("category").value = m.category || ""; $("mode").value = m.mode;
          $("tags").value = m.tags; $("description").value = m.description;
          $("mode_note").textContent = "Editing: " + m.title;
          say("Change what you want, then click Save model. File boxes can stay empty.");
          window.scrollTo({top:0, behavior:"smooth"});
        };
        td.appendChild(e);
      }
      const b = document.createElement("button"); b.className = "small danger"; b.textContent = "Delete";
      b.onclick = async () => {
        if(!confirm("Delete " + m.title + "? This removes it from the library and deletes its files in Cloudflare.")) return;
        try{ await api("/admin/models/delete", "POST", {id:m.id}); loadList(); }catch(err){ say(err.message, true); }
      };
      td.appendChild(b); tr.appendChild(td); body.appendChild(tr);
    });
  }catch(e){ say(e.message, true); }
}
$("refresh").onclick = loadList;
// END: ADMIN PAGE SCRIPT
</script>
</main></body></html>"""
# END: ADMIN MODELS PAGE v3
