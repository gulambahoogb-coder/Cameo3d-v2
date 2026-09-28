"""
Cameo3D - Meshy-inspired Image-to-3D web app
Deploy this file as app.py on Render.

Backend:
- Accepts an image in the browser
- Sends it to the RunPod Serverless endpoint
- Polls RunPod until the GLB is ready
- Displays the GLB in a 3D viewer

The visual design is intentionally dark, premium, creator-focused,
with lime/lime-to-pink accent colors inspired by modern 3D creation tools.
"""

import os
import base64
import requests
from flask import Flask, request, jsonify, render_template_string

app = Flask(__name__)

RUNPOD_API_KEY = os.environ.get("RUNPOD_API_KEY")
ENDPOINT_ID = "egysfj217v2p31"

BASE_URL = f"https://api.runpod.ai/v2/{ENDPOINT_ID}"
HEADERS = {
    "Authorization": f"Bearer {RUNPOD_API_KEY}",
    "Content-Type": "application/json",
}

PAGE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Cameo3D — AI 3D Creator</title>

    <script type="module"
        src="https://cdnjs.cloudflare.com/ajax/libs/model-viewer/3.4.0/model-viewer.min.js">
    </script>

    <style>
        :root {
            --bg: #0b0709;
            --panel: #140a0e;
            --panel-2: #1a0d12;
            --panel-3: #211017;
            --line: #3a1824;
            --text: #f5f5ef;
            --muted: #989a91;
            --muted-2: #6f7169;
            --lime: #a91f4f;
            --lime-2: #86163e;
            --pink: #d94f78;
            --purple: #b85b78;
            --danger: #ff718e;
            --shadow: 0 25px 80px rgba(0,0,0,.35);
        }

        * { box-sizing: border-box; }

        html, body {
            margin: 0;
            width: 100%;
            height: 100%;
            overflow: hidden;
            background: var(--bg);
            color: var(--text);
            font-family: Inter, ui-sans-serif, system-ui, -apple-system,
                         BlinkMacSystemFont, "Segoe UI", sans-serif;
        }

        button, input { font: inherit; }

        button { cursor: pointer; }

        .app {
            height: 100vh;
            display: grid;
            grid-template-columns: 76px 360px minmax(0, 1fr) 320px;
            grid-template-rows: 66px minmax(0, 1fr);
            background:
                radial-gradient(circle at 50% 35%, rgba(169,31,79,.055), transparent 28%),
                var(--bg);
        }

        /* TOP BAR */
        .topbar {
            grid-column: 1 / -1;
            display: flex;
            align-items: center;
            gap: 22px;
            padding: 0 18px;
            border-bottom: 1px solid var(--line);
            background: rgba(17,18,15,.94);
            z-index: 10;
        }

        .brand {
            width: 190px;
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 21px;
            font-weight: 800;
            letter-spacing: -.8px;
        }

        .brand-mark {
            width: 32px;
            height: 32px;
            border-radius: 10px;
            display: grid;
            place-items: center;
            color: #0b0709;
            background: linear-gradient(135deg, var(--lime), #d96a8d);
            box-shadow: 0 0 25px rgba(169,31,79,.16);
            font-weight: 900;
        }

        .brand small {
            color: var(--muted);
            font-size: 10px;
            font-weight: 600;
            margin-left: -5px;
            margin-top: 18px;
        }

        .workspace {
            height: 40px;
            display: flex;
            align-items: center;
            gap: 9px;
            padding: 0 13px;
            border: 1px solid var(--line);
            border-radius: 10px;
            background: #160b10;
            color: var(--text);
        }

        .workspace .dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--lime);
        }

        .top-spacer { flex: 1; }

        .top-link {
            color: #d6d7d0;
            font-size: 13px;
            text-decoration: none;
        }

        .credits {
            display: flex;
            align-items: center;
            gap: 7px;
            padding: 8px 12px;
            border-radius: 9px;
            background: #1b1c18;
            border: 1px solid var(--line);
            color: #ddd;
            font-size: 13px;
        }

        .coin {
            width: 18px;
            height: 18px;
            display: grid;
            place-items: center;
            border-radius: 50%;
            background: var(--lime);
            color: #111;
            font-size: 10px;
            font-weight: 900;
        }

        .upgrade {
            border: 0;
            border-radius: 9px;
            padding: 10px 16px;
            font-weight: 800;
            color: #171815;
            background: linear-gradient(90deg, var(--lime), #c13b68);
        }

        .avatar {
            width: 35px;
            height: 35px;
            border-radius: 50%;
            display: grid;
            place-items: center;
            background: #34352e;
            border: 1px solid #512433;
            font-weight: 800;
        }

        /* LEFT NAV */
        .sidebar {
            grid-row: 2;
            border-right: 1px solid var(--line);
            padding: 14px 9px;
            background: #10080b;
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 7px;
        }

        .nav-item {
            width: 58px;
            min-height: 60px;
            border-radius: 11px;
            border: 1px solid transparent;
            background: transparent;
            color: var(--muted);
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 5px;
            font-size: 10px;
        }

        .nav-item svg { width: 21px; height: 21px; }

        .nav-item:hover {
            background: #1a1b17;
            color: var(--text);
        }

        .nav-item.active {
            background: #211017;
            color: var(--lime);
            border-color: #4b1f30;
        }

        .nav-spacer { flex: 1; }

        /* LEFT WORKSPACE PANEL */
        .left-panel {
            grid-row: 2;
            border-right: 1px solid var(--line);
            background: #130a0e;
            overflow-y: auto;
            padding: 20px 18px;
        }

        .mode-row {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 5px;
            padding: 4px;
            background: #0d070a;
            border: 1px solid var(--line);
            border-radius: 13px;
        }

        .mode {
            height: 52px;
            border: 0;
            border-radius: 9px;
            background: transparent;
            color: var(--muted);
            display: grid;
            place-items: center;
            gap: 1px;
            font-size: 10px;
        }

        .mode strong { font-size: 18px; color: #aaa; }
        .mode.active {
            background: #261019;
            color: var(--text);
        }
        .mode.active strong { color: var(--lime); }

        .section-title {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin: 22px 2px 9px;
        }

        .section-title h3 {
            margin: 0;
            font-size: 13px;
            font-weight: 700;
        }

        .section-title span {
            color: var(--muted-2);
            font-size: 11px;
        }

        .model-choice {
            padding: 14px;
            border: 1px solid #4a2030;
            border-radius: 12px;
            background: linear-gradient(145deg, #241018, #170b10);
        }

        .model-choice .name {
            color: var(--lime);
            font-weight: 800;
            font-size: 14px;
        }

        .model-choice .desc {
            color: var(--muted);
            font-size: 11px;
            margin-top: 5px;
        }

        .upload-box {
            min-height: 250px;
            border: 1px dashed #5c293b;
            border-radius: 15px;
            background:
                radial-gradient(circle at 50% 30%, rgba(169,31,79,.045), transparent 38%),
                #180c11;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 20px;
            text-align: center;
            transition: .2s ease;
        }

        .upload-box.dragging,
        .upload-box:hover {
            border-color: var(--lime);
            background: #211018;
        }

        .upload-icon {
            width: 52px;
            height: 52px;
            border-radius: 15px;
            display: grid;
            place-items: center;
            background: #27111a;
            color: var(--lime);
            margin-bottom: 12px;
        }

        .upload-icon svg { width: 26px; }

        .upload-title {
            font-size: 13px;
            font-weight: 700;
        }

        .upload-sub {
            margin-top: 7px;
            color: var(--muted);
            font-size: 11px;
            line-height: 1.5;
        }

        #fileInput { display: none; }

        .choose {
            margin-top: 15px;
            border: 1px solid #5a2939;
            border-radius: 8px;
            padding: 8px 13px;
            color: #eee;
            background: #252720;
            font-size: 12px;
            font-weight: 700;
        }

        .preview {
            width: 100%;
            max-height: 180px;
            object-fit: contain;
            border-radius: 10px;
            margin-bottom: 12px;
            display: none;
        }

        .option-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 13px 2px;
            border-bottom: 1px solid #252620;
        }

        .option-label strong {
            display: block;
            font-size: 12px;
        }

        .option-label span {
            display: block;
            color: var(--muted);
            font-size: 10px;
            margin-top: 3px;
        }

        .switch {
            width: 42px;
            height: 24px;
            padding: 3px;
            border-radius: 30px;
            background: #3a2029;
            border: 0;
        }

        .switch span {
            display: block;
            width: 18px;
            height: 18px;
            border-radius: 50%;
            background: #b5b7ae;
            transition: .2s;
        }

        .switch.on {
            background: var(--lime);
        }

        .switch.on span {
            transform: translateX(18px);
            background: #130a0e;
        }

        .generate {
            width: 100%;
            margin-top: 18px;
            height: 48px;
            border: 0;
            border-radius: 11px;
            color: #141510;
            font-weight: 900;
            background: linear-gradient(100deg, #86163e 0%, #a91f4f 50%, #d94f78 100%);
            box-shadow: 0 8px 30px rgba(169,31,79,.10);
        }

        .generate:disabled {
            opacity: .45;
            cursor: not-allowed;
        }

        .estimate {
            text-align: center;
            color: var(--muted);
            font-size: 10px;
            margin-top: 9px;
        }

        /* MAIN CANVAS */
        .main {
            grid-row: 2;
            position: relative;
            min-width: 0;
            overflow: hidden;
            background:
                radial-gradient(circle at 50% 45%, rgba(255,255,255,.025), transparent 38%),
                #1a1b19;
        }

        .canvas-top {
            position: absolute;
            top: 16px;
            left: 18px;
            right: 18px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            z-index: 3;
        }

        .canvas-pill {
            display: flex;
            gap: 5px;
            align-items: center;
            border: 1px solid var(--line);
            background: rgba(19,20,17,.8);
            border-radius: 9px;
            padding: 6px;
        }

        .canvas-pill button {
            border: 0;
            color: var(--muted);
            background: transparent;
            padding: 7px 10px;
            border-radius: 6px;
            font-size: 11px;
        }

        .canvas-pill button.active {
            color: var(--text);
            background: #351621;
        }

        .canvas-tools {
            display: flex;
            gap: 7px;
        }

        .icon-btn {
            width: 35px;
            height: 35px;
            border-radius: 9px;
            border: 1px solid var(--line);
            background: rgba(20,21,18,.85);
            color: #aaa;
            display: grid;
            place-items: center;
        }

        .icon-btn svg { width: 17px; }

        .empty-canvas {
            position: absolute;
            inset: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            flex-direction: column;
            padding: 80px 40px 40px;
            text-align: center;
        }

        .hero-symbol {
            width: 86px;
            height: 86px;
            display: grid;
            place-items: center;
            margin-bottom: 20px;
            color: var(--lime);
        }

        .hero-symbol svg {
            width: 72px;
            height: 72px;
            filter: drop-shadow(0 0 22px rgba(169,31,79,.10));
        }

        .empty-canvas h1 {
            margin: 0;
            font-size: clamp(25px, 3vw, 40px);
            letter-spacing: -1.5px;
        }

        .empty-canvas p {
            max-width: 570px;
            margin: 11px 0 22px;
            color: var(--muted);
            line-height: 1.6;
            font-size: 14px;
        }

        .hero-button {
            border: 0;
            padding: 13px 22px;
            border-radius: 10px;
            font-weight: 900;
            color: #141510;
            background: linear-gradient(100deg, var(--lime-2), var(--lime), var(--pink));
        }

        #viewerWrap {
            position: absolute;
            inset: 0;
            display: none;
        }

        model-viewer {
            width: 100%;
            height: 100%;
            --poster-color: transparent;
            background:
                radial-gradient(circle at 50% 45%, #321722 0%, #1a1b19 55%, #130a0e 100%);
        }

        .viewer-overlay {
            position: absolute;
            left: 20px;
            bottom: 20px;
            right: 20px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            pointer-events: none;
        }

        .viewer-status {
            pointer-events: auto;
            background: rgba(18,19,16,.88);
            border: 1px solid var(--line);
            padding: 10px 13px;
            border-radius: 9px;
            color: var(--muted);
            font-size: 11px;
        }

        .viewer-actions {
            display: flex;
            gap: 7px;
            pointer-events: auto;
        }

        .viewer-actions button {
            border: 1px solid var(--line);
            border-radius: 9px;
            padding: 10px 13px;
            background: rgba(18,19,16,.9);
            color: #eee;
            font-size: 11px;
        }

        /* RIGHT ASSET PANEL */
        .right-panel {
            grid-row: 2;
            border-left: 1px solid var(--line);
            background: #130a0e;
            padding: 20px 14px;
            overflow-y: auto;
        }

        .right-head {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 13px;
        }

        .right-head h2 {
            margin: 0;
            font-size: 14px;
        }

        .search {
            width: 100%;
            height: 38px;
            border: 1px solid var(--line);
            border-radius: 9px;
            background: #1b1c19;
            color: var(--text);
            padding: 0 12px;
            outline: none;
            font-size: 11px;
        }

        .asset-tabs {
            display: flex;
            justify-content: space-between;
            margin: 13px 0;
            color: var(--muted);
        }

        .asset-tabs span {
            font-size: 10px;
            padding: 7px 8px;
            border-radius: 6px;
        }

        .asset-tabs span.active {
            background: #351520;
            color: var(--lime);
        }

        .asset-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 9px;
        }

        .asset {
            min-height: 126px;
            border: 1px solid #3a1a25;
            border-radius: 11px;
            background: linear-gradient(145deg, #22231f, #180c11);
            overflow: hidden;
            position: relative;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .asset img {
            width: 100%;
            height: 100%;
            object-fit: cover;
            opacity: .78;
        }

        .asset .asset-name {
            position: absolute;
            left: 8px;
            right: 8px;
            bottom: 7px;
            padding: 5px 7px;
            border-radius: 6px;
            background: rgba(0,0,0,.58);
            font-size: 9px;
            color: #ddd;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .shape {
            width: 43px;
            height: 76px;
            border-radius: 45% 45% 28% 28%;
            background: linear-gradient(90deg, #72756d, #d5d8cf 45%, #666960);
            box-shadow: 0 14px 28px rgba(0,0,0,.45);
        }

        .shape.bottle {
            width: 38px;
            height: 72px;
            border-radius: 10px 10px 15px 15px;
        }

        .shape.bottle:before {
            content: "";
            position: absolute;
            width: 17px;
            height: 18px;
            margin-top: -12px;
            margin-left: 10px;
            border-radius: 5px 5px 1px 1px;
            background: #aeb1a7;
        }

        .asset-more {
            margin-top: 15px;
            text-align: center;
            color: var(--muted);
            font-size: 10px;
        }

        /* STATUS TOAST */
        .toast {
            position: fixed;
            left: 50%;
            bottom: 22px;
            transform: translate(-50%, 120px);
            z-index: 100;
            padding: 12px 18px;
            border-radius: 10px;
            border: 1px solid #3d4036;
            background: #20221d;
            box-shadow: var(--shadow);
            color: #eee;
            font-size: 12px;
            transition: transform .25s ease;
        }

        .toast.show { transform: translate(-50%, 0); }

        .loading {
            display: none;
            align-items: center;
            gap: 9px;
        }

        .loading.show { display: inline-flex; }

        .spinner {
            width: 14px;
            height: 14px;
            border: 2px solid #55584e;
            border-top-color: var(--lime);
            border-radius: 50%;
            animation: spin .8s linear infinite;
        }

        @keyframes spin { to { transform: rotate(360deg); } }

        @media (max-width: 1100px) {
            .app { grid-template-columns: 68px 310px minmax(0,1fr); }
            .right-panel { display: none; }
            .brand { width: 155px; }
        }

        @media (max-width: 760px) {
            html, body { overflow: auto; }
            .app {
                height: auto;
                min-height: 100vh;
                grid-template-columns: 1fr;
                grid-template-rows: 62px auto auto;
            }
            .topbar { grid-column: 1; }
            .sidebar { display: none; }
            .left-panel {
                grid-column: 1;
                grid-row: 2;
                border-right: 0;
                border-bottom: 1px solid var(--line);
            }
            .main {
                grid-column: 1;
                grid-row: 3;
                min-height: 650px;
            }
            .top-link, .credits { display: none; }
            .brand { width: auto; }
        }
    </style>
</head>

<body>
<div class="app">

    <!-- TOP BAR -->
    <header class="topbar">
        <div class="brand">
            <div class="brand-mark">C</div>
            Cameo3D
            <small>AI</small>
        </div>

        <div class="workspace">
            <span class="dot"></span>
            My Workspace
            <span style="color:#777;font-size:12px;">⌄</span>
        </div>

        <a class="top-link" href="javascript:void(0)">Community</a>
        <a class="top-link" href="javascript:void(0)">API</a>
        <a class="top-link" href="javascript:void(0)">Resources</a>

        <div class="top-spacer"></div>

        <div class="credits">
            <span class="coin">✦</span>
            <span>100 credits</span>
        </div>

        <a class="upgrade" href="https://cameo3d.odoo.com/pricing">Upgrade</a>
        <div class="avatar">G</div>
    </header>

    <!-- LEFT NAVIGATION -->
    <aside class="sidebar">
        <button class="nav-item active" title="Model">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7">
                <path d="m12 3 8 4.5v9L12 21l-8-4.5v-9L12 3Z"/>
                <path d="m4.5 7.5 7.5 4 7.5-4M12 12v9"/>
            </svg>
            Model
        </button>

        <button class="nav-item" title="Image">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7">
                <rect x="3" y="4" width="18" height="16" rx="3"/>
                <circle cx="8.5" cy="9" r="1.5"/>
                <path d="m5 17 5-5 3 3 2-2 4 4"/>
            </svg>
            Image
        </button>

        <button class="nav-item" title="Print">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7">
                <path d="M6 9V4h12v5M6 17H4a1 1 0 0 1-1-1v-5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v5a1 1 0 0 1-1 1h-2"/>
                <path d="M6 14h12v7H6z"/>
            </svg>
            Print
        </button>

        <button class="nav-item" title="Animate">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7">
                <circle cx="12" cy="12" r="8"/>
                <path d="m10 8 6 4-6 4V8Z"/>
            </svg>
            Animate
        </button>

        <button class="nav-item" title="Inspiration">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7">
                <path d="m12 3 1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3Z"/>
                <path d="m19 16 .8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8L19 16Z"/>
            </svg>
            Inspire
        </button>

        <div class="nav-spacer"></div>

        <button class="nav-item" title="Settings">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7">
                <path d="M12 15.2a3.2 3.2 0 1 0 0-6.4 3.2 3.2 0 0 0 0 6.4Z"/>
                <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-1.7 1.7-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.1h-2.4v-.1a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L8 17l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.6-1H6.7v-2.4h.1a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L8 8.6l1.7-1.7.1.1a1.7 1.7 0 0 0 1.9.3 1.7 1.7 0 0 0 1-1.6v-.1h2.4v.1a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1 1.7 1.7-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.1v2.4H21a1.7 1.7 0 0 0-1.6 1Z"/>
            </svg>
            Settings
        </button>
    </aside>

    <!-- LEFT CREATION PANEL -->
    <aside class="left-panel">
        <div class="mode-row">
            <button class="mode active">
                <strong>◈</strong>
                Image → 3D
            </button>
            <button class="mode">
                <strong>✦</strong>
                Text → 3D
            </button>
            <button class="mode">
                <strong>◇</strong>
                Multi-view
            </button>
        </div>

        <div class="section-title">
            <h3>Model</h3>
            <span>Shape + texture</span>
        </div>

        <div class="model-choice">
            <div class="name">Cameo3D AI</div>
            <div class="desc">High-detail single image reconstruction</div>
        </div>

        <div class="section-title">
            <h3>Image</h3>
            <span>PNG · JPG · WEBP</span>
        </div>

        <input id="fileInput" type="file" accept="image/png,image/jpeg,image/webp">

        <div id="uploadBox" class="upload-box">
            <img id="preview" class="preview" alt="Selected image">
            <div id="uploadIcon" class="upload-icon">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7">
                    <rect x="3" y="3" width="18" height="18" rx="3"/>
                    <circle cx="8.5" cy="8.5" r="1.5"/>
                    <path d="m4.5 18 5-5 3 3 2-2 4 4"/>
                </svg>
            </div>
            <div id="uploadTitle" class="upload-title">
                Click, drag & drop, or paste an image
            </div>
            <div id="uploadSub" class="upload-sub">
                Use a clear image with the subject visible.<br>
                Maximum recommended size: 20 MB
            </div>
            <button class="choose" type="button" id="chooseBtn">Choose image</button>
        </div>

        <div class="section-title">
            <h3>Generation options</h3>
            <span>Optional</span>
        </div>

        <div class="option-row">
            <div class="option-label">
                <strong>Remove background</strong>
                <span>Clean subject before 3D generation</span>
            </div>
            <button class="switch on" id="bgSwitch"><span></span></button>
        </div>

        <div class="option-row">
            <div class="option-label">
                <strong>High detail</strong>
                <span>Prioritize geometry detail</span>
            </div>
            <button class="switch on" id="detailSwitch"><span></span></button>
        </div>

        <button class="generate" id="generateBtn" disabled>
            <span id="generateText">✦ Generate Model</span>
            <span id="loading" class="loading">
                <span class="spinner"></span> Generating...
            </span>
        </button>

        <div class="estimate">Estimated generation time: 1–4 minutes</div>
    </aside>

    <!-- MAIN 3D CANVAS -->
    <main class="main">
        <div class="canvas-top">
            <div class="canvas-pill">
                <button class="active">3D Preview</button>
                <button>Material</button>
                <button>Wireframe</button>
            </div>

            <div class="canvas-tools">
                <button class="icon-btn" title="Reset view" id="resetView">↻</button>
                <button class="icon-btn" title="Fullscreen" id="fullscreen">⛶</button>
            </div>
        </div>

        <div id="emptyCanvas" class="empty-canvas">
            <div class="hero-symbol">
                <svg viewBox="0 0 80 80" fill="none">
                    <path d="M40 8 61 20v24L40 56 19 44V20L40 8Z"
                          stroke="currentColor" stroke-width="2"/>
                    <path d="m19 20 21 12 21-12M40 32v24" stroke="currentColor" stroke-width="2"/>
                    <path d="M28 61 40 68l12-7" stroke="currentColor" stroke-width="2" opacity=".55"/>
                </svg>
            </div>
            <h1>What will you create today?</h1>
            <p>
                Turn a single image into a textured 3D model with Cameo3D.
                Upload an image from the panel on the left and your model will
                appear here.
            </p>
            <button class="hero-button" id="heroUpload">✦ Generate your first model</button>
        </div>

        <div id="viewerWrap">
            <model-viewer id="viewer"
                camera-controls
                auto-rotate
                shadow-intensity="1"
                exposure="1.05"
                environment-image="neutral"
                interaction-prompt="none">
            </model-viewer>

            <div class="viewer-overlay">
                <div class="viewer-status" id="viewerStatus">3D model ready</div>
                <div class="viewer-actions">
                    <button id="rotateBtn">Auto-rotate</button>
                    <button id="downloadBtn">Download GLB</button>
                </div>
            </div>
        </div>
    </main>

    <!-- RIGHT ASSET LIBRARY -->
    <aside class="right-panel">
        <div class="right-head">
            <h2>My Assets</h2>
            <span style="color:var(--muted);font-size:16px;">⋮</span>
        </div>

        <input class="search" id="assetSearch" placeholder="Search my generations...">

        <div class="asset-tabs">
            <span class="active">All</span>
            <span>Models</span>
            <span>Images</span>
            <span>Recent</span>
        </div>

        <div class="asset-grid" id="assetGrid">
            <div class="asset">
                <div class="shape bottle"></div>
                <div class="asset-name">Bottle concept</div>
            </div>
            <div class="asset">
                <div class="shape"></div>
                <div class="asset-name">Product model</div>
            </div>
            <div class="asset">
                <div class="shape bottle" style="transform:scale(.85);"></div>
                <div class="asset-name">Glass bottle</div>
            </div>
            <div class="asset">
                <div class="shape" style="transform:scale(.8);"></div>
                <div class="asset-name">Prototype</div>
            </div>
            <div class="asset">
                <div class="shape bottle" style="transform:scale(.72);"></div>
                <div class="asset-name">New asset</div>
            </div>
            <div class="asset">
                <div class="shape" style="transform:scale(.7);"></div>
                <div class="asset-name">Demo model</div>
            </div>
        </div>

        <div class="asset-more">Your generated models will appear here.</div>
    </aside>
</div>

<div id="toast" class="toast"></div>

<script>
    const fileInput = document.getElementById("fileInput");
    const uploadBox = document.getElementById("uploadBox");
    const chooseBtn = document.getElementById("chooseBtn");
    const heroUpload = document.getElementById("heroUpload");
    const preview = document.getElementById("preview");
    const uploadIcon = document.getElementById("uploadIcon");
    const uploadTitle = document.getElementById("uploadTitle");
    const uploadSub = document.getElementById("uploadSub");
    const generateBtn = document.getElementById("generateBtn");
    const generateText = document.getElementById("generateText");
    const loading = document.getElementById("loading");
    const emptyCanvas = document.getElementById("emptyCanvas");
    const viewerWrap = document.getElementById("viewerWrap");
    const viewer = document.getElementById("viewer");
    const viewerStatus = document.getElementById("viewerStatus");
    const toast = document.getElementById("toast");

    let selectedFile = null;
    let currentModelBase64 = null;
    let pollTimer = null;

    function showToast(message) {
        toast.textContent = message;
        toast.classList.add("show");
        setTimeout(() => toast.classList.remove("show"), 3200);
    }

    function selectFile(file) {
        if (!file) return;

        if (!file.type.startsWith("image/")) {
            showToast("Please choose a PNG, JPG, or WEBP image.");
            return;
        }

        if (file.size > 20 * 1024 * 1024) {
            showToast("Please choose an image smaller than 20 MB.");
            return;
        }

        selectedFile = file;
        generateBtn.disabled = false;

        const url = URL.createObjectURL(file);
        preview.src = url;
        preview.style.display = "block";
        uploadIcon.style.display = "none";
        uploadTitle.textContent = file.name;
        uploadSub.textContent = "Image selected — ready to generate";
        chooseBtn.textContent = "Change image";

        showToast("Image ready.");
    }

    chooseBtn.addEventListener("click", () => fileInput.click());
    heroUpload.addEventListener("click", () => fileInput.click());
    uploadBox.addEventListener("click", (e) => {
        if (e.target !== chooseBtn) fileInput.click();
    });

    fileInput.addEventListener("change", () => {
        if (fileInput.files.length) selectFile(fileInput.files[0]);
    });

    ["dragenter", "dragover"].forEach(eventName => {
        uploadBox.addEventListener(eventName, e => {
            e.preventDefault();
            uploadBox.classList.add("dragging");
        });
    });

    ["dragleave", "drop"].forEach(eventName => {
        uploadBox.addEventListener(eventName, e => {
            e.preventDefault();
            uploadBox.classList.remove("dragging");
        });
    });

    uploadBox.addEventListener("drop", e => {
        const file = e.dataTransfer.files[0];
        selectFile(file);
    });

    window.addEventListener("paste", e => {
        const items = e.clipboardData?.items || [];
        for (const item of items) {
            if (item.type.startsWith("image/")) {
                selectFile(item.getAsFile());
                break;
            }
        }
    });

    document.querySelectorAll(".switch").forEach(sw => {
        sw.addEventListener("click", () => sw.classList.toggle("on"));
    });

    document.querySelectorAll(".mode").forEach(mode => {
        mode.addEventListener("click", () => {
            document.querySelectorAll(".mode").forEach(m => m.classList.remove("active"));
            mode.classList.add("active");
        });
    });

    document.querySelectorAll(".canvas-pill button").forEach(btn => {
        btn.addEventListener("click", () => {
            document.querySelectorAll(".canvas-pill button").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
        });
    });

    document.getElementById("rotateBtn").addEventListener("click", () => {
        viewer.autoRotate = !viewer.autoRotate;
        document.getElementById("rotateBtn").textContent =
            viewer.autoRotate ? "Auto-rotate" : "Rotate";
    });

    document.getElementById("resetView").addEventListener("click", () => {
        viewer.cameraOrbit = "auto auto auto";
        viewer.fieldOfView = "auto";
    });

    document.getElementById("fullscreen").addEventListener("click", async () => {
        const target = document.getElementById("viewerWrap");
        if (target.requestFullscreen) await target.requestFullscreen();
    });

    document.getElementById("downloadBtn").addEventListener("click", () => {
        if (!currentModelBase64) return;

        const bytes = Uint8Array.from(atob(currentModelBase64), c => c.charCodeAt(0));
        const blob = new Blob([bytes], {type: "model/gltf-binary"});
        const url = URL.createObjectURL(blob);

        const a = document.createElement("a");
        a.href = url;
        a.download = "cameo3d-model.glb";
        document.body.appendChild(a);
        a.click();
        a.remove();

        setTimeout(() => URL.revokeObjectURL(url), 1000);
    });

    async function submitImage() {
        if (!selectedFile) {
            showToast("Choose an image first.");
            return;
        }

        generateBtn.disabled = true;
        generateText.style.display = "none";
        loading.classList.add("show");

        viewerWrap.style.display = "none";
        emptyCanvas.style.display = "flex";

        try {
            const reader = new FileReader();

            const base64Data = await new Promise((resolve, reject) => {
                reader.onload = () => resolve(reader.result.split(",")[1]);
                reader.onerror = reject;
                reader.readAsDataURL(selectedFile);
            });

            showToast("Uploading image...");

            const submitRes = await fetch("/submit", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({image_base64: base64Data})
            });

            const submitData = await submitRes.json();

            if (!submitRes.ok || !submitData.job_id) {
                throw new Error(submitData.error || "Could not submit the image.");
            }

            const jobId = submitData.job_id;
            viewerStatus.textContent = "Generating 3D model...";
            showToast("Generation started. This can take a few minutes.");

            if (pollTimer) clearInterval(pollTimer);

            pollTimer = setInterval(async () => {
                try {
                    const statusRes = await fetch("/status/" + encodeURIComponent(jobId));
                    const statusData = await statusRes.json();

                    if (statusData.status === "COMPLETED") {
                        clearInterval(pollTimer);
                        pollTimer = null;

                        currentModelBase64 = statusData.model_base64;
                        viewer.src = "data:model/gltf-binary;base64," + currentModelBase64;

                        emptyCanvas.style.display = "none";
                        viewerWrap.style.display = "block";
                        viewerStatus.textContent = "3D model ready";

                        showToast("Your 3D model is ready!");
                        generateBtn.disabled = false;
                        generateText.style.display = "inline";
                        loading.classList.remove("show");
                    } else if (statusData.status === "FAILED") {
                        clearInterval(pollTimer);
                        pollTimer = null;

                        throw new Error(statusData.error || "Generation failed.");
                    } else {
                        viewerStatus.textContent =
                            "Status: " + (statusData.status || "IN_QUEUE");
                    }
                } catch (err) {
                    clearInterval(pollTimer);
                    pollTimer = null;
                    showToast(err.message || "Generation failed.");
                    generateBtn.disabled = false;
                    generateText.style.display = "inline";
                    loading.classList.remove("show");
                }
            }, 5000);

        } catch (err) {
            showToast(err.message || "Something went wrong.");
            generateBtn.disabled = false;
            generateText.style.display = "inline";
            loading.classList.remove("show");
        }
    }

    generateBtn.addEventListener("click", submitImage);
</script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(PAGE)


@app.route("/submit", methods=["POST"])
def submit():
    if not RUNPOD_API_KEY:
        return jsonify({"error": "RUNPOD_API_KEY is not configured on Render."}), 500

    data = request.get_json(silent=True) or {}
    image_b64 = data.get("image_base64")

    if not image_b64:
        return jsonify({"error": "No image was provided."}), 400

    try:
        response = requests.post(
            f"{BASE_URL}/run",
            headers=HEADERS,
            json={"input": {"image_base64": image_b64, "prompt": None}},
            timeout=60,
        )

        if not response.ok:
            return jsonify({
                "error": f"RunPod returned HTTP {response.status_code}: {response.text[:1000]}"
            }), response.status_code

        result = response.json()
        job_id = result.get("id")

        if not job_id:
            return jsonify({"error": "RunPod did not return a job ID.", "raw": result}), 502

        return jsonify({"job_id": job_id})

    except requests.RequestException as exc:
        return jsonify({"error": f"Could not contact RunPod: {exc}"}), 502


@app.route("/status/<job_id>")
def status(job_id):
    if not RUNPOD_API_KEY:
        return jsonify({"error": "RUNPOD_API_KEY is not configured on Render."}), 500

    try:
        response = requests.get(
            f"{BASE_URL}/status/{job_id}",
            headers=HEADERS,
            timeout=30,
        )

        if not response.ok:
            return jsonify({
                "error": f"RunPod returned HTTP {response.status_code}: {response.text[:1000]}"
            }), response.status_code

        data = response.json()
        job_status = data.get("status", "UNKNOWN")

        result = {"status": job_status}

        if job_status == "COMPLETED":
            output = data.get("output") or {}
            model_base64 = output.get("model_base64")

            if not model_base64:
                return jsonify({
                    "status": "FAILED",
                    "error": "RunPod completed but did not return model_base64."
                }), 502

            result["model_base64"] = model_base64

        elif job_status == "FAILED":
            result["error"] = data.get("error") or data.get("output")

        return jsonify(result)

    except requests.RequestException as exc:
        return jsonify({"error": f"Could not contact RunPod: {exc}"}), 502


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
