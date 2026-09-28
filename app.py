"""
Cameo3D - Image to 3D Web App

Frontend:
    User uploads an image.

Backend:
    Sends the image to RunPod Hunyuan3D-2.1.

Result:
    Displays the generated GLB model in the browser.
"""

import os
import base64
import requests

from flask import Flask, request, jsonify, render_template_string


app = Flask(__name__)


# ============================================================
# RUNPOD CONFIGURATION
# ============================================================

RUNPOD_API_KEY = os.environ.get("RUNPOD_API_KEY")
ENDPOINT_ID = "egysfj217v2p31"

BASE_URL = f"https://api.runpod.ai/v2/{ENDPOINT_ID}"

HEADERS = {
    "Authorization": f"Bearer {RUNPOD_API_KEY}",
    "Content-Type": "application/json",
}


# ============================================================
# FRONTEND
# ============================================================

PAGE = """
<!DOCTYPE html>
<html lang="en">

<head>

    <meta charset="UTF-8">

    <meta name="viewport"
          content="width=device-width, initial-scale=1.0">

    <title>Cameo3D - Image to 3D</title>

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
            padding: 40px 20px;
            font-family: Arial, sans-serif;
            background: #f7f7f7;
            color: #222;
        }

        .container {
            max-width: 800px;
            margin: auto;
            text-align: center;
        }

        h1 {
            margin-bottom: 10px;
        }

        .subtitle {
            color: #666;
            margin-bottom: 30px;
        }

        .upload-box {
            background: white;
            padding: 30px;
            border-radius: 16px;
            box-shadow: 0 5px 25px rgba(0,0,0,0.08);
        }

        input[type="file"] {
            width: 100%;
            padding: 12px;
            margin-bottom: 20px;
        }

        button {
            border: none;
            background: #111;
            color: white;
            padding: 14px 25px;
            border-radius: 10px;
            cursor: pointer;
            font-size: 16px;
        }

        button:hover {
            background: #333;
        }

        button:disabled {
            background: #999;
            cursor: not-allowed;
        }

        #status {
            margin: 25px 0;
            color: #555;
            min-height: 24px;
        }

        model-viewer {
            width: 100%;
            height: 550px;
            background: #e9e9e9;
            border-radius: 16px;
            display: none;
        }

        .error {
            color: #d00 !important;
        }

        .success {
            color: #168000 !important;
        }

    </style>

</head>


<body>

<div class="container">

    <h1>Cameo3D</h1>

    <div class="subtitle">
        Turn your image into a 3D model
    </div>


    <div class="upload-box">

        <input
            type="file"
            id="fileInput"
            accept="image/*"
        >

        <br>

        <button
            id="generateButton"
            onclick="submitImage()">
            Generate 3D Model
        </button>

        <div id="status"></div>

        <model-viewer
            id="viewer"
            camera-controls
            auto-rotate
            shadow-intensity="1"
            exposure="1">
        </model-viewer>

    </div>

</div>


<script>

async function submitImage() {

    const fileInput = document.getElementById("fileInput");
    const status = document.getElementById("status");
    const viewer = document.getElementById("viewer");
    const button = document.getElementById("generateButton");


    // --------------------------------------------------------
    // CHECK FILE
    // --------------------------------------------------------

    if (!fileInput.files.length) {

        status.innerText = "Please choose an image first.";
        status.className = "error";

        return;
    }


    const file = fileInput.files[0];


    // --------------------------------------------------------
    // UI
    // --------------------------------------------------------

    button.disabled = true;

    status.className = "";
    status.innerText = "Uploading image...";

    viewer.style.display = "none";


    try {

        // ----------------------------------------------------
        // CONVERT IMAGE TO BASE64
        // ----------------------------------------------------

        const base64Data = await fileToBase64(file);


        // ----------------------------------------------------
        // SEND TO FLASK
        // ----------------------------------------------------

        const submitRes = await fetch("/submit", {

            method: "POST",

            headers: {
                "Content-Type": "application/json"
            },

            body: JSON.stringify({
                image_base64: base64Data
            })

        });


        const submitData = await submitRes.json();


        if (!submitRes.ok) {

            throw new Error(
                submitData.error || "Failed to submit image."
            );

        }


        const jobId = submitData.job_id;


        if (!jobId) {

            throw new Error("RunPod did not return a job ID.");

        }


        status.innerText =
            "3D generation started. This may take 1-4 minutes...";


        // ----------------------------------------------------
        // START POLLING
        // ----------------------------------------------------

        pollJob(jobId);


    } catch (error) {

        console.error(error);

        status.innerText =
            "Error: " + error.message;

        status.className = "error";

        button.disabled = false;

    }

}


// ============================================================
// FILE -> BASE64
// ============================================================

function fileToBase64(file) {

    return new Promise((resolve, reject) => {

        const reader = new FileReader();


        reader.onload = function() {

            const result = reader.result;

            // Remove:
            // data:image/png;base64,
            // data:image/jpeg;base64,
            // etc.

            const base64 =
                result.split(",")[1];

            resolve(base64);

        };


        reader.onerror = function() {

            reject(
                new Error("Could not read image.")
            );

        };


        reader.readAsDataURL(file);

    });

}


// ============================================================
// POLL RUNPOD JOB
// ============================================================

async function pollJob(jobId) {

    const status =
        document.getElementById("status");

    const viewer =
        document.getElementById("viewer");

    const button =
        document.getElementById("generateButton");


    const interval =
        setInterval(async () => {

            try {

                const response =
                    await fetch(
                        "/status/" + jobId
                    );


                const data =
                    await response.json();


                if (!response.ok) {

                    throw new Error(
                        data.error ||
                        "Could not check job status."
                    );

                }


                console.log("Job status:", data);


                // ------------------------------------------------
                // COMPLETED
                // ------------------------------------------------

                if (data.status === "COMPLETED") {

                    clearInterval(interval);

                    status.innerText =
                        "Done! Your 3D model is ready.";

                    status.className =
                        "success";


                    if (!data.model_base64) {

                        throw new Error(
                            "RunPod completed the job but returned no model."
                        );

                    }


                    // Convert base64 GLB into a Blob.
                    const binaryString =
                        atob(data.model_base64);

                    const len =
                        binaryString.length;

                    const bytes =
                        new Uint8Array(len);


                    for (let i = 0; i < len; i++) {

                        bytes[i] =
                            binaryString.charCodeAt(i);

                    }


                    const blob =
                        new Blob(
                            [bytes],
                            {
                                type: "model/gltf-binary"
                            }
                        );


                    const modelURL =
                        URL.createObjectURL(blob);


                    viewer.src =
                        modelURL;

                    viewer.style.display =
                        "block";


                    button.disabled =
                        false;

                }


                // ------------------------------------------------
                // FAILED
                // ------------------------------------------------

                else if (data.status === "FAILED") {

                    clearInterval(interval);

                    console.error(
                        "RunPod error:",
                        data.error
                    );


                    status.innerText =
                        "3D generation failed: " +
                        (data.error || "Unknown error");


                    status.className =
                        "error";


                    button.disabled =
                        false;

                }


                // ------------------------------------------------
                // OTHER STATES
                // ------------------------------------------------

                else {

                    status.innerText =
                        "Generating 3D model... Status: " +
                        data.status;

                }


            } catch (error) {

                clearInterval(interval);

                console.error(error);

                status.innerText =
                    "Error: " + error.message;

                status.className =
                    "error";

                button.disabled =
                    false;

            }

        }, 5000);

}


</script>

</body>

</html>
"""


# ============================================================
# HOME PAGE
# ============================================================

@app.route("/")
def index():

    return render_template_string(PAGE)


# ============================================================
# SUBMIT IMAGE TO RUNPOD
# ============================================================

@app.route("/submit", methods=["POST"])
def submit():

    try:

        # ----------------------------------------------------
        # CHECK API KEY
        # ----------------------------------------------------

        if not RUNPOD_API_KEY:

            return jsonify({
                "error": "RUNPOD_API_KEY is not configured on Render."
            }), 500


        # ----------------------------------------------------
        # READ REQUEST
        # ----------------------------------------------------

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


        # ----------------------------------------------------
        # SEND JOB TO RUNPOD
        # ----------------------------------------------------

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


        # ----------------------------------------------------
        # CHECK RUNPOD RESPONSE
        # ----------------------------------------------------

        if not response.ok:

            print(
                "RunPod submit error:",
                response.status_code,
                response.text
            )


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
                "error":
                    "RunPod did not return a job ID.",
                "runpod_response":
                    result
            }), 502


        print(
            "RunPod job submitted:",
            job_id
        )


        return jsonify({
            "job_id": job_id
        })


    except requests.RequestException as e:

        print(
            "RunPod connection error:",
            str(e)
        )


        return jsonify({
            "error":
                "Could not connect to RunPod: " +
                str(e)
        }), 502


    except Exception as e:

        print(
            "Submit error:",
            str(e)
        )


        return jsonify({
            "error":
                str(e)
        }), 500


# ============================================================
# CHECK RUNPOD JOB STATUS
# ============================================================

@app.route("/status/<job_id>")
def status(job_id):

    try:

        # ----------------------------------------------------
        # CHECK API KEY
        # ----------------------------------------------------

        if not RUNPOD_API_KEY:

            return jsonify({
                "error":
                    "RUNPOD_API_KEY is not configured."
            }), 500


        # ----------------------------------------------------
        # REQUEST STATUS
        # ----------------------------------------------------

        response = requests.get(

            f"{BASE_URL}/status/{job_id}",

            headers=HEADERS,

            timeout=60

        )


        if not response.ok:

            print(
                "RunPod status error:",
                response.status_code,
                response.text
            )


            return jsonify({
                "error":
                    f"RunPod error {response.status_code}: "
                    f"{response.text}"
            }), 502


        data =
            response.json()


        current_status =
            data.get("status")


        result = {
            "status": current_status
        }


        # ----------------------------------------------------
        # COMPLETED
        # ----------------------------------------------------

        if current_status == "COMPLETED":

            output =
                data.get("output", {})


            model_base64 =
                output.get("model_base64")


            if not model_base64:

                return jsonify({
                    "status": "FAILED",
                    "error":
                        "RunPod completed but no model was returned."
                })


            result["model_base64"] =
                model_base64


        # ----------------------------------------------------
        # FAILED
        # ----------------------------------------------------

        elif current_status == "FAILED":

            result["error"] =
                data.get(
                    "error",
                    "RunPod job failed."
                )


        # ----------------------------------------------------
        # RETURN
        # ----------------------------------------------------

        return jsonify(result)


    except requests.RequestException as e:

        print(
            "RunPod status connection error:",
            str(e)
        )


        return jsonify({
            "error":
                "Could not connect to RunPod: " +
                str(e)
        }), 502


    except Exception as e:

        print(
            "Status error:",
            str(e)
        )


        return jsonify({
            "error":
                str(e)
        }), 500


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
