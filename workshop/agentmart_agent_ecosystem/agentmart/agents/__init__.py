"""One module per agent. Import the nodes from here; the graph wires them."""

from .base import make_agent_node
from .batched import BATCHED_NODE, WORKER_AGENTS, WORKER_BRIEFS, batched_workers_node, split_sections, workers_in_path
from .myshopper import hermes_myshopper_node
from .order import ORDER_AGENT_SYSTEM_PROMPT, order_agent_node
from .payment import PAYMENT_AGENT_SYSTEM_PROMPT, payment_agent_node
from .shipping import SHIPPING_AGENT_SYSTEM_PROMPT, shipping_agent_node
from .workers import fulfillment_agent_node, inventory_agent_node, pricing_agent_node, shopping_agent_node

__all__ = [
    "make_agent_node", "hermes_myshopper_node", "shopping_agent_node", "pricing_agent_node",
    "inventory_agent_node", "fulfillment_agent_node", "shipping_agent_node", "order_agent_node",
    "payment_agent_node", "batched_workers_node", "BATCHED_NODE", "WORKER_AGENTS",
    "WORKER_BRIEFS", "workers_in_path", "split_sections",
    "ORDER_AGENT_SYSTEM_PROMPT", "PAYMENT_AGENT_SYSTEM_PROMPT", "SHIPPING_AGENT_SYSTEM_PROMPT",
]
