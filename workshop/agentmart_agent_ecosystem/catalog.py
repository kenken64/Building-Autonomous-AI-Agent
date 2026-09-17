"""Read-side helpers over the seeded AgentMart product listing.

`seed_data.py` writes `data/agentmart.db`; the AgentMart agents call into this
module so their prompts carry real SKUs, prices, stock levels, and delivery
options instead of invented ones.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).with_name("data") / "agentmart.db"


class CatalogNotSeededError(RuntimeError):
    """Raised when the SQLite catalog is missing or empty."""


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else DB_PATH
    if not path.exists():
        raise CatalogNotSeededError(
            f"Product listing not found at {path}. Run: python seed_data.py"
        )
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def query_products(
    category: str | None = None,
    max_price: float | None = None,
    min_rating: float | None = None,
    limit: int = 25,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Return products with their stock and fulfillment options attached."""
    sql = ["SELECT * FROM products WHERE 1 = 1"]
    params: list[Any] = []
    if category:
        sql.append("AND category LIKE ?")
        params.append(f"{category}%")
    if max_price is not None:
        sql.append("AND price_usd <= ?")
        params.append(max_price)
    if min_rating is not None:
        sql.append("AND rating >= ?")
        params.append(min_rating)
    sql.append("ORDER BY rating DESC, price_usd ASC LIMIT ?")
    params.append(limit)

    conn = _connect(db_path)
    try:
        rows = conn.execute(" ".join(sql), params).fetchall()
        products: list[dict[str, Any]] = []
        for row in rows:
            product = dict(row)
            product["features"] = json.loads(product["features"])
            stock = conn.execute(
                "SELECT i.warehouse, w.name AS warehouse_name, w.region,"
                " i.on_hand, i.reserved, (i.on_hand - i.reserved) AS available,"
                " i.restock_eta_days"
                " FROM inventory i JOIN warehouses w ON w.code = i.warehouse"
                " WHERE i.sku = ? ORDER BY available DESC",
                (product["sku"],),
            ).fetchall()
            product["inventory"] = [dict(entry) for entry in stock]
            product["total_available"] = sum(entry["available"] for entry in product["inventory"])
            product["fulfillment"] = fulfillment_for_warehouses(
                [entry["warehouse"] for entry in product["inventory"]], db_path=db_path
            )
            products.append(product)
        return products
    finally:
        conn.close()


def fulfillment_for_warehouses(
    warehouses: list[str], db_path: Path | None = None
) -> list[dict[str, Any]]:
    if not warehouses:
        return []
    placeholders = ",".join("?" for _ in warehouses)
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            f"SELECT warehouse, method, eta_days, cost_usd FROM fulfillment_options"
            f" WHERE warehouse IN ({placeholders}) ORDER BY eta_days ASC",
            warehouses,
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def catalog_stats(db_path: Path | None = None) -> dict[str, int]:
    conn = _connect(db_path)
    try:
        counts = {}
        for table in ("products", "inventory", "warehouses", "fulfillment_options"):
            counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        if counts["products"] == 0:
            raise CatalogNotSeededError("Product listing is empty. Run: python seed_data.py")
        return counts
    finally:
        conn.close()


def format_product_listing(products: list[dict[str, Any]]) -> str:
    """Render the listing as compact text suitable for an agent prompt."""
    lines = []
    for product in products:
        stock = ", ".join(
            f"{entry['warehouse']}:{entry['available']} avail (restock {entry['restock_eta_days']}d)"
            for entry in product["inventory"]
        ) or "no stock records"
        delivery = ", ".join(
            f"{option['method']} {option['eta_days']}d ${option['cost_usd']:.2f}"
            for option in product["fulfillment"]
        ) or "no fulfillment options"
        lines.append(
            f"- {product['sku']} | {product['name']} ({product['brand']}) | {product['category']}\n"
            f"    price ${product['price_usd']:.2f} (list ${product['list_price_usd']:.2f})"
            f" | rating {product['rating']} from {product['review_count']} reviews"
            f" | battery {product['battery_hours']}h\n"
            f"    features: {', '.join(product['features']) or 'n/a'}\n"
            f"    stock: {stock}\n"
            f"    delivery: {delivery}"
        )
    return "\n".join(lines)
