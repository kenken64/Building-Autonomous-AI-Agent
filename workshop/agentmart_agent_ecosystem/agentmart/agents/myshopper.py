"""Hermes/MyShopper: the lab's own buying agent.

When a real Hermes calls in over A2A this still runs -- two buying agents in series.
That is deliberate: the hand-off is what the workshop demonstrates."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from ..context import load_hermes_a2a_config, load_order_context
from ..intents import classify_intent, extract_order_id, extract_sku
from ..state import A2AEnvelope, DEFAULT_CUSTOMER_ID
from ..client import OpenRouterHermesClient
from ..context import model_config_from_state
from ..prompts import shared_agent_system, worker_model
from ..state import AgentMartState, emit_envelope, transcript_entry




def hermes_myshopper_node(state: AgentMartState) -> AgentMartState:
    customer_request = state["customer_request"]
    config = state.get("hermes_a2a_config") or load_hermes_a2a_config()
    hermes_config = config["hermes_agent"]
    a2a_config = config["a2a_connection"]
    agentmart_config = config["agentmart"]

    intent = state.get("intent") or classify_intent(customer_request)
    customer_id = state.get("customer_id") or DEFAULT_CUSTOMER_ID
    task_id = str(uuid4())

    envelope = A2AEnvelope(
        task_id=task_id,
        correlation_id=task_id,
        state="proposed",
        sender=hermes_config["id"],
        recipient=agentmart_config["id"],
        intent=intent,
        payload={
            "customer_request": customer_request,
            "customer_id": customer_id,
            "channel": state.get("channel", "webchat"),
            "target_sku": state.get("target_sku") or extract_sku(customer_request),
            "target_order_id": state.get("target_order_id") or extract_order_id(customer_request),
            "hermes_agent": hermes_config,
            "a2a_connection": a2a_config,
            "target_agents": agentmart_config["agents"],
            "constraints": {
                "representing": "customer",
                "ecosystem": agentmart_config["display_name"],
            },
        },
        protocol=a2a_config["protocol"],
    ).to_dict()

    client = OpenRouterHermesClient(
        dry_run=state.get("dry_run", False),
        model_config=hermes_config.get("model", {}),
    )
    message = client.complete(
        "hermes_myshopper",
        (
            "You are Hermes/MyShopper, a personal buying agent. "
            "You represent the customer, not AgentMart. "
            "Create a short handoff note for the AgentMart agent ecosystem."
        ),
        json.dumps(envelope, indent=2),
    )

    next_state: AgentMartState = {
        "transcript": [transcript_entry("hermes_myshopper", message, envelope)],
        "a2a_log": [envelope],
        "a2a_task": envelope,
        "intent": intent,
        "customer_id": customer_id,
        "target_sku": envelope["payload"]["target_sku"],
        "target_order_id": envelope["payload"]["target_order_id"],
    }
    # Order and Payment agents read the customer's real order book.
    if intent in ("order_status", "checkout_payment", "purchase_intent"):
        next_state["order_context"] = load_order_context(
            customer_id, envelope["payload"]["target_order_id"]
        )
    return next_state
