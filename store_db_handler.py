import os
import sqlite3
import json

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "multi_store.db")
JSON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database.json")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. Create tables
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS stores (
        id TEXT PRIMARY KEY,
        name TEXT,
        desc TEXT,
        admin_id TEXT,
        sector TEXT,
        hidden INTEGER,
        wallet_number TEXT,
        delivery_mode TEXT,
        delivery_fee REAL,
        promo_active INTEGER,
        promo_interval INTEGER,
        promo_product TEXT,
        promo_last_sent REAL
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS categories (
        id TEXT,
        store_id TEXT,
        name TEXT,
        PRIMARY KEY (id, store_id)
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS products (
        id TEXT,
        store_id TEXT,
        category_id TEXT,
        name TEXT,
        price REAL,
        desc TEXT,
        image TEXT,
        discount_price REAL,
        PRIMARY KEY (id, store_id)
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        id TEXT PRIMARY KEY,
        store_id TEXT,
        chat_id INTEGER,
        customer_name TEXT,
        customer_phone TEXT,
        address TEXT,
        order_type TEXT,
        payment_method TEXT,
        total REAL,
        status TEXT,
        time TEXT,
        receipt_photo TEXT
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS order_items (
        order_id TEXT,
        product_id TEXT,
        quantity INTEGER
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        chat_id INTEGER PRIMARY KEY
    )
    """)
    
    conn.commit()
    
    # 2. Check if DB is empty and database.json exists for migration
    cursor.execute("SELECT COUNT(*) FROM stores")
    if cursor.fetchone()[0] == 0 and os.path.exists(JSON_PATH):
        print("[SQLite Migration] Migrating data from database.json to SQLite database...")
        try:
            with open(JSON_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            # Migrate stores
            for s_id, s_info in data.get("stores", {}).items():
                promo = s_info.get("promo", {})
                cursor.execute("""
                INSERT INTO stores (id, name, desc, admin_id, sector, hidden, wallet_number, delivery_mode, delivery_fee, promo_active, promo_interval, promo_product, promo_last_sent)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    s_id,
                    s_info.get("name"),
                    s_info.get("desc"),
                    str(s_info.get("admin_id", "")),
                    s_info.get("sector"),
                    1 if s_info.get("hidden") else 0,
                    s_info.get("wallet_number"),
                    s_info.get("delivery_mode"),
                    s_info.get("delivery_fee", 0.0),
                    1 if promo.get("active") else 0,
                    promo.get("interval_hours", 24),
                    promo.get("product_id", "random"),
                    promo.get("last_sent", 0.0)
                ))
                
                # Migrate categories
                for c_id, c_name in s_info.get("categories", {}).items():
                    cursor.execute("""
                    INSERT INTO categories (id, store_id, name) VALUES (?, ?, ?)
                    """, (c_id, s_id, c_name))
                
                # Migrate products
                for p_id, p_info in s_info.get("products", {}).items():
                    cursor.execute("""
                    INSERT INTO products (id, store_id, category_id, name, price, desc, image, discount_price)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        p_id,
                        s_id,
                        p_info.get("category_id"),
                        p_info.get("name"),
                        p_info.get("price", 0.0),
                        p_info.get("desc"),
                        p_info.get("image"),
                        p_info.get("discount_price")
                    ))
            
            # Migrate orders
            for o_id, o_info in data.get("orders", {}).items():
                cursor.execute("""
                INSERT INTO orders (id, store_id, chat_id, customer_name, customer_phone, address, order_type, payment_method, total, status, time, receipt_photo)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    o_id,
                    o_info.get("store_id"),
                    o_info.get("chat_id"),
                    o_info.get("customer_name"),
                    o_info.get("customer_phone"),
                    o_info.get("address"),
                    o_info.get("order_type"),
                    o_info.get("payment_method"),
                    o_info.get("total", 0.0),
                    o_info.get("status"),
                    o_info.get("time"),
                    o_info.get("receipt_photo")
                ))
                
                # Migrate order items
                for pid, qty in o_info.get("items", {}).items():
                    cursor.execute("""
                    INSERT INTO order_items (order_id, product_id, quantity) VALUES (?, ?, ?)
                    """, (o_id, pid, qty))
            
            # Migrate users
            for uid in data.get("users", []):
                cursor.execute("INSERT OR IGNORE INTO users (chat_id) VALUES (?)", (uid,))
                
            conn.commit()
            print("[SQLite Migration] Migration completed successfully!")
        except Exception as e:
            conn.rollback()
            print(f"[SQLite Migration ERROR]: {e}")
            
    conn.close()

def load_db():
    init_db()
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 1. Fetch Users
    cursor.execute("SELECT chat_id FROM users")
    users = [row['chat_id'] for row in cursor.fetchall()]
    
    # 2. Fetch Stores
    cursor.execute("SELECT * FROM stores")
    stores_rows = cursor.fetchall()
    stores = {}
    for sr in stores_rows:
        s_id = sr['id']
        stores[s_id] = {
            "name": sr['name'],
            "desc": sr['desc'],
            "admin_id": sr['admin_id'],
            "sector": sr['sector'],
            "hidden": True if sr['hidden'] == 1 else False,
            "wallet_number": sr['wallet_number'],
            "delivery_mode": sr['delivery_mode'],
            "delivery_fee": sr['delivery_fee'],
            "categories": {},
            "products": {},
            "promo": {
                "active": True if sr['promo_active'] == 1 else False,
                "interval_hours": sr['promo_interval'] if sr['promo_interval'] is not None else 24,
                "product_id": sr['promo_product'] if sr['promo_product'] is not None else "random",
                "last_sent": sr['promo_last_sent'] if sr['promo_last_sent'] is not None else 0.0
            }
        }
        
    # Fetch Categories
    cursor.execute("SELECT * FROM categories")
    for r in cursor.fetchall():
        s_id = r['store_id']
        if s_id in stores:
            stores[s_id]['categories'][r['id']] = r['name']
            
    # Fetch Products
    cursor.execute("SELECT * FROM products")
    for r in cursor.fetchall():
        s_id = r['store_id']
        if s_id in stores:
            stores[s_id]['products'][r['id']] = {
                "id": r['id'],
                "category_id": r['category_id'],
                "name": r['name'],
                "price": r['price'],
                "desc": r['desc'],
                "image": r['image'],
                "discount_price": r['discount_price']
            }
            
    # 3. Fetch Orders
    cursor.execute("SELECT * FROM orders")
    orders_rows = cursor.fetchall()
    orders = {}
    for r in orders_rows:
        o_id = r['id']
        orders[o_id] = {
            "id": r['id'],
            "store_id": r['store_id'],
            "chat_id": r['chat_id'],
            "customer_name": r['customer_name'],
            "customer_phone": r['customer_phone'],
            "address": r['address'],
            "order_type": r['order_type'],
            "payment_method": r['payment_method'],
            "total": r['total'],
            "status": r['status'],
            "time": r['time'],
            "receipt_photo": r['receipt_photo'],
            "items": {}
        }
        
    # Fetch Order Items
    cursor.execute("SELECT * FROM order_items")
    for r in cursor.fetchall():
        o_id = r['order_id']
        if o_id in orders:
            orders[o_id]['items'][r['product_id']] = r['quantity']
            
    conn.close()
    
    return {
        "stores": stores,
        "orders": orders,
        "users": users
    }

def save_db(db_dict):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # Clear tables
        cursor.execute("DELETE FROM stores")
        cursor.execute("DELETE FROM categories")
        cursor.execute("DELETE FROM products")
        cursor.execute("DELETE FROM orders")
        cursor.execute("DELETE FROM order_items")
        cursor.execute("DELETE FROM users")
        
        # Save stores
        for s_id, s_info in db_dict.get("stores", {}).items():
            promo = s_info.get("promo", {})
            cursor.execute("""
            INSERT INTO stores (id, name, desc, admin_id, sector, hidden, wallet_number, delivery_mode, delivery_fee, promo_active, promo_interval, promo_product, promo_last_sent)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                s_id,
                s_info.get("name"),
                s_info.get("desc"),
                str(s_info.get("admin_id", "")),
                s_info.get("sector"),
                1 if s_info.get("hidden") else 0,
                s_info.get("wallet_number"),
                s_info.get("delivery_mode"),
                s_info.get("delivery_fee", 0.0),
                1 if promo.get("active") else 0,
                promo.get("interval_hours", 24),
                promo.get("product_id", "random"),
                promo.get("last_sent", 0.0)
            ))
            
            # Save categories
            for c_id, c_name in s_info.get("categories", {}).items():
                cursor.execute("""
                INSERT INTO categories (id, store_id, name) VALUES (?, ?, ?)
                """, (c_id, s_id, c_name))
            
            # Save products
            for p_id, p_info in s_info.get("products", {}).items():
                cursor.execute("""
                INSERT INTO products (id, store_id, category_id, name, price, desc, image, discount_price)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    p_id,
                    s_id,
                    p_info.get("category_id"),
                    p_info.get("name"),
                    p_info.get("price", 0.0),
                    p_info.get("desc"),
                    p_info.get("image"),
                    p_info.get("discount_price")
                ))
                
        # Save orders
        for o_id, o_info in db_dict.get("orders", {}).items():
            cursor.execute("""
            INSERT INTO orders (id, store_id, chat_id, customer_name, customer_phone, address, order_type, payment_method, total, status, time, receipt_photo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                o_id,
                o_info.get("store_id"),
                o_info.get("chat_id"),
                o_info.get("customer_name"),
                o_info.get("customer_phone"),
                o_info.get("address"),
                o_info.get("order_type"),
                o_info.get("payment_method"),
                o_info.get("total", 0.0),
                o_info.get("status"),
                o_info.get("time"),
                o_info.get("receipt_photo")
            ))
            
            # Save order items
            for pid, qty in o_info.get("items", {}).items():
                cursor.execute("""
                INSERT INTO order_items (order_id, product_id, quantity) VALUES (?, ?, ?)
                """, (o_id, pid, qty))
                
        # Save users
        for uid in db_dict.get("users", []):
            cursor.execute("INSERT OR IGNORE INTO users (chat_id) VALUES (?)", (uid,))
            
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"[SQLite Sync ERROR]: {e}")
        raise e
    finally:
        conn.close()
