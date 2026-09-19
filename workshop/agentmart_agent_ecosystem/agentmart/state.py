"""Shared state and the A2A envelope that every hop appends to.

The two accumulating keys carry ``operator.add`` reducers, which is why nodes return
deltas -- ``{"transcript": [entry]}`` -- and never the whole list."""

from __future__ import annotations

import operator
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, TypedDict
from uuid import uuid4




AgentName = Literal[
    "hermes_myshopper",
    "shopping_agent",
    "pricing_agent",
    "inventory_agent",
    "fulfillment_agent",
    "shipping_agent",
    "order_agent",
    "payment_agent",
]



# What the customer actually wants. The router is deterministic on purpose:
# the teaching point in Part 7 is capability + heartbeat routing, not intent
# classification, and reproducible routing keeps the scenario suite assertable.
Intent = Literal[
    "browse_catalog",
    "product_advice",
    "purchase_intent",
    "checkout_payment",
    "order_status",
    "shipping_estimate",
]



DEFAULT_CUSTOMER_ID = "CUST-1001"




class AgentMartState(TypedDict, total=False):
    customer_request: str
    channel: str
    dry_run: bool
    customer_id: str
    intent: Intent
    target_sku: str | None
    target_order_id: str | None
    hermes_a2a_config: dict[str, Any]
    a2a_task: dict[str, Any]
    # Reducers: the parallel agents all append here in the same superstep, so
    # LangGraph needs to be told how to merge their writes instead of rejecting them.
    a2a_log: Annotated[list[dict[str, Any]], operator.add]
    batch_workers: bool
    product_listing: str
    order_context: str
    shopping_result: str
    pricing_result: str
    inventory_result: str
    fulfillment_result: str
    shipping_result: str
    shipping_estimates: str
    order_result: str
    payment_result: str
    draft_order: dict[str, Any]
    payment_receipt: dict[str, Any]
    transcript: Annotated[list[dict[str, Any]], operator.add]


@dataclass
class A2AEnvelope:
    """One hop on the A2A stream.

    `correlation_id` ties every hop of a single customer request together, and
    `state` mirrors the task lifecycle from Part 7 of the lecture, so a consumer
    can rebuild the whole conversation by replaying the log.
    """

    task_id: str
    sender: AgentName
    recipient: str
    intent: str
    payload: dict[str, Any]
    correlation_id: str = ""
    state: str = "proposed"
    protocol: str = "agentmart.a2a.v1"
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if not data["created_at"]:
            data["created_at"] = datetime.now(timezone.utc).isoformat()
        if not data["correlation_id"]:
            data["correlation_id"] = data["task_id"]
        return data




A2A_LIFECYCLE = ("proposed", "accepted", "in_progress", "completed", "failed")




def emit_envelope(
    state: AgentMartState,
    sender: AgentName,
    recipient: str,
    intent: str,
    payload: dict[str, Any],
    lifecycle: str = "in_progress",
) -> dict[str, Any]:
    """Build one A2A hop. Pure: parallel branches share a state snapshot, so the
    caller collects the returned envelopes and hands them back as an ``a2a_log`` delta."""
    task = state.get("a2a_task") or {}
    envelope = A2AEnvelope(
        task_id=str(uuid4()),
        sender=sender,
        recipient=recipient,
        intent=intent,
        payload=payload,
        correlation_id=task.get("correlation_id") or task.get("task_id") or str(uuid4()),
        state=lifecycle,
        protocol=task.get("protocol", "agentmart.a2a.v1"),
    ).to_dict()
    return envelope




def transcript_entry(
    agent: AgentName,
    message: str,
    envelope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One transcript row. Nodes return ``{"transcript": [entry]}`` and the reducer
    concatenates -- returning the whole list would double it under a reducer."""
    return {"agent": agent, "message": message, "a2a": envelope}
