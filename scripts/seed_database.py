"""Create deterministic sample customers, products, and orders in DuckDB.

Running this script replaces the three demo tables in ``data/business.duckdb``.
"""

import random
from datetime import date, timedelta
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "business.duckdb"

DB_PATH.parent.mkdir(parents=True, exist_ok=True)

random.seed(42)

con = duckdb.connect(str(DB_PATH))

# Recreate our demo tables
con.execute("DROP TABLE IF EXISTS orders")
con.execute("DROP TABLE IF EXISTS products")
con.execute("DROP TABLE IF EXISTS customers")

con.execute("""
    CREATE TABLE customers (
        customer_id INTEGER PRIMARY KEY,
        customer_name VARCHAR,
        country VARCHAR
    )
""")

con.execute("""
    CREATE TABLE products (
        product_id INTEGER PRIMARY KEY,
        product_name VARCHAR,
        category VARCHAR,
        price DOUBLE,
        unit_cost DOUBLE
    )
""")

con.execute("""
    CREATE TABLE orders (
        order_id INTEGER PRIMARY KEY,
        customer_id INTEGER,
        product_id INTEGER,
        order_date DATE,
        quantity INTEGER
    )
""")

customers = [
    (1, "Anna", "Sweden"),
    (2, "Erik", "Sweden"),
    (3, "Maria", "Norway"),
    (4, "John", "Denmark"),
    (5, "Sofia", "Finland"),
]

products = [
    (1, "Laptop", "Electronics", 1200, 900),
    (2, "Headphones", "Electronics", 150, 80),
    (3, "Desk", "Furniture", 350, 200),
    (4, "Chair", "Furniture", 180, 90),
    (5, "Lamp", "Home", 60, 25),
]

con.executemany("INSERT INTO customers VALUES (?, ?, ?)", customers)

con.executemany("INSERT INTO products VALUES (?, ?, ?, ?, ?)", products)

orders = []

for order_id in range(1, 101):
    customer_id = random.randint(1, 5)
    product_id = random.randint(1, 5)
    order_date = date(2026, 8, 1) + timedelta(days=random.randint(0, 60))
    quantity = random.randint(1, 3)

    orders.append(
        (
            order_id,
            customer_id,
            product_id,
            order_date,
            quantity,
        )
    )

con.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?)", orders)

print(f"Database created: {DB_PATH}")
print(f"Orders: {con.execute('SELECT COUNT(*) FROM orders').fetchone()[0]}")

con.close()
