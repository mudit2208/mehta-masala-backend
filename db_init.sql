CREATE DATABASE IF NOT EXISTS mehta_masala CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE mehta_masala;

CREATE TABLE IF NOT EXISTS orders (
  id INT AUTO_INCREMENT PRIMARY KEY,
  order_id VARCHAR(50) UNIQUE,        -- our generated order id (ORDxxxxx)
  razorpay_order_id VARCHAR(100),
  razorpay_payment_id VARCHAR(100),
  razorpay_signature VARCHAR(255),
  customer_name VARCHAR(200),
  customer_phone VARCHAR(20),
  customer_address TEXT,
  customer_city VARCHAR(100),
  customer_pincode VARCHAR(20),
  payment_method VARCHAR(50),
  total_amount INT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  payment_status VARCHAR(50) DEFAULT 'created' -- created / paid / failed
);

CREATE TABLE IF NOT EXISTS order_items (
  id INT AUTO_INCREMENT PRIMARY KEY,
  order_ref INT,
  slug VARCHAR(100),
  name VARCHAR(255),
  price INT,
  weight INT,
  quantity INT,
  image VARCHAR(255),
  FOREIGN KEY (order_ref) REFERENCES orders(id) ON DELETE CASCADE
);

