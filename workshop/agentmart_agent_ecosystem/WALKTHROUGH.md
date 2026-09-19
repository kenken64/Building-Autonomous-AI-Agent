# AgentMart Code Walkthrough

A guided read of the lab, following one customer request from a Telegram message
to a grounded answer.

Read this with the files open. Each section says what to look at, what it does,
and — where it matters — why it is written that way rather than the obvious way.
References are `symbol` (file:line) and are asserted by
`test_scenarios.py -s doc-refs`, so a line number here is either right or the
suite is red.

## Where the code lives

```
agentmart_ecosystem.py .... entry point: the CLI, and a re-export of the package
agentmart/
  state.py ................ AgentMartState, A2AEnvelope, transcript/envelope helpers
  client.py ............... the model client, per-endpoint shaping, PERF + trace
  intents.py .............. the routing rules and each intent's agent path
  context.py .............. catalog, order book, Hermes A2A config
  prompts.py .............. the cacheable system prefix every worker shares
  agents/
    base.py ............... the worker factory
    workers.py ............ Shopping, Pricing, Inventory, Fulfillment
    myshopper.py .......... Hermes/MyShopper, the lab's own buying agent
    shipping.py ........... quotes dates; never computes them
    order.py .............. the only hop that writes
    payment.py ............ simulated payments
    batched.py ............ every worker in one call, opt-in
  graph.py ................ wiring, routing, run_agentmart()
a2a_server.py ............. the A2A v1.0 front door, cache and console
shipping.py ............... deterministic dispatch/delivery date arithmetic
console.html .............. the web console
```

Nothing that imported `agentmart_ecosystem` had to change: it re-exports the
package's public surface and keeps the command line, so
`from agentmart_ecosystem import run_agentmart` and every documented command work
exactly as before.

---

## The map

```
Telegram
   │
   ▼
Hermes / MyShopper ................ a real agent, outside this repo
   │  a2a_call("agentmart", "...")
   ▼
a2a_server.py ..................... A2A v1.0 front door (HTTP + JSON-RPC)
   │  run_agentmart(text)
   ▼
agentmart_ecosystem.py ............ the LangGraph pipeline
   │      hermes_myshopper → shopping → pricing → inventory → fulfillment → order
   ▼
catalog.py / orders.py ............ SQLite: products, stock, orders, payments
```

Two things are called A2A here. The **protocol** layer is what Hermes speaks; the
**envelope** layer is the correlated hop record inside the graph. `A2A_API.md`
separates them properly.

---

## 1. The state that flows through the graph

`AgentMartState` (agentmart/state.py:49) is a `TypedDict` carrying everything a hop might need: the
request, the intent, the product listing, each agent's result, the draft order,
and two accumulating lists.

Those two lists are declared differently:

```python
a2a_log: Annotated[list[dict[str, Any]], operator.add]
transcript: Annotated[list[dict[str, Any]], operator.add]
```

The `Annotated[..., operator.add]` is a LangGraph **reducer**: it tells the graph
how to merge writes to the same key instead of rejecting them. Because of it,
nodes return **deltas** — `{"transcript": [one_entry]}` — never the whole list.
Returning the full list under a reducer would concatenate it with itself.

## 2. The A2A envelope

`A2AEnvelope` (agentmart/state.py:79) is the teaching artifact: one record per hop, carrying
`task_id`, `sender`, `recipient`, `intent`, `payload`, `state`, and a
`correlation_id` shared by every hop of one request.

`emit_envelope` (agentmart/state.py:113) builds one and **returns it without touching state**.
It used to append to `state["a2a_log"]` directly. That was fine while hops ran in
sequence and became a bug the moment they did not, so it is pure now and callers
hand the envelopes back as a delta.

Lifecycle: `proposed → accepted → in_progress → completed | failed`.

## 3. The model client

`OpenRouterHermesClient` (agentmart/client.py:38) resolves settings in one order and shapes the request per
endpoint. Two things to notice.

**Endpoint detection.** `openai_native` is true when the base URL is
OpenAI's own. It matters because the two endpoints disagree: OpenAI wants
`max_completion_tokens`, rejects any temperature but its default on the gpt-5.6
family, and takes `reasoning_effort` as a top-level parameter. OpenRouter accepts
the older spelling of all three. `openai_reasoning_family` splits OpenAI's own
catalogue again, because gpt-4.x rejects `reasoning_effort` outright.

**The PERF line** at the end of `complete()`. Every call logs its own duration,
model, prompt/cached/completion/reasoning tokens and finish reason. This exists
because `httpx`'s log lines are emitted when response *headers* arrive, not when
the body is read — they make a slow call look fast and the time appear to vanish
afterwards. `cached_tok` is the prefix-cache hit; a column of zeros means the
shared prefix has drifted.

## 4. Intent routing

`INTENT_RULES` is an ordered list of `(intent, regex)`. First match wins.
Deterministic on purpose: the agents are the model-driven part, the routing is
not, so a scenario run is reproducible.

Read the order carefully — it encodes hard-won distinctions:

1. Explicit `draft order` requests → `purchase_intent`, ahead of any payment word
   trailing them.
2. Unambiguous checkout imperatives, with `checkout` excluded when followed by
   `step`/`process`/`flow`/`page` — that is a noun phrase, not an instruction to charge.
3. Status questions, including questions *about* a payment, which must never charge.
4. Weaker payment wording, only once a status reading is ruled out.
5. `buy` only when intentional: "wants to buy" is intent, "where to buy" is advice.

`strip_prohibitions` (agentmart/intents.py:115) runs **before** any rule. A remote agent states
its guardrails inline — "do not charge or capture payment" — and those clauses
name the exact capability they forbid. Without the strip, a prohibition routes
straight to the Payment Agent. That is not hypothetical: it once settled a
customer's unrelated unpaid order.

The fallback at the end of `classify_intent` returns `order_status` rather than
`product_advice` when the text names an order id, so an order question never
wakes Shopping and Pricing.

## 5. The shared, cacheable prefix

`SHARED_AGENT_SYSTEM` (agentmart/prompts.py:23) holds the catalog and is **identical for every worker
agent**. OpenAI reuses an identical leading span across calls, halving prefill
latency, but only if it comes first and is byte-identical.

That is why the per-agent role travels in the *user* turn rather than
the system message, and why the `a2a_task` — which carries a fresh uuid — is
nowhere near the front. Both would break the cache.

## 6. The worker agents

`make_agent_node` (agentmart/agents/base.py:18) is a factory. Each worker gets a role, a prompt builder, an
output key and a capability name, and returns a delta:

```python
return {
    "transcript": [transcript_entry(agent, result, envelope)],
    "a2a_log": [envelope, done],
    output_key: result,
}
```

The four workers are declared just below it. Read their `instruction` strings:
each asks for compact lines under a character budget, because **their reader is
another agent, not the customer**. Verbose intermediate answers are paid for
twice — once to generate, again when the next agent reads them.

Note what each one consumes:

| Agent | Reads |
| --- | --- |
| shopping | the task and the listing |
| pricing | `shopping_result` |
| inventory | `shopping_result`, `pricing_result` |
| fulfillment | `inventory_result` |

**The path is a pipeline, not a fan-out.** Running pricing, inventory and
fulfillment concurrently is about 8s faster and wrong: the two downstream agents
receive `"(agent not on this path)"` where their input belongs. It passed every
test when it was tried, because the Order Agent still saw all three at the join.
`test_scenarios.py -s pipeline-inputs` now reads the prompts themselves and fails
if a hand-off is empty.

## 7. The customer-facing hops

**`hermes_myshopper_node`** (agentmart_ecosystem.py:496) is the lab's own buying agent: it
classifies, builds the opening `proposed` envelope, resolves the SKU or order id,
and loads the order book when the intent needs it. When a *real* Hermes calls in
over A2A this node runs anyway — two buying agents in series. That is deliberate:
the hand-off is what the workshop demonstrates.

**`order_agent_node`** (agentmart_ecosystem.py:816) is the only hop that writes. On a
`purchase_intent` it calls `create_draft_order` **before** the model speaks, so
the order id in the answer is a real row, not a generated string. Its system
prompt (agentmart_ecosystem.py:732) forbids inventing an order id, tracking reference, amount or
date, and asks for compact structured facts — Hermes rewrites them into prose for
the chat, so framing here is wasted work.

**`payment_agent_node`** (agentmart_ecosystem.py:899) settles a **simulated** payment: it writes
rows through `checkout_and_pay` and contacts no processor. `sim_auth_*` references
are local.

## 7b. Batching the worker hops — optional

`batched_workers_node` (agentmart/agents/batched.py:76) runs every worker on the
intent's path in **one** model call, and `effective_path` (agentmart/graph.py:45) collapses the path when `batch_workers` is set.
`split_sections` (agentmart/agents/batched.py:56) parses the reply back into the
individual `*_result` keys, so the Order Agent receives exactly what it would
have.

Worth understanding why this is safe where concurrency was not. Parallel branches
each read a **stale state snapshot**, so Inventory never saw Pricing's ranking.
One batched call puts the whole chain in a **single context**, so the hand-off is
stronger, not weaker.

The transcript records one hop. Synthesising four entries from a single call would
make the replay lie about what ran.

Off by default: four agents negotiating over A2A becoming one prompt with four
headings is a real loss for a workshop about agent ecosystems. Measured
13.3s -> 8.4s on `product_advice`.

## 7c. The Shipping Agent — computed dates, explained by a model

`shipping.py` calculates dispatch and delivery dates from warehouse calendars, a
15:00 dispatch cut-off and per-warehouse holidays. No model is involved, so the same
inputs give the same answer and a test can assert on it.

`shipping_agent_node` (agentmart/agents/shipping.py:33) receives those dates and is told
never to compute, adjust or invent one — only to quote and explain them. Every other
prompt in this lab forbids inventing a delivery date; handing the model real dates is
the only way to hold that line.

`shipping_estimate` routes `shipping_agent → order_agent`, and its intent rule sits
ahead of the status rule: "when will it arrive" and "where is my order" want
different agents.

## 8. Building and running the graph

`INTENT_PATHS` (agentmart/intents.py:159) maps each intent to its agent sequence. `route_from_hermes` picks
the first hop; `_next_after` follows the path and falls off to `END`.
`build_graph` wires conditional edges from every node to every other, and the
routers decide.

`run_agentmart` (agentmart/graph.py:153) assembles the initial state — including
`classify_intent` and `load_product_listing` — invokes the graph, and passes the
result through `normalize_ordering` (agentmart/graph.py:131), which sorts the transcript and
A2A log into the declared path order. With a sequential pipeline they already
arrive in order, so it is a guard rather than a necessity.

---

## 9. The A2A front door — `a2a_server.py`

Without this file the lab's A2A never leaves the process and no outside agent can
call it.

**Discovery** — `build_agent_card` (a2a_server.py:262) advertises every AgentMart
capability as an A2A skill tagged with its owning agent, served at
`/.well-known/agent-card.json`.

**Transport** — `do_POST` accepts `SendMessage` and two pre-1.0
aliases, pulls the text out of the message parts, and returns a v1.0 `Task` whose
`artifacts[0]` carries the answer. A graph failure becomes `TASK_STATE_FAILED` —
a failed task, not a transport error.

**The cache.** `CACHEABLE_INTENTS` (a2a_server.py:75) — only `product_advice` and `browse_catalog` are
eligible. `purchase_intent` writes a draft and `checkout_payment` captures a
payment, so replaying either would report work that never happened; `order_status`
is read-only but goes stale the moment any order moves. After a mutating intent
the whole cache is dropped. Every replayed answer is marked `[cached]`, because a
demo that silently replays a stored answer is a demo that lies about what ran.

A repeat question returns in ~0.04s against ~17s cold.

---

## 10. Reading a run

```bash
# the chain, per hop
python agentmart_ecosystem.py --timing "Find me wireless earbuds under $120."

# the graph without the model
python test_scenarios.py

# routing and hand-offs on their own
python test_scenarios.py -s intent-routing
python test_scenarios.py -s pipeline-inputs
```

In the server log, `PERF agent=` lines give the per-hop breakdown and
`A2A task done` the total. `cached_tok` should be non-zero on every worker after
the first; zeros mean the shared prefix drifted.

For what a Telegram user actually waits, read `~/.hermes/logs/gateway.log`:
`response ready … time=` — `hermes -z` adds ~3s of process startup that the
gateway never pays.

---

## Where the interesting decisions live

| Question | Look at |
| --- | --- |
| Why is a prohibition not an instruction? | `strip_prohibitions` (agentmart/intents.py:115) |
| Why is the catalog in the system message? | `SHARED_AGENT_SYSTEM` (agentmart/prompts.py:23) |
| Why do nodes return deltas? | the reducers on `AgentMartState` (agentmart/state.py:49) |
| Why is `emit_envelope` pure? | `emit_envelope` (agentmart/state.py:113) |
| Why is the path sequential? | README, "The arrows are load-bearing" |
| Why is the model client endpoint-aware? | `OpenRouterHermesClient` (agentmart/client.py:38) |
| Why can't a checkout be cached? | `CACHEABLE_INTENTS` (a2a_server.py:75) |
