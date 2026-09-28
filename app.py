"""
Cameo3D
Image-to-3D Web Application

Frontend:
    Cameo3D Home
    Cameo3D 3D Workspace

Backend:
    Flask -> RunPod Serverless -> Hunyuan3D-2.1

Deploy on Render.com
"""

import os
import base64
import requests

from flask import (
    Flask,
    request,
    jsonify,
    render_template_string,
    redirect,
    url_for
)

app = Flask(__name__)

# =========================================================
# RUNPOD CONFIGURATION
# =========================================================

RUNPOD_API_KEY = os.environ.get("RUNPOD_API_KEY")

ENDPOINT_ID = "egysfj217v2p31"

BASE_URL = f"https://api.runpod.ai/v2/{ENDPOINT_ID}"

HEADERS = {
    "Authorization": f"Bearer {RUNPOD_API_KEY}",
    "Content-Type": "application/json",
}


# =========================================================
# GLOBAL CSS
# =========================================================

GLOBAL_CSS = r"""
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

:root {
    --bg: #09090b;
    --bg-2: #0d0b0e;
    --panel: #141214;
    --panel-2: #191619;
    --panel-3: #211c20;

    --border: rgba(255,255,255,.08);
    --border-light: rgba(255,255,255,.13);

    --text: #f7f4f6;
    --muted: #a9a1a6;
    --muted-2: #777075;

    --burgundy: #9f2349;
    --burgundy-2: #c12d58;
    --burgundy-dark: #54132a;

    --pink: #ef5b87;
    --rose: #d83d69;

    --success: #9de45d;

    --shadow:
        0 20px 60px rgba(0,0,0,.45);

    --glow:
        0 0 35px rgba(185,35,82,.22);
}

* {
    box-sizing: border-box;
}

html,
body {
    margin: 0;
    padding: 0;
    min-height: 100%;
    font-family: Inter, Arial, sans-serif;
    background: var(--bg);
    color: var(--text);
}

button,
input {
    font-family: inherit;
}

button {
    cursor: pointer;
}

a {
    color: inherit;
    text-decoration: none;
}

/* =======================================================
   HOME PAGE
   ======================================================= */

.home {
    min-height: 100vh;
    overflow-x: hidden;
    background:
        radial-gradient(
            circle at 50% 15%,
            rgba(157,30,69,.10),
            transparent 35%
        ),
        #09090b;
}

.home-nav {
    height: 74px;
    display: flex;
    align-items: center;
    justify-content: space-between;

    padding: 0 6vw;

    background: rgba(5,5,6,.82);

    border-bottom:
        1px solid rgba(255,255,255,.06);

    backdrop-filter: blur(18px);

    position: relative;
    z-index: 20;
}

.brand {
    display: flex;
    align-items: center;
    gap: 12px;

    font-weight: 800;
    font-size: 20px;
    letter-spacing: -.5px;
}

.brand-mark {
    width: 34px;
    height: 34px;

    border-radius: 11px;

    background:
        linear-gradient(
            135deg,
            #ef6c96,
            #8d1d43
        );

    box-shadow:
        0 0 25px rgba(205,48,92,.30);

    position: relative;
}

.brand-mark::before,
.brand-mark::after {
    content: "";
    position: absolute;

    background: rgba(255,255,255,.9);

    border-radius: 5px;
}

.brand-mark::before {
    width: 16px;
    height: 8px;
    left: 9px;
    top: 9px;
}

.brand-mark::after {
    width: 12px;
    height: 8px;
    left: 11px;
    top: 19px;
}

.home-nav-links {
    display: flex;
    gap: 34px;
    align-items: center;
}

.home-nav-links a {
    color: #aaa2a7;
    font-size: 14px;
    transition: .2s;
}

.home-nav-links a:hover {
    color: white;
}

.home-nav-right {
    display: flex;
    gap: 12px;
    align-items: center;
}

.nav-login {
    color: #aaa2a7;
    padding: 10px 15px;
}

.nav-start {
    border: 0;
    color: white;

    padding: 11px 19px;

    border-radius: 13px;

    font-weight: 700;

    background:
        linear-gradient(
            100deg,
            #8c1f43,
            #bd315c,
            #e25b82
        );

    box-shadow:
        0 8px 28px rgba(166,35,76,.27);

    transition: .2s;
}

.nav-start:hover {
    transform: translateY(-1px);
    box-shadow:
        0 12px 35px rgba(190,42,85,.38);
}

.hero {
    min-height: calc(100vh - 74px);

    display: flex;
    flex-direction: column;
    align-items: center;

    text-align: center;

    padding-top: 105px;

    position: relative;

    overflow: hidden;
}

.hero::before {
    content: "";

    position: absolute;

    width: 800px;
    height: 500px;

    left: 50%;
    top: 200px;

    transform: translateX(-50%);

    background:
        radial-gradient(
            ellipse,
            rgba(154,27,68,.18),
            transparent 68%
        );

    filter: blur(30px);

    pointer-events: none;
}

.hero-badge {
    position: relative;

    padding: 8px 14px;

    border: 1px solid rgba(221,81,119,.22);

    background:
        rgba(128,26,58,.10);

    border-radius: 999px;

    color: #df8da6;

    font-size: 12px;
    font-weight: 600;

    margin-bottom: 28px;
}

.hero h1 {
    position: relative;

    margin: 0;

    max-width: 1000px;

    font-size:
        clamp(52px, 7vw, 92px);

    line-height: .98;

    letter-spacing: -5px;

    font-weight: 800;
}

.hero h1 span {
    background:
        linear-gradient(
            100deg,
            #fff 25%,
            #f09bb6 55%,
            #b72957 100%
        );

    -webkit-background-clip: text;
    background-clip: text;

    color: transparent;
}

.hero p {
    position: relative;

    max-width: 680px;

    margin: 32px auto 0;

    color: #aaa2a7;

    line-height: 1.8;

    font-size: 17px;
}

.hero-actions {
    position: relative;

    display: flex;
    gap: 13px;

    margin-top: 38px;
}

.hero-primary {
    border: 0;

    padding: 15px 28px;

    border-radius: 15px;

    color: white;

    font-size: 15px;
    font-weight: 700;

    background:
        linear-gradient(
            110deg,
            #8c1e43,
            #bd315c,
            #e55a82
        );

    box-shadow:
        0 15px 45px rgba(168,34,77,.28);

    transition: .25s;
}

.hero-primary:hover {
    transform: translateY(-3px) scale(1.01);

    box-shadow:
        0 20px 60px rgba(184,39,84,.40);
}

.hero-secondary {
    padding: 14px 25px;

    border-radius: 15px;

    background: rgba(255,255,255,.025);

    border: 1px solid rgba(216,76,115,.42);

    color: #e4a4b7;

    font-weight: 600;

    transition: .2s;
}

.hero-secondary:hover {
    background: rgba(180,38,82,.08);
}

.hero-grid {
    position: absolute;

    left: 0;
    right: 0;
    bottom: -100px;

    height: 440px;

    background-image:
        linear-gradient(
            rgba(193,45,88,.11) 1px,
            transparent 1px
        ),
        linear-gradient(
            90deg,
            rgba(193,45,88,.11) 1px,
            transparent 1px
        );

    background-size: 51px 51px;

    mask-image:
        linear-gradient(
            to top,
            rgba(0,0,0,1),
            transparent
        );

    -webkit-mask-image:
        linear-gradient(
            to top,
            rgba(0,0,0,1),
            transparent
        );

    opacity: .75;
}

.hero-glow {
    position: absolute;

    left: 0;
    right: 0;
    bottom: -250px;

    height: 550px;

    background:
        radial-gradient(
            ellipse at center,
            rgba(178,31,77,.42),
            transparent 65%
        );

    filter: blur(25px);
}


/* =======================================================
   WORKSPACE
   ======================================================= */

.workspace {
    height: 100vh;

    display: flex;
    flex-direction: column;

    overflow: hidden;

    background:
        #09090b;
}

.workspace-top {
    height: 64px;

    flex-shrink: 0;

    display: flex;
    align-items: center;

    padding: 0 18px;

    background:
        rgba(13,12,14,.96);

    border-bottom:
        1px solid rgba(255,255,255,.07);

    z-index: 30;
}

.workspace-brand {
    width: 205px;

    display: flex;
    align-items: center;

    gap: 10px;
}

.workspace-brand-name {
    font-weight: 800;
    font-size: 18px;
}

.workspace-brand-name span {
    color: #cf5579;
}

.workspace-top-center {
    flex: 1;

    display: flex;
    justify-content: center;
}

.workspace-title {
    color: #aaa2a7;
    font-size: 13px;
}

.workspace-top-right {
    display: flex;
    align-items: center;
    gap: 10px;
}

.credits {
    padding: 9px 14px;

    border-radius: 11px;

    background: #171418;

    border: 1px solid rgba(255,255,255,.07);

    font-size: 13px;

    color: #c8c0c5;
}

.credit-number {
    color: #f08ba8;
    font-weight: 700;
}

.workspace-button {
    border: 0;

    padding: 9px 14px;

    border-radius: 11px;

    background:
        linear-gradient(
            100deg,
            #8d2045,
            #bd315d
        );

    color: white;

    font-weight: 700;
}

.workspace-body {
    display: flex;

    flex: 1;

    min-height: 0;
}


/* =======================================================
   SIDEBAR
   ======================================================= */

.sidebar {
    width: 74px;

    flex-shrink: 0;

    background: #0c0b0d;

    border-right:
        1px solid rgba(255,255,255,.06);

    display: flex;

    flex-direction: column;

    align-items: center;

    padding: 13px 8px;

    gap: 8px;
}

.side-item {
    width: 58px;
    min-height: 60px;

    border-radius: 13px;

    display: flex;

    flex-direction: column;

    align-items: center;

    justify-content: center;

    gap: 5px;

    color: #777176;

    font-size: 10px;

    transition: .2s;

    border: 1px solid transparent;
}

.side-icon {
    font-size: 21px;
}

.side-item:hover {
    color: #e4dce0;

    background:
        rgba(255,255,255,.035);
}

.side-item.active {
    color: #f0a1b8;

    background:
        linear-gradient(
            145deg,
            rgba(163,36,76,.20),
            rgba(117,25,54,.08)
        );

    border-color:
        rgba(203,55,94,.20);

    box-shadow:
        inset 0 0 25px rgba(173,36,78,.05);
}

.sidebar-bottom {
    margin-top: auto;
}


/* =======================================================
   LEFT GENERATION PANEL
   ======================================================= */

.generator-panel {
    width: 370px;

    flex-shrink: 0;

    padding: 16px;

    overflow-y: auto;

    background:
        #121012;

    border-right:
        1px solid rgba(255,255,255,.06);
}

.panel-tabs {
    display: flex;

    gap: 5px;

    padding: 4px;

    background: #1a1719;

    border-radius: 13px;

    margin-bottom: 18px;
}

.panel-tab {
    flex: 1;

    border: 0;

    padding: 10px;

    border-radius: 10px;

    color: #8f878c;

    background: transparent;

    font-size: 12px;
}

.panel-tab.active {
    color: white;

    background:
        linear-gradient(
            135deg,
            rgba(159,35,73,.35),
            rgba(205,67,105,.14)
        );

    box-shadow:
        0 5px 20px rgba(0,0,0,.2);
}

.section-label {
    display: flex;

    justify-content: space-between;

    align-items: center;

    margin-bottom: 9px;

    color: #d0c8cc;

    font-size: 12px;

    font-weight: 600;
}

.section-label small {
    color: #70696d;

    font-weight: 400;
}


/* =======================================================
   UPLOAD BOX
   ======================================================= */

.upload-box {
    height: 235px;

    border-radius: 15px;

    border:
        1px dashed rgba(255,255,255,.14);

    background:
        radial-gradient(
            circle at center,
            rgba(154,30,67,.07),
            transparent 65%
        ),
        #171517;

    display: flex;

    align-items: center;

    justify-content: center;

    text-align: center;

    cursor: pointer;

    transition: .25s;

    overflow: hidden;

    position: relative;
}

.upload-box:hover,
.upload-box.dragging {
    border-color:
        rgba(215,75,116,.65);

    background:
        radial-gradient(
            circle at center,
            rgba(170,35,76,.15),
            transparent 65%
        ),
        #191518;

    box-shadow:
        inset 0 0 35px rgba(172,37,77,.08);
}

.upload-content {
    padding: 20px;
}

.upload-icon {
    width: 48px;
    height: 48px;

    margin: 0 auto 14px;

    border-radius: 14px;

    display: flex;

    align-items: center;

    justify-content: center;

    font-size: 23px;

    background:
        linear-gradient(
            135deg,
            rgba(190,45,88,.24),
            rgba(102,21,47,.12)
        );

    border:
        1px solid rgba(207,65,104,.18);
}

.upload-title {
    color: #e6dfe2;

    font-size: 13px;

    font-weight: 600;
}

.upload-subtitle {
    margin-top: 7px;

    color: #70696e;

    font-size: 11px;

    line-height: 1.6;
}

#fileInput {
    display: none;
}

.upload-preview {
    width: 100%;
    height: 100%;

    object-fit: contain;

    background: #101012;
}


/* =======================================================
   OPTIONS
   ======================================================= */

.option-card {
    margin-top: 15px;

    padding: 14px;

    border-radius: 14px;

    background: #181518;

    border:
        1px solid rgba(255,255,255,.055);
}

.option-row {
    display: flex;

    justify-content: space-between;

    align-items: center;

    padding: 8px 0;
}

.option-name {
    color: #a8a0a5;

    font-size: 12px;
}

.option-value {
    color: #ddd5d9;

    font-size: 12px;

    font-weight: 600;
}

.select-like {
    padding: 7px 10px;

    background: #211d20;

    border:
        1px solid rgba(255,255,255,.08);

    border-radius: 8px;

    color: #ddd6da;

    font-size: 11px;
}


/* =======================================================
   GENERATE BUTTON
   ======================================================= */

.generate-area {
    position: sticky;

    bottom: 0;

    margin-top: 18px;

    padding-top: 10px;

    background:
        linear-gradient(
            to bottom,
            transparent,
            #121012 20%
        );
}

.generate-button {
    width: 100%;

    border: 0;

    padding: 15px;

    border-radius: 13px;

    color: white;

    font-size: 13px;

    font-weight: 700;

    background:
        linear-gradient(
            105deg,
            #831d40,
            #a82750,
            #d24970
        );

    box-shadow:
        0 12px 35px rgba(163,35,75,.25);

    transition: .2s;
}

.generate-button:hover:not(:disabled) {
    transform: translateY(-2px);

    box-shadow:
        0 16px 45px rgba(187,43,86,.38);
}

.generate-button:disabled {
    opacity: .45;

    cursor: not-allowed;
}

.cost-line {
    text-align: center;

    margin-top: 8px;

    color: #6f676c;

    font-size: 10px;
}


/* =======================================================
   MAIN VIEWER
   ======================================================= */

.main-workspace {
    flex: 1;

    min-width: 0;

    position: relative;

    display: flex;

    flex-direction: column;

    background:
        radial-gradient(
            circle at 50% 42%,
            rgba(255,255,255,.035),
            transparent 45%
        ),
        #151416;
}

.viewer-toolbar {
    height: 52px;

    display: flex;

    align-items: center;

    justify-content: space-between;

    padding: 0 17px;

    border-bottom:
        1px solid rgba(255,255,255,.055);

    color: #8d858a;

    font-size: 11px;
}

.toolbar-left,
.toolbar-right {
    display: flex;

    align-items: center;

    gap: 8px;
}

.tool-button {
    border: 1px solid rgba(255,255,255,.06);

    background: rgba(255,255,255,.025);

    color: #a59da2;

    width: 34px;
    height: 30px;

    border-radius: 8px;
}

.tool-button:hover {
    color: white;

    background: rgba(255,255,255,.06);
}

.viewer-stage {
    flex: 1;

    position: relative;

    overflow: hidden;

    display: flex;

    align-items: center;

    justify-content: center;
}

.viewer-empty {
    text-align: center;

    max-width: 500px;

    padding: 40px;
}

.viewer-logo {
    width: 66px;
    height: 66px;

    border-radius: 21px;

    margin: 0 auto 20px;

    background:
        linear-gradient(
            135deg,
            #e36a92,
            #761a3b
        );

    display: flex;

    align-items: center;

    justify-content: center;

    font-size: 29px;

    box-shadow:
        0 0 45px rgba(184,43,86,.18);
}

.viewer-empty h2 {
    margin: 0;

    font-size: 24px;

    letter-spacing: -.7px;
}

.viewer-empty p {
    color: #81797e;

    line-height: 1.7;

    font-size: 13px;
}

#viewer {
    width: 100%;
    height: 100%;

    --poster-color: transparent;

    background:
        radial-gradient(
            circle at center,
            rgba(255,255,255,.025),
            transparent 50%
        );

    display: none;
}

.viewer-loading {
    position: absolute;

    inset: 0;

    display: none;

    align-items: center;

    justify-content: center;

    flex-direction: column;

    background:
        rgba(9,8,10,.76);

    backdrop-filter: blur(10px);

    z-index: 10;
}

.spinner {
    width: 45px;
    height: 45px;

    border-radius: 50%;

    border:
        3px solid rgba(255,255,255,.08);

    border-top-color: #d64c74;

    animation:
        spin .8s linear infinite;

    margin-bottom: 18px;
}

@keyframes spin {
    to {
        transform: rotate(360deg);
    }
}

.loading-title {
    font-size: 14px;

    font-weight: 600;
}

.loading-status {
    color: #827a7f;

    font-size: 11px;

    margin-top: 7px;
}


/* =======================================================
   RIGHT ASSET PANEL
   ======================================================= */

.asset-panel {
    width: 280px;

    flex-shrink: 0;

    background: #111012;

    border-left:
        1px solid rgba(255,255,255,.06);

    padding: 15px;

    overflow-y: auto;
}

.asset-header {
    display: flex;

    justify-content: space-between;

    align-items: center;

    margin-bottom: 15px;
}

.asset-title {
    font-size: 13px;

    font-weight: 700;
}

.asset-count {
    color: #6f686d;

    font-size: 10px;
}

.search-box {
    width: 100%;

    padding: 10px 12px;

    background: #191719;

    border:
        1px solid rgba(255,255,255,.07);

    border-radius: 10px;

    color: #aaa2a7;

    outline: none;

    font-size: 11px;
}

.asset-grid {
    display: grid;

    grid-template-columns: 1fr 1fr;

    gap: 9px;

    margin-top: 13px;
}

.asset-card {
    aspect-ratio: 1;

    border-radius: 12px;

    background:
        linear-gradient(
            145deg,
            #211d20,
            #141214
        );

    border:
        1px solid rgba(255,255,255,.05);

    display: flex;

    align-items: center;

    justify-content: center;

    color: #504a4e;

    position: relative;

    overflow: hidden;
}

.asset-card::after {
    content: "";

    position: absolute;

    inset: 0;

    background:
        radial-gradient(
            circle at 50% 35%,
            rgba(208,62,104,.07),
            transparent 55%
        );
}

.asset-placeholder {
    font-size: 28px;

    opacity: .35;
}

.asset-card.generated {
    border-color:
        rgba(204,62,103,.3);

    box-shadow:
        0 5px 25px rgba(153,29,67,.12);
}


/* =======================================================
   STATUS
   ======================================================= */

.status-message {
    margin-top: 10px;

    padding: 10px 12px;

    border-radius: 9px;

    background:
        rgba(255,255,255,.025);

    color: #8e868b;

    font-size: 11px;

    line-height: 1.5;

    display: none;
}

.status-message.error {
    display: block;

    color: #f08aa6;

    background:
        rgba(180,30,67,.08);

    border:
        1px solid rgba(203,49,89,.15);
}

.status-message.success {
    display: block;

    color: #b9d99c;

    background:
        rgba(110,160,70,.07);

    border:
        1px solid rgba(120,180,85,.12);
}


/* =======================================================
   DOWNLOAD
   ======================================================= */

.download-button {
    width: 100%;

    margin-top: 12px;

    padding: 11px;

    border-radius: 10px;

    border:
        1px solid rgba(213,66,106,.35);

    color: #e99ab1;

    background:
        rgba(155,31,69,.08);

    font-size: 11px;

    font-weight: 600;

    display: none;
}

.download-button:hover {
    background:
        rgba(155,31,69,.15);
}


/* =======================================================
   RESPONSIVE
   ======================================================= */

@media (max-width: 1100px) {

    .asset-panel {
        width: 220px;
    }

    .generator-panel {
        width: 330px;
    }

}

@media (max-width: 850px) {

    .asset-panel {
        display: none;
    }

    .generator-panel {
        width: 320px;
    }

}

@media (max-width: 680px) {

    .home-nav-links {
        display: none;
    }

    .hero {
        padding: 80px 20px 0;
    }

    .hero h1 {
        font-size: 48px;
        letter-spacing: -3px;
    }

    .workspace-top-center {
        display: none;
    }

    .generator-panel {
        width: 100%;
        max-width: 350px;
    }

    .sidebar {
        width: 62px;
    }

    .side-item {
        width: 48px;
    }

}

"""


# =========================================================
# HOME PAGE
# =========================================================

HOME_PAGE = r"""
<!DOCTYPE html>
<html lang="en">

<head>

<meta charset="UTF-8">

<meta name="viewport"
      content="width=device-width, initial-scale=1.0">

<title>Cameo3D — Bring Ideas Into 3D</title>

{{ css|safe }}

</head>

<body>

<div class="home">

    <!-- NAVIGATION -->

    <nav class="home-nav">

        <a href="/" class="brand">

            <div class="brand-mark"></div>

            <span>Cameo3D</span>

        </a>


        <div class="home-nav-links">

            <a href="/">Home</a>

            <a href="/workspace">Create</a>

            <a href="#features">Features</a>

            <a href="/pricing">Pricing</a>

        </div>


        <div class="home-nav-right">

            <a class="nav-login"
               href="/workspace">
                Workspace
            </a>

            <a class="nav-start"
               href="/workspace">
                Get Started
            </a>

        </div>

    </nav>


    <!-- HERO -->

    <main class="hero">

        <div class="hero-badge">
            AI-Powered Image to 3D
        </div>


        <h1>
            Bring Your Ideas
            <br>
            <span>Into 3D.</span>
        </h1>


        <p>
            Turn a single image into a beautiful,
            ready-to-use 3D model with Cameo3D.
            Create assets for games, films, design,
            products and more.
        </p>


        <div class="hero-actions">

            <a
                class="hero-primary"
                href="/workspace"
            >
                ✦ Get started
            </a>


            <a
                class="hero-secondary"
                href="/pricing"
            >
                View pricing
            </a>

        </div>


        <!-- Decorative grid -->

        <div class="hero-grid"></div>

        <div class="hero-glow"></div>

    </main>

</div>

</body>
</html>
"""


# =========================================================
# PRICING PAGE
# =========================================================

PRICING_PAGE = r"""
<!DOCTYPE html>
<html>

<head>

<meta charset="UTF-8">

<meta name="viewport"
      content="width=device-width, initial-scale=1.0">

<title>Cameo3D Pricing</title>

{{ css|safe }}

<style>

.pricing-page {

    min-height:100vh;

    background:#09090b;

    padding:80px 25px;

}

.pricing-container {

    max-width:1050px;

    margin:auto;

    text-align:center;

}

.pricing-container h1 {

    font-size:55px;

    margin-bottom:15px;

}

.pricing-container p {

    color:#999196;

}

.pricing-grid {

    display:grid;

    grid-template-columns:
        repeat(3,1fr);

    gap:18px;

    margin-top:55px;

}

.price-card {

    text-align:left;

    padding:30px;

    border-radius:20px;

    background:#151315;

    border:
        1px solid rgba(255,255,255,.07);

}

.price-card.featured {

    border-color:
        rgba(202,57,98,.45);

    box-shadow:
        0 20px 60px
        rgba(158,30,68,.14);

}

.price-card h2 {

    margin-top:0;

}

.price {

    font-size:42px;

    font-weight:800;

    margin:20px 0;

}

.price small {

    font-size:13px;

    color:#777;

}

.price-card li {

    color:#aaa;

    margin:12px 0;

    font-size:13px;

}

.price-button {

    width:100%;

    padding:13px;

    border:0;

    border-radius:11px;

    background:
        linear-gradient(
            100deg,
            #8d2045,
            #ca416d
        );

    color:white;

    font-weight:700;

}

@media(max-width:800px){

    .pricing-grid {

        grid-template-columns:1fr;

    }

}

</style>

</head>

<body>

<div class="pricing-page">

<div class="pricing-container">

<a class="brand"
   href="/"
   style="justify-content:center">

<div class="brand-mark"></div>

Cameo3D

</a>

<h1>Simple pricing.</h1>

<p>
Create 3D assets without complicated software.
</p>

<div class="pricing-grid">

<div class="price-card">

<h2>Free</h2>

<div class="price">
$0
</div>

<ul>

<li>Limited generations</li>
<li>AI image-to-3D</li>
<li>GLB export</li>

</ul>

<a href="/workspace">

<button class="price-button">
Start creating
</button>

</a>

</div>


<div class="price-card featured">

<h2>Creator</h2>

<div class="price">
$9
<small>/month</small>
</div>

<ul>

<li>More generations</li>
<li>Higher priority</li>
<li>HD assets</li>
<li>Commercial use</li>

</ul>

<a href="/workspace">

<button class="price-button">
Get started
</button>

</a>

</div>


<div class="price-card">

<h2>Studio</h2>

<div class="price">
$29
<small>/month</small>
</div>

<ul>

<li>Large generation allowance</li>
<li>Priority processing</li>
<li>High-quality assets</li>
<li>Commercial workflow</li>

</ul>

<a href="/workspace">

<button class="price-button">
Start creating
</button>

</a>

</div>

</div>

</div>

</div>

</body>

</html>
"""


# =========================================================
# WORKSPACE PAGE
# =========================================================

WORKSPACE_PAGE = r"""
<!DOCTYPE html>
<html lang="en">

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width,
             initial-scale=1.0"
>

<title>Cameo3D Workspace</title>

<script
    type="module"
    src="https://cdnjs.cloudflare.com/ajax/libs/model-viewer/3.4.0/model-viewer.min.js">
</script>

{{ css|safe }}

</head>


<body>


<div class="workspace">


    <!-- =================================================
         TOP BAR
         ================================================= -->

    <header class="workspace-top">


        <div class="workspace-brand">

            <a href="/" class="brand">

                <div class="brand-mark"></div>

                <div class="workspace-brand-name">
                    Cameo<span>3D</span>
                </div>

            </a>

        </div>


        <div class="workspace-top-center">

            <div class="workspace-title">
                Image to 3D Workspace
            </div>

        </div>


        <div class="workspace-top-right">

            <div class="credits">
                ✦
                <span class="credit-number">
                    20
                </span>
                credits
            </div>


            <button
                class="workspace-button"
                onclick="window.location='/pricing'"
            >
                Upgrade
            </button>

        </div>

    </header>


    <!-- =================================================
         BODY
         ================================================= -->

    <div class="workspace-body">


        <!-- =============================================
             LEFT SIDEBAR
             ============================================= -->

        <aside class="sidebar">


            <a
                class="side-item"
                href="/workspace"
            >

                <div class="side-icon">
                    ▦
                </div>

                Assets

            </a>


            <div class="side-item active">

                <div class="side-icon">
                    ◈
                </div>

                Model

            </div>


            <div class="side-item">

                <div class="side-icon">
                    ◇
                </div>

                Texture

            </div>


            <div class="side-item">

                <div class="side-icon">
                    ♢
                </div>

                Animate

            </div>


            <div class="side-item">

                <div class="side-icon">
                    ✧
                </div>

                Enhance

            </div>


            <div class="sidebar-bottom">

                <div class="side-item">

                    <div class="side-icon">
                        ?
                    </div>

                    Help

                </div>

            </div>

        </aside>


        <!-- =============================================
             GENERATOR PANEL
             ============================================= -->

        <aside class="generator-panel">


            <div class="panel-tabs">

                <button
                    class="panel-tab active"
                    onclick="selectTab(this)"
                >
                    Image
                </button>

                <button
                    class="panel-tab"
                    onclick="selectTab(this)"
                >
                    Text
                </button>

                <button
                    class="panel-tab"
                    onclick="selectTab(this)"
                >
                    Multi-view
                </button>

            </div>


            <!-- IMAGE -->

            <div class="section-label">

                <span>
                    Image
                </span>

                <small>
                    JPG / PNG / WEBP
                </small>

            </div>


            <div
                class="upload-box"
                id="uploadBox"
                onclick="document.getElementById('fileInput').click()"
            >

                <input
                    id="fileInput"
                    type="file"
                    accept="image/png,image/jpeg,image/webp"
                >


                <div
                    class="upload-content"
                    id="uploadContent"
                >

                    <div class="upload-icon">
                        ＋
                    </div>

                    <div class="upload-title">
                        Click or drag & drop an image
                    </div>

                    <div class="upload-subtitle">
                        Upload a clear image of the
                        object you want to convert into 3D.
                        <br>
                        Maximum recommended size: 20 MB
                    </div>

                </div>

            </div>


            <!-- OPTIONS -->

            <div class="option-card">


                <div class="section-label">

                    <span>
                        Generation
                    </span>

                    <small>
                        AI
                    </small>

                </div>


                <div class="option-row">

                    <span class="option-name">
                        Quality
                    </span>

                    <select
                        id="qualitySelect"
                        class="select-like"
                    >

                        <option value="standard">
                            Standard
                        </option>

                        <option value="high">
                            High Quality
                        </option>

                    </select>

                </div>


                <div class="option-row">

                    <span class="option-name">
                        Texture
                    </span>

                    <span class="option-value">
                        PBR
                    </span>

                </div>


                <div class="option-row">

                    <span class="option-name">
                        Output
                    </span>

                    <span class="option-value">
                        GLB
                    </span>

                </div>


                <div class="option-row">

                    <span class="option-name">
                        AI Model
                    </span>

                    <span class="option-value">
                        Hunyuan 3D
                    </span>

                </div>


            </div>


            <!-- STATUS -->

            <div
                id="statusMessage"
                class="status-message"
            ></div>


            <!-- GENERATE -->

            <div class="generate-area">

                <button
                    id="generateButton"
                    class="generate-button"
                    disabled
                    onclick="submitImage()"
                >
                    ✦ Generate 3D Model
                </button>


                <div class="cost-line">
                    One generation uses 1 credit
                </div>

            </div>


        </aside>


        <!-- =============================================
             MAIN 3D VIEWER
             ============================================= -->

        <main class="main-workspace">


            <div class="viewer-toolbar">


                <div class="toolbar-left">

                    <button
                        class="tool-button"
                        title="Reset view"
                        onclick="resetViewer()"
                    >
                        ↻
                    </button>

                    <button
                        class="tool-button"
                        title="Auto rotate"
                        onclick="toggleRotate()"
                    >
                        ◌
                    </button>

                </div>


                <div>
                    3D Preview
                </div>


                <div class="toolbar-right">

                    <button
                        class="tool-button"
                        title="Fullscreen"
                        onclick="fullscreenViewer()"
                    >
                        ⛶
                    </button>

                </div>

            </div>


            <div class="viewer-stage">


                <!-- EMPTY -->

                <div
                    class="viewer-empty"
                    id="viewerEmpty"
                >

                    <div class="viewer-logo">
                        ◆
                    </div>

                    <h2>
                        What will you create today?
                    </h2>

                    <p>
                        Upload an image on the left
                        and Cameo3D will transform
                        it into a 3D model.
                    </p>

                </div>


                <!-- MODEL VIEWER -->

                <model-viewer
                    id="viewer"
                    camera-controls
                    auto-rotate
                    shadow-intensity="1"
                    exposure="1"
                    environment-image="neutral"
                >
                </model-viewer>


                <!-- LOADING -->

                <div
                    class="viewer-loading"
                    id="viewerLoading"
                >

                    <div class="spinner"></div>

                    <div
                        class="loading-title"
                        id="loadingTitle"
                    >
                        Creating your 3D model
                    </div>

                    <div
                        class="loading-status"
                        id="loadingStatus"
                    >
                        Starting AI generation...
                    </div>

                </div>


            </div>


        </main>


        <!-- =============================================
             RIGHT ASSET PANEL
             ============================================= -->

        <aside class="asset-panel">


            <div class="asset-header">

                <div class="asset-title">
                    My Assets
                </div>

                <div
                    class="asset-count"
                    id="assetCount"
                >
                    0 models
                </div>

            </div>


            <input
                class="search-box"
                placeholder="Search your generations..."
                oninput="filterAssets(this.value)"
            >


            <div
                class="asset-grid"
                id="assetGrid"
            >

                <div class="asset-card">

                    <div class="asset-placeholder">
                        ◇
                    </div>

                </div>


                <div class="asset-card">

                    <div class="asset-placeholder">
                        ◇
                    </div>

                </div>


                <div class="asset-card">

                    <div class="asset-placeholder">
                        ◇
                    </div>

                </div>


                <div class="asset-card">

                    <div class="asset-placeholder">
                        ◇
                    </div>

                </div>

            </div>


            <button
                id="downloadButton"
                class="download-button"
                onclick="downloadModel()"
            >
                ↓ Download GLB
            </button>


        </aside>


    </div>

</div>


<script>

let selectedFile = null;
let currentModelBase64 = null;
let currentJobId = null;
let pollTimer = null;
let isRotating = true;


/* ======================================================
   FILE SELECTION
   ====================================================== */

const fileInput =
    document.getElementById("fileInput");

const uploadBox =
    document.getElementById("uploadBox");

const uploadContent =
    document.getElementById("uploadContent");

const generateButton =
    document.getElementById("generateButton");

const viewer =
    document.getElementById("viewer");

const viewerEmpty =
    document.getElementById("viewerEmpty");

const viewerLoading =
    document.getElementById("viewerLoading");

const statusMessage =
    document.getElementById("statusMessage");


fileInput.addEventListener(
    "change",
    function() {

        if (this.files.length > 0) {

            handleFile(this.files[0]);

        }

    }
);


/* ======================================================
   DRAG & DROP
   ====================================================== */

uploadBox.addEventListener(
    "dragover",
    function(e) {

        e.preventDefault();

        uploadBox.classList.add("dragging");

    }
);


uploadBox.addEventListener(
    "dragleave",
    function() {

        uploadBox.classList.remove("dragging");

    }
);


uploadBox.addEventListener(
    "drop",
    function(e) {

        e.preventDefault();

        uploadBox.classList.remove("dragging");

        if (e.dataTransfer.files.length) {

            handleFile(
                e.dataTransfer.files[0]
            );

        }

    }
);


/* ======================================================
   HANDLE FILE
   ====================================================== */

function handleFile(file) {

    if (!file.type.startsWith("image/")) {

        showError(
            "Please upload an image file."
        );

        return;

    }


    if (file.size > 20 * 1024 * 1024) {

        showError(
            "Image is larger than 20 MB."
        );

        return;

    }


    selectedFile = file;

    generateButton.disabled = false;

    clearMessage();


    const reader =
        new FileReader();


    reader.onload = function(e) {

        uploadContent.innerHTML = `

            <img
                class="upload-preview"
                src="${e.target.result}"
            >

        `;

    };


    reader.readAsDataURL(file);

}


/* ======================================================
   SUBMIT IMAGE
   ====================================================== */

async function submitImage() {

    if (!selectedFile) {

        showError(
            "Please choose an image first."
        );

        return;

    }


    generateButton.disabled = true;

    viewer.style.display = "none";

    viewerEmpty.style.display = "none";

    viewerLoading.style.display = "flex";


    setLoading(
        "Uploading image",
        "Sending your image to Cameo3D..."
    );


    try {

        const base64Data =
            await fileToBase64(selectedFile);


        const quality =
            document.getElementById(
                "qualitySelect"
            ).value;


        let settings = {};


        if (quality === "high") {

            settings = {

                steps: 30,

                octree_resolution: 384,

                guidance_scale: 5.0,

                num_chunks: 8000

            };

        } else {

            settings = {

                steps: 20,

                octree_resolution: 256,

                guidance_scale: 5.0,

                num_chunks: 8000

            };

        }


        const submitRes =
            await fetch(
                "/submit",
                {

                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body: JSON.stringify({

                        image_base64:
                            base64Data,

                        settings:
                            settings

                    })

                }
            );


        const submitData =
            await submitRes.json();


        if (!submitRes.ok) {

            throw new Error(
                submitData.error ||
                "Could not start generation."
            );

        }


        currentJobId =
            submitData.job_id;


        setLoading(
            "Creating your 3D model",
            "AI is generating the geometry..."
        );


        pollTimer =
            setInterval(
                pollStatus,
                5000
            );


        await pollStatus();


    } catch (error) {

        stopLoading();

        showError(
            error.message ||
            "Something went wrong."
        );

        generateButton.disabled = false;

    }

}


/* ======================================================
   POLL RUNPOD
   ====================================================== */

async function pollStatus() {

    if (!currentJobId) {
        return;
    }


    try {

        const response =
            await fetch(
                "/status/" +
                currentJobId
            );


        const data =
            await response.json();


        if (!response.ok) {

            throw new Error(
                data.error ||
                "Status request failed."
            );

        }


        const status =
            data.status;


        if (
            status === "IN_QUEUE" ||
            status === "IN_PROGRESS"
        ) {

            setLoading(
                "Creating your 3D model",
                "Cameo3D is processing the geometry and textures..."
            );

            return;

        }


        if (status === "COMPLETED") {

            clearInterval(
                pollTimer
            );

            pollTimer = null;


            currentModelBase64 =
                data.model_base64;


            viewer.src =
                "data:model/gltf-binary;base64," +
                currentModelBase64;


            viewer.style.display =
                "block";


            viewerEmpty.style.display =
                "none";


            viewerLoading.style.display =
                "none";


            generateButton.disabled =
                false;


            showSuccess(
                "Your 3D model is ready."
            );


            document.getElementById(
                "downloadButton"
            ).style.display =
                "block";


            addGeneratedAsset();


            return;

        }


        if (status === "FAILED") {

            clearInterval(
                pollTimer
            );

            pollTimer = null;


            stopLoading();


            showError(
                data.error ||
                "Generation failed. Please try another image."
            );


            generateButton.disabled =
                false;


            return;

        }


        setLoading(
            "Creating your 3D model",
            "Status: " + status
        );


    } catch (error) {

        clearInterval(
            pollTimer
        );

        pollTimer = null;


        stopLoading();


        showError(
            error.message ||
            "Could not check generation status."
        );


        generateButton.disabled =
            false;

    }

}


/* ======================================================
   FILE TO BASE64
   ====================================================== */

function fileToBase64(file) {

    return new Promise(
        (resolve, reject) => {

            const reader =
                new FileReader();


            reader.onload = function() {

                const result =
                    reader.result;


                resolve(
                    result.split(",")[1]
                );

            };


            reader.onerror =
                reject;


            reader.readAsDataURL(file);

        }
    );

}


/* ======================================================
   LOADING
   ====================================================== */

function setLoading(
    title,
    message
) {

    viewerLoading.style.display =
        "flex";


    document.getElementById(
        "loadingTitle"
    ).innerText =
        title;


    document.getElementById(
        "loadingStatus"
    ).innerText =
        message;

}


function stopLoading() {

    viewerLoading.style.display =
        "none";

}


/* ======================================================
   MESSAGES
   ====================================================== */

function showError(message) {

    statusMessage.className =
        "status-message error";

    statusMessage.innerText =
        message;

}


function showSuccess(message) {

    statusMessage.className =
        "status-message success";

    statusMessage.innerText =
        message;

}


function clearMessage() {

    statusMessage.className =
        "status-message";

    statusMessage.innerText =
        "";

}


/* ======================================================
   VIEWER CONTROLS
   ====================================================== */

function resetViewer() {

    viewer.cameraOrbit =
        "auto auto auto";

    viewer.cameraTarget =
        "auto auto auto";

}


function toggleRotate() {

    isRotating =
        !isRotating;


    viewer.autoRotate =
        isRotating;

}


function fullscreenViewer() {

    if (
        viewer.requestFullscreen
    ) {

        viewer.requestFullscreen();

    }

}


/* ======================================================
   DOWNLOAD
   ====================================================== */

function downloadModel() {

    if (!currentModelBase64) {

        return;

    }


    const binary =
        atob(currentModelBase64);


    const bytes =
        new Uint8Array(
            binary.length
        );


    for (
        let i = 0;
        i < binary.length;
        i++
    ) {

        bytes[i] =
            binary.charCodeAt(i);

    }


    const blob =
        new Blob(
            [bytes],
            {
                type:
                    "model/gltf-binary"
            }
        );


    const url =
        URL.createObjectURL(blob);


    const a =
        document.createElement("a");


    a.href = url;

    a.download =
        "cameo3d-model.glb";

    a.click();


    URL.revokeObjectURL(url);

}


/* ======================================================
   ADD GENERATED ASSET
   ====================================================== */

function addGeneratedAsset() {

    const grid =
        document.getElementById(
            "assetGrid"
        );


    const card =
        document.createElement("div");


    card.className =
        "asset-card generated";


    card.innerHTML = `
        <div
            class="asset-placeholder"
            style="color:#cf5579"
        >
            ◈
        </div>
    `;


    grid.prepend(card);


    const count =
        grid.querySelectorAll(
            ".generated"
        ).length;


    document.getElementById(
        "assetCount"
    ).innerText =
        count + " model" +
        (count === 1 ? "" : "s");

}


/* ======================================================
   FILTER ASSETS
   ====================================================== */

function filterAssets(value) {

    /*
       Placeholder for your future database-backed
       asset library.

       The frontend is already prepared for it.
    */

}


/* ======================================================
   TABS
   ====================================================== */

function selectTab(button) {

    document
        .querySelectorAll(
            ".panel-tab"
        )
        .forEach(
            b => b.classList.remove(
                "active"
            )
        );


    button.classList.add(
        "active"
    );

}


/* ======================================================
   PREVENT PAGE DRAGGING
   ====================================================== */

document.addEventListener(
    "dragover",
    function(e) {

        e.preventDefault();

    }
);

</script>


</body>
</html>
"""


# =========================================================
# ROUTES
# =========================================================

@app.route("/")
def index():

    return render_template_string(
        HOME_PAGE,
        css=GLOBAL_CSS
    )


@app.route("/workspace")
def workspace():

    return render_template_string(
        WORKSPACE_PAGE,
        css=GLOBAL_CSS
    )


@app.route("/pricing")
def pricing():

    return render_template_string(
        PRICING_PAGE,
        css=GLOBAL_CSS
    )


# =========================================================
# SUBMIT RUNPOD JOB
# =========================================================

@app.route(
    "/submit",
    methods=["POST"]
)
def submit():

    try:

        data = request.get_json()

        if not data:

            return jsonify({
                "error":
                    "No request data received."
            }), 400


        image_b64 =
            data.get("image_base64")


        if not image_b64:

            return jsonify({
                "error":
                    "No image provided."
            }), 400


        # ---------------------------------------------
        # Optional generation settings
        # ---------------------------------------------

        settings =
            data.get(
                "settings",
                {}
            )


        # ---------------------------------------------
        # Send job to RunPod
        # ---------------------------------------------

        payload = {

            "input": {

                "image_base64":
                    image_b64,

                "prompt":
                    None,

                # These are optional.
                # Your handler can read them.
                **settings

            }

        }


        response = requests.post(

            f"{BASE_URL}/run",

            headers=HEADERS,

            json=payload,

            timeout=60

        )


        response.raise_for_status()


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

            }), 500


        return jsonify({

            "job_id":
                job_id

        })


    except requests.exceptions.RequestException as e:

        return jsonify({

            "error":
                f"RunPod request failed: {str(e)}"

        }), 502


    except Exception as e:

        return jsonify({

            "error":
                str(e)

        }), 500


# =========================================================
# CHECK RUNPOD JOB
# =========================================================

@app.route(
    "/status/<job_id>"
)
def status(job_id):

    try:

        response = requests.get(

            f"{BASE_URL}/status/{job_id}",

            headers=HEADERS,

            timeout=30

        )


        response.raise_for_status()


        data =
            response.json()


        result = {

            "status":
                data.get("status")

        }


        # ---------------------------------------------
        # COMPLETED
        # ---------------------------------------------

        if (
            data.get("status")
            == "COMPLETED"
        ):

            output =
                data.get(
                    "output",
                    {}
                )


            result[
                "model_base64"
            ] = output.get(
                "model_base64"
            )


        # ---------------------------------------------
        # FAILED
        # ---------------------------------------------

        elif (
            data.get("status")
            == "FAILED"
        ):

            result[
                "error"
            ] = data.get(
                "error",
                "Unknown RunPod error."
            )


        return jsonify(result)


    except requests.exceptions.RequestException as e:

        return jsonify({

            "status":
                "FAILED",

            "error":
                f"RunPod status request failed: {str(e)}"

        }), 502


    except Exception as e:

        return jsonify({

            "status":
                "FAILED",

            "error":
                str(e)

        }), 500


# =========================================================
# HEALTH CHECK
# =========================================================

@app.route("/health")
def health():

    return jsonify({

        "status":
            "ok",

        "service":
            "Cameo3D",

        "runpod_endpoint":
            ENDPOINT_ID

    })


# =========================================================
# START FLASK
# =========================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            5000
        )
    )


    app.run(

        host="0.0.0.0",

        port=port

    )
