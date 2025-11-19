from flask import Flask, request, jsonify
from flask_cors import CORS
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import csv
from datetime import datetime
from time import time
import os

app = Flask(__name__)
CORS(app)

# ================================
# GLOBAL SPAM PROTECTION
# ================================
LAST_SENT = {}   # IP → timestamp


# ================================
# ROOT ROUTE
# ================================
@app.route("/")
def home():
    return jsonify({"message": "Backend running — Contact form ready!"})


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
# EMAIL SETTINGS (from Render ENV variables)
# ================================
EMAIL_USER = os.environ.get("SMTP_SENDER")
EMAIL_PASS = os.environ.get("SMTP_APP_PASSWORD")


# ================================
# SEND EMAIL FUNCTION
# ================================
def send_email(name, email, phone, subject, message):
    receiver = EMAIL_USER
    cc_email = EMAIL_USER  # send copy to yourself

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

    msg = MIMEMultipart()
    msg["From"] = EMAIL_USER
    msg["To"] = receiver
    msg["Cc"] = cc_email
    msg["Subject"] = f"New Message — {subject}"
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_USER, EMAIL_PASS)
        server.sendmail(EMAIL_USER, [receiver, cc_email], msg.as_string())


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
    ip = request.remote_addr
    now = time()

    # rate limit 1 request per 30 sec
    if ip in LAST_SENT and now - LAST_SENT[ip] < 30:
        return jsonify({"success": False, "error": "Wait 30 sec before sending again"}), 429

    LAST_SENT[ip] = now

    data = request.get_json()

    name = data.get("name")
    email = data.get("email")
    phone = data.get("phone")
    subject = data.get("subject")
    message = data.get("message")
    honeypot = data.get("hp_field")

    # Bot detection (honeypot)
    if honeypot:
        return jsonify({"success": True})

    # Save CSV
    log_to_csv(name, email, phone, subject, message)

    # Send email
    try:
        send_email(name, email, phone, subject, message)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# ================================
# RUN SERVER (local only)
# ================================
if __name__ == "__main__":
    app.run(debug=True)
