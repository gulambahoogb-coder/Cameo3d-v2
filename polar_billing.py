"""
Cameo3D - Polar billing (works next to Paddle, nothing in app.py is changed)

What it adds:
    POST /polar/checkout   logged-in user picks a plan -> returns a Polar checkout link
    POST /polar/webhook    Polar tells us a payment happened -> credits are added ONE time

Render environment variables:
    POLAR_ACCESS_TOKEN       Polar API token (Organization Access Token)
    POLAR_WEBHOOK_SECRET     secret of the Polar webhook endpoint
    POLAR_SERVER             "sandbox" while testing, "production" when live (default production)
    POLAR_PRODUCT_STARTER    Polar product id of the $19.90 plan  (1000 credits)
    POLAR_PRODUCT_PRO        Polar product id of the $29 plan     (1500 credits)
    POLAR_PRODUCT_STUDIO     Polar product id of the $49 plan     (2750 credits)

Optional:
    POLAR_SUCCESS_URL        where the user lands after paying (default: ODOO_URL + /workspace-1,
                             which is https://www.cameo3d.com/workspace-1)
    ODOO_URL                 your primary website domain, e.g. https://www.cameo3d.com (no slash at the end)

Sandbox and production are two separate Polar accounts: each has its own token,
webhook secret and product ids. When you go live, just replace those 5 values on Render
and set POLAR_SERVER to production.
"""

import os
import time
import hmac
import base64
import hashlib

import psycopg2.errors
import requests
from flask import request, jsonify

# plan name sent by the website -> (Render variable with the Polar product id, credits given)
PLANS = {
    "starter": ("POLAR_PRODUCT_STARTER", 1000),
    "pro": ("POLAR_PRODUCT_PRO", 1500),
    "studio": ("POLAR_PRODUCT_STUDIO", 2750),
}


def _api_base():
    if os.environ.get("POLAR_SERVER", "").strip().lower() == "sandbox":
        return "https://sandbox-api.polar.sh/v1"
    return "https://api.polar.sh/v1"


def _plan_table():
    """plan -> (product_id, credits), read from Render at request time."""
    out = {}
    for plan, (env_name, credits) in PLANS.items():
        out[plan] = (os.environ.get(env_name, "").strip(), credits)
    return out


def _credits_for_product(product_id):
    for pid, credits in _plan_table().values():
        if pid and pid == product_id:
            return credits
    return 0


def _signature_ok(raw, headers, secret):
    """Standard Webhooks check. Polar secrets made before 8 Sept 2026 sign with the secret's
    own bytes, newer ones with the base64-decoded secret, so both keys are tried."""
    msg_id = headers.get("webhook-id", "")
    ts = headers.get("webhook-timestamp", "")
    sig_header = headers.get("webhook-signature", "")
    if not msg_id or not ts or not sig_header:
        return False
    try:
        if abs(time.time() - int(ts)) > 300:  # reject very old messages
            return False
    except ValueError:
        return False

    keys = [secret.encode()]
    try:
        body = secret[len("whsec_"):] if secret.startswith("whsec_") else secret
        keys.append(base64.b64decode(body + "=" * (-len(body) % 4)))
    except Exception:
        pass

    signed = msg_id.encode() + b"." + ts.encode() + b"." + raw
    sent = [p[3:] for p in sig_header.split() if p.startswith("v1,")]
    for key in keys:
        good = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
        for s in sent:
            if hmac.compare_digest(s, good):
                return True
    return False


def register_polar(app, cursor, add_credits, current_user, origin_ok, auth_limited):
    """Adds the two Polar routes to the existing Flask app."""

    odoo_url = os.environ.get("ODOO_URL", "https://www.cameo3d.com").rstrip("/")

    # -----------------------------------------------------------
    # 1) CHECKOUT: the website calls this when the user clicks a plan
    # -----------------------------------------------------------
    @app.route("/polar/checkout", methods=["POST", "OPTIONS"])
    def polar_checkout():
        if request.method == "OPTIONS":
            return ("", 204)
        if not origin_ok():
            return jsonify({"error": "Forbidden."}), 403
        uid = current_user()
        if not uid:
            return jsonify({"error": "Please log in."}), 401
        token = os.environ.get("POLAR_ACCESS_TOKEN", "").strip()
        if not token:
            return jsonify({"error": "Payments are not enabled yet."}), 503
        if auth_limited():
            return jsonify({"error": "Too many attempts. Please try again later."}), 429

        d = request.get_json(silent=True) or {}
        plan = str(d.get("plan", "")).strip().lower()
        product_id = _plan_table().get(plan, ("", 0))[0]
        if not product_id:
            return jsonify({"error": "Unknown plan."}), 400

        with cursor() as cur:
            cur.execute("select email from users where id=%s", (uid,))
            row = cur.fetchone()
        if not row:
            return jsonify({"error": "Please log in."}), 401
        email = row[0] or ""

        body = {
            "products": [product_id],
            "external_customer_id": str(uid),
            "metadata": {"user_id": str(uid), "plan": plan},
            "success_url": os.environ.get("POLAR_SUCCESS_URL", "").strip() or (odoo_url + "/workspace-1"),
        }
        if "@" in email:
            body["customer_email"] = email

        try:
            r = requests.post(
                _api_base() + "/checkouts/",
                json=body,
                headers={"Authorization": "Bearer " + token},
                timeout=30,
            )
        except Exception:
            app.logger.exception("polar checkout request failed")
            return jsonify({"error": "Could not reach the payment service. Please try again."}), 502
        if r.status_code not in (200, 201):
            app.logger.error("polar checkout failed %s %s", r.status_code, r.text[:500])
            return jsonify({"error": "Could not start the payment. Please try again."}), 502
        url = (r.json() or {}).get("url")
        if not url:
            app.logger.error("polar checkout returned no url: %s", r.text[:500])
            return jsonify({"error": "Could not start the payment. Please try again."}), 502
        return jsonify({"url": url})

    # -----------------------------------------------------------
    # 2) WEBHOOK: Polar calls this after a payment or a refund
    # -----------------------------------------------------------
    def order_user_id(data):
        cust = data.get("customer") or {}
        for raw in (cust.get("external_id"), (data.get("metadata") or {}).get("user_id")):
            try:
                return int(raw)
            except (TypeError, ValueError):
                continue
        return None

    def handle_paid(data):
        order_id = str(data.get("id") or "")
        if not order_id:
            return "bad payload", 400

        # A mid-month plan change would repeat the full credits, so only these give credits.
        reason = data.get("billing_reason")
        if reason not in ("purchase", "subscription_create", "subscription_cycle"):
            app.logger.error("polar order %s (%s) gives no credits: check by hand if needed", order_id, reason)
            return "ignored", 200

        uid = order_user_id(data)
        if not uid:
            app.logger.error("polar order %s has no valid user id", order_id)
            return "no user id", 200  # 200 so Polar does not retry forever

        product_id = str(data.get("product_id") or (data.get("product") or {}).get("id") or "")
        credits = _credits_for_product(product_id)
        if credits <= 0:
            app.logger.error("polar order %s: product %s is not one of the POLAR_PRODUCT_* values", order_id, product_id)
            return "unknown product", 200

        key = "polar:" + order_id
        try:
            with cursor() as cur:
                cur.execute("select 1 from users where id=%s", (uid,))
                if not cur.fetchone():
                    app.logger.error("polar order %s: user %s does not exist", order_id, uid)
                    return "unknown user", 200
                cur.execute("select 1 from processed_orders where order_id=%s", (key,))
                if cur.fetchone():
                    return "already done", 200  # Polar retried: never add credits twice
                cur.execute("insert into processed_orders(order_id) values(%s)", (key,))
                add_credits(cur, uid, credits, "purchase " + key)
        except psycopg2.errors.UniqueViolation:
            return "already done", 200
        return "ok", 200

    def handle_refunded(data):
        order_id = str(data.get("id") or "")
        if not order_id:
            return "bad payload", 400

        total = data.get("total_amount") or 0
        refunded = data.get("refunded_amount") or 0
        full = data.get("status") == "refunded" or (total > 0 and refunded >= total)
        if not full:
            app.logger.error("polar order %s: partial refund, change the credits by hand", order_id)
            return "not a full refund", 200

        key = "polar:" + order_id
        adj = "adj:" + key
        try:
            with cursor() as cur:
                cur.execute("select 1 from processed_orders where order_id=%s", (adj,))
                if cur.fetchone():
                    return "already done", 200
                cur.execute(
                    "select user_id,amount from credit_ledger where reason=%s and amount > 0 limit 1",
                    ("purchase " + key,),
                )
                row = cur.fetchone()
                if not row:
                    app.logger.error("polar refund %s: no credits found for that purchase", order_id)
                    return "no purchase found", 200
                uid, granted = row
                cur.execute("select credits from users where id=%s for update", (uid,))
                bal = cur.fetchone()
                if not bal:
                    return "unknown user", 200
                cur.execute("insert into processed_orders(order_id) values(%s)", (adj,))
                take = min(granted, max(bal[0], 0))  # never push the balance below zero
                if take > 0:
                    cur.execute("update users set credits = credits - %s where id=%s", (take, uid))
                    cur.execute(
                        "insert into credit_ledger(user_id,amount,reason) values(%s,%s,%s)",
                        (uid, -take, "refund for purchase " + key),
                    )
                if take < granted:
                    app.logger.error("polar refund %s: user %s had already spent %s credits", order_id, uid, granted - take)
        except psycopg2.errors.UniqueViolation:
            return "already done", 200
        return "ok", 200

    @app.post("/polar/webhook")
    def polar_webhook():
        secret = os.environ.get("POLAR_WEBHOOK_SECRET", "").strip()
        if not secret:
            return "billing not enabled", 503

        raw = request.get_data()
        if not _signature_ok(raw, request.headers, secret):
            return "bad signature", 401

        event = request.get_json(silent=True) or {}
        kind = event.get("type")
        data = event.get("data") or {}
        if kind == "order.paid":
            return handle_paid(data)
        if kind == "order.refunded":
            return handle_refunded(data)
        return "ignored", 200  # subscription.* and other events need no action
