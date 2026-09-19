"""The factory behind the read-only worker agents.

Each worker is a role, a prompt builder and an output key. The role rides in the
user turn so the system message stays identical and the prefix stays cacheable."""

from __future__ import annotations

from typing import Any, Callable

from ..client import OpenRouterHermesClient
from ..context import model_config_from_state
from ..prompts import shared_agent_system, worker_model
from ..state import AgentMartState, AgentName, emit_envelope, transcript_entry




def make_agent_node(
    agent: AgentName,
    system_prompt: str,
    prompt_builder: Callable[[AgentMartState], str],
    output_key: str,
    capability: str = "",
) -> Callable[[AgentMartState], AgentMartState]:
    def node(state: AgentMartState) -> AgentMartState:
        envelope = emit_envelope(
            state,
            sender="hermes_myshopper",
            recipient=agent,
            intent=capability or output_key,
            payload={"intent": state.get("intent"), "capability": capability or output_key},
            lifecycle="accepted",
        )
        client = OpenRouterHermesClient(
            dry_run=state.get("dry_run", False),
            model_config=model_config_from_state(state),
            model_override=worker_model(state),
        )
        # The agent's own role rides in the user turn so the system message stays
        # identical across agents and the shared prefix can be cached.
        result = client.complete(
            agent,
            shared_agent_system(state),
            f"Your role: {system_prompt}\n\n{prompt_builder(state)}",
        )
        done = emit_envelope(
            state,
            sender=agent,
            recipient="hermes_myshopper",
            intent=capability or output_key,
            payload={"result_chars": len(result)},
            lifecycle="completed",
        )
        return {
            "transcript": [transcript_entry(agent, result, envelope)],
            "a2a_log": [envelope, done],
            output_key: result,
        }

    return node
