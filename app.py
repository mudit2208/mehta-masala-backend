from flask import Flask, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import jwt
from functools import wraps
from datetime import datetime, timedelta
from flask_cors import CORS
import csv
from time import time
import os
import requests
import io
import base64
import razorpay
import psycopg2
import psycopg2.extras

app = Flask(__name__)
SECRET_KEY = "your_secret_key_here_change_it"
CORS(
    app,
    resources={r"/*": {"origins": "*"}},
    supports_credentials=True,
    allow_headers=["Content-Type", "Authorization"],
    expose_headers=["Authorization"],
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



def get_db_connection():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST"),
        database=os.environ.get("DB_NAME"),
        user=os.environ.get("DB_USER"),
        password=os.environ.get("DB_PASSWORD"),
        port=os.environ.get("DB_PORT")
    )

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

    # Generate order ID
    order_id = "ORD" + str(int(time() * 100))[-8:]

    # Defaults
    payment_info.setdefault("method", "unknown")
    payment_info.setdefault("status", "pending")
    payment_info.setdefault("razorpay_order_id", None)
    payment_info.setdefault("razorpay_payment_id", None)
    payment_info.setdefault("razorpay_signature", None)

    # Insert into PostgreSQL
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Insert order
        cur.execute("""
            INSERT INTO orders (
                order_id, razorpay_order_id, razorpay_payment_id, razorpay_signature,
                customer_name, customer_phone, customer_address, customer_city, customer_pincode,
                payment_method, total_amount, payment_status
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id;
        """, (
            order_id,
            payment_info.get("razorpay_order_id"),
            payment_info.get("razorpay_payment_id"),
            payment_info.get("razorpay_signature"),
            customer.get("name"),
            customer.get("phone"),
            customer.get("address"),
            customer.get("city"),
            customer.get("pincode"),
            payment_info.get("method"),
            int(total),
            payment_info.get("status")
        ))

        order_db_id = cur.fetchone()[0]

        # Insert items
        for item in cart:
            cur.execute("""
                INSERT INTO order_items (
                    order_ref, slug, name, price, weight, quantity, image
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s)
            """, (
                order_db_id,
                item.get("slug"),
                item.get("name"),
                int(item.get("price", 0)),
                int(item.get("weight", 0) or 0),
                int(item.get("quantity", 0)),
                item.get("image")
            ))

        conn.commit()
        cur.close()
        conn.close()

    except Exception as e:
        print("DB error:", e)
        return jsonify({"success": False, "error": "Database write error"}), 500

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
            os.getenv("RAZORPAY_KEY_SECRET")
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

def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        token = request.headers.get("Authorization")
        if not token:
            return jsonify({"success": False, "message": "Missing token"}), 401
        try:
            decoded = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            request.admin_id = decoded["admin_id"]
        except:
            return jsonify({"success": False, "message": "Invalid or expired token"}), 401
        return fn(*args, **kwargs)
    return wrapper

@app.post("/admin/login")
def admin_login():
    data = request.get_json() or {}
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"success": False, "message": "Email and password required"}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        cur.execute("SELECT * FROM admin_users WHERE email=%s", (email,))
        admin = cur.fetchone()

        cur.close()
        conn.close()
    except Exception as e:
        print("DB error in admin_login:", e)
        return jsonify({"success": False, "message": "Database error"}), 500

    if not admin:
        return jsonify({"success": False, "message": "Invalid credentials"}), 401

    if not check_password_hash(admin["password_hash"], password):
        return jsonify({"success": False, "message": "Invalid credentials"}), 401

    token = jwt.encode(
        {"admin_id": admin["id"], "exp": datetime.utcnow() + timedelta(hours=12)},
        SECRET_KEY,
        algorithm="HS256"
    )

    return jsonify({"success": True, "token": token})

@app.get("/admin/orders")
@admin_required
def admin_orders():
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        cur.execute("SELECT * FROM orders ORDER BY created_at DESC")
        rows = cur.fetchall()

        cur.close()
        conn.close()
    except Exception as e:
        print("DB error in admin_orders:", e)
        return jsonify({"success": False, "message": "Database error"}), 500

    orders = [dict(r) for r in rows]  # Convert DictRow → dict

    return jsonify({"success": True, "orders": orders})


# ================================
# RUN LOCAL
# ================================
if __name__ == "__main__":
    app.run(debug=True)