# START: ADMIN MODELS PAGE (add library models from a form; files go straight to Cloudflare R2)
#
# What this file does:
#   - Opens a form page at  /admin/models  on your Render service
#   - You pick the files, fill the boxes, click Save. Done.
#   - The page uploads the 3 files directly to Cloudflare R2 and adds the row in Supabase.
#   - It also creates the new columns (viewer_url, slug, tags) by itself the first time.
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
from flask import jsonify, request, Response

PREVIEW_BUCKET = os.environ.get("R2_PREVIEW_BUCKET", "cameo-previews")
PREVIEW_BASE = os.environ.get(
    "R2_PREVIEW_BASE_URL", "https://pub-5b01e64ba08c4a6eafb3de4a956cd45a.r2.dev"
).rstrip("/")

SLUG_OK = re.compile(r"^[a-z0-9][a-z0-9-]{0,59}$")   # short name: lowercase letters, numbers, dashes
EXT_OK = re.compile(r"^[a-z0-9]{2,5}$")              # file ending like glb, stl, webp
_columns_ready = [False]


def r2_client():
    return boto3.client(
        "s3",
        endpoint_url="https://%s.r2.cloudflarestorage.com" % os.environ["R2_ACCOUNT_ID"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
                # START: R2 CHECKSUM FIX (stops boto3 adding fields Cloudflare rejects)
        config=Config(signature_version="s3v4", request_checksum_calculation="when_required", response_checksum_validation="when_required"),
        # END: R2 CHECKSUM FIX
    )


def register_models_admin(app, cursor):
    def key_ok():
        key = os.environ.get("ADMIN_KEY", "")
        return bool(key) and hmac.compare_digest(request.headers.get("X-Admin-Key", ""), key)

    def ensure_columns(cur):
        if _columns_ready[0]:
            return
        cur.execute("alter table models add column if not exists viewer_url text")
        cur.execute("alter table models add column if not exists slug text")
        cur.execute("alter table models add column if not exists tags text")
        _columns_ready[0] = True

    @app.get("/admin/models")
    def admin_models_page():
        return Response(PAGE_HTML, mimetype="text/html")

    # Step 1 of saving: the page asks for permission slips (signed upload links) for each file.
    @app.post("/admin/models/sign")
    def admin_models_sign():
        if not key_ok():
            return jsonify({"error": "Wrong admin key."}), 403
        d = request.get_json(silent=True) or {}
        slug = str(d.get("slug", ""))
        if not SLUG_OK.match(slug):
            return jsonify({"error": "URL name can only use a-z, 0-9 and dashes."}), 400
        out = {}
        for item in d.get("files") or []:
            kind = item.get("kind")
            ext = str(item.get("ext", "")).lower().lstrip(".")
            ctype = str(item.get("type") or "application/octet-stream")[:100]
            if kind not in ("thumb", "viewer", "full") or not EXT_OK.match(ext):
                return jsonify({"error": "Bad file type."}), 400
            if kind == "full":
                bucket, key = os.environ["R2_BUCKET"], "%s.%s" % (slug, ext)
            elif kind == "thumb":
                bucket, key = PREVIEW_BUCKET, "thumbs/%s.%s" % (slug, ext)
            else:
                bucket, key = PREVIEW_BUCKET, "viewer/%s.glb" % slug
            url = r2_client().generate_presigned_url(
                "put_object",
                Params={"Bucket": bucket, "Key": key, "ContentType": ctype},
                ExpiresIn=1800,
            )
            out[kind] = {"url": url, "key": key}
        return jsonify(out)

    # Step 2 of saving: after the files are uploaded, write the row in the models table.
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
        try:
            price = int(d.get("price"))
        except (TypeError, ValueError):
            return jsonify({"error": "Credits must be a number (0 = free)."}), 400
        thumb_key = str(d.get("thumb_key", ""))
        viewer_key = str(d.get("viewer_key", ""))
        full_key = str(d.get("full_key", ""))
        if not SLUG_OK.match(slug) or not title or not category or price < 0 or price > 100000:
            return jsonify({"error": "Title, URL name, category and credits are needed."}), 400
        if not (thumb_key.startswith("thumbs/" + slug + ".") and viewer_key == "viewer/%s.glb" % slug
                and full_key.startswith(slug + ".")):
            return jsonify({"error": "File names do not match the URL name."}), 400
        preview_url = PREVIEW_BASE + "/" + thumb_key
        viewer_url = PREVIEW_BASE + "/" + viewer_key
        with cursor() as cur:
            ensure_columns(cur)
            cur.execute("select id from models where slug=%s", (slug,))
            row = cur.fetchone()
            if row:
                cur.execute(
                    "update models set title=%s, category=%s, price_credits=%s, tags=%s, description=%s,"
                    " preview_url=%s, viewer_url=%s, file_path=%s where id=%s",
                    (title, category, price, tags, description, preview_url, viewer_url, full_key, row[0]),
                )
                mid = row[0]
            else:
                cur.execute(
                    "insert into models(title,slug,category,price_credits,tags,description,preview_url,viewer_url,file_path)"
                    " values(%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id",
                    (title, slug, category, price, tags, description, preview_url, viewer_url, full_key),
                )
                mid = cur.fetchone()[0]
        return jsonify({"ok": True, "id": mid})

    @app.get("/admin/models/list")
    def admin_models_list():
        if not key_ok():
            return jsonify({"error": "Wrong admin key."}), 403
        with cursor() as cur:
            ensure_columns(cur)
            cur.execute("select id,title,slug,category,price_credits from models order by id desc")
            rows = cur.fetchall()
        return jsonify([{"id": r[0], "title": r[1], "slug": r[2], "category": r[3], "price": r[4]} for r in rows])

    # Removes only the library row. The files stay in R2 (delete them in Cloudflare if you want).
    @app.post("/admin/models/delete")
    def admin_models_delete():
        if not key_ok():
            return jsonify({"error": "Wrong admin key."}), 403
        try:
            mid = int((request.get_json(silent=True) or {}).get("id"))
        except (TypeError, ValueError):
            return jsonify({"error": "Bad id."}), 400
        with cursor() as cur:
            cur.execute("delete from models where id=%s", (mid,))
        return jsonify({"ok": True})


PAGE_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cameo3D - Add model</title>
<style>
:root{--bg:#101012;--card:#19191d;--line:#2c2c33;--text:#f2f2f4;--dim:#9a9aa6;--lime:#c9f23b;--pink:#f58cb4}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:16px/1.5 system-ui,Segoe UI,Arial,sans-serif}
main{max-width:760px;margin:0 auto;padding:28px 18px 80px}
h1{font-size:28px;margin:0 0 4px}
h2{font-size:19px;margin:34px 0 10px}
p.sub{color:var(--dim);margin:0 0 22px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px}
label{display:block;font-weight:600;margin:14px 0 5px}
.hint{font-weight:400;color:var(--dim);font-size:14px}
input,select,textarea{width:100%;background:#0e0e10;color:var(--text);border:1px solid var(--line);border-radius:9px;padding:10px 12px;font:inherit}
input:focus,select:focus,textarea:focus,button:focus-visible{outline:2px solid var(--lime);outline-offset:1px}
input[type=file]{padding:9px}
.row{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:560px){.row{grid-template-columns:1fr}}
button{font:inherit;font-weight:700;border:0;border-radius:10px;padding:12px 20px;cursor:pointer;background:var(--lime);color:#14160a}
button:disabled{opacity:.5;cursor:wait}
button.small{padding:6px 12px;font-size:14px;background:#2a2a31;color:var(--text)}
#status{margin-top:14px;min-height:24px;font-weight:600}
#status.err{color:var(--pink)}
table{width:100%;border-collapse:collapse}
td,th{text-align:left;padding:9px 6px;border-bottom:1px solid var(--line);font-size:15px}
th{color:var(--dim);font-weight:600}
pre{background:#0e0e10;border:1px solid var(--line);border-radius:9px;padding:12px;overflow:auto;font-size:13px}
</style></head>
<body><main>
<!-- START: ADMIN FORM - ADD MODEL -->
<h1>Add a model</h1>
<p class="sub">Fill the boxes, choose 3 files, click Save. The model appears in the library.</p>

<div class="card">
  <label for="key">Admin key <span class="hint">(the ADMIN_KEY from Render)</span></label>
  <input id="key" type="password" autocomplete="off">

  <label for="title">Title</label>
  <input id="title" maxlength="120" placeholder="Modern chair">

  <div class="row">
    <div>
      <label for="slug">URL name <span class="hint">(made from the title, you can change it)</span></label>
      <input id="slug" maxlength="60" placeholder="modern-chair">
    </div>
    <div>
      <label for="price">Credits <span class="hint">(0 = free, more than 0 = premium)</span></label>
      <input id="price" type="number" min="0" value="0">
    </div>
  </div>

  <label for="category">Category</label>
  <input id="category" list="cats" placeholder="Furniture">
  <datalist id="cats"><option>Characters</option><option>Props</option><option>Vehicles</option><option>Furniture</option></datalist>

  <label for="tags">Search words <span class="hint">(separate with commas)</span></label>
  <input id="tags" maxlength="300" placeholder="chair, seat, furniture, home, modern">

  <label for="description">Description</label>
  <textarea id="description" rows="3" maxlength="1000"></textarea>

  <label for="thumb">1. Thumbnail picture <span class="hint">(shows in the library grid; webp, png or jpg)</span></label>
  <input id="thumb" type="file" accept="image/*">

  <label for="viewer">2. Viewer model <span class="hint">(.glb, opens when someone clicks the card; leave empty to use the full file when it is a .glb)</span></label>
  <input id="viewer" type="file" accept=".glb">

  <label for="full">3. Full model for download <span class="hint">(private; .glb, .stl, .zip, .3mf)</span></label>
  <input id="full" type="file">

  <p style="margin:20px 0 0"><button id="go">Save model</button></p>
  <div id="status"></div>
</div>
<!-- END: ADMIN FORM - ADD MODEL -->

<!-- START: ADMIN LIST - MODELS IN LIBRARY -->
<h2>Models in the library</h2>
<div class="card">
  <p style="margin:0 0 10px"><button class="small" id="refresh">Show list</button></p>
  <table><thead><tr><th>Title</th><th>Category</th><th>Credits</th><th></th></tr></thead><tbody id="rows"></tbody></table>
</div>
<!-- END: ADMIN LIST - MODELS IN LIBRARY -->

<!-- START: ADMIN CORS BOX (one-time setup in Cloudflare) -->
<h2>One-time setup in Cloudflare</h2>
<div class="card">
  <p style="margin:0 0 10px">Uploads go straight from this page to Cloudflare, so both buckets must allow this page. Add this rule in <b>cameo-models</b> and also in <b>cameo-previews</b> (Bucket, Settings, CORS policy, Add). Keep the rule that is already in cameo-previews and add this one next to it.</p>
  <pre id="cors"></pre>
</div>
<!-- END: ADMIN CORS BOX -->

<script>
// START: ADMIN PAGE SCRIPT
const $ = id => document.getElementById(id);
$("cors").textContent = JSON.stringify([{AllowedOrigins:[location.origin],AllowedMethods:["PUT"],AllowedHeaders:["*"],MaxAgeSeconds:3600}], null, 2);

function say(text, bad){ const s=$("status"); s.textContent=text; s.className = bad ? "err" : ""; }
function extOf(f){ const m=/\.([A-Za-z0-9]+)$/.exec(f.name); return m ? m[1].toLowerCase() : ""; }

async function api(path, method, body){
  const r = await fetch(path, {method, headers:{"Content-Type":"application/json","X-Admin-Key":$("key").value.trim()}, body: body ? JSON.stringify(body) : undefined});
  const j = await r.json().catch(()=>({}));
  if(!r.ok) throw new Error(j.error || ("Server error " + r.status));
  return j;
}

function put(url, file, type, label){
  return new Promise((ok, fail) => {
    const x = new XMLHttpRequest();
    x.open("PUT", url);
    x.setRequestHeader("Content-Type", type);
    x.upload.onprogress = e => { if(e.lengthComputable) say(label + ": " + Math.round(e.loaded/e.total*100) + "%"); };
    x.onload = () => x.status < 300 ? ok() : fail(new Error(label + " upload failed (" + x.status + ")."));
    x.onerror = () => fail(new Error(label + " was blocked. Add the CORS rule from the bottom of this page to both buckets."));
    x.send(file);
  });
}

$("title").addEventListener("input", () => {
  if(!$("slug").dataset.touched) $("slug").value = $("title").value.toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/^-+|-+$/g,"").slice(0,60);
});
$("slug").addEventListener("input", () => { $("slug").dataset.touched = "1"; });

$("go").onclick = async () => {
  try{
    const thumb=$("thumb").files[0], full=$("full").files[0], viewer=$("viewer").files[0];
    const slug=$("slug").value.trim(), title=$("title").value.trim();
    if(!title || !slug) throw new Error("Write a title first.");
    if(!$("category").value.trim()) throw new Error("Write a category.");
    if(!thumb || !full) throw new Error("Choose the thumbnail picture and the full model file.");
    const fullExt=extOf(full), thumbExt=extOf(thumb);
    if(!viewer && fullExt !== "glb") throw new Error("The viewer needs a .glb file. Choose one in box 2.");
    const viewerFile = viewer || full;
    const thumbType = thumb.type || "image/webp";
    $("go").disabled = true;
    say("Preparing upload...");
    const signed = await api("/admin/models/sign", "POST", {slug, files:[
      {kind:"thumb", ext:thumbExt, type:thumbType},
      {kind:"viewer", ext:"glb", type:"model/gltf-binary"},
      {kind:"full", ext:fullExt, type:"application/octet-stream"}]});
    await put(signed.thumb.url, thumb, thumbType, "Thumbnail");
    await put(signed.viewer.url, viewerFile, "model/gltf-binary", "Viewer model");
    await put(signed.full.url, full, "application/octet-stream", "Full model");
    await api("/admin/models/save", "POST", {slug, title, category:$("category").value, price:$("price").value,
      tags:$("tags").value, description:$("description").value,
      thumb_key:signed.thumb.key, viewer_key:signed.viewer.key, full_key:signed.full.key});
    say("Saved. The model is in the library.");
    ["title","slug","tags","description","thumb","viewer","full"].forEach(i => { $(i).value = ""; });
    delete $("slug").dataset.touched;
    loadList();
  }catch(e){ say(e.message, true); }
  finally{ $("go").disabled = false; }
};

async function loadList(){
  try{
    const rows = await api("/admin/models/list", "GET");
    const body = $("rows"); body.innerHTML = "";
    rows.forEach(m => {
      const tr = document.createElement("tr");
      [m.title, m.category || "", m.price === 0 ? "Free" : String(m.price)].forEach(t => {
        const td = document.createElement("td"); td.textContent = t; tr.appendChild(td);
      });
      const td = document.createElement("td");
      const b = document.createElement("button"); b.className = "small"; b.textContent = "Delete";
      b.onclick = async () => {
        if(!confirm("Remove " + m.title + " from the library? The files stay in Cloudflare.")) return;
        try{ await api("/admin/models/delete", "POST", {id:m.id}); loadList(); }catch(e){ say(e.message, true); }
      };
      td.appendChild(b); tr.appendChild(td); body.appendChild(tr);
    });
  }catch(e){ say(e.message, true); }
}
$("refresh").onclick = loadList;
// END: ADMIN PAGE SCRIPT
</script>
</main></body></html>"""
# END: ADMIN MODELS PAGE
