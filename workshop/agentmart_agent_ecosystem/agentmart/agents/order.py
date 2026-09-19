"""The Order Agent: the only hop that writes.

On a purchase intent it creates the draft order BEFORE the model speaks, so the order
id in the answer is a real row rather than a generated string."""

from __future__ import annotations

import json
from typing import Any

from catalog import CatalogNotSeededError
from orders import (
    OrderBookNotSeededError,
    create_draft_order,
    find_payable_order,
    format_order,
)
from ..state import DEFAULT_CUSTOMER_ID
from ..client import OpenRouterHermesClient
from ..context import model_config_from_state
from ..prompts import shared_agent_system, worker_model
from ..state import AgentMartState, emit_envelope, transcript_entry




ORDER_AGENT_SYSTEM_PROMPT = (
    "You are the AgentMart Order Agent. You speak to Hermes/MyShopper, which relays to the customer. "
    "Work only from the order book and agent results you are given. Never invent an order id, "
    "tracking reference, amount, or delivery date. If something is missing, say what is missing. "
    # Your reader is another agent, not the customer. Hermes rewrites this into prose for
    # the chat, so every word of framing here is paid for twice: once to generate, again
    # when Hermes reads it back. Facts are what travel; the phrasing is Hermes' job.
    "Answer as compact structured facts, not prose. No greeting, no preamble, no closing "
    "offer, no restating the question. One line per option: SKU, name, price, the one or "
    "two attributes that decide it, stock, and delivery. Put any caveat on its own short "
    "line. Aim for 600 characters or fewer."
)




def _order_agent_prompt(state: AgentMartState) -> str:
    intent = state.get("intent", "product_advice")
    common = {
        "a2a_task": state["a2a_task"],
        "intent": intent,
        "customer_id": state.get("customer_id"),
    }

    if intent == "shipping_estimate":
        return json.dumps(
            {
                **common,
                "order_book": state.get("order_context", ""),
                # Already-calculated dates. The Order Agent relays them; it must not
                # recompute or round them, and must not answer if they are missing.
                "shipping_result": state.get("shipping_result", "(agent not on this path)"),
                "instruction": (
                    "Answer the customer's timing question using the Shipping Agent's "
                    "result. Quote its dates exactly and say the estimate is simulated. "
                    "If the shipping result is missing, say so instead of estimating."
                ),
            },
            indent=2,
        )

    if intent == "order_status":
        return json.dumps(
            {
                **common,
                "order_book": state.get("order_context", ""),
                "instruction": (
                    "Answer the customer's order-status question from the order book. "
                    "For each relevant order give: order id, status, what happens next, "
                    "tracking reference and ETA when present. Flag any order that is "
                    "awaiting payment as needing the customer's action."
                ),
            },
            indent=2,
        )

    if intent == "purchase_intent":
        return json.dumps(
            {
                **common,
                "draft_order": state.get("draft_order", {}),
                "inventory_result": state.get("inventory_result", "(agent not on this path)"),
                "fulfillment_result": state.get("fulfillment_result", "(agent not on this path)"),
                "instruction": (
                    "A draft order has been created and is awaiting payment. Confirm back to the "
                    "customer what is reserved, the line items, the total, and the delivery path. "
                    "State clearly that nothing is charged until they confirm checkout."
                ),
            },
            indent=2,
        )

    if intent == "checkout_payment":
        return json.dumps(
            {
                **common,
                "order_book": state.get("order_context", ""),
                "order_to_settle": state.get("target_order_id"),
                "instruction": (
                    "Identify the single order to settle and restate its total and payment method "
                    "for confirmation. Do not claim payment has happened: the Payment Agent runs next."
                ),
            },
            indent=2,
        )

    # browse_catalog / product_advice: the original recommendation summary
    return json.dumps(
        {
            **common,
            "shopping_result": state.get("shopping_result", "(agent not on this path)"),
            "pricing_result": state.get("pricing_result", "(agent not on this path)"),
            "inventory_result": state.get("inventory_result", "(agent not on this path)"),
            "fulfillment_result": state.get("fulfillment_result", "(agent not on this path)"),
            "instruction": (
                "Produce a final recommendation that Hermes/MyShopper can send back to the customer. "
                "Do not pretend an order was placed; summarize the recommended next action."
            ),
        },
        indent=2,
    )




def order_agent_node(state: AgentMartState) -> AgentMartState:
    """Order Agent. Reads the order book; creates a draft order on a purchase intent."""
    intent = state.get("intent", "product_advice")
    customer_id = state.get("customer_id", DEFAULT_CUSTOMER_ID)

    envelope = emit_envelope(
        state,
        sender="hermes_myshopper",
        recipient="order_agent",
        intent=intent,
        payload={"capability": "order_summary", "customer_id": customer_id},
        lifecycle="accepted",
    )

    next_state: AgentMartState = {**state}

    # A purchase intent materialises a real draft order before the model speaks.
    if intent == "purchase_intent":
        sku = state.get("target_sku")
        if not sku:
            next_state["draft_order"] = {"error": "no SKU identified in the customer request"}
        else:
            try:
                draft = create_draft_order(
                    customer_id=customer_id,
                    items=[{"sku": sku, "quantity": 1}],
                    warehouse="SG-CENTRAL",
                    fulfillment_method="standard_delivery",
                    shipping_usd=3.5,
                )
                next_state["draft_order"] = draft
                next_state["target_order_id"] = draft["order_id"]
                next_state["order_context"] = format_order(draft)
            except (CatalogNotSeededError, OrderBookNotSeededError, ValueError) as exc:
                next_state["draft_order"] = {"error": f"{type(exc).__name__}: {exc}"}

    # A bare "checkout and pay" resolves to the customer's oldest unpaid order.
    if intent == "checkout_payment" and not next_state.get("target_order_id"):
        try:
            payable = find_payable_order(customer_id)
            if payable:
                next_state["target_order_id"] = payable["order_id"]
                next_state["order_context"] = format_order(payable)
        except OrderBookNotSeededError as exc:
            next_state["order_context"] = f"(order book unavailable: {exc})"

    client = OpenRouterHermesClient(
        dry_run=state.get("dry_run", False),
        model_config=model_config_from_state(state),
    )
    result = client.complete("order_agent", ORDER_AGENT_SYSTEM_PROMPT, _order_agent_prompt(next_state))

    done = emit_envelope(
        next_state,
        sender="order_agent",
        recipient="hermes_myshopper",
        intent=intent,
        payload={
            "order_id": next_state.get("target_order_id"),
            "draft_created": bool(next_state.get("draft_order", {}).get("order_id")),
        },
        lifecycle="completed",
    )

    # Only the keys this node actually decided; transcript/a2a_log go back as deltas.
    delta: AgentMartState = {
        k: v for k, v in next_state.items()
        if k in ("draft_order", "target_order_id", "order_context")
    }
    delta["transcript"] = [transcript_entry("order_agent", result, envelope)]
    delta["a2a_log"] = [envelope, done]
    delta["order_result"] = result
    return delta
