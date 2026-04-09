from flask import Flask, request, jsonify
import anthropic
import os
import requests
import threading
import html

app = Flask(__name__)

# --- Environment config (fail fast if required vars are missing) ---
ANTHROPIC_API_KEY = (os.environ.get("ANTHROPIC_API_KEY") or "").strip().replace("\n", "").replace(" ", "")
print(f"ANTHROPIC_API_KEY: {'configured' if ANTHROPIC_API_KEY else 'MISSING'}", flush=True)

RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
if not RESEND_API_KEY:
    print("WARNING: RESEND_API_KEY not set — email notifications disabled", flush=True)

CRM_URL = os.environ.get("CRM_URL")
if not CRM_URL:
    print("WARNING: CRM_URL not set — CRM lead capture disabled", flush=True)

NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL", "lee@digitalscanninggroup.com")

# --- CORS ---
ALLOWED_ORIGINS = {
    "https://www.digitalscanninggroup.com",
    "https://digitalscanninggroup.com",
}

# --- Rate limiting ---
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)

SYSTEM = """You are a friendly sales assistant for Digital Scanning Group (DSG), a professional surveying company.

DSG's services:
- Matterport 3D surveys & virtual tours
- Point cloud surveys (LiDAR)
- Revit modelling (BIM)
- Drone surveys & aerial photography
- Timelapse cameras
- Gridlines and datums

Key facts:
- Coverage: London and UK-wide
- Turnaround: Typically 1-2 days
- Sectors: Construction, architecture, property/real estate, heritage, retail, hotels, NHS/healthcare
- Enquiries: lee@digitalscanninggroup.com | 07577705477
- Website: www.digitalscanninggroup.com

Rules:
- Be friendly, professional and concise (2-4 sentences max)
- Never quote specific prices — say "we'll provide a tailored quote based on your requirements"
- Do not mention competitors
- When someone shows interest, ask for their name, email and phone number so Lee can follow up
- Once you have their name and email, confirm you'll pass details to Lee and he'll be in touch within 1 business day"""


def send_notification(name, email, phone, resend_key=None, notify_email=None):
    resend_key = resend_key or RESEND_API_KEY
    if not resend_key:
        return
    notify_email = notify_email or NOTIFY_EMAIL
    try:
        safe_name = html.escape(str(name or ""))
        safe_email = html.escape(str(email or ""))
        safe_phone = html.escape(str(phone or ""))
        html_body = f"""<html><body style="font-family:Arial,sans-serif;max-width:600px;margin:32px auto">
<h2 style="color:#1a3c6e">New Website Lead!</h2>
<table style="width:100%;border-collapse:collapse">
<tr><td style="padding:8px;color:#666;width:100px">Name</td><td style="padding:8px;font-weight:bold">{safe_name or '—'}</td></tr>
<tr style="background:#f9f9f9"><td style="padding:8px;color:#666">Email</td><td style="padding:8px">{safe_email}</td></tr>
<tr><td style="padding:8px;color:#666">Phone</td><td style="padding:8px">{safe_phone or '—'}</td></tr>
<tr style="background:#f9f9f9"><td style="padding:8px;color:#666">Source</td><td style="padding:8px">Website Chatbot</td></tr>
</table>
</body></html>"""
        response = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {resend_key}", "Content-Type": "application/json"},
            json={
                "from": "DSG Chatbot <onboarding@resend.dev>",
                "to": notify_email,
                "subject": "New Website Lead",
                "html": html_body
            },
            timeout=10
        )
        app.logger.info(f"Email notification sent: status={response.status_code}")
    except Exception as e:
        app.logger.error(f"Email notification error: {e}")


def add_to_crm(name, email, phone):
    if not CRM_URL:
        return
    try:
        import urllib.request
        import urllib.parse
        data = urllib.parse.urlencode({
            "title": "Website Enquiry",
            "contact_name": name,
            "org_name": "",
            "stage_id": "30",
            "stage_name": "Lead",
            "pipeline_id": "4",
            "pipeline_name": "New pipeline 2026",
            "notes": f"Email: {email} | Phone: {phone or ''} | Source: Website Chatbot"
        }).encode()
        req = urllib.request.Request(f"{CRM_URL}/pipeline/deal/new", data=data, method="POST")
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


@app.after_request
def apply_security_headers(response):
    # CORS
    origin = request.headers.get("Origin", "")
    if origin in ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        response.headers["Vary"] = "Origin"

    # Security headers
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.route("/chat", methods=["POST", "OPTIONS"])
@limiter.limit("10 per minute")
def chat():
    if request.method == "OPTIONS":
        return jsonify({})

    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    messages = data.get("messages", [])
    lead = data.get("lead", {})

    # Input validation
    if not isinstance(messages, list):
        return jsonify({"error": "messages must be a list"}), 400
    if len(messages) > 20:
        return jsonify({"error": "messages exceeds maximum length of 20"}), 400
    for msg in messages:
        if not isinstance(msg, dict):
            return jsonify({"error": "each message must be an object"}), 400
        if msg.get("role") not in ("user", "assistant"):
            return jsonify({"error": "message role must be 'user' or 'assistant'"}), 400
        if not isinstance(msg.get("content", ""), str):
            return jsonify({"error": "message content must be a string"}), 400
        if len(msg.get("content", "")) > 2000:
            return jsonify({"error": "message content exceeds 2000 characters"}), 400

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    result = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        system=SYSTEM,
        messages=messages
    )
    reply = result.content[0].text.strip()

    saved = False
    if lead.get("email") and not lead.get("saved"):
        app.logger.info("Lead received from website chatbot")
        t = threading.Thread(
            target=send_notification,
            args=(lead.get("name", ""), lead.get("email", ""), lead.get("phone", ""), RESEND_API_KEY, NOTIFY_EMAIL)
        )
        t.daemon = False
        t.start()
        add_to_crm(lead.get("name", ""), lead.get("email", ""), lead.get("phone", ""))
        saved = True

    return jsonify({"reply": reply, "saved": saved})


@app.errorhandler(500)
def handle_500(e):
    import traceback
    app.logger.error(f"Internal server error: {traceback.format_exc()}")
    return jsonify({"error": "An internal error occurred"}), 500


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5050)))
