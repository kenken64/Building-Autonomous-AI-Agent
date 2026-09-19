"""The Shipping Agent: quotes dates, never computes them.

``shipping.py`` at the project root does the arithmetic. Every prompt in this lab
forbids inventing a delivery date, and handing the model real dates is the only way
to hold that line."""

from __future__ import annotations

import json
from typing import Any

from catalog import CatalogNotSeededError, fulfillment_for_warehouses
from orders import OrderBookNotSeededError, OrderNotFoundError, get_order
from shipping import format_estimates, simulate_options
from ..client import OpenRouterHermesClient
from ..context import model_config_from_state
from ..prompts import shared_agent_system, worker_model
from ..state import AgentMartState, emit_envelope, transcript_entry




SHIPPING_AGENT_SYSTEM_PROMPT = (
    "You are the AgentMart Shipping Agent. You are given simulated dispatch and delivery "
    "dates that were CALCULATED for you, with the reason behind each. Never compute, adjust, "
    "or invent a date: quote the ones you are given and explain them. Say plainly that the "
    "estimate is simulated. Answer in compact lines, 500 characters or fewer."
)




def shipping_agent_node(state: AgentMartState) -> AgentMartState:
    """Dates are computed in shipping.py; this agent only explains them.

    Every other prompt in this lab forbids inventing a delivery date. The only way to
    hold that line is to hand the model real dates, so the arithmetic happens in
    Python and the model never sees a reason to guess.
    """
    intent = state.get("intent", "shipping_estimate")
    order_id = state.get("target_order_id")
    envelope = emit_envelope(
        state, sender="hermes_myshopper", recipient="shipping_agent", intent=intent,
        payload={"capability": "shipping_estimate", "order_id": order_id}, lifecycle="accepted",
    )

    placed_at = None
    warehouses = ["SG-CENTRAL", "MY-JB", "US-WEST"]
    if order_id:
        try:
            order = get_order(order_id)
            placed_at = order.get("placed_at")
            if order.get("warehouse"):
                warehouses = [order["warehouse"]]
        except (OrderNotFoundError, OrderBookNotSeededError):
            pass  # no such order: fall back to a general estimate across warehouses

    try:
        options = fulfillment_for_warehouses(warehouses)
        options = options if isinstance(options, list) else sum(options.values(), [])
        estimates = format_estimates(simulate_options(options, placed_at))
    except CatalogNotSeededError as exc:
        estimates = f"(fulfillment options unavailable: {exc})"

    client = OpenRouterHermesClient(
        dry_run=state.get("dry_run", False),
        model_config=model_config_from_state(state),
        model_override=worker_model(state),
    )
    result = client.complete(
        "shipping_agent",
        SHIPPING_AGENT_SYSTEM_PROMPT,
        json.dumps({
            "customer_request": state["customer_request"],
            "order_id": order_id,
            "order_placed_at": placed_at,
            "calculated_estimates": estimates,
            "instruction": (
                "Answer the customer's timing question using only the calculated "
                "estimates above. One line per option. State that these are simulated."
            ),
        }, indent=2),
    )
    done = emit_envelope(
        state, sender="shipping_agent", recipient="hermes_myshopper", intent=intent,
        payload={"result_chars": len(result), "options": len(estimates.splitlines())},
        lifecycle="completed",
    )
    return {
        "transcript": [transcript_entry("shipping_agent", result, envelope)],
        "a2a_log": [envelope, done],
        "shipping_result": result,
        "shipping_estimates": estimates,
    }
