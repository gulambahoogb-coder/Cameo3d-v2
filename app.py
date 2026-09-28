import os
import requests
from flask import Flask, request, jsonify, render_template_string

app = Flask(__name__)

RUNPOD_API_KEY = os.environ.get("RUNPOD_API_KEY")
ENDPOINT_ID = "egysfj217v2p31"
BASE_URL = f"https://api.runpod.ai/v2/{ENDPOINT_ID}"

PAGE = """
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Cameo3D</title>
<script type="module" src="https://cdnjs.cloudflare.com/ajax/libs/model-viewer/3.4.0/model-viewer.min.js"></script>
<style>
body{font-family:Arial,sans-serif;max-width:800px;margin:40px auto;padding:20px;text-align:center;background:#f7f7f7}
.box{background:white;padding:30px;border-radius:16px}
button{padding:12px 22px;border:0;border-radius:8px;background:#111;color:white;cursor:pointer;font-size:16px}
button:disabled{opacity:.5}
#status{margin:20px 0;min-height:24px}
model-viewer{width:100%;height:550px;background:#e9e9e9;border-radius:12px;display:none}
</style>
</head>
<body>
<div class="box">
<h1>Cameo3D</h1>
<p>Turn an image into a 3D model</p>
<input type="file" id="fileInput" accept="image/*"><br><br>
<button id="generateButton" onclick="submitImage()">Generate 3D Model</button>
<div id="status"></div>
<model-viewer id="viewer" camera-controls auto-rotate shadow-intensity="1"></model-viewer>
</div>
<script>
function fileToBase64(file){
    return new Promise(function(resolve,reject){
        var reader=new FileReader();
        reader.onload=function(){resolve(reader.result.split(",")[1]);};
        reader.onerror=function(){reject(new Error("Could not read image."));};
        reader.readAsDataURL(file);
    });
}

async function submitImage(){
    var input=document.getElementById("fileInput");
    var status=document.getElementById("status");
    var viewer=document.getElementById("viewer");
    var button=document.getElementById("generateButton");

    if(!input.files.length){
        status.innerText="Please choose an image first.";
        return;
    }

    button.disabled=true;
    viewer.style.display="none";
    status.innerText="Uploading image...";

    try{
        var base64=await fileToBase64(input.files[0]);
        var response=await fetch("/submit",{
            method:"POST",
            headers:{"Content-Type":"application/json"},
            body:JSON.stringify({image_base64:base64})
        });
        var data=await response.json();

        if(!response.ok) throw new Error(data.error||"Failed to submit image.");
        if(!data.job_id) throw new Error("RunPod did not return a job ID.");

        status.innerText="Generating 3D model. Please wait...";
        pollJob(data.job_id);
    }catch(error){
        console.error(error);
        status.innerText="Error: "+error.message;
        button.disabled=false;
    }
}

function pollJob(jobId){
    var status=document.getElementById("status");
    var viewer=document.getElementById("viewer");
    var button=document.getElementById("generateButton");

    var timer=setInterval(async function(){
        try{
            var response=await fetch("/status/"+jobId);
            var data=await response.json();

            if(!response.ok) throw new Error(data.error||"Status request failed.");

            if(data.status==="COMPLETED"){
                clearInterval(timer);
                if(!data.model_base64) throw new Error("RunPod completed but returned no model.");

                var binary=atob(data.model_base64);
                var bytes=new Uint8Array(binary.length);
                for(var i=0;i<binary.length;i++) bytes[i]=binary.charCodeAt(i);

                var blob=new Blob([bytes],{type:"model/gltf-binary"});
                viewer.src=URL.createObjectURL(blob);
                viewer.style.display="block";
                status.innerText="Done!";
                button.disabled=false;
            }else if(data.status==="FAILED"){
                clearInterval(timer);
                status.innerText="Generation failed: "+(data.error||"Unknown error");
                button.disabled=false;
            }else{
                status.innerText="Generating... Status: "+data.status;
            }
        }catch(error){
            clearInterval(timer);
            console.error(error);
            status.innerText="Error: "+error.message;
            button.disabled=false;
        }
    },5000);
}
</script>
</body>
</html>
"""

def runpod_headers():
    return {
        "Authorization": f"Bearer {RUNPOD_API_KEY}",
        "Content-Type": "application/json"
    }

@app.route("/")
def index():
    return render_template_string(PAGE)

@app.route("/submit", methods=["POST"])
def submit():
    try:
        if not RUNPOD_API_KEY:
            return jsonify({"error":"RUNPOD_API_KEY is not configured on Render."}),500

        data=request.get_json(silent=True)
        if not data:
            return jsonify({"error":"No JSON data received."}),400

        image_b64=data.get("image_base64")
        if not image_b64:
            return jsonify({"error":"No image was provided."}),400

        response=requests.post(
            f"{BASE_URL}/run",
            headers=runpod_headers(),
            json={"input":{"image_base64":image_b64}},
            timeout=60
        )

        if not response.ok:
            return jsonify({"error":f"RunPod error {response.status_code}: {response.text}"}),502

        result=response.json()
        job_id=result.get("id")

        if not job_id:
            return jsonify({"error":"RunPod did not return a job ID.","runpod_response":result}),502

        return jsonify({"job_id":job_id})

    except requests.RequestException as error:
        return jsonify({"error":"Could not connect to RunPod: "+str(error)}),502
    except Exception as error:
        return jsonify({"error":str(error)}),500

@app.route("/status/<job_id>")
def status(job_id):
    try:
        if not RUNPOD_API_KEY:
            return jsonify({"error":"RUNPOD_API_KEY is not configured on Render."}),500

        response=requests.get(
            f"{BASE_URL}/status/{job_id}",
            headers=runpod_headers(),
            timeout=60
        )

        if not response.ok:
            return jsonify({"error":f"RunPod error {response.status_code}: {response.text}"}),502

        data=response.json()
        current_status=data.get("status")
        result={"status":current_status}

        if current_status=="COMPLETED":
            output=data.get("output") or {}
            model_base64=output.get("model_base64")
            if not model_base64:
                return jsonify({"status":"FAILED","error":"RunPod completed but returned no model."})
            result["model_base64"]=model_base64

        elif current_status=="FAILED":
            result["error"]=data.get("error","RunPod job failed.")

        return jsonify(result)

    except requests.RequestException as error:
        return jsonify({"error":"Could not connect to RunPod: "+str(error)}),502
    except Exception as error:
        return jsonify({"error":str(error)}),500

if __name__=="__main__":
    port=int(os.environ.get("PORT",5000))
    app.run(host="0.0.0.0",port=port)
