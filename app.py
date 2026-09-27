"""
Small web app: user uploads a photo, it calls your RunPod endpoint,
and shows the resulting 3D model on the page.

DEPLOY THIS on Render.com (steps given separately). This file plus
requirements.txt are everything needed.
"""

import os
import base64
import requests
from flask import Flask, request, jsonify, render_template_string

app = Flask(__name__)

# ---- FILL THESE IN ----
# The API key is read from Render's "Environment Variables" setting,
# NOT written here directly - this keeps it out of GitHub entirely.
RUNPOD_API_KEY = os.environ.get("rpa_5PWJZZJE7RMK679DCS5L6P8D1INRHP8Z25JU8E10tp9zfp")
ENDPOINT_ID = "egysfj217v2p31"
# -------------------------------------------------------

BASE_URL = f"https://api.runpod.ai/v2/{ENDPOINT_ID}"
HEADERS = {
    "Authorization": f"Bearer {RUNPOD_API_KEY}",
    "Content-Type": "application/json",
}

PAGE = """
<!DOCTYPE html>
<html>
<head>
    <title>gb.com - Image to 3D</title>
    <script type="module" src="https://cdnjs.cloudflare.com/ajax/libs/model-viewer/3.4.0/model-viewer.min.js"></script>
    <style>
        body { font-family: sans-serif; max-width: 600px; margin: 40px auto; text-align: center; }
        model-viewer { width: 100%; height: 400px; background: #f2f2f2; }
        #status { margin: 20px 0; color: #555; }
    </style>
</head>
<body>
    <h1>Image to 3D Model</h1>
    <input type="file" id="fileInput" accept="image/*">
    <button onclick="submitImage()">Generate 3D Model</button>
    <div id="status"></div>
    <model-viewer id="viewer" camera-controls auto-rotate style="display:none;"></model-viewer>

    <script>
    async function submitImage() {
        const fileInput = document.getElementById('fileInput');
        const status = document.getElementById('status');
        const viewer = document.getElementById('viewer');

        if (!fileInput.files.length) {
            status.innerText = "Please choose an image first.";
            return;
        }

        status.innerText = "Uploading...";
        viewer.style.display = "none";

        const file = fileInput.files[0];
        const reader = new FileReader();
        reader.onload = async function() {
            const base64Data = reader.result.split(',')[1];

            const submitRes = await fetch('/submit', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({image_base64: base64Data})
            });
            const submitData = await submitRes.json();
            const jobId = submitData.job_id;

            status.innerText = "Generating your 3D model (1-4 minutes)...";

            // Poll every 5 seconds until done
            const poll = setInterval(async () => {
                const statusRes = await fetch('/status/' + jobId);
                const statusData = await statusRes.json();

                if (statusData.status === "COMPLETED") {
                    clearInterval(poll);
                    status.innerText = "Done!";
                    viewer.src = "data:model/gltf-binary;base64," + statusData.model_base64;
                    viewer.style.display = "block";
                } else if (statusData.status === "FAILED") {
                    clearInterval(poll);
                    status.innerText = "Generation failed. Please try another image.";
                } else {
                    status.innerText = "Status: " + statusData.status + " ...";
                }
            }, 5000);
        };
        reader.readAsDataURL(file);
    }
    </script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(PAGE)


@app.route("/submit", methods=["POST"])
def submit():
    data = request.get_json()
    image_b64 = data["image_base64"]

    response = requests.post(
        f"{BASE_URL}/run",
        headers=HEADERS,
        json={"input": {"image_base64": image_b64, "prompt": None}},
    )
    response.raise_for_status()
    job_id = response.json()["id"]
    return jsonify({"job_id": job_id})


@app.route("/status/<job_id>")
def status(job_id):
    response = requests.get(f"{BASE_URL}/status/{job_id}", headers=HEADERS)
    response.raise_for_status()
    data = response.json()

    result = {"status": data["status"]}
    if data["status"] == "COMPLETED":
        result["model_base64"] = data["output"]["model_base64"]
    elif data["status"] == "FAILED":
        result["error"] = data.get("error")

    return jsonify(result)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
