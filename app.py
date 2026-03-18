from flask import Flask, request, jsonify
import anthropic
import os
import smtplib
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

app = Flask(__name__)

ANTHROPIC_API_KEY = (os.environ.get("ANTHROPIC_API_KEY") or "").strip().replace("\n", "").replace(" ", "")
print(f"API KEY LOADED: {'YES - starts with ' + ANTHROPIC_API_KEY[:10] if ANTHROPIC_API_KEY else 'NO - NOT FOUND'}", flush=True)
NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL", "lee@digitalscanninggroup.com")
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASS = os.environ.get("SMTP_PASS")
CRM_URL = os.environ.get("CRM_URL", "http://100.127.244.118:5050")

SYSTEM = """You are a friendly sales assistant for Digital Scanning Group (DSG), a professional surveying company.

DSG's services:
- Matterport 3D surveys & virtual tours
- Point cloud surveys (LiDAR)
- Revit modelling (BIM)
- Drone surveys & aerial photography
- Timelapse cameras
- Gridlines and datums

Key facts:
- Coverage: Europe-wide and worldwide
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


def send_notification(name, email, phone):
    if not SMTP_USER or not SMTP_PASS:
        return
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"New Website Lead – {name}"
        msg["From"] = SMTP_USER
        msg["To"] = NOTIFY_EMAIL
        html = f"""<html><body style="font-family:Arial,sans-serif;max-width:600px;margin:32px auto">
<h2 style="color:#1a3c6e">New Website Lead!</h2>
<table style="width:100%;border-collapse:collapse">
<tr><td style="padding:8px;color:#666;width:100px">Name</td><td style="padding:8px;font-weight:bold">{name}</td></tr>
<tr style="background:#f9f9f9"><td style="padding:8px;color:#666">Email</td><td style="padding:8px">{email}</td></tr>
<tr><td style="padding:8px;color:#666">Phone</td><td style="padding:8px">{phone or '—'}</td></tr>
<tr style="background:#f9f9f9"><td style="padding:8px;color:#666">Source</td><td style="padding:8px">Website Chatbot</td></tr>
</table>
</body></html>"""
        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, NOTIFY_EMAIL, msg.as_string())
        print(f"EMAIL SENT to {NOTIFY_EMAIL}", flush=True)
    except Exception as e:
        print(f"EMAIL ERROR: {e}", flush=True)


def add_to_crm(name, email, phone):
    try:
        import urllib.request
        import urllib.parse
        data = urllib.parse.urlencode({
            "title": f"Website Enquiry – {name}",
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


@app.route("/chat", methods=["POST", "OPTIONS"])
def chat():
    if request.method == "OPTIONS":
        response = jsonify({})
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        return response

    data = request.get_json()
    messages = data.get("messages", [])
    lead = data.get("lead", {})

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    result = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        system=SYSTEM,
        messages=messages
    )
    reply = result.content[0].text.strip()

    saved = False
    print(f"LEAD STATE: {lead}", flush=True)
    if lead.get("email") and not lead.get("saved"):
        print(f"LEAD CAPTURED: {lead}", flush=True)
        send_notification(lead.get("name",""), lead.get("email",""), lead.get("phone",""))
        add_to_crm(lead.get("name",""), lead.get("email",""), lead.get("phone",""))
        saved = True

    response = jsonify({"reply": reply, "saved": saved})
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response

@app.errorhandler(500)
def handle_500(e):
    import traceback
    response = jsonify({"error": str(e), "trace": traceback.format_exc()})
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.status_code = 500
    return response


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5050)))
