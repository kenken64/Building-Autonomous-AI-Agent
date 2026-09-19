"""Graph construction, routing, and the entry point.

The path is a pipeline: each hop reads the previous one's output. Running the workers
concurrently was tried and reverted -- both downstream agents lost their upstream input
while every test still passed."""

from __future__ import annotations

from typing import Any, Callable

from langgraph.graph import END, START, StateGraph

from .agents import (
    BATCHED_NODE,
    WORKER_AGENTS,
    batched_workers_node,
    fulfillment_agent_node,
    hermes_myshopper_node,
    inventory_agent_node,
    order_agent_node,
    payment_agent_node,
    pricing_agent_node,
    shipping_agent_node,
    shopping_agent_node,
)
from .context import _env_flag, load_hermes_a2a_config, load_product_listing
from .state import DEFAULT_CUSTOMER_ID
from .intents import INTENT_PATHS, classify_intent
from .state import Intent
from .state import AgentMartState




# The intent path is a pipeline, not a fan-out: the Inventory Agent reads the
# Pricing Agent's ranking and the Fulfillment Agent reads the Inventory Agent's
# stock findings. Running the three concurrently was tried and reverted -- it cut
# roughly 8s off a run, but both downstream agents then received
# "(agent not on this path)" where their upstream input should have been, and
# reasoned without it. The Order Agent still saw all three at the join, so the
# final answer looked correct and the scenario suite still passed, which is what
# made the regression easy to miss. Each hop building on the last is the point.


def effective_path(state: AgentMartState) -> tuple[str, ...]:
    """The intent's path, with the worker run collapsed to one hop when batching."""
    path = INTENT_PATHS[state.get("intent", "product_advice")]
    if not state.get("batch_workers"):
        return path
    collapsed: list[str] = []
    for agent in path:
        if agent in WORKER_AGENTS:
            if BATCHED_NODE not in collapsed:
                collapsed.append(BATCHED_NODE)
        else:
            collapsed.append(agent)
    return tuple(collapsed)




def route_from_hermes(state: AgentMartState) -> str:
    """First AgentMart hop for this intent."""
    return effective_path(state)[0]




def _next_after(node: str) -> Callable[[AgentMartState], str]:
    """Follow this intent's path; fall off to END when the node is its last hop."""

    def router(state: AgentMartState) -> str:
        path = effective_path(state)
        if node not in path:
            return END
        index = path.index(node)
        return path[index + 1] if index + 1 < len(path) else END

    return router




def build_graph():
    graph = StateGraph(AgentMartState)
    graph.add_node("hermes_myshopper", hermes_myshopper_node)
    graph.add_node("shopping_agent", shopping_agent_node)
    graph.add_node("pricing_agent", pricing_agent_node)
    graph.add_node("inventory_agent", inventory_agent_node)
    graph.add_node("fulfillment_agent", fulfillment_agent_node)
    graph.add_node("order_agent", order_agent_node)
    graph.add_node("shipping_agent", shipping_agent_node)
    graph.add_node("payment_agent", payment_agent_node)
    graph.add_node(BATCHED_NODE, batched_workers_node)

    graph.add_edge(START, "hermes_myshopper")

    agent_nodes = [
        BATCHED_NODE,
        "shopping_agent",
        "pricing_agent",
        "inventory_agent",
        "fulfillment_agent",
        "shipping_agent",
        "order_agent",
        "payment_agent",
    ]
    graph.add_conditional_edges(
        "hermes_myshopper",
        route_from_hermes,
        {name: name for name in agent_nodes},
    )
    for name in agent_nodes:
        graph.add_conditional_edges(
            name,
            _next_after(name),
            {**{other: other for other in agent_nodes if other != name}, END: END},
        )
    return graph.compile()




def _hop_agent(hop: dict[str, Any]) -> str:
    """The AgentMart agent a hop concerns, whichever side of the exchange it sits on."""
    return hop["recipient"] if hop["sender"] == "hermes_myshopper" else hop["sender"]




def normalize_ordering(result: AgentMartState) -> AgentMartState:
    """Sort the transcript and A2A log into the intent's declared path order.

    With a sequential pipeline the rows already arrive in order, so this is a guard
    rather than a necessity: it keeps the replay deterministic if a future change
    ever runs hops concurrently again. The sort is stable, so each agent's
    accepted/completed envelope pair keeps its relative order.
    """
    order = ["hermes_myshopper", *effective_path(result)]
    rank = {name: index for index, name in enumerate(order)}
    result["transcript"] = sorted(
        result.get("transcript", []), key=lambda e: rank.get(e["agent"], len(rank))
    )
    # The opening handoff is addressed to 'agentmart' itself, so it sorts ahead of everything.
    result["a2a_log"] = sorted(
        result.get("a2a_log", []), key=lambda h: rank.get(_hop_agent(h), -1)
    )
    return result




def run_agentmart(
    customer_request: str,
    channel: str = "webchat",
    dry_run: bool = False,
    config_path: str | None = None,
    category: str | None = None,
    max_price: float | None = None,
    customer_id: str = DEFAULT_CUSTOMER_ID,
    intent: Intent | None = None,
    batch_workers: bool = False,
) -> AgentMartState:
    app = build_graph()
    return normalize_ordering(app.invoke(
        {
            "customer_request": customer_request,
            "channel": channel,
            "dry_run": dry_run,
            "customer_id": customer_id,
            "intent": intent or classify_intent(customer_request),
            "batch_workers": batch_workers or _env_flag("AGENTMART_BATCH_WORKERS"),
            "hermes_a2a_config": load_hermes_a2a_config(config_path),
            "product_listing": load_product_listing(category=category, max_price=max_price),
            "transcript": [],
            "a2a_log": [],
        }
    ))
