#!/usr/bin/env python3
"""AgentMart entry point and compatibility surface.

The implementation moved into the ``agentmart`` package -- one module per agent,
plus state, client, intents, context, prompts and graph. This module re-exports
that package's public names and keeps the command line, so every existing import
(`from agentmart_ecosystem import run_agentmart`) and every documented command
still works unchanged.

Read `agentmart/__init__.py` for the layout, or WALKTHROUGH.md for a guided tour.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from agentmart import *  # noqa: F401,F403 -- deliberate re-export of the public surface
from agentmart import (  # noqa: F401 -- names the CLI and callers use directly
    DEFAULT_CUSTOMER_ID,
    Intent,
    OpenRouterHermesClient,
    classify_intent,
    load_hermes_a2a_config,
    run_agentmart,
)




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
