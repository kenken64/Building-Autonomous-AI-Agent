"""Deterministic intent routing: the rule table, prohibition stripping, and the
agent path each intent takes.

Rule order is load-bearing and every entry has a reason -- read the comments before
reordering anything."""

from __future__ import annotations

import re

from .state import Intent




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
        # These must match a question ABOUT timing, not a request that merely lists
        # timing among the fields it wants back. A remote agent asking for a product
        # shortlist routinely says "...and delivery options/ETA", and a bare \beta\b
        # once sent exactly that to the Shipping Agent, so the catalog was never
        # searched and the customer got no products at all. ETA and "shipping options"
        # now have to be the subject, not an item on a wish list.
        re.compile(
            r"when\s+(will|would|can|does|do)\b[^.?!]{0,60}\b"
            r"(arrive|deliver|delivered|ship|shipped|dispatch|get\s+here|reach)|"
            r"how\s+(long|many\s+days)\b[^.?!]{0,40}\b(deliver|ship|arriv|dispatch|take)|"
            r"(delivery|shipping|dispatch)\s+(date|dates|window|timeline)\b|"
            r"estimated\s+(delivery|arrival|dispatch)|"
            r"what(?:'s|\s+is)\s+the\s+eta\b|\beta\s+(for|on|of)\b|"
            r"(get|have|receive)\s+it\s+by\b|arrive\s+(by|before)\b",
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
