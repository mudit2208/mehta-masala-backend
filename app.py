from flask import Flask, request, jsonify
from flask_cors import CORS
import csv
from datetime import datetime
from time import time
import os
import requests  # <-- for SendGrid API

app = Flask(__name__)
CORS(app)

# ================================
# GLOBAL SPAM PROTECTION
# ================================
LAST_SENT = {}   # IP → timestamp (when last message was sent)

# ================================
# ROOT ROUTE
# ================================
@app.route("/")
def home():
    return jsonify({"message": "Backend running — Contact form via SendGrid ready!"})

# ================================
# TEST MODE: CREATE ORDER (NO RAZORPAY)
# ================================
@app.route("/create-order", methods=["POST"])
def create_order():
    data = request.get_json()

    if not data or "amount" not in data:
        return jsonify({"error": "Amount is required"}), 400

    fake_order = {
        "id": "test_order_12345",
        "amount": int(data["amount"]) * 100,
        "currency": "INR",
        "status": "created"
    }

    return jsonify({"success": True, "order": fake_order})

# ================================
# TEST MODE: VERIFY PAYMENT
# ================================
@app.route("/verify-payment", methods=["POST"])
def verify_payment():
    return jsonify({"success": True, "message": "Payment verified (TEST MODE)"})


# ================================
# SENDGRID SETTINGS FROM ENV
# ================================
SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY")
SENDGRID_FROM = os.environ.get("SENDGRID_FROM")
SENDGRID_TO = os.environ.get("SENDGRID_TO", SENDGRID_FROM)


# ================================
# SEND EMAIL VIA SENDGRID API
# ================================
def send_email(name, email, phone, subject, message):
    """
    Uses SendGrid's v3 Mail Send API over HTTPS (no SMTP).
    """

    if not SENDGRID_API_KEY or not SENDGRID_FROM:
        raise RuntimeError("SendGrid environment variables are not set")

    # Build email content
    html_body = f"""
    <html>
    <body style="font-family: Arial; padding: 20px;">
        <h2 style="color:#2C7A52;">New Contact Form Message</h2>

        <p><strong>Name:</strong> {name}</p>
        <p><strong>Email:</strong> {email}</p>
        <p><strong>Phone:</strong> {phone}</p>
        <p><strong>Subject:</strong> {subject}</p>

        <p><strong>Message:</strong><br>{message}</p>

        <hr>
        <p style="color:#777;font-size:13px;">
            Submitted via Mehta Masala Website.
        </p>
    </body>
    </html>
    """

    # SendGrid API payload
    payload = {
        "personalizations": [
            {
                "to": [{"email": SENDGRID_TO}],
                "subject": f"New Message — {subject}"
            }
        ],
        "from": {"email": SENDGRID_FROM, "name": "Mehta Masala Website"},
        "reply_to": {"email": email or SENDGRID_FROM},
        "content": [
            {
                "type": "text/html",
                "value": html_body
            }
        ]
    }

    headers = {
        "Authorization": f"Bearer {SENDGRID_API_KEY}",
        "Content-Type": "application/json"
    }

    resp = requests.post(
        "https://api.sendgrid.com/v3/mail/send",
        json=payload,
        headers=headers,
        timeout=10  # seconds
    )

    # SendGrid returns 202 for success
    if resp.status_code not in (200, 202):
        raise RuntimeError(f"SendGrid error {resp.status_code}: {resp.text}")


# ================================
# CSV LOGGING
# ================================
def log_to_csv(name, email, phone, subject, message):
    with open("contact_logs.csv", "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            name, email, phone, subject, message
        ])


# ================================
# CONTACT FORM ROUTE
# ================================
@app.route("/send-message", methods=["POST"])
def send_message():
    global LAST_SENT
    ip = request.remote_addr or "unknown"
    now = time()

    # Rate limit: 1 request per 30 seconds from same IP
    if ip in LAST_SENT and now - LAST_SENT[ip] < 30:
        return jsonify({"success": False, "error": "Wait 30 sec before sending again"}), 429

    LAST_SENT[ip] = now

    data = request.get_json() or {}

    name = data.get("name")
    email = data.get("email")
    phone = data.get("phone")
    subject = data.get("subject") or "Contact form"
    message = data.get("message")
    honeypot = data.get("hp_field")

    # Honeypot for bots
    if honeypot:
        # silently accept (but do nothing)
        return jsonify({"success": True})

    # Basic validation
    if not name or not email or not message:
        return jsonify({"success": False, "error": "Name, email and message are required"}), 400

    # Save CSV
    log_to_csv(name, email, phone, subject, message)

    # Send email via SendGrid
    try:
        send_email(name, email, phone, subject, message)
        return jsonify({"success": True})
    except Exception as e:
        # Return error so we can see it while testing
        return jsonify({"success": False, "error": str(e)}), 500


# ================================
# RUN SERVER (local dev only)
# ================================
if __name__ == "__main__":
    app.run(debug=True)