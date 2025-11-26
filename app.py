from flask import Flask, request, jsonify
from flask_cors import CORS
import csv
from datetime import datetime
from time import time
import os
import requests
import io
import base64
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
# CONFIG
# ================================
SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY")
SENDGRID_FROM = os.environ.get("SENDGRID_FROM")
SENDGRID_TO = os.environ.get("SENDGRID_TO", SENDGRID_FROM)

RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET")
razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

LAST_SENT = {}  # contact form spam protection
ADMIN_DASHBOARD_KEY = os.environ.get("ADMIN_DASHBOARD_KEY", "MehtaMasalaAdmin2025")


# ================================
# HELPERS
# ================================
def log_contact_to_csv(name, email, phone, subject, message):
    with open("contact_logs.csv", "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            name, email, phone, subject, message
        ])


def log_order_to_csv(order_id, customer, cart, total, payment_info):
    with open("orders.csv", "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            order_id,
            customer.get("name"),
            customer.get("email"),
            customer.get("phone"),
            customer.get("address"),
            customer.get("city"),
            customer.get("pincode"),
            total,
            payment_info.get("method"),
            payment_info.get("status"),
            payment_info.get("razorpay_order_id"),
            payment_info.get("razorpay_payment_id")
        ])

STATUS_FILE = "order_status.csv"

def load_order_statuses():
    """
    Read shipping statuses from order_status.csv
    Returns dict: {order_id: status_str}
    """
    statuses = {}
    if not os.path.exists(STATUS_FILE):
        return statuses

    try:
        with open(STATUS_FILE, "r", newline="") as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) < 2:
                    continue
                oid, st = row[0], row[1]
                statuses[oid] = st
    except Exception as e:
        print("Error reading order_status.csv:", e)

    return statuses


def save_order_statuses(statuses):
    """
    Overwrite order_status.csv with current statuses dict.
    """
    try:
        with open(STATUS_FILE, "w", newline="") as f:
            writer = csv.writer(f)
            for oid, st in statuses.items():
                writer.writerow([oid, st])
    except Exception as e:
        print("Error writing order_status.csv:", e)


def load_orders_from_csv():
    """
    Read orders from orders.csv and attach shipping_status from order_status.csv
    """
    orders = []
    if not os.path.exists("orders.csv"):
        return orders

    # Load shipping statuses once
    statuses = load_order_statuses()

    try:
        with open("orders.csv", "r", newline="") as f:
            reader = csv.reader(f)
            for row in reader:
                # row format:
                # 0: timestamp
                # 1: order_id
                # 2: name
                # 3: email
                # 4: phone
                # 5: address
                # 6: city
                # 7: pincode
                # 8: total
                # 9: payment_method
                # 10: payment_status
                # 11: razorpay_order_id
                # 12: razorpay_payment_id
                if len(row) < 13:
                    continue

                oid = row[1]
                shipping_status = statuses.get(oid, "Pending")

                orders.append({
                    "created_at": row[0],
                    "order_id": oid,
                    "name": row[2],
                    "email": row[3],
                    "phone": row[4],
                    "address": row[5],
                    "city": row[6],
                    "pincode": row[7],
                    "total": row[8],
                    "payment_method": row[9],
                    "payment_status": row[10],
                    "razorpay_order_id": row[11],
                    "razorpay_payment_id": row[12],
                    "shipping_status": shipping_status,
                })
    except Exception as e:
        print("Error reading orders.csv:", e)

    # newest first
    orders.reverse()
    return orders


def send_sendgrid_email(to_emails, subject, html_body, attachments=None):
    """
    Generic SendGrid email sender with optional attachments.
    to_emails: list of emails
    attachments: list of dicts with keys (content, type, filename)
    """
    if not SENDGRID_API_KEY or not SENDGRID_FROM:
        raise RuntimeError("SendGrid environment variables are not set")

    personalizations = [{
        "to": [{"email": e} for e in to_emails],
        "subject": subject
    }]

    payload = {
        "personalizations": personalizations,
        "from": {"email": SENDGRID_FROM, "name": "Mehta Masala Website"},
        "content": [{"type": "text/html", "value": html_body}]
    }

    if attachments:
        payload["attachments"] = attachments

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


def build_order_csv_attachment(order_id, customer, cart, total, payment_info):
    """
    Build a CSV file (as base64) for a single order.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)

    writer.writerow(["Order ID", order_id])
    writer.writerow(["Date", datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
    writer.writerow([])
    writer.writerow(["Customer Name", customer.get("name")])
    writer.writerow(["Email", customer.get("email")])
    writer.writerow(["Phone", customer.get("phone")])
    writer.writerow(["Address", customer.get("address")])
    writer.writerow(["City", customer.get("city")])
    writer.writerow(["Pincode", customer.get("pincode")])
    writer.writerow([])
    writer.writerow(["Payment Method", payment_info.get("method")])
    writer.writerow(["Payment Status", payment_info.get("status")])
    writer.writerow(["Razorpay Order ID", payment_info.get("razorpay_order_id")])
    writer.writerow(["Razorpay Payment ID", payment_info.get("razorpay_payment_id")])
    writer.writerow([])

    writer.writerow(["Item Name", "Quantity", "Price (₹)", "Weight", "Line Total (₹)"])
    subtotal = 0
    for item in cart:
        qty = int(item.get("quantity", 0))
        price = float(item.get("price", 0))
        line_total = qty * price
        subtotal += line_total
        writer.writerow([
            item.get("name"),
            qty,
            price,
            item.get("weight"),
            line_total
        ])

    writer.writerow([])
    writer.writerow(["Subtotal", subtotal])
    writer.writerow(["Final Total", total])

    csv_string = buffer.getvalue()
    csv_bytes = csv_string.encode("utf-8")
    b64 = base64.b64encode(csv_bytes).decode("utf-8")

    return [{
        "content": b64,
        "type": "text/csv",
        "filename": f"order_{order_id}.csv"
    }]


def send_order_email(order_id, customer, cart, total, payment_info):
    """
    Sends order confirmation to customer + you, with CSV attachment.
    """
    customer_email = customer.get("email")
    to_emails = []

    if customer_email:
        to_emails.append(customer_email)

    # Always send to your business email
    to_emails.append(SENDGRID_TO)

    items_html = ""
    for item in cart:
        items_html += f"""
        <tr>
            <td>{item.get('name')}</td>
            <td>{item.get('quantity')}</td>
            <td>₹{item.get('price')}</td>
            <td>{item.get('weight') or ''}</td>
        </tr>
        """

    html_body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; padding: 20px;">
        <h2 style="color:#2C7A52;">Order Confirmation – {order_id}</h2>

        <p>Thank you for your order with <strong>Mehta Masala Gruh Udhyog</strong>.</p>

        <h3>Customer Details</h3>
        <p>
            <strong>Name:</strong> {customer.get('name')}<br/>
            <strong>Email:</strong> {customer.get('email') or '-'}<br/>
            <strong>Phone:</strong> {customer.get('phone')}<br/>
            <strong>Address:</strong> {customer.get('address')}, {customer.get('city')} - {customer.get('pincode')}
        </p>

        <h3>Payment Details</h3>
        <p>
            <strong>Method:</strong> {payment_info.get('method')}<br/>
            <strong>Status:</strong> {payment_info.get('status')}<br/>
            <strong>Razorpay Order ID:</strong> {payment_info.get('razorpay_order_id') or '-'}<br/>
            <strong>Razorpay Payment ID:</strong> {payment_info.get('razorpay_payment_id') or '-'}
        </p>

        <h3>Order Items</h3>
        <table border="1" cellpadding="6" cellspacing="0" style="border-collapse: collapse;">
            <tr style="background:#f2f2f2;">
                <th>Item</th>
                <th>Qty</th>
                <th>Price (₹)</th>
                <th>Weight</th>
            </tr>
            {items_html}
        </table>

        <h3>Total Amount: ₹{total}</h3>

        <p style="margin-top:20px; font-size:13px; color:#555;">
            A CSV copy of this order is attached for your records.
        </p>

        <hr/>
        <p style="font-size:12px; color:#777;">
            Mehta Masala Gruh Udhyog<br/>
            Ujjain, Madhya Pradesh
        </p>
    </body>
    </html>
    """

    attachments = build_order_csv_attachment(order_id, customer, cart, total, payment_info)
    send_sendgrid_email(to_emails, f"Order Confirmation – {order_id}", html_body, attachments=attachments)


# ================================
# ROUTES
# ================================
@app.route("/")
def home():
    return jsonify({"message": "Backend running – orders via CSV + Email + Razorpay."})


@app.route("/create-order", methods=["POST"])
def create_order():
    data = request.get_json() or {}

    customer = data.get("customer", {})
    cart = data.get("cart", [])
    total = data.get("total", 0)
    payment_info = data.get("payment", {}) or {}

    # Basic validation
    required = ["name", "phone", "email", "address", "city", "pincode"]
    missing = [field for field in required if not customer.get(field)]
    if missing:
        return jsonify({"success": False, "error": f"Missing fields: {', '.join(missing)}"}), 400

    if not cart:
        return jsonify({"success": False, "error": "Cart empty"}), 400

    order_id = "ORD" + str(int(time() * 100))[-8:]

    # Ensure basic payment defaults
    payment_info.setdefault("method", "unknown")
    payment_info.setdefault("status", "pending")
    payment_info.setdefault("razorpay_order_id", None)
    payment_info.setdefault("razorpay_payment_id", None)

    # 1) Log to CSV file
    log_order_to_csv(order_id, customer, cart, total, payment_info)

    # 2) Send emails with CSV attachment
    try:
        send_order_email(order_id, customer, cart, total, payment_info)
    except Exception as e:
        return jsonify({"success": False, "error": f"Email error: {e}"}), 500

    return jsonify({"success": True, "order_id": order_id})


@app.route("/verify-payment", methods=["POST"])
def verify_payment():
    data = request.get_json() or {}

    try:
        razorpay_client.utility.verify_payment_signature({
            "razorpay_order_id": data["razorpay_order_id"],
            "razorpay_payment_id": data["razorpay_payment_id"],
            "razorpay_signature": data["razorpay_signature"],
        })
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

@app.route("/admin/orders", methods=["GET"])
def admin_get_orders():
    """
    Simple admin API endpoint to fetch all orders from CSV.
    Protected by a query parameter ?key=ADMIN_DASHBOARD_KEY.
    """
    key = request.args.get("key")
    if key != ADMIN_DASHBOARD_KEY:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    orders = load_orders_from_csv()
    return jsonify({"success": True, "orders": orders})

@app.route("/admin/update-status", methods=["POST"])
def admin_update_status():
    """
    Update shipping status for an order.
    Body JSON: { key: ADMIN_DASHBOARD_KEY, order_id: "...", status: "Pending/Shipped/Delivered" }
    """
    data = request.get_json() or {}
    key = data.get("key")
    if key != ADMIN_DASHBOARD_KEY:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    order_id = data.get("order_id")
    new_status = data.get("status")

    allowed_statuses = {"Pending", "Shipped", "Delivered"}
    if not order_id or new_status not in allowed_statuses:
        return jsonify({"success": False, "error": "Invalid order_id or status"}), 400

    statuses = load_order_statuses()
    statuses[order_id] = new_status
    save_order_statuses(statuses)

    return jsonify({"success": True})



# ----------------------------
# CONTACT FORM ROUTES (unchanged)
# ----------------------------
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

    log_contact_to_csv(name, email, phone, subject, message)

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

    try:
        send_sendgrid_email([SENDGRID_TO], f"New Contact – {subject}", html_body)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# =====================================
# RAZORPAY ORDER CREATION (NEW ROUTE)
# =====================================
@app.route("/create-razorpay-order", methods=["POST"])
def create_razorpay_order():
    try:
        data = request.get_json()
        amount = int(data.get("amount", 0))

        if amount <= 0:
            return jsonify({"success": False, "error": "Invalid amount"}), 400

        # Razorpay works in paise → convert rupees to paise
        amount_paise = amount * 100

        # Initialize Razorpay client
        client = razorpay.Client(auth=(
            os.getenv("RAZORPAY_KEY_ID"),
            os.getenv("RAZORPAY_SECRET")
        ))

        order = client.order.create({
            "amount": amount_paise,
            "currency": "INR",
            "payment_capture": 1
        })

        return jsonify({
            "success": True,
            "order_id": order["id"],
            "amount": order["amount"],
            "key": os.getenv("RAZORPAY_KEY_ID")
        })

    except Exception as e:
        print("Razorpay Order Error:", e)
        return jsonify({"success": False, "error": str(e)}), 500


# ================================
# RUN LOCAL
# ================================
if __name__ == "__main__":
    app.run(debug=True)
