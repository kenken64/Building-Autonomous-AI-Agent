"""The system prefix every worker agent shares.

It is byte-identical across agents on purpose: that is what makes it a cacheable
prefix. Per-agent text belongs in the user turn, never here."""

from __future__ import annotations

import os

from .state import AgentMartState
from .context import model_config_from_state




# Prefix caching. OpenAI reuses an identical leading span of >=1024 tokens across
# calls, which cuts prefill latency by roughly half -- but only if that span is
# byte-identical and comes FIRST. The catalog is the one large thing every agent
# carries, so it lives here, in a system message shared verbatim by all of them,
# with everything variable (task id, upstream results, role, instruction) moved
# into the user turn. Putting the per-agent role in the system message, or the
# a2a_task with its fresh uuid anywhere near the front, defeats the cache.
SHARED_AGENT_SYSTEM = (
    "You are one agent inside the AgentMart agent ecosystem. Work only from the data "
    "you are given. Never invent a SKU, price, stock figure, delivery option, or date. "
    "Your reader is another agent, not the customer: answer in compact facts, with no "
    "greeting, preamble, or closing offer.\n\n"
    "AgentMart product listing:\n{listing}"
)




def shared_agent_system(state: AgentMartState) -> str:
    """The cacheable prefix: identical for every agent on every run of one catalog."""
    return SHARED_AGENT_SYSTEM.format(listing=state.get("product_listing", ""))




def worker_model(state: AgentMartState) -> str | None:
    """Model for the read-only worker agents (shopping/pricing/inventory/fulfillment).

    They never call tools and never speak to the customer, so a fast non-reasoning
    model suits them while the customer-facing hops keep the primary model.
    """
    return (os.getenv("AGENTMART_WORKER_MODEL")
            or (model_config_from_state(state) or {}).get("worker_model")
            or None)
