from __future__ import annotations

import argparse
import json
import logging
import operator
import os
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Callable, Literal, TypedDict
from uuid import uuid4

from dotenv import load_dotenv
from langgraph.graph import END, START, StateGraph

from catalog import (
    CatalogNotSeededError,
    format_product_listing,
    fulfillment_for_warehouses,
    query_products,
)
from shipping import format_estimates, simulate_options

# Per-hop timing. httpx logs when response *headers* arrive, not when the body is
# read, so its lines understate a slow call and cannot be used to find the slowest
# agent. These measure the whole call.
logger = logging.getLogger("agentmart")

# Optional trace sink. The console needs the prompt, the reply and the token counts
# for every hop; the log line carries only the numbers. Set to a callable to receive
# one dict per model call. Left None everywhere else so a CLI run costs nothing.
TRACE_SINK: Callable[[dict[str, Any]], None] | None = None


def set_trace_sink(sink: Callable[[dict[str, Any]], None] | None) -> None:
    """Install (or clear) the per-hop trace callback."""
    global TRACE_SINK
    TRACE_SINK = sink
from orders import (
    OrderBookNotSeededError,
    OrderNotFoundError,
    checkout_and_pay,
    create_draft_order,
    find_payable_order,
    format_order,
    format_orders,
    get_customer,
    get_order,
    list_orders,
)


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


DEFAULT_MODEL = "moonshotai/kimi-k3"


class OpenRouterHermesClient:
    """OpenAI-compatible client for OpenRouter, configured for Hermes/MyShopper.

    Settings resolve in this order, first match wins:
      1. environment variables / .env  (OPENROUTER_MODEL, ...)
      2. the model block in hermes_a2a_config.json
      3. the built-in defaults
    """

    def __init__(self, dry_run: bool = False, model_config: dict[str, Any] | None = None,
                 model_override: str | None = None) -> None:
        load_dotenv()
        config = model_config or {}
        self.dry_run = dry_run
        # OPENAI_* wins when set, so pointing the lab at OpenAI directly needs no rename.
        self.api_key = os.getenv("OPENAI_API_KEY") or os.getenv("OPENROUTER_API_KEY", "")
        self.base_url = (os.getenv("OPENAI_BASE_URL") or
                         os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"))
        self.model = (model_override
                      or os.getenv("OPENAI_MODEL") or os.getenv("OPENROUTER_MODEL")
                      or config.get("default_model") or DEFAULT_MODEL)
        # OpenAI's own endpoint and OpenRouter disagree on three parameters, so the
        # request has to be shaped per endpoint rather than sent one way and hoped for.
        self.openai_native = "api.openai.com" in self.base_url
        # OpenAI splits its own catalogue in two: the reasoning families take
        # reasoning_effort and reject any temperature but their default, while
        # gpt-4.x takes temperature and rejects reasoning_effort outright.
        # OpenRouter normalizes both, so this only matters on the direct endpoint.
        self.openai_reasoning_family = self.model.startswith(("gpt-5", "o1", "o3", "o4"))
        self.fallback_models = config.get("fallback_models", [])
        self.temperature = float(os.getenv("OPENROUTER_TEMPERATURE", config.get("temperature", 0.2)))
        self.max_tokens = int(os.getenv("OPENROUTER_MAX_TOKENS", config.get("max_tokens", 1200)))
        # Kimi K3 reasons before it answers, and reasoning is billed and timed like any
        # other completion token. Capping the effort is the single biggest latency win;
        # set OPENROUTER_REASONING_EFFORT=default to hand the model its full budget back.
        self.reasoning_effort = os.getenv(
            "OPENROUTER_REASONING_EFFORT", config.get("reasoning_effort", "medium")
        )
        self.http_referer = os.getenv("OPENROUTER_HTTP_REFERER", "http://localhost")
        self.app_title = os.getenv("OPENROUTER_APP_TITLE", "AgentMart Workshop")

    def complete(self, agent_name: str, system_prompt: str, user_prompt: str) -> str:
        if self.dry_run or not self.api_key:
            reply = self._dry_run_reply(agent_name, user_prompt)
            # Trace dry runs too, so the console can be demonstrated without spend.
            if TRACE_SINK is not None:
                TRACE_SINK({
                    "agent": agent_name, "model": "(dry-run)", "seconds": 0.0,
                    "system_prompt": system_prompt, "user_prompt": user_prompt,
                    "response": reply, "prompt_tokens": 0, "cached_tokens": 0,
                    "completion_tokens": 0, "reasoning_tokens": 0, "finish_reason": "dry_run",
                })
            return reply

        from openai import OpenAI

        client = OpenAI(base_url=self.base_url, api_key=self.api_key)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        kwargs: dict[str, Any] = {"model": self.model, "messages": messages}

        if self.openai_native:
            # The gpt-5.6 family rejects `max_tokens` (wants `max_completion_tokens`),
            # rejects any temperature but the default, and takes reasoning as a
            # top-level `reasoning_effort` rather than OpenRouter's `reasoning` object.
            # Model fallbacks and the attribution headers are OpenRouter features.
            kwargs["max_completion_tokens"] = self.max_tokens
            if self.openai_reasoning_family:
                if self.reasoning_effort and self.reasoning_effort != "default":
                    kwargs["reasoning_effort"] = self.reasoning_effort
            else:
                kwargs["temperature"] = self.temperature
        else:
            extra_body: dict[str, Any] = {}
            if self.fallback_models:
                # OpenRouter retries these in order if the primary model is unavailable.
                extra_body["models"] = [self.model, *self.fallback_models]
            if self.reasoning_effort and self.reasoning_effort != "default":
                extra_body["reasoning"] = {"effort": self.reasoning_effort}
            kwargs.update(
                extra_headers={"HTTP-Referer": self.http_referer, "X-Title": self.app_title},
                extra_body=extra_body,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )

        started = time.time()
        response = client.chat.completions.create(**kwargs)
        elapsed = time.time() - started
        content = response.choices[0].message.content or ""
        usage = getattr(response, "usage", None)
        details = getattr(usage, "completion_tokens_details", None) if usage else None
        prompt_details = getattr(usage, "prompt_tokens_details", None) if usage else None
        # cached_tok is the prefix-cache hit: it should cover the shared catalog on
        # every call after the first. A run of zeros means the prefix drifted.
        logger.info(
            "PERF agent=%s %.1fs model=%s prompt_tok=%s cached_tok=%s completion_tok=%s "
            "reasoning_tok=%s out_chars=%d finish=%s",
            agent_name, elapsed, self.model,
            getattr(usage, "prompt_tokens", "?"),
            getattr(prompt_details, "cached_tokens", 0) if prompt_details else "?",
            getattr(usage, "completion_tokens", "?"),
            getattr(details, "reasoning_tokens", "?") if details else "?",
            len(content), response.choices[0].finish_reason,
        )
        if TRACE_SINK is not None:
            TRACE_SINK({
                "agent": agent_name,
                "model": self.model,
                "seconds": round(elapsed, 2),
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "response": content,
                "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                "cached_tokens": (getattr(prompt_details, "cached_tokens", 0) or 0) if prompt_details else 0,
                "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
                "reasoning_tokens": (getattr(details, "reasoning_tokens", 0) or 0) if details else 0,
                "finish_reason": response.choices[0].finish_reason,
            })
        return content

    @staticmethod
    def _dry_run_reply(agent_name: str, user_prompt: str) -> str:
        compact_prompt = " ".join(user_prompt.split())
        return f"[dry-run:{agent_name}] {compact_prompt[:260]}"


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


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


SKU_PATTERN = re.compile(r"\bAM-[A-Z]{3}-\d{4}\b", re.IGNORECASE)
ORDER_ID_PATTERN = re.compile(r"\bAM-ORD-[\w-]+\b", re.IGNORECASE)

# Checked in order: the first rule that matches wins. Order matters here —
# "checkout and pay for my order" contains "my order", so the explicit checkout
# imperative has to outrank the status rule, while a *question* about payment
# ("has my payment gone through?") must stay a status lookup and never charge.
INTENT_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        # 0. An explicit request to *draft* an order outranks every payment word
        # that may trail it ("...just confirm the draft and the next checkout step").
        "purchase_intent",
        re.compile(r"draft\s+order|create\s+(?:a\s+)?draft", re.IGNORECASE),
    ),
    (
        # 1. Unambiguous checkout imperatives.
        "checkout_payment",
        re.compile(
            r"check\s?out\b(?!\s*(?:step|steps|process|flow|page|link|option|details))|"
            r"\bpay\s+now\b|place\s+the\s+order|settle\s+(up|the\s+bill)",
            re.IGNORECASE,
        ),
    ),
    (
        # 1b. Date questions about delivery. Ahead of the status rule because "where
        # is my order" and "when will it arrive" want different agents -- the second
        # needs simulated dates, not a status row.
        "shipping_estimate",
        re.compile(
            r"when\s+(will|would|can|do)\s+.*(arrive|deliver|ship|get\s+here|reach)|"
            r"how\s+(long|many\s+days)\s+.*(deliver|ship|arriv)|"
            r"delivery\s+(date|estimate|eta)|shipping\s+(date|estimate|eta|options?)|"
            r"\beta\b|estimated\s+(delivery|arrival)|"
            r"(get|have)\s+it\s+by\b|arrive\s+(by|before)\b",
            re.IGNORECASE,
        ),
    ),
    (
        # 2. Status questions, including questions *about* a payment.
        "order_status",
        re.compile(
            r"order\s+status|order\s+summary|order[_\s]status[_\s]lookup|"
            r"status\s+of\s+(my|the|order)|where\s+is\s+my|"
            r"track(ing)?\b|my\s+orders?\b|delivery\s+status|has\s+it\s+shipped|"
            r"payment\s+.*(gone\s+through|received|cleared|succeed)",
            re.IGNORECASE,
        ),
    ),
    (
        # 3. Weaker payment wording, only once a status reading is ruled out.
        "checkout_payment",
        re.compile(r"\bpay\b|\bpaying\b|payment", re.IGNORECASE),
    ),
    (
        "purchase_intent",
        re.compile(
            r"(?:want|wants|wish|would\s+like|going)\s+to\s+buy|i.?ll\s+buy|"
            r"\bbuy\s+(?:this|it|the|sku)\b|purchase\s+(?:this|it|the|sku)|"
            r"add\s+to\s+(the\s+)?cart|i.?ll\s+take|take\s+(it|this)|order\s+(this|the)",
            re.IGNORECASE,
        ),
    ),
    (
        "browse_catalog",
        re.compile(
            r"list\s+(me|the|all|available)|show\s+me|what\s+(do\s+you\s+have|is\s+available|"
            r"products?\s+are)|browse|catalog(ue)?|available\s+product",
            re.IGNORECASE,
        ),
    ),
)


# A remote agent states its guardrails in the request itself -- "do not charge or
# capture payment", "without taking any refund action". Those clauses name the very
# capability they are forbidding, so matching them verbatim routes a prohibition to
# the Payment Agent. Drop each one up to its clause boundary before any rule runs.
PROHIBITION_CLAUSE = re.compile(
    r"\b(?:do\s+not|do\s?n['\u2019]t|does\s+not|never|without|avoid|no\s+need\s+to)\b[^.;:\n]*",
    re.IGNORECASE,
)


def strip_prohibitions(text: str) -> str:
    """Remove negated clauses so a forbidden action cannot be read as a requested one."""
    return PROHIBITION_CLAUSE.sub(" ", text)


def classify_intent(customer_request: str) -> Intent:
    """Deterministic intent routing.

    Kept rule-based so a scenario run is reproducible and the assertions in
    `test_scenarios.py` mean something: the agents are the model-driven part,
    the routing is not.
    """
    customer_request = strip_prohibitions(customer_request)
    for intent, pattern in INTENT_RULES:
        if pattern.search(customer_request):
            return intent  # type: ignore[return-value]
    # A request naming an existing order is about that order, whatever else it says.
    # Falling through to product_advice here would wake Shopping and Pricing to answer
    # a question about an order already in the book.
    if extract_order_id(customer_request):
        return "order_status"
    return "product_advice"


def extract_sku(customer_request: str) -> str | None:
    match = SKU_PATTERN.search(customer_request)
    return match.group(0).upper() if match else None


def extract_order_id(customer_request: str) -> str | None:
    match = ORDER_ID_PATTERN.search(customer_request)
    return match.group(0).upper() if match else None


def load_order_context(customer_id: str, order_id: str | None = None) -> str:
    """Render the customer's order book for the Order and Payment agent prompts."""
    try:
        if order_id:
            return format_order(get_order(order_id))
        customer = get_customer(customer_id)
        header = (
            f"customer {customer['customer_id']} | {customer['name']}"
            f" | {customer['channel']} {customer['channel_handle']}"
            f" | ships to {customer['shipping_address']}"
            f" | default payment {customer['default_payment_method']}"
            if customer
            else f"(no customer record for {customer_id})"
        )
        return header + "\n" + format_orders(list_orders(customer_id=customer_id))
    except OrderNotFoundError as exc:
        return f"(order not found: {exc})"
    except OrderBookNotSeededError as exc:
        return f"(order book unavailable: {exc})"


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


def load_hermes_a2a_config(config_path: str | None = None) -> dict[str, Any]:
    path = Path(config_path) if config_path else Path(__file__).with_name("hermes_a2a_config.json")
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def model_config_from_state(state: AgentMartState) -> dict[str, Any]:
    """Read the Hermes model block (provider, model, temperature) from graph state."""
    config = state.get("hermes_a2a_config") or {}
    return config.get("hermes_agent", {}).get("model", {})


def transcript_entry(
    agent: AgentName,
    message: str,
    envelope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One transcript row. Nodes return ``{"transcript": [entry]}`` and the reducer
    concatenates -- returning the whole list would double it under a reducer."""
    return {"agent": agent, "message": message, "a2a": envelope}


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


shopping_agent_node = make_agent_node(
    "shopping_agent",
    (
        "You are the AgentMart Shopping Agent. Find candidate products that match the customer's intent. "
        "Only recommend SKUs that appear in the AgentMart product listing you are given."
    ),
    lambda state: json.dumps(
        {
            "a2a_task": state["a2a_task"],
            "instruction": (
                "Pick 3 candidate SKUs from the product listing and give a short reason for each. "
                "Cite the SKU and price exactly as listed. Do not invent products. "
                "One line per SKU, 300 characters total or fewer."
            ),
        },
        indent=2,
    ),
    "shopping_result",
    capability="product_search",
)


pricing_agent_node = make_agent_node(
    "pricing_agent",
    "You are the AgentMart Pricing Agent. Evaluate price, value, and budget fit.",
    lambda state: json.dumps(
        {
            "a2a_task": state["a2a_task"],
            "shopping_result": state.get("shopping_result", "(agent not on this path)"),
            "instruction": (
                "Rank the candidates by value using the listed price and list price. "
                "Note any discount, budget overrun, or price risk. "
                "One line per candidate plus at most one risk line, 400 characters or fewer."
            ),
        },
        indent=2,
    ),
    "pricing_result",
    capability="price_check",
)


inventory_agent_node = make_agent_node(
    "inventory_agent",
    "You are the AgentMart Inventory Agent. Check stock assumptions and availability risks.",
    lambda state: json.dumps(
        {
            "a2a_task": state["a2a_task"],
            "shopping_result": state.get("shopping_result", "(agent not on this path)"),
            "pricing_result": state.get("pricing_result", "(agent not on this path)"),
            "instruction": (
                "Use the stock lines in the product listing. Mark which options are in stock now, "
                "which depend on a restock, and what needs confirmation. "
                "One line per SKU, 400 characters or fewer."
            ),
        },
        indent=2,
    ),
    "inventory_result",
    capability="stock_check",
)


fulfillment_agent_node = make_agent_node(
    "fulfillment_agent",
    "You are the AgentMart Fulfillment Agent. Check delivery, pickup, and fulfillment constraints.",
    lambda state: json.dumps(
        {
            "a2a_task": state["a2a_task"],
            "inventory_result": state.get("inventory_result", "(agent not on this path)"),
            "instruction": (
                "Recommend a fulfillment path using the delivery methods, ETAs, and costs in the listing. "
                "Mention which warehouse ships the item. 400 characters or fewer."
            ),
        },
        indent=2,
    ),
    "fulfillment_result",
    capability="delivery_options",
)


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


SHIPPING_AGENT_SYSTEM_PROMPT = (
    "You are the AgentMart Shipping Agent. You are given simulated dispatch and delivery "
    "dates that were CALCULATED for you, with the reason behind each. Never compute, adjust, "
    "or invent a date: quote the ones you are given and explain them. Say plainly that the "
    "estimate is simulated. Answer in compact lines, 500 characters or fewer."
)


def shipping_agent_node(state: AgentMartState) -> AgentMartState:
    """Dates are computed in shipping.py; this agent only explains them.

    Every other prompt in this lab forbids inventing a delivery date. The only way to
    hold that line is to hand the model real dates, so the arithmetic happens in
    Python and the model never sees a reason to guess.
    """
    intent = state.get("intent", "shipping_estimate")
    order_id = state.get("target_order_id")
    envelope = emit_envelope(
        state, sender="hermes_myshopper", recipient="shipping_agent", intent=intent,
        payload={"capability": "shipping_estimate", "order_id": order_id}, lifecycle="accepted",
    )

    placed_at = None
    warehouses = ["SG-CENTRAL", "MY-JB", "US-WEST"]
    if order_id:
        try:
            order = get_order(order_id)
            placed_at = order.get("placed_at")
            if order.get("warehouse"):
                warehouses = [order["warehouse"]]
        except (OrderNotFoundError, OrderBookNotSeededError):
            pass  # no such order: fall back to a general estimate across warehouses

    try:
        options = fulfillment_for_warehouses(warehouses)
        options = options if isinstance(options, list) else sum(options.values(), [])
        estimates = format_estimates(simulate_options(options, placed_at))
    except CatalogNotSeededError as exc:
        estimates = f"(fulfillment options unavailable: {exc})"

    client = OpenRouterHermesClient(
        dry_run=state.get("dry_run", False),
        model_config=model_config_from_state(state),
        model_override=worker_model(state),
    )
    result = client.complete(
        "shipping_agent",
        SHIPPING_AGENT_SYSTEM_PROMPT,
        json.dumps({
            "customer_request": state["customer_request"],
            "order_id": order_id,
            "order_placed_at": placed_at,
            "calculated_estimates": estimates,
            "instruction": (
                "Answer the customer's timing question using only the calculated "
                "estimates above. One line per option. State that these are simulated."
            ),
        }, indent=2),
    )
    done = emit_envelope(
        state, sender="shipping_agent", recipient="hermes_myshopper", intent=intent,
        payload={"result_chars": len(result), "options": len(estimates.splitlines())},
        lifecycle="completed",
    )
    return {
        "transcript": [transcript_entry("shipping_agent", result, envelope)],
        "a2a_log": [envelope, done],
        "shipping_result": result,
        "shipping_estimates": estimates,
    }


ORDER_AGENT_SYSTEM_PROMPT = (
    "You are the AgentMart Order Agent. You speak to Hermes/MyShopper, which relays to the customer. "
    "Work only from the order book and agent results you are given. Never invent an order id, "
    "tracking reference, amount, or delivery date. If something is missing, say what is missing. "
    # Your reader is another agent, not the customer. Hermes rewrites this into prose for
    # the chat, so every word of framing here is paid for twice: once to generate, again
    # when Hermes reads it back. Facts are what travel; the phrasing is Hermes' job.
    "Answer as compact structured facts, not prose. No greeting, no preamble, no closing "
    "offer, no restating the question. One line per option: SKU, name, price, the one or "
    "two attributes that decide it, stock, and delivery. Put any caveat on its own short "
    "line. Aim for 600 characters or fewer."
)


def _order_agent_prompt(state: AgentMartState) -> str:
    intent = state.get("intent", "product_advice")
    common = {
        "a2a_task": state["a2a_task"],
        "intent": intent,
        "customer_id": state.get("customer_id"),
    }

    if intent == "shipping_estimate":
        return json.dumps(
            {
                **common,
                "order_book": state.get("order_context", ""),
                # Already-calculated dates. The Order Agent relays them; it must not
                # recompute or round them, and must not answer if they are missing.
                "shipping_result": state.get("shipping_result", "(agent not on this path)"),
                "instruction": (
                    "Answer the customer's timing question using the Shipping Agent's "
                    "result. Quote its dates exactly and say the estimate is simulated. "
                    "If the shipping result is missing, say so instead of estimating."
                ),
            },
            indent=2,
        )

    if intent == "order_status":
        return json.dumps(
            {
                **common,
                "order_book": state.get("order_context", ""),
                "instruction": (
                    "Answer the customer's order-status question from the order book. "
                    "For each relevant order give: order id, status, what happens next, "
                    "tracking reference and ETA when present. Flag any order that is "
                    "awaiting payment as needing the customer's action."
                ),
            },
            indent=2,
        )

    if intent == "purchase_intent":
        return json.dumps(
            {
                **common,
                "draft_order": state.get("draft_order", {}),
                "inventory_result": state.get("inventory_result", "(agent not on this path)"),
                "fulfillment_result": state.get("fulfillment_result", "(agent not on this path)"),
                "instruction": (
                    "A draft order has been created and is awaiting payment. Confirm back to the "
                    "customer what is reserved, the line items, the total, and the delivery path. "
                    "State clearly that nothing is charged until they confirm checkout."
                ),
            },
            indent=2,
        )

    if intent == "checkout_payment":
        return json.dumps(
            {
                **common,
                "order_book": state.get("order_context", ""),
                "order_to_settle": state.get("target_order_id"),
                "instruction": (
                    "Identify the single order to settle and restate its total and payment method "
                    "for confirmation. Do not claim payment has happened: the Payment Agent runs next."
                ),
            },
            indent=2,
        )

    # browse_catalog / product_advice: the original recommendation summary
    return json.dumps(
        {
            **common,
            "shopping_result": state.get("shopping_result", "(agent not on this path)"),
            "pricing_result": state.get("pricing_result", "(agent not on this path)"),
            "inventory_result": state.get("inventory_result", "(agent not on this path)"),
            "fulfillment_result": state.get("fulfillment_result", "(agent not on this path)"),
            "instruction": (
                "Produce a final recommendation that Hermes/MyShopper can send back to the customer. "
                "Do not pretend an order was placed; summarize the recommended next action."
            ),
        },
        indent=2,
    )


def order_agent_node(state: AgentMartState) -> AgentMartState:
    """Order Agent. Reads the order book; creates a draft order on a purchase intent."""
    intent = state.get("intent", "product_advice")
    customer_id = state.get("customer_id", DEFAULT_CUSTOMER_ID)

    envelope = emit_envelope(
        state,
        sender="hermes_myshopper",
        recipient="order_agent",
        intent=intent,
        payload={"capability": "order_summary", "customer_id": customer_id},
        lifecycle="accepted",
    )

    next_state: AgentMartState = {**state}

    # A purchase intent materialises a real draft order before the model speaks.
    if intent == "purchase_intent":
        sku = state.get("target_sku")
        if not sku:
            next_state["draft_order"] = {"error": "no SKU identified in the customer request"}
        else:
            try:
                draft = create_draft_order(
                    customer_id=customer_id,
                    items=[{"sku": sku, "quantity": 1}],
                    warehouse="SG-CENTRAL",
                    fulfillment_method="standard_delivery",
                    shipping_usd=3.5,
                )
                next_state["draft_order"] = draft
                next_state["target_order_id"] = draft["order_id"]
                next_state["order_context"] = format_order(draft)
            except (CatalogNotSeededError, OrderBookNotSeededError, ValueError) as exc:
                next_state["draft_order"] = {"error": f"{type(exc).__name__}: {exc}"}

    # A bare "checkout and pay" resolves to the customer's oldest unpaid order.
    if intent == "checkout_payment" and not next_state.get("target_order_id"):
        try:
            payable = find_payable_order(customer_id)
            if payable:
                next_state["target_order_id"] = payable["order_id"]
                next_state["order_context"] = format_order(payable)
        except OrderBookNotSeededError as exc:
            next_state["order_context"] = f"(order book unavailable: {exc})"

    client = OpenRouterHermesClient(
        dry_run=state.get("dry_run", False),
        model_config=model_config_from_state(state),
    )
    result = client.complete("order_agent", ORDER_AGENT_SYSTEM_PROMPT, _order_agent_prompt(next_state))

    done = emit_envelope(
        next_state,
        sender="order_agent",
        recipient="hermes_myshopper",
        intent=intent,
        payload={
            "order_id": next_state.get("target_order_id"),
            "draft_created": bool(next_state.get("draft_order", {}).get("order_id")),
        },
        lifecycle="completed",
    )

    # Only the keys this node actually decided; transcript/a2a_log go back as deltas.
    delta: AgentMartState = {
        k: v for k, v in next_state.items()
        if k in ("draft_order", "target_order_id", "order_context")
    }
    delta["transcript"] = [transcript_entry("order_agent", result, envelope)]
    delta["a2a_log"] = [envelope, done]
    delta["order_result"] = result
    return delta


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


# Which AgentMart agents each intent actually visits. Routing on capability is
# the Part 7 teaching point: a status question must not wake the whole ecosystem.
INTENT_PATHS: dict[str, tuple[str, ...]] = {
    "browse_catalog": ("shopping_agent", "pricing_agent", "inventory_agent", "order_agent"),
    "product_advice": (
        "shopping_agent",
        "pricing_agent",
        "inventory_agent",
        "fulfillment_agent",
        "order_agent",
    ),
    # Stops at the Order Agent on purpose: a purchase intent leaves a draft in
    # `awaiting_payment`. Settling it is a separate, explicit checkout turn.
    "purchase_intent": ("inventory_agent", "fulfillment_agent", "order_agent"),
    "checkout_payment": ("order_agent", "payment_agent"),
    "order_status": ("order_agent",),
    # Dates come from shipping.py, not from the model; the Order Agent then speaks
    # to the customer using them.
    "shipping_estimate": ("shipping_agent", "order_agent"),
}


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


def check_model_connection(config_path: str | None = None) -> int:
    """Verify the key, endpoint and model before running the full graph."""
    config = load_hermes_a2a_config(config_path)
    model_config = config["hermes_agent"].get("model", {})
    client = OpenRouterHermesClient(model_config=model_config)

    endpoint = "OpenAI" if client.openai_native else "OpenRouter"
    print("Hermes model configuration")
    print(f"  endpoint    : {endpoint}")
    print(f"  base_url    : {client.base_url}")
    print(f"  model       : {client.model}")
    # Model fallbacks and temperature are OpenRouter features; say so rather than
    # printing settings that this endpoint will silently ignore.
    if client.openai_native:
        print(f"  fallbacks   : n/a (OpenRouter only)")
        print(f"  temperature : n/a (model default)")
        print(f"  max_tokens  : {client.max_tokens} (sent as max_completion_tokens)")
    else:
        print(f"  fallbacks   : {', '.join(client.fallback_models) or 'none'}")
        print(f"  temperature : {client.temperature}")
        print(f"  max_tokens  : {client.max_tokens}")
    print(f"  reasoning   : {client.reasoning_effort or 'default'}")
    print(f"  api_key     : {'set' if client.api_key else 'MISSING'}")

    if not client.api_key:
        key_var = "OPENAI_API_KEY" if client.openai_native else "OPENROUTER_API_KEY"
        print(f"\n{key_var} is not set. Add it to .env, then re-run.")
        return 1

    print(f"\nCalling {endpoint}...")
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
    parser.add_argument(
        "--customer",
        default=DEFAULT_CUSTOMER_ID,
        help=f"Customer id from the seeded order book (default: {DEFAULT_CUSTOMER_ID}).",
    )
    parser.add_argument(
        "--intent",
        choices=list(INTENT_PATHS),
        help="Force an intent instead of routing on the request text.",
    )
    parser.add_argument("--config", help="Path to Hermes A2A configuration JSON.")
    parser.add_argument("--dry-run", action="store_true", help="Run without calling OpenRouter.")
    parser.add_argument("--batch-workers", action="store_true",
                        help="Run every worker agent on the path in ONE model call "
                             "(~2.7x faster; collapses four demo hops into one).")
    parser.add_argument("--timing", action="store_true",
                        help="Print a PERF line per agent hop (duration, tokens, finish reason).")
    parser.add_argument("--category", help="Limit the seeded product listing to a category, e.g. audio/earbuds.")
    parser.add_argument("--max-price", type=float, help="Limit the seeded product listing by maximum price.")
    parser.add_argument(
        "--check-model",
        action="store_true",
        help="Print the Hermes model settings and test the OpenRouter connection, then exit.",
    )
    args = parser.parse_args()

    if args.timing:
        logging.basicConfig(level=logging.INFO, format="%(message)s")

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
        customer_id=args.customer,
        intent=args.intent,
        batch_workers=args.batch_workers,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
