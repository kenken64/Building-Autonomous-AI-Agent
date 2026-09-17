"""Seed the AgentMart product listing into a local SQLite database.

The AgentMart agents (Shopping, Pricing, Inventory, Fulfillment) read this
database instead of inventing products, so the workshop flow stays grounded
in the same catalog every run.

Usage:
    python seed_data.py                 # create/refresh data/agentmart.db
    python seed_data.py --reset         # drop and rebuild every table
    python seed_data.py --list          # print the seeded product listing
    python seed_data.py --list --category audio/earbuds --max-price 120
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).with_name("data")
CATALOG_PATH = DATA_DIR / "products.json"
DB_PATH = DATA_DIR / "agentmart.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS warehouses (
    code    TEXT PRIMARY KEY,
    name    TEXT NOT NULL,
    region  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    sku             TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    brand           TEXT NOT NULL,
    category        TEXT NOT NULL,
    price_usd       REAL NOT NULL,
    list_price_usd  REAL NOT NULL,
    rating          REAL NOT NULL,
    review_count    INTEGER NOT NULL,
    battery_hours   INTEGER NOT NULL,
    features        TEXT NOT NULL,
    description     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS inventory (
    sku              TEXT NOT NULL REFERENCES products(sku),
    warehouse        TEXT NOT NULL REFERENCES warehouses(code),
    on_hand          INTEGER NOT NULL,
    reserved         INTEGER NOT NULL,
    restock_eta_days INTEGER NOT NULL,
    PRIMARY KEY (sku, warehouse)
);

CREATE TABLE IF NOT EXISTS fulfillment_options (
    warehouse TEXT NOT NULL REFERENCES warehouses(code),
    method    TEXT NOT NULL,
    eta_days  INTEGER NOT NULL,
    cost_usd  REAL NOT NULL,
    PRIMARY KEY (warehouse, method)
);

CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
CREATE INDEX IF NOT EXISTS idx_products_price ON products(price_usd);
"""

TABLES = ("inventory", "fulfillment_options", "products", "warehouses")


def load_catalog(path: Path = CATALOG_PATH) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Catalog file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def seed(db_path: Path = DB_PATH, catalog_path: Path = CATALOG_PATH, reset: bool = False) -> dict[str, int]:
    catalog = load_catalog(catalog_path)
    conn = connect(db_path)
    try:
        with conn:
            if reset:
                for table in TABLES:
                    conn.execute(f"DROP TABLE IF EXISTS {table}")
            conn.executescript(SCHEMA)

            # Idempotent: clear rows, then re-insert from the JSON catalog.
            for table in TABLES:
                conn.execute(f"DELETE FROM {table}")

            conn.executemany(
                "INSERT INTO warehouses (code, name, region) VALUES (:code, :name, :region)",
                catalog["warehouses"],
            )
            conn.executemany(
                "INSERT INTO fulfillment_options (warehouse, method, eta_days, cost_usd)"
                " VALUES (:warehouse, :method, :eta_days, :cost_usd)",
                catalog["fulfillment_options"],
            )

            product_rows = []
            inventory_rows = []
            for product in catalog["products"]:
                product_rows.append(
                    {
                        "sku": product["sku"],
                        "name": product["name"],
                        "brand": product["brand"],
                        "category": product["category"],
                        "price_usd": product["price_usd"],
                        "list_price_usd": product.get("list_price_usd", product["price_usd"]),
                        "rating": product["rating"],
                        "review_count": product["review_count"],
                        "battery_hours": product.get("battery_hours", 0),
                        "features": json.dumps(product.get("features", [])),
                        "description": product["description"],
                    }
                )
                for stock in product.get("inventory", []):
                    inventory_rows.append({"sku": product["sku"], **stock})

            conn.executemany(
                "INSERT INTO products (sku, name, brand, category, price_usd, list_price_usd,"
                " rating, review_count, battery_hours, features, description)"
                " VALUES (:sku, :name, :brand, :category, :price_usd, :list_price_usd,"
                " :rating, :review_count, :battery_hours, :features, :description)",
                product_rows,
            )
            conn.executemany(
                "INSERT INTO inventory (sku, warehouse, on_hand, reserved, restock_eta_days)"
                " VALUES (:sku, :warehouse, :on_hand, :reserved, :restock_eta_days)",
                inventory_rows,
            )

        return {
            "warehouses": len(catalog["warehouses"]),
            "fulfillment_options": len(catalog["fulfillment_options"]),
            "products": len(product_rows),
            "inventory": len(inventory_rows),
        }
    finally:
        conn.close()


def print_listing(category: str | None = None, max_price: float | None = None, db_path: Path = DB_PATH) -> None:
    from catalog import format_product_listing, query_products

    products = query_products(category=category, max_price=max_price, db_path=db_path)
    if not products:
        print("No products matched.")
        return
    print(format_product_listing(products))


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the AgentMart product listing.")
    parser.add_argument("--reset", action="store_true", help="Drop and rebuild all tables.")
    parser.add_argument("--list", action="store_true", help="Print the seeded product listing.")
    parser.add_argument("--category", help="Filter the listing by category, e.g. audio/earbuds.")
    parser.add_argument("--max-price", type=float, help="Filter the listing by maximum price.")
    parser.add_argument("--db", default=str(DB_PATH), help="SQLite database path.")
    parser.add_argument("--catalog", default=str(CATALOG_PATH), help="Source catalog JSON path.")
    args = parser.parse_args()

    db_path = Path(args.db)
    counts = seed(db_path=db_path, catalog_path=Path(args.catalog), reset=args.reset)
    summary = ", ".join(f"{count} {table}" for table, count in counts.items())
    print(f"Seeded {db_path}: {summary}")

    if args.list:
        print()
        print_listing(category=args.category, max_price=args.max_price, db_path=db_path)


if __name__ == "__main__":
    main()
