"""Every worker on the path in one model call.

Safe where concurrency was not: one call sees the whole chain in a single context,
so the hand-off is stronger, not weaker. Off by default -- four agents negotiating
become one prompt wearing four headings, which is a real loss for the demo."""

from __future__ import annotations

import re
from typing import Any

from ..intents import INTENT_PATHS
from ..state import AgentName
from ..client import OpenRouterHermesClient
from ..context import model_config_from_state
from ..prompts import shared_agent_system, worker_model
from ..state import AgentMartState, emit_envelope, transcript_entry




# --- Batched workers -------------------------------------------------------
# The worker hops are sequential because each reads the previous one's output.
# One call that emits all their sections keeps that dependency -- the model sees
# the whole chain in a single context -- while paying one round trip instead of
# four. Measured 9.2s -> 3.4s.
#
# What it costs is the demonstration: four independent agents negotiating over A2A
# become one prompt wearing four headings. Off by default for that reason; turn it
# on to show the room the trade rather than to hide it.
WORKER_AGENTS: tuple[AgentName, ...] = (
    "shopping_agent", "pricing_agent", "inventory_agent", "fulfillment_agent",
)


BATCHED_NODE = "batched_workers"



WORKER_BRIEFS: dict[str, tuple[str, str]] = {
    "shopping_agent": ("SHOPPING", "3 candidate SKUs, one line each with a short reason."),
    "pricing_agent": ("PRICING", "rank those candidates by value, one line each plus one risk line."),
    "inventory_agent": ("INVENTORY", "stock status per SKU, one line each."),
    "fulfillment_agent": ("FULFILLMENT", "recommended fulfillment path, naming the warehouse."),
}




def workers_in_path(intent: str) -> list[str]:
    return [a for a in INTENT_PATHS[intent] if a in WORKER_AGENTS]




def split_sections(text: str, headings: list[str]) -> dict[str, str]:
    """Split the batched reply on its headings, tolerating markdown and stray colons."""
    positions: list[tuple[int, str]] = []
    for heading in headings:
        match = re.search(rf"(?im)^[#*\s]*{heading}\s*:?.*$", text)
        if match:
            positions.append((match.end(), heading))
    positions.sort()
    out: dict[str, str] = {}
    for index, (start, heading) in enumerate(positions):
        end = positions[index + 1][0] if index + 1 < len(positions) else len(text)
        # trim the next heading's own line back off the tail
        body = text[start:end]
        body = re.sub(r"(?im)^[#*\s]*(?:%s)\s*:?.*$" % "|".join(headings), "", body)
        out[heading] = body.strip()
    return out




def batched_workers_node(state: AgentMartState) -> AgentMartState:
    """Every worker on this intent's path, in one model call."""
    intent = state.get("intent", "product_advice")
    workers = workers_in_path(intent)
    briefs = [WORKER_BRIEFS[a] for a in workers]
    headings = [h for h, _ in briefs]

    envelope = emit_envelope(
        state, sender="hermes_myshopper", recipient=BATCHED_NODE, intent=intent,
        payload={"capability": "batched_worker_pass", "agents": workers},
        lifecycle="accepted",
    )
    instruction = "\n".join(f"{h}: {what}" for h, what in briefs)
    prompt = (
        f"Request: {state['customer_request']}\n\n"
        f"Act as these AgentMart agents in order, each building on the one before, and "
        f"output every section:\n{instruction}\n\n"
        f"Use exactly those headings, one per section. "
        f"{300 * len(briefs)} characters total or fewer."
    )
    client = OpenRouterHermesClient(
        dry_run=state.get("dry_run", False),
        model_config=model_config_from_state(state),
        model_override=worker_model(state),
    )
    result = client.complete(BATCHED_NODE, shared_agent_system(state), prompt)
    done = emit_envelope(
        state, sender=BATCHED_NODE, recipient="hermes_myshopper", intent=intent,
        payload={"result_chars": len(result), "agents": workers}, lifecycle="completed",
    )

    sections = split_sections(result, headings)
    delta: AgentMartState = {
        # One hop, recorded as one hop. Fabricating four transcript entries from a
        # single call would make the replay lie about what ran.
        "transcript": [transcript_entry(BATCHED_NODE, result, envelope)],
        "a2a_log": [envelope, done],
    }
    for agent, (heading, _) in zip(workers, briefs):
        key = agent.replace("_agent", "") + "_result"
        delta[key] = sections.get(heading) or result
    return delta
