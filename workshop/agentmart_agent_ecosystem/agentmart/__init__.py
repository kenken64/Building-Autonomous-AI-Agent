"""AgentMart: the LangGraph agent ecosystem behind the A2A server.

Layout, roughly in dependency order:

    state.py        AgentMartState, A2AEnvelope, transcript/envelope helpers
    client.py       the model client, per-endpoint request shaping, PERF + trace
    intents.py      the routing rules and each intent's agent path
    context.py      catalog, order book, and the Hermes A2A config
    prompts.py      the cacheable system prefix shared by every worker
    agents/         one module per agent
    graph.py        wiring, routing and run_agentmart()

``agentmart_ecosystem.py`` re-exports this package's public surface and keeps the
CLI, so existing imports and commands are unchanged.
"""

from __future__ import annotations

from .agents import (
    BATCHED_NODE,
    ORDER_AGENT_SYSTEM_PROMPT,
    PAYMENT_AGENT_SYSTEM_PROMPT,
    SHIPPING_AGENT_SYSTEM_PROMPT,
    WORKER_AGENTS,
    WORKER_BRIEFS,
    batched_workers_node,
    fulfillment_agent_node,
    hermes_myshopper_node,
    inventory_agent_node,
    make_agent_node,
    order_agent_node,
    payment_agent_node,
    pricing_agent_node,
    shipping_agent_node,
    shopping_agent_node,
    split_sections,
    workers_in_path,
)
from .client import DEFAULT_MODEL, OpenRouterHermesClient, set_trace_sink
from .context import (
    load_hermes_a2a_config,
    load_order_context,
    load_product_listing,
    model_config_from_state,
)
from .graph import (
    build_graph,
    effective_path,
    normalize_ordering,
    route_from_hermes,
    run_agentmart,
)
from .intents import (
    INTENT_PATHS,
    INTENT_RULES,
    ORDER_ID_PATTERN,
    SKU_PATTERN,
    classify_intent,
    extract_order_id,
    extract_sku,
    strip_prohibitions,
)
from .prompts import SHARED_AGENT_SYSTEM, shared_agent_system, worker_model
from .state import (
    A2A_LIFECYCLE,
    DEFAULT_CUSTOMER_ID,
    A2AEnvelope,
    AgentMartState,
    AgentName,
    Intent,
    emit_envelope,
    transcript_entry,
)

__all__ = [n for n in dir() if not n.startswith("_")]
