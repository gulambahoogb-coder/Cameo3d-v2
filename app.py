import os
import time
import requests

from flask import Flask, request, jsonify, render_template_string

app = Flask(__name__)

# ============================================================
# RUNPOD CONFIG
# ============================================================

RUNPOD_API_KEY = os.environ.get("RUNPOD_API_KEY")
ENDPOINT_ID = "egysfj217v2p31"

BASE_URL = f"https://api.runpod.ai/v2/{ENDPOINT_ID}"

HEADERS = {
    "Authorization": f"Bearer {RUNPOD_API_KEY}",
    "Content-Type": "application/json",
}


# ============================================================
# WORKSPACE PAGE
# ============================================================

PAGE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">

    <title>Cameo3D — AI 3D Generator</title>

    <script
        type="module"
        src="https://cdnjs.cloudflare.com/ajax/libs/model-viewer/3.4.0/model-viewer.min.js">
    </script>

    <style>

        * {
            box-sizing: border-box;
        }

        body {
            margin: 0;
            background: #111111;
            color: #eeeeee;
            font-family:
                Inter,
                -apple-system,
                BlinkMacSystemFont,
                "Segoe UI",
                sans-serif;
            height: 100vh;
            overflow: hidden;
        }

        /* ====================================================
           TOP BAR
        ==================================================== */

        .topbar {
            height: 68px;
            border-bottom: 1px solid #292929;
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0 24px;
            background: #0d0d0d;
        }

        .brand {
            display: flex;
            align-items: center;
            gap: 12px;
            font-size: 21px;
            font-weight: 700;
        }

        .brand-icon {
            width: 34px;
            height: 34px;
            border-radius: 10px;
            background: linear-gradient(135deg, #c9ff3d, #ff9bc8);
            display: flex;
            align-items: center;
            justify-content: center;
            color: #111;
            font-weight: 900;
        }

        .top-actions {
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .credits {
            padding: 9px 14px;
            border-radius: 10px;
            background: #1d1d1d;
            color: #d7ff45;
            font-size: 14px;
        }

        .upgrade {
            border: 0;
            padding: 10px 17px;
            border-radius: 10px;
            background: #8dff4e;
            color: #111;
            font-weight: 700;
            cursor: pointer;
        }

        /* ====================================================
           MAIN LAYOUT
        ==================================================== */

        .workspace {
            height: calc(100vh - 68px);
            display: grid;
            grid-template-columns: 72px 360px 1fr 300px;
        }

        /* ====================================================
           LEFT NAV
        ==================================================== */

        .sidebar {
            border-right: 1px solid #292929;
            background: #101010;
            display: flex;
            flex-direction: column;
            align-items: center;
            padding-top: 15px;
            gap: 8px;
        }

        .side-item {
            width: 55px;
            min-height: 62px;
            border-radius: 12px;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            gap: 5px;
            color: #9a9a9a;
            font-size: 11px;
            cursor: pointer;
        }

        .side-item:hover {
            background: #1c1c1c;
            color: white;
        }

        .side-item.active {
            color: #caff4b;
            background: #1c1c1c;
        }

        .side-icon {
            font-size: 21px;
        }

        /* ====================================================
           CONTROL PANEL
        ==================================================== */

        .controls {
            border-right: 1px solid #292929;
            background: #151515;
            padding: 20px;
            overflow-y: auto;
        }

        .mode-tabs {
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            background: #1d1d1d;
            border-radius: 13px;
            padding: 4px;
            margin-bottom: 18px;
        }

        .mode {
            padding: 12px 4px;
            text-align: center;
            border-radius: 10px;
            color: #999;
            font-size: 13px;
            cursor: pointer;
        }

        .mode.active {
            background: #292929;
            color: white;
        }

        .section-title {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin: 14px 0 10px;
            font-size: 14px;
            font-weight: 600;
        }

        .quality {
            border: 1px solid #2b2b2b;
            border-radius: 12px;
            padding: 15px;
            background: #1b1b1b;
            margin-bottom: 18px;
        }

        .quality-title {
            font-weight: 700;
            color: #caff4b;
            margin-bottom: 5px;
        }

        .quality-sub {
            font-size: 12px;
            color: #898989;
        }

        /* ====================================================
           UPLOAD
        ==================================================== */

        .upload-box {
            border: 1px dashed #444;
            border-radius: 14px;
            min-height: 185px;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            text-align: center;
            cursor: pointer;
            background: #181818;
            transition: 0.2s;
        }

        .upload-box:hover {
            border-color: #caff4b;
            background: #1d1d1d;
        }

        .upload-icon {
            font-size: 38px;
            margin-bottom: 10px;
            opacity: .7;
        }

        .upload-title {
            font-size: 14px;
            font-weight: 600;
        }

        .upload-sub {
            margin-top: 8px;
            color: #777;
            font-size: 11px;
            line-height: 1.5;
        }

        #fileInput {
            display: none;
        }

        .preview {
            width: 100%;
            max-height: 190px;
            object-fit: contain;
            border-radius: 12px;
            display: none;
            margin-top: 10px;
            background: #222;
        }

        /* ====================================================
           GENERATE BUTTON
        ==================================================== */

        .generate-button {
            width: 100%;
            border: 0;
            border-radius: 13px;
            padding: 16px;
            margin-top: 18px;

            background:
                linear-gradient(
                    100deg,
                    #bfff3f,
                    #f99bc4
                );

            color: #111;
            font-size: 15px;
            font-weight: 800;
            cursor: pointer;
            transition: transform .15s;
        }

        .generate-button:hover {
            transform: translateY(-1px);
        }

        .generate-button:disabled {
            opacity: .45;
            cursor: not-allowed;
            transform: none;
        }

        /* ====================================================
           CENTER VIEWER
        ==================================================== */

        .viewer-area {
            position: relative;
            background:
                radial-gradient(
                    circle at center,
                    #292929 0%,
                    #1a1a1a 38%,
                    #111111 80%
                );
            overflow: hidden;
        }

        .viewer-header {
            position: absolute;
            left: 22px;
            right: 22px;
            top: 18px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            z-index: 5;
        }

        .viewer-title {
            font-size: 14px;
            color: #aaa;
        }

        .viewer-tools {
            display: flex;
            gap: 8px;
        }

        .tool {
            width: 36px;
            height: 36px;
            border: 1px solid #333;
            background: #191919;
            border-radius: 9px;
            color: #ccc;
            cursor: pointer;
        }

        model-viewer {
            width: 100%;
            height: 100%;
            background: transparent;
            display: none;
        }

        .empty-view {
            position: absolute;
            inset: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            flex-direction: column;
            pointer-events: none;
        }

        .empty-symbol {
            font-size: 64px;
            margin-bottom: 22px;
            filter: drop-shadow(0 0 18px rgba(202,255,75,.2));
        }

        .empty-title {
            font-size: 26px;
            font-weight: 700;
        }

        .empty-sub {
            color: #777;
            margin-top: 8px;
            font-size: 14px;
        }

        /* ====================================================
           RIGHT ASSET PANEL
        ==================================================== */

        .assets {
            border-left: 1px solid #292929;
            background: #151515;
            padding: 18px;
            overflow-y: auto;
        }

        .asset-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
        }

        .asset-title {
            font-weight: 700;
        }

        .asset-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
        }

        .asset-card {
            height: 125px;
            background: #202020;
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #777;
            font-size: 12px;
            border: 1px solid #292929;
        }

        .asset-card:hover {
            border-color: #caff4b;
        }

        /* ====================================================
           STATUS
        ==================================================== */

        #status {
            margin-top: 12px;
            font-size: 12px;
            color: #999;
            min-height: 18px;
            text-align: center;
        }

        .loading {
            color: #caff4b !important;
        }

        .error {
            color: #ff7777 !important;
        }

        /* ====================================================
           RESPONSIVE
        ==================================================== */

        @media (max-width: 1000px) {

            .workspace {
                grid-template-columns: 64px 320px 1fr;
            }

            .assets {
                display: none;
            }
        }

        @media (max-width: 700px) {

            body {
                overflow: auto;
            }

            .workspace {
                display: block;
                height: auto;
            }

            .sidebar {
                display: none;
            }

            .controls {
                border-right: 0;
                min-height: auto;
            }

            .viewer-area {
                height: 500px;
            }
        }

    </style>
</head>

<body>

<!-- ==========================================================
     TOP BAR
=========================================================== -->

<header class="topbar">

    <div class="brand">
        <div class="brand-icon">C</div>
        Cameo3D
    </div>

    <div class="top-actions">
        <div class="credits">
            ✦ 100 Credits
        </div>

        <button class="upgrade">
            Upgrade
        </button>
    </div>

</header>


<!-- ==========================================================
     WORKSPACE
=========================================================== -->

<div class="workspace">

    <!-- LEFT NAV -->

    <aside class="sidebar">

        <div class="side-item active">
            <div class="side-icon">◈</div>
            Model
        </div>

        <div class="side-item">
            <div class="side-icon">▣</div>
            Image
        </div>

        <div class="side-item">
            <div class="side-icon">◇</div>
            Texture
        </div>

        <div class="side-item">
            <div class="side-icon">◫</div>
            Animate
        </div>

    </aside>


    <!-- CONTROL PANEL -->

    <section class="controls">

        <div class="mode-tabs">

            <div class="mode active">
                Image
            </div>

            <div class="mode">
                Text
            </div>

            <div class="mode">
                Multi-view
            </div>

        </div>


        <div class="section-title">
            <span>Generation Model</span>
        </div>

        <div class="quality">

            <div class="quality-title">
                Cameo3D AI
            </div>

            <div class="quality-sub">
                High detail image-to-3D generation
            </div>

        </div>


        <div class="section-title">
            <span>Input Image</span>
        </div>


        <label class="upload-box" for="fileInput">

            <div id="uploadContent">

                <div class="upload-icon">
                    ▧
                </div>

                <div class="upload-title">
                    Click / Drag & Drop / Paste Image
                </div>

                <div class="upload-sub">
                    PNG, JPG, JPEG or WEBP<br>
                    Maximum recommended size: 20MB
                </div>

            </div>

            <img id="preview" class="preview">

        </label>

        <input
            type="file"
            id="fileInput"
            accept="image/png,image/jpeg,image/webp"
        >


        <button
            class="generate-button"
            id="generateButton"
            onclick="submitImage()"
            disabled
        >
            ✦ Generate 3D Model
        </button>

        <div id="status"></div>

    </section>


    <!-- 3D VIEWER -->

    <main class="viewer-area">

        <div class="viewer-header">

            <div class="viewer-title">
                3D Preview
            </div>

            <div class="viewer-tools">

                <button class="tool" onclick="resetViewer()">
                    ↻
                </button>

                <button class="tool" onclick="toggleAutoRotate()">
                    ◉
                </button>

            </div>

        </div>


        <div
            class="empty-view"
            id="emptyView"
        >

            <div class="empty-symbol">
                ◆
            </div>

            <div class="empty-title">
                What will you create today?
            </div>

            <div class="empty-sub">
                Upload an image and generate your 3D model
            </div>

        </div>


        <model-viewer
            id="viewer"
            camera-controls
            auto-rotate
            shadow-intensity="1"
            exposure="1"
            environment-image="neutral"
        >
        </model-viewer>

    </main>


    <!-- ASSETS -->

    <aside class="assets">

        <div class="asset-header">

            <div class="asset-title">
                My Assets
            </div>

            <div style="color:#caff4b">
                +
            </div>

        </div>


        <div class="asset-grid">

            <div class="asset-card">
                Your models
            </div>

            <div class="asset-card">
                Your models
            </div>

            <div class="asset-card">
                Your models
            </div>

            <div class="asset-card">
                Your models
            </div>

        </div>

    </aside>

</div>


<script>

let selectedFile = null;
let autoRotate = true;


/* ============================================================
   IMAGE SELECTION
============================================================ */

const fileInput =
    document.getElementById("fileInput");

const preview =
    document.getElementById("preview");

const uploadContent =
    document.getElementById("uploadContent");

const generateButton =
    document.getElementById("generateButton");

const statusElement =
    document.getElementById("status");


fileInput.addEventListener("change", function() {

    if (!this.files.length) {
        return;
    }

    selectedFile = this.files[0];

    showPreview(selectedFile);

});


function showPreview(file) {

    const reader = new FileReader();

    reader.onload = function(event) {

        preview.src = event.target.result;

        preview.style.display = "block";

        uploadContent.style.display = "none";

        generateButton.disabled = false;

    };

    reader.readAsDataURL(file);
}


/* ============================================================
   GENERATE MODEL
============================================================ */

async function submitImage() {

    if (!selectedFile) {

        statusElement.innerText =
            "Please choose an image first.";

        return;
    }


    generateButton.disabled = true;

    statusElement.className = "loading";

    statusElement.innerText =
        "Uploading your image...";


    try {

        const base64Data =
            await fileToBase64(selectedFile);


        const submitResponse =
            await fetch("/submit", {

                method: "POST",

                headers: {
                    "Content-Type": "application/json"
                },

                body: JSON.stringify({
                    image_base64: base64Data
                })

            });


        const submitData =
            await submitResponse.json();


        if (!submitResponse.ok) {

            throw new Error(
                submitData.error ||
                "Unable to start generation."
            );

        }


        const jobId =
            submitData.job_id;


        statusElement.innerText =
            "Generating your 3D model...";


        await pollJob(jobId);

    }

    catch (error) {

        console.error(error);

        statusElement.className = "error";

        statusElement.innerText =
            error.message ||
            "Something went wrong.";

        generateButton.disabled = false;

    }

}


/* ============================================================
   FILE -> BASE64
============================================================ */

function fileToBase64(file) {

    return new Promise(function(resolve, reject) {

        const reader =
            new FileReader();

        reader.onload =
            function() {

                const result =
                    reader.result;

                resolve(
                    result.split(",")[1]
                );

            };

        reader.onerror =
            reject;

        reader.readAsDataURL(file);

    });

}


/* ============================================================
   POLL RUNPOD JOB
============================================================ */

async function pollJob(jobId) {

    let attempts = 0;

    const maxAttempts = 180;


    while (attempts < maxAttempts) {

        attempts++;


        const response =
            await fetch(
                "/status/" + jobId
            );


        const data =
            await response.json();


        if (!response.ok) {

            throw new Error(
                data.error ||
                "Unable to check generation status."
            );

        }


        if (data.status === "COMPLETED") {

            statusElement.className = "";

            statusElement.innerText =
                "✓ Your 3D model is ready!";


            const viewer =
                document.getElementById("viewer");

            const emptyView =
                document.getElementById("emptyView");


            viewer.src =
                "data:model/gltf-binary;base64," +
                data.model_base64;


            viewer.style.display =
                "block";

            emptyView.style.display =
                "none";


            generateButton.disabled =
                false;


            return;
        }


        if (data.status === "FAILED") {

            throw new Error(
                data.error ||
                "3D generation failed."
            );

        }


        if (data.status === "CANCELLED") {

            throw new Error(
                "Generation was cancelled."
            );

        }


        statusElement.innerText =
            "Generating 3D model • " +
            data.status;


        await sleep(5000);

    }


    throw new Error(
        "Generation is taking longer than expected."
    );

}


/* ============================================================
   UTILITIES
============================================================ */

function sleep(ms) {

    return new Promise(
        resolve => setTimeout(resolve, ms)
    );

}


function resetViewer() {

    const viewer =
        document.getElementById("viewer");

    viewer.cameraOrbit =
        "0deg 75deg 105%";

}


function toggleAutoRotate() {

    const viewer =
        document.getElementById("viewer");

    autoRotate =
        !autoRotate;

    viewer.autoRotate =
        autoRotate;

}

</script>

</body>
</html>
"""


# ============================================================
# HOME / WORKSPACE
# ============================================================

@app.route("/")
def index():
    return render_template_string(PAGE)


@app.route("/workspace")
def workspace():
    return render_template_string(PAGE)


# ============================================================
# SUBMIT IMAGE TO RUNPOD
# ============================================================

@app.route("/submit", methods=["POST"])
def submit():

    try:

        if not RUNPOD_API_KEY:
            return jsonify({
                "error": "RUNPOD_API_KEY is not configured on Render."
            }), 500


        data = request.get_json(silent=True)

        if not data:
            return jsonify({
                "error": "No JSON data received."
            }), 400


        image_b64 = data.get("image_base64")

        if not image_b64:
            return jsonify({
                "error": "No image was provided."
            }), 400


        response = requests.post(

            f"{BASE_URL}/run",

            headers=HEADERS,

            json={
                "input": {
                    "image_base64": image_b64
                }
            },

            timeout=60

        )


        if not response.ok:

            return jsonify({
                "error":
                    f"RunPod error {response.status_code}: "
                    f"{response.text}"
            }), 502


        result =
            response.json()


        job_id =
            result.get("id")


        if not job_id:

            return jsonify({
                "error": "RunPod did not return a job ID.",
                "runpod_response": result
            }), 502


        return jsonify({
            "job_id": job_id
        })


    except requests.RequestException as e:

        return jsonify({
            "error":
                f"Could not connect to RunPod: {str(e)}"
        }), 502


    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500


# ============================================================
# CHECK RUNPOD STATUS
# ============================================================

@app.route("/status/<job_id>")
def status(job_id):

    try:

        response = requests.get(

            f"{BASE_URL}/status/{job_id}",

            headers=HEADERS,

            timeout=30

        )


        if not response.ok:

            return jsonify({
                "error":
                    f"RunPod error {response.status_code}: "
                    f"{response.text}"
            }), 502


        data =
            response.json()


        job_status =
            data.get("status", "UNKNOWN")


        result = {
            "status": job_status
        }


        if job_status == "COMPLETED":

            output =
                data.get("output", {})


            model_base64 =
                output.get("model_base64")


            if not model_base64:

                return jsonify({
                    "status": "FAILED",
                    "error":
                        "RunPod completed the job but returned no model."
                })


            result["model_base64"] =
                model_base64


        elif job_status == "FAILED":

            result["error"] =
                data.get(
                    "error",
                    "Unknown RunPod error."
                )


        return jsonify(result)


    except requests.RequestException as e:

        return jsonify({
            "error":
                f"Could not connect to RunPod: {str(e)}"
        }), 502


    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route("/health")
def health():

    return jsonify({
        "status": "ok",
        "service": "Cameo3D",
        "runpod_configured": bool(RUNPOD_API_KEY)
    })


# ============================================================
# LOCAL DEVELOPMENT
# ============================================================

if __name__ == "__main__":

    port =
        int(
            os.environ.get(
                "PORT",
                5000
            )
        )

    app.run(
        host="0.0.0.0",
        port=port
    )
