from flask import Flask, request, jsonify
from flask_cors import CORS
import csv
from datetime import datetime
from time import time
import os
import requests
import psycopg2  # <-- ADD THIS
from psycopg2.extras import RealDictCursor  # <-- ADD THIS

app = Flask(__name__)
CORS(
    app,
    resources={r"/*": {"origins": "*"}},
    supports_credentials=True,
    allow_headers=["Content-Type"],
    methods=["GET", "POST", "OPTIONS"]
)

# ================================
# DATABASE CONNECTION
# ================================
def get_db_connection():
    """Connect to PostgreSQL database"""
    try:
        conn = psycopg2.connect(
            host=os.environ.get('DB_HOST'),
            database=os.environ.get('DB_NAME'),
            user=os.environ.get('DB_USER'),
            password=os.environ.get('DB_PASSWORD'),
            port=os.environ.get('DB_PORT', 5432)
        )
        return conn
    except Exception as e:
        print(f"Database connection error: {e}")
        return None

initialize_database()

# ================================
# GLOBAL SPAM PROTECTION
# ================================
LAST_SENT = {}

# ================================
# ROOT ROUTE
# ================================
@app.route("/")
def home():
    return jsonify({"message": "Backend running with PostgreSQL!"})

# ================================
# SAVE ORDER TO DATABASE
# ================================
@app.route("/create-order", methods=["POST"])
def create_order():
    data = request.get_json()
    
    if not data:
        return jsonify({"error": "No data provided"}), 400

    # Extract order data
    customer = data.get('customer', {})
    cart = data.get('cart', [])
    total = data.get('total', 0)

    # Generate order ID
    order_id = "ORD" + str(int(time() * 100))[-8:]

    # Save to database
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    try:
        cur = conn.cursor()
        
        # Insert into orders table
        cur.execute("""
            INSERT INTO orders 
            (order_id, customer_name, customer_phone, customer_address, customer_city, customer_pincode, total_amount, payment_status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            order_id,
            customer.get('name'),
            customer.get('phone'),
            customer.get('address'),
            customer.get('city'),
            customer.get('pincode'),
            total,
            'created'
        ))

        order_db_id = cur.fetchone()[0]

        # Insert order items
        for item in cart:
            cur.execute("""
                INSERT INTO order_items 
                (order_ref, slug, name, price, weight, quantity, image)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                order_db_id,
                item.get('slug'),
                item.get('name'),
                item.get('price'),
                item.get('weight'),
                item.get('quantity'),
                item.get('image')
            ))

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            "success": True,
            "order_id": order_id,
            "message": "Order saved successfully"
        })

    except Exception as e:
        conn.rollback()
        return jsonify({"error": f"Database error: {str(e)}"}), 500

# ================================
# GET ORDERS (for testing)
# ================================
@app.route("/orders", methods=["GET"])
def get_orders():
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT o.*, 
                   json_agg(json_build_object(
                       'name', oi.name,
                       'price', oi.price,
                       'quantity', oi.quantity,
                       'weight', oi.weight
                   )) as items
            FROM orders o
            LEFT JOIN order_items oi ON o.id = oi.order_ref
            GROUP BY o.id
            ORDER BY o.created_at DESC
            LIMIT 10
        """)
        orders = cur.fetchall()
        cur.close()
        conn.close()

        return jsonify({"orders": orders})

    except Exception as e:
        return jsonify({"error": f"Database error: {str(e)}"}), 500

# ================================
# REST OF YOUR EXISTING CODE (SendGrid, etc.)
# ================================
# [Keep all your existing SendGrid and contact form code here]
# ... your existing contact form code ...

SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY")
SENDGRID_FROM = os.environ.get("SENDGRID_FROM")
SENDGRID_TO = os.environ.get("SENDGRID_TO", SENDGRID_FROM)

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

def log_to_csv(name, email, phone, subject, message):
    with open("contact_logs.csv", "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            name, email, phone, subject, message
        ])

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

@app.route("/debug-db")
def debug_db():
    return {
        "DB_HOST": os.environ.get("DB_HOST"),
        "DB_NAME": os.environ.get("DB_NAME"),
        "DB_USER": os.environ.get("DB_USER"),
        "DB_PORT": os.environ.get("DB_PORT")
    }

def initialize_database():
    conn = get_db_connection()
    if not conn:
        print("Could not connect to DB at startup.")
        return

    try:
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id SERIAL PRIMARY KEY,
                order_id VARCHAR(50) NOT NULL,
                customer_name TEXT,
                customer_phone TEXT,
                customer_address TEXT,
                customer_city TEXT,
                customer_pincode TEXT,
                total_amount NUMERIC,
                payment_status TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS order_items (
                id SERIAL PRIMARY KEY,
                order_ref INTEGER REFERENCES orders(id) ON DELETE CASCADE,
                slug TEXT,
                name TEXT,
                price NUMERIC,
                weight TEXT,
                quantity INTEGER,
                image TEXT
            );
        """)

        conn.commit()
        cur.close()
        conn.close()
        print("Database tables ensured.")

    except Exception as e:
        print("Error creating tables:", e)



# ================================
# RUN SERVER
# ================================
if __name__ == "__main__":
    app.run(debug=True)