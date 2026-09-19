"""The Payment Agent. Payments are SIMULATED: rows are written locally and no
payment processor is contacted."""

from __future__ import annotations

import json
from typing import Any

from orders import OrderBookNotSeededError, OrderNotFoundError, checkout_and_pay
from ..client import OpenRouterHermesClient
from ..context import model_config_from_state
from ..prompts import shared_agent_system, worker_model
from ..state import AgentMartState, emit_envelope, transcript_entry




PAYMENT_AGENT_SYSTEM_PROMPT = (
    "You are the AgentMart Payment Agent. Payments in this workshop are SIMULATED: "
    "the receipt you are given was written to a local database and no payment processor "
    "was contacted. Confirm the settled order back to Hermes/MyShopper using only the "
    "receipt values, and state plainly that this was a simulated payment."
)




def payment_agent_node(state: AgentMartState) -> AgentMartState:
    """Payment Agent. Authorizes and captures a SIMULATED payment, then reports back."""
    order_id = state.get("target_order_id")

    envelope = emit_envelope(
        state,
        sender="order_agent",
        recipient="payment_agent",
        intent="checkout_payment",
        payload={"capability": "payment_capture", "order_id": order_id, "simulated": True},
        lifecycle="accepted",
    )

    next_state: AgentMartState = {**state}
    receipt: dict[str, Any]
    if not order_id:
        receipt = {"error": "no payable order found for this customer"}
    else:
        try:
            settled = checkout_and_pay(order_id)
            receipt = {
                "simulated": True,
                "payment_id": settled["payment"]["payment_id"],
                "processor_ref": settled["payment"]["processor_ref"],
                "status": settled["payment"]["status"],
                "amount_usd": settled["payment"]["amount_usd"],
                "method_id": settled["payment"]["method_id"],
                "order_id": order_id,
                "order_status": settled["order"]["status"],
            }
        except (OrderNotFoundError, OrderBookNotSeededError, ValueError) as exc:
            receipt = {"error": f"{type(exc).__name__}: {exc}", "order_id": order_id}

    next_state["payment_receipt"] = receipt

    client = OpenRouterHermesClient(
        dry_run=state.get("dry_run", False),
        model_config=model_config_from_state(state),
    )
    result = client.complete(
        "payment_agent",
        PAYMENT_AGENT_SYSTEM_PROMPT,
        json.dumps({"a2a_task": state["a2a_task"], "receipt": receipt}, indent=2),
    )

    done = emit_envelope(
        next_state,
        sender="payment_agent",
        recipient="hermes_myshopper",
        intent="checkout_payment",
        payload={k: v for k, v in receipt.items() if k != "error"} or {"error": receipt.get("error")},
        lifecycle="failed" if "error" in receipt else "completed",
    )

    return {
        "transcript": [transcript_entry("payment_agent", result, envelope)],
        "a2a_log": [envelope, done],
        "payment_receipt": receipt,
        "payment_result": result,
    }
