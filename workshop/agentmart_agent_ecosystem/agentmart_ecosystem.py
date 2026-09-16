from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, TypedDict
from uuid import uuid4

from dotenv import load_dotenv
from langgraph.graph import END, START, StateGraph


AgentName = Literal[
    "hermes_myshopper",
    "shopping_agent",
    "pricing_agent",
    "inventory_agent",
    "fulfillment_agent",
    "order_agent",
]


class AgentMartState(TypedDict, total=False):
    customer_request: str
    channel: str
    dry_run: bool
    hermes_a2a_config: dict[str, Any]
    a2a_task: dict[str, Any]
    shopping_result: str
    pricing_result: str
    inventory_result: str
    fulfillment_result: str
    order_result: str
    transcript: list[dict[str, Any]]


@dataclass
class A2AEnvelope:
    task_id: str
    sender: AgentName
    recipient: str
    intent: str
    payload: dict[str, Any]
    protocol: str = "agentmart.a2a.v1"
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if not data["created_at"]:
            data["created_at"] = datetime.now(timezone.utc).isoformat()
        return data


class OpenRouterHermesClient:
    def __init__(self, dry_run: bool = False) -> None:
        load_dotenv()
        self.dry_run = dry_run
        self.api_key = os.getenv("OPENROUTER_API_KEY", "")
        self.base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        self.model = os.getenv("OPENROUTER_MODEL", "openai/gpt-5.2")
        self.http_referer = os.getenv("OPENROUTER_HTTP_REFERER", "http://localhost")
        self.app_title = os.getenv("OPENROUTER_APP_TITLE", "AgentMart Workshop")

    def complete(self, agent_name: str, system_prompt: str, user_prompt: str) -> str:
        if self.dry_run or not self.api_key:
            return self._dry_run_reply(agent_name, user_prompt)

        from openai import OpenAI

        client = OpenAI(base_url=self.base_url, api_key=self.api_key)
        response = client.chat.completions.create(
            extra_headers={
                "HTTP-Referer": self.http_referer,
                "X-OpenRouter-Title": self.app_title,
            },
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )
        return response.choices[0].message.content or ""

    @staticmethod
    def _dry_run_reply(agent_name: str, user_prompt: str) -> str:
        compact_prompt = " ".join(user_prompt.split())
        return f"[dry-run:{agent_name}] {compact_prompt[:260]}"


def load_hermes_a2a_config(config_path: str | None = None) -> dict[str, Any]:
    path = Path(config_path) if config_path else Path(__file__).with_name("hermes_a2a_config.json")
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def append_transcript(
    state: AgentMartState,
    agent: AgentName,
    message: str,
    envelope: dict[str, Any] | None = None,
) -> AgentMartState:
    transcript = list(state.get("transcript", []))
    transcript.append(
        {
            "agent": agent,
            "message": message,
            "a2a": envelope,
        }
    )
    return {**state, "transcript": transcript}


def make_agent_node(
    agent: AgentName,
    system_prompt: str,
    prompt_builder: Callable[[AgentMartState], str],
    output_key: str,
) -> Callable[[AgentMartState], AgentMartState]:
    def node(state: AgentMartState) -> AgentMartState:
        client = OpenRouterHermesClient(dry_run=state.get("dry_run", False))
        result = client.complete(agent, system_prompt, prompt_builder(state))
        next_state = append_transcript(state, agent, result)
        next_state[output_key] = result
        return next_state

    return node


def hermes_myshopper_node(state: AgentMartState) -> AgentMartState:
    customer_request = state["customer_request"]
    config = state.get("hermes_a2a_config") or load_hermes_a2a_config()
    hermes_config = config["hermes_agent"]
    a2a_config = config["a2a_connection"]
    agentmart_config = config["agentmart"]

    envelope = A2AEnvelope(
        task_id=str(uuid4()),
        sender=hermes_config["id"],
        recipient=agentmart_config["id"],
        intent="personal_buying_request",
        payload={
            "customer_request": customer_request,
            "channel": state.get("channel", "webchat"),
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

    client = OpenRouterHermesClient(dry_run=state.get("dry_run", False))
    message = client.complete(
        "hermes_myshopper",
        (
            "You are Hermes/MyShopper, a personal buying agent. "
            "You represent the customer, not AgentMart. "
            "Create a short handoff note for the AgentMart agent ecosystem."
        ),
        json.dumps(envelope, indent=2),
    )

    next_state = append_transcript(state, "hermes_myshopper", message, envelope)
    next_state["a2a_task"] = envelope
    return next_state


shopping_agent_node = make_agent_node(
    "shopping_agent",
    "You are the AgentMart Shopping Agent. Find candidate products that match the customer's intent.",
    lambda state: json.dumps(
        {
            "a2a_task": state["a2a_task"],
            "instruction": "Return 3 candidate options with a short reason for each.",
        },
        indent=2,
    ),
    "shopping_result",
)


pricing_agent_node = make_agent_node(
    "pricing_agent",
    "You are the AgentMart Pricing Agent. Evaluate price, value, and budget fit.",
    lambda state: json.dumps(
        {
            "a2a_task": state["a2a_task"],
            "shopping_result": state["shopping_result"],
            "instruction": "Rank the candidates by value and note any price risks.",
        },
        indent=2,
    ),
    "pricing_result",
)


inventory_agent_node = make_agent_node(
    "inventory_agent",
    "You are the AgentMart Inventory Agent. Check stock assumptions and availability risks.",
    lambda state: json.dumps(
        {
            "a2a_task": state["a2a_task"],
            "shopping_result": state["shopping_result"],
            "pricing_result": state["pricing_result"],
            "instruction": "Mark which options are easiest to fulfill and what needs confirmation.",
        },
        indent=2,
    ),
    "inventory_result",
)


fulfillment_agent_node = make_agent_node(
    "fulfillment_agent",
    "You are the AgentMart Fulfillment Agent. Check delivery, pickup, and fulfillment constraints.",
    lambda state: json.dumps(
        {
            "a2a_task": state["a2a_task"],
            "inventory_result": state["inventory_result"],
            "instruction": "Recommend fulfillment path and mention delivery constraints.",
        },
        indent=2,
    ),
    "fulfillment_result",
)


order_agent_node = make_agent_node(
    "order_agent",
    (
        "You are the AgentMart Order Agent. Prepare the final customer-facing response for Hermes/MyShopper. "
        "Do not pretend an order was placed; summarize the recommended next action."
    ),
    lambda state: json.dumps(
        {
            "a2a_task": state["a2a_task"],
            "shopping_result": state["shopping_result"],
            "pricing_result": state["pricing_result"],
            "inventory_result": state["inventory_result"],
            "fulfillment_result": state["fulfillment_result"],
            "instruction": "Produce a final recommendation that Hermes/MyShopper can send back to the customer.",
        },
        indent=2,
    ),
    "order_result",
)


def build_graph():
    graph = StateGraph(AgentMartState)
    graph.add_node("hermes_myshopper", hermes_myshopper_node)
    graph.add_node("shopping_agent", shopping_agent_node)
    graph.add_node("pricing_agent", pricing_agent_node)
    graph.add_node("inventory_agent", inventory_agent_node)
    graph.add_node("fulfillment_agent", fulfillment_agent_node)
    graph.add_node("order_agent", order_agent_node)

    graph.add_edge(START, "hermes_myshopper")
    graph.add_edge("hermes_myshopper", "shopping_agent")
    graph.add_edge("shopping_agent", "pricing_agent")
    graph.add_edge("pricing_agent", "inventory_agent")
    graph.add_edge("inventory_agent", "fulfillment_agent")
    graph.add_edge("fulfillment_agent", "order_agent")
    graph.add_edge("order_agent", END)
    return graph.compile()


def run_agentmart(
    customer_request: str,
    channel: str = "webchat",
    dry_run: bool = False,
    config_path: str | None = None,
) -> AgentMartState:
    app = build_graph()
    return app.invoke(
        {
            "customer_request": customer_request,
            "channel": channel,
            "dry_run": dry_run,
            "hermes_a2a_config": load_hermes_a2a_config(config_path),
            "transcript": [],
        }
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the AgentMart LangGraph workshop demo.")
    parser.add_argument("request", help="Customer buying request to send through Hermes/MyShopper.")
    parser.add_argument("--channel", default="webchat", help="Customer channel name.")
    parser.add_argument("--config", help="Path to Hermes A2A configuration JSON.")
    parser.add_argument("--dry-run", action="store_true", help="Run without calling OpenRouter.")
    args = parser.parse_args()

    result = run_agentmart(args.request, channel=args.channel, dry_run=args.dry_run, config_path=args.config)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
