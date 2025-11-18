from flask import Flask, request, jsonify
from flask_cors import CORS
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

app = Flask(__name__)
CORS(app)


# -------------------------------------------------
# ROOT
# -------------------------------------------------
@app.route("/")
def home():
    return jsonify({"message": "Backend running — Test Mode (No Razorpay)"})


# -------------------------------------------------
# TEST MODE — CREATE ORDER (NO PAYMENT GATEWAY)
# -------------------------------------------------
@app.route("/create-order", methods=["POST"])
def create_order():
    data = request.get_json()

    if not data or "amount" not in data:
        return jsonify({"error": "Amount is required"}), 400

    amount = int(data["amount"])

    fake_order = {
        "id": "test_order_12345",
        "amount": amount * 100,
        "currency": "INR",
        "status": "created"
    }

    return jsonify({
        "success": True,
        "order": fake_order
    })


# -------------------------------------------------
# TEST MODE — VERIFY PAYMENT (ALWAYS SUCCESS)
# -------------------------------------------------
@app.route("/verify-payment", methods=["POST"])
def verify_payment():
    return jsonify({"success": True, "message": "Payment verified (TEST MODE)"})


# -------------------------------------------------
# CONTACT FORM — WITH HONEYPOT PROTECTION
# -------------------------------------------------
@app.route("/send-message", methods=["POST"])
def send_message():
    data = request.get_json()

    # -----------------------------
    # Honeypot spam detection
    # -----------------------------
    if data.get("hp_field"):  
        return jsonify({"success": True})   # silently ignore spam

    # Extract details
    name = data.get("name")
    email = data.get("email")
    phone = data.get("phone")
    subject = data.get("subject")
    message = data.get("message")

    # Build email body
    full_message = f"""
New message received from Mehta Masala Contact Page:

Name: {name}
Email: {email}
Phone: {phone}
Subject: {subject}

Message:
{message}
"""

    # Gmail credentials
    sender_email = "masalamehta@gmail.com"
    receiver_email = "masalamehta@gmail.com"
    password = "awbfzkmolwtwcddj"   # your Gmail App Password

    try:
        msg = MIMEMultipart()
        msg["From"] = sender_email
        msg["To"] = receiver_email
        msg["Subject"] = f"New Contact Message — {subject}"

        msg.attach(MIMEText(full_message, "plain"))

        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(sender_email, password)
        server.sendmail(sender_email, receiver_email, msg.as_string())
        server.quit()

        return jsonify({"success": True})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# -------------------------------------------------
# RUN SERVER
# -------------------------------------------------
if __name__ == "__main__":
    app.run(debug=True)
