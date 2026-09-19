"""Everything the agents read from outside themselves: the seeded catalog, the
customer's order book, and the Hermes A2A configuration file."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from catalog import CatalogNotSeededError, format_product_listing, query_products
from orders import (
    OrderBookNotSeededError,
    OrderNotFoundError,
    format_order,
    format_orders,
    get_customer,
    get_order,
    list_orders,
)

from .state import AgentMartState




def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}




def load_product_listing(
    category: str | None = None,
    max_price: float | None = None,
    limit: int = 25,
) -> str:
    """Render the seeded AgentMart product listing for the agent prompts."""
    try:
        products = query_products(category=category, max_price=max_price, limit=limit)
    except CatalogNotSeededError as exc:
        return f"(catalog unavailable: {exc})"
    if not products:
        return "(no products in the seeded catalog matched the filters)"
    return format_product_listing(products)




def load_order_context(customer_id: str, order_id: str | None = None) -> str:
    """Render the customer's order book for the Order and Payment agent prompts."""
    try:
        if order_id:
            return format_order(get_order(order_id))
        customer = get_customer(customer_id)
        header = (
            f"customer {customer['customer_id']} | {customer['name']}"
            f" | {customer['channel']} {customer['channel_handle']}"
            f" | ships to {customer['shipping_address']}"
            f" | default payment {customer['default_payment_method']}"
            if customer
            else f"(no customer record for {customer_id})"
        )
        return header + "\n" + format_orders(list_orders(customer_id=customer_id))
    except OrderNotFoundError as exc:
        return f"(order not found: {exc})"
    except OrderBookNotSeededError as exc:
        return f"(order book unavailable: {exc})"




def load_hermes_a2a_config(config_path: str | None = None) -> dict[str, Any]:
    # The package lives one level below the lab root, where the data files are.
    default = Path(__file__).resolve().parent.parent / "hermes_a2a_config.json"
    path = Path(config_path) if config_path else default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)




def model_config_from_state(state: AgentMartState) -> dict[str, Any]:
    """Read the Hermes model block (provider, model, temperature) from graph state."""
    config = state.get("hermes_a2a_config") or {}
    return config.get("hermes_agent", {}).get("model", {})
