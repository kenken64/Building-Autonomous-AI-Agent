"""Shopping, Pricing, Inventory and Fulfillment.

Read-only, no tools, never read by the customer -- only by the next agent. Their
instructions carry character budgets for that reason: verbose intermediate answers
are paid for twice, once to write and again to read."""

from __future__ import annotations

import json

from .base import make_agent_node




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
