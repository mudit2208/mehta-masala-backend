from flask import Flask, request, jsonify
from flask_cors import CORS
import csv
from datetime import datetime
from time import time
import os
import requests
import razorpay

app = Flask(__name__)
CORS(
    app,
    resources={r"/*": {"origins": "*"}},
    supports_credentials=True,
    allow_headers=["Content-Type"],
    methods=["GET", "POST", "OPTIONS"]
)

# ================================
# GLOBAL SPAM PROTECTION
# ================================
LAST_SENT = {}

# ================================
# ROOT ROUTE
# ================================
@app.route("/")
def home():
    return jsonify({"message": "Backend running without database, using CSV + Email!"})

# ================================
# SAVE ORDER TO CSV + SEND EMAIL
# ================================
@app.route("/create-order", methods=["POST"])
def create_order():
    data = request.get_json()

    if not data:
        return jsonify({"error": "No data provided"}), 400

    customer = data.get('customer', {})
    cart = data.get('cart', [])
    total = data.get('total', 0)

    order_id = "ORD" + str(int(time() * 100))[-8:]

    # ====================
    # SAVE ORDER TO CSV
    # ====================
    try:
        with open("orders.csv", "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                order_id,
                customer.get('name'),
                customer.get('phone'),
                customer.get('address'),
                customer.get('city'),
                customer.get('pincode'),
                total,
                cart
            ])
    except Exception as e:
        return jsonify({"error": f"CSV error: {e}"}), 500

    # ====================
    # SEND ORDER EMAIL
    # ====================
    try:
        order_email_body = f"""
        <h2>New Order Received</h2>
        <p><strong>Order ID:</strong> {order_id}</p>
        <p><strong>Name:</strong> {customer.get('name')}</p>
        <p><strong>Phone:</strong> {customer.get('phone')}</p>
        <p><strong>Address:</strong> {customer.get('address')}, {customer.get('city')}, {customer.get('pincode')}</p>
        <p><strong>Total Amount:</strong> {total}</p>

        <h3>Items:</h3>
        """
        for item in cart:
            order_email_body += f"""
                <p>{item.get('name')} — {item.get('quantity')} pcs — ₹{item.get('price')}</p>
            """

        send_email(
            name=customer.get("name"),
            email="order@mehtamasala.com",  # your dummy sender
            phone=customer.get("phone"),
            subject=f"New Order — {order_id}",
            message=order_email_body
        )

    except Exception as e:
        return jsonify({"error": f"Email error: {e}"}), 500

    return jsonify({"success": True, "order_id": order_id})


# ================================
# CONTACT FORM HANDLER
# ================================
SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY")
SENDGRID_FROM = os.environ.get("SENDGRID_FROM")
SENDGRID_TO = os.environ.get("SENDGRID_TO", SENDGRID_FROM)
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET")

razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

def send_email(name, email, phone, subject, message):
    if not SENDGRID_API_KEY or not SENDGRID_FROM:
        raise RuntimeError("SendGrid environment variables are not set")

    payload = {
        "personalizations": [
            {
                "to": [{"email": SENDGRID_TO}],
                "subject": subject
            }
        ],
        "from": {"email": SENDGRID_FROM, "name": "Mehta Masala Website"},
        "reply_to": {"email": email or SENDGRID_FROM},
        "content": [{"type": "text/html", "value": message}],
    }

    headers = {
        "Authorization": f"Bearer {SENDGRID_API_KEY}",
        "Content-Type": "application/json"
    }

    resp = requests.post(
        "https://api.sendgrid.com/v3/mail/send",
        json=payload,
        headers=headers,
        timeout=10
    )

    if resp.status_code not in (200, 202):
        raise RuntimeError(f"SendGrid error {resp.status_code}: {resp.text}")


def log_to_csv(name, email, phone, subject, message):
    with open("contact_logs.csv", "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            name, email, phone, subject, message
        ])

@app.route("/create-razorpay-order", methods=["POST"])
def create_razorpay_order():
    data = request.get_json()
    amount = int(data.get("amount", 0)) * 100  # Convert to paise

    try:
        rzp_order = razorpay_client.order.create({
            "amount": amount,
            "currency": "INR",
            "payment_capture": 1
        })

        return jsonify({
            "success": True,
            "razorpay_order_id": rzp_order["id"],
            "amount": amount,
            "key": RAZORPAY_KEY_ID
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/verify-payment", methods=["POST"])
def verify_payment():
    data = request.get_json()

    try:
        razorpay_client.utility.verify_payment_signature({
            "razorpay_order_id": data["razorpay_order_id"],
            "razorpay_payment_id": data["razorpay_payment_id"],
            "razorpay_signature": data["razorpay_signature"]
        })
        return jsonify({"success": True})

    except:
        return jsonify({"success": False}), 400

@app.route("/send-message", methods=["POST"])
def send_message():
    global LAST_SENT
    ip = request.remote_addr or "unknown"
    now = time()

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

    if honeypot:
        return jsonify({"success": True})

    if not name or not email or not message:
        return jsonify({"success": False, "error": "Name, email and message are required"}), 400

    log_to_csv(name, email, phone, subject, message)

    try:
        send_email(name, email, phone, subject, message)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ================================
# RUN SERVER
# ================================
if __name__ == "__main__":
    app.run(debug=True)
