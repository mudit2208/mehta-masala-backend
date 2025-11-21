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
    # [Keep your existing SendGrid code]
    # ... your existing send_email function ...

def log_to_csv(name, email, phone, subject, message):
    # [Keep your existing CSV logging]
    # ... your existing log_to_csv function ...

@app.route("/send-message", methods=["POST"])
def send_message():
    # [Keep your existing contact form code]
    # ... your existing send_message function ...

# ================================
# RUN SERVER
# ================================
if __name__ == "__main__":
    app.run(debug=True)