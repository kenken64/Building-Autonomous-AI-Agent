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

from catalog import CatalogNotSeededError, format_product_listing, query_products


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
    product_listing: str
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


DEFAULT_MODEL = "moonshotai/kimi-k3"


class OpenRouterHermesClient:
    """OpenAI-compatible client for OpenRouter, configured for Hermes/MyShopper.

    Settings resolve in this order, first match wins:
      1. environment variables / .env  (OPENROUTER_MODEL, ...)
      2. the model block in hermes_a2a_config.json
      3. the built-in defaults
    """

    def __init__(self, dry_run: bool = False, model_config: dict[str, Any] | None = None) -> None:
        load_dotenv()
        config = model_config or {}
        self.dry_run = dry_run
        self.api_key = os.getenv("OPENROUTER_API_KEY", "")
        self.base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        self.model = os.getenv("OPENROUTER_MODEL") or config.get("default_model") or DEFAULT_MODEL
        self.fallback_models = config.get("fallback_models", [])
        self.temperature = float(os.getenv("OPENROUTER_TEMPERATURE", config.get("temperature", 0.2)))
        self.max_tokens = int(os.getenv("OPENROUTER_MAX_TOKENS", config.get("max_tokens", 1200)))
        self.http_referer = os.getenv("OPENROUTER_HTTP_REFERER", "http://localhost")
        self.app_title = os.getenv("OPENROUTER_APP_TITLE", "AgentMart Workshop")

    def complete(self, agent_name: str, system_prompt: str, user_prompt: str) -> str:
        if self.dry_run or not self.api_key:
            return self._dry_run_reply(agent_name, user_prompt)

        from openai import OpenAI

        client = OpenAI(base_url=self.base_url, api_key=self.api_key)
        extra_body: dict[str, Any] = {}
        if self.fallback_models:
            # OpenRouter retries these in order if the primary model is unavailable.
            extra_body["models"] = [self.model, *self.fallback_models]

        response = client.chat.completions.create(
            extra_headers={
                "HTTP-Referer": self.http_referer,
                "X-Title": self.app_title,
            },
            extra_body=extra_body,
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        return response.choices[0].message.content or ""

    @staticmethod
    def _dry_run_reply(agent_name: str, user_prompt: str) -> str:
        compact_prompt = " ".join(user_prompt.split())
        return f"[dry-run:{agent_name}] {compact_prompt[:260]}"


def load_product_listing(
    category: str | None = None,
    max_price: float | None = None,
    limit: int = 25,
) -> str:
    """Render the seeded AgentMart product listing for the agent prompts."""
    try:
        products = query_products(category=category, max_price=max_price, limit=limit)
    except CatalogNotSeededError as exc:
        return f"(catalog unavailable: {exc})"
    if not products:
        return "(no products in the seeded catalog matched the filters)"
    return format_product_listing(products)


def load_hermes_a2a_config(config_path: str | None = None) -> dict[str, Any]:
    path = Path(config_path) if config_path else Path(__file__).with_name("hermes_a2a_config.json")
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def model_config_from_state(state: AgentMartState) -> dict[str, Any]:
    """Read the Hermes model block (provider, model, temperature) from graph state."""
    config = state.get("hermes_a2a_config") or {}
    return config.get("hermes_agent", {}).get("model", {})


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
        client = OpenRouterHermesClient(
            dry_run=state.get("dry_run", False),
            model_config=model_config_from_state(state),
        )
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

    next_state = append_transcript(state, "hermes_myshopper", message, envelope)
    next_state["a2a_task"] = envelope
    return next_state


shopping_agent_node = make_agent_node(
    "shopping_agent",
    (
        "You are the AgentMart Shopping Agent. Find candidate products that match the customer's intent. "
        "Only recommend SKUs that appear in the AgentMart product listing you are given."
    ),
    lambda state: json.dumps(
        {
            "a2a_task": state["a2a_task"],
            "product_listing": state.get("product_listing", ""),
            "instruction": (
                "Pick 3 candidate SKUs from the product listing and give a short reason for each. "
                "Cite the SKU and price exactly as listed. Do not invent products."
            ),
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
            "product_listing": state.get("product_listing", ""),
            "instruction": (
                "Rank the candidates by value using the listed price and list price. "
                "Note any discount, budget overrun, or price risk."
            ),
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
            "product_listing": state.get("product_listing", ""),
            "instruction": (
                "Use the stock lines in the product listing. Mark which options are in stock now, "
                "which depend on a restock, and what needs confirmation."
            ),
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
            "product_listing": state.get("product_listing", ""),
            "instruction": (
                "Recommend a fulfillment path using the delivery methods, ETAs, and costs in the listing. "
                "Mention which warehouse ships the item."
            ),
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
    category: str | None = None,
    max_price: float | None = None,
) -> AgentMartState:
    app = build_graph()
    return app.invoke(
        {
            "customer_request": customer_request,
            "channel": channel,
            "dry_run": dry_run,
            "hermes_a2a_config": load_hermes_a2a_config(config_path),
            "product_listing": load_product_listing(category=category, max_price=max_price),
            "transcript": [],
        }
    )


def check_model_connection(config_path: str | None = None) -> int:
    """Verify the OpenRouter key and model before running the full graph."""
    config = load_hermes_a2a_config(config_path)
    model_config = config["hermes_agent"].get("model", {})
    client = OpenRouterHermesClient(model_config=model_config)

    print("Hermes model configuration")
    print(f"  provider    : {model_config.get('provider', 'openrouter')}")
    print(f"  base_url    : {client.base_url}")
    print(f"  model       : {client.model}")
    print(f"  fallbacks   : {', '.join(client.fallback_models) or 'none'}")
    print(f"  temperature : {client.temperature}")
    print(f"  max_tokens  : {client.max_tokens}")
    print(f"  api_key     : {'set' if client.api_key else 'MISSING'}")

    if not client.api_key:
        print("\nOPENROUTER_API_KEY is not set. Add it to .env, then re-run.")
        return 1

    print("\nCalling OpenRouter...")
    try:
        reply = client.complete(
            "hermes_myshopper",
            "You are Hermes/MyShopper. Reply with a single short sentence.",
            "Confirm that the Hermes model connection is working.",
        )
    except Exception as exc:  # noqa: BLE001 - surface any client/transport error to the workshop user
        print(f"Connection failed: {type(exc).__name__}: {exc}")
        return 1

    print(f"Reply: {reply.strip()[:300]}")
    print("\nConnection OK.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the AgentMart LangGraph workshop demo.")
    parser.add_argument(
        "request",
        nargs="?",
        help="Customer buying request to send through Hermes/MyShopper.",
    )
    parser.add_argument("--channel", default="webchat", help="Customer channel name.")
    parser.add_argument("--config", help="Path to Hermes A2A configuration JSON.")
    parser.add_argument("--dry-run", action="store_true", help="Run without calling OpenRouter.")
    parser.add_argument("--category", help="Limit the seeded product listing to a category, e.g. audio/earbuds.")
    parser.add_argument("--max-price", type=float, help="Limit the seeded product listing by maximum price.")
    parser.add_argument(
        "--check-model",
        action="store_true",
        help="Print the Hermes model settings and test the OpenRouter connection, then exit.",
    )
    args = parser.parse_args()

    if args.check_model:
        raise SystemExit(check_model_connection(args.config))

    if not args.request:
        parser.error("a customer request is required (or use --check-model)")

    result = run_agentmart(
        args.request,
        channel=args.channel,
        dry_run=args.dry_run,
        config_path=args.config,
        category=args.category,
        max_price=args.max_price,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
