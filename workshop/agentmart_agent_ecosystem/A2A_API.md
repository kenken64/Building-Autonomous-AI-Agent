# AgentMart A2A API Reference

What AgentMart exposes over A2A, which agent owns which capability, and how a
caller discovers all of it at runtime.

There are **two layers called A2A** in this lab. They are different things and it
is worth keeping them apart:

| Layer | What it is | Where it lives |
| --- | --- | --- |
| **Protocol A2A** | The real [A2A v1.0](https://a2a-protocol.org) wire: an Agent Card over HTTP and JSON-RPC 2.0. This is what Hermes actually speaks. | `a2a_server.py` |
| **Lab envelope A2A** | The teaching layer: a correlated envelope per agent hop, with a `proposed → completed` lifecycle. It never leaves the process. | `agentmart_ecosystem.py` |

A caller only ever sees the protocol layer. The envelope layer is what the
workshop is *about*.

---

## 1. Discovery

Everything below is discoverable at runtime — no client needs this document.

```bash
curl -s http://127.0.0.1:9901/.well-known/agent-card.json | python3 -m json.tool
```

The card advertises the name, description, the JSON-RPC interface, and one
**skill per capability**, each tagged with the agent that owns it. The legacy
`/.well-known/agent.json` path answers too, for pre-1.0 clients.

From Hermes, the same card rendered for a human:

```
Ask Hermes: "Discover the A2A agent at http://127.0.0.1:9901"
```

or directly: `a2a_discover(url="http://127.0.0.1:9901")`.

---

## 2. Transport

| | |
| --- | --- |
| Endpoint | `POST /` |
| Protocol | JSON-RPC 2.0, A2A v1.0 |
| Methods | `SendMessage` (canonical), `message/send`, `tasks/send` (pre-1.0 aliases) |
| Health | `GET /health` |
| Auth | none when bound to `127.0.0.1`; bearer token via `AGENTMART_A2A_TOKEN` |
| Streaming | **not implemented** — `SendStreamingMessage` is unsupported, and Hermes' client does not use it |

### Request

```json
{
  "jsonrpc": "2.0", "id": "task-1", "method": "SendMessage",
  "params": {"message": {
    "role": "ROLE_USER",
    "contextId": "ctx-abc123",
    "parts": [{"text": "Find me wireless earbuds under $120."}]
  }}
}
```

`contextId` is optional and carries a multi-turn conversation. Parts are
member-presence discriminated (v1.0), but `kind`/`type` from older peers parse too.

### Response

```json
{"jsonrpc": "2.0", "id": "task-1", "result": {"task": {
  "id": "task-1",
  "contextId": "ctx-abc123",
  "status": {"state": "TASK_STATE_COMPLETED", "timestamp": "...", "message": {...}},
  "artifacts": [{"artifactId": "...", "parts": [{"text": "...", "mediaType": "text/plain"}]}]
}}}
```

The answer is in `artifacts[0].parts[0].text`, with `status.message` mirroring it.
A graph failure returns `TASK_STATE_FAILED` — a failed task, not a transport error.

### Errors

| Code | Meaning |
| --- | --- |
| `-32700` | body is not valid JSON |
| `-32600` | request is not a JSON object |
| `-32601` | unknown method |
| `-32602` | params not an object, or no text part in the message |
| `-32603` | internal error |
| `-32050` | unauthorized (a token is configured and was missing or wrong) |

---

## 2b. Server behaviour a caller will notice

**Caching.** Repeats of a `product_advice` or `browse_catalog` question return in
~0.04s with `\n[cached]` appended to the text. Nothing that writes is ever
cached: `purchase_intent` drafts an order, `checkout_payment` captures a
simulated payment, and `order_status` goes stale the moment either runs. A
mutating call clears the cache. Disable with `--no-cache`.

**Batching.** With `--batch-workers` the server runs every worker agent in one
model call. The answer and the SKUs are the same; the hop trailer shows
`batched_workers` in place of the individual worker hops, and roughly 1.6x less
time on worker-heavy intents.

Neither changes the wire format. A caller sees an ordinary `Task` either way.

## 3. Capability map

Nineteen capabilities across seven agents. These are the `skills[].id` values on the
Agent Card, and the same names appear in `hermes_a2a_config.json`.

| Agent | Capability | Answers |
| --- | --- | --- |
| **shopping** | `product_search` | Which SKUs in the catalog match the request? |
| | `candidate_shortlist` | Which three are worth considering, and why? |
| **pricing** | `price_check` | What is the current price against list price? |
| | `budget_fit` | Does it fit the customer's stated budget? |
| | `value_ranking` | Which is the best value, and on what basis? |
| **inventory** | `stock_check` | How many units, at which warehouse? |
| | `availability_risk` | Will thin stock or a restock delay this? |
| **fulfillment** | `delivery_options` | Which delivery methods, at what ETA and cost? |
| | `pickup_options` | Is locker or store pickup available? |
| **shipping** | `shipping_estimate` | When does it dispatch and arrive? |
| | `dispatch_date_simulation` | Which working day does it leave the warehouse? |
| | `delivery_window_check` | Can it arrive by a given date? |
| **order** | `order_summary` | What is in this order, and what does it total? |
| | `order_status_lookup` | Where is it now — paid, packed, in transit, delivered? |
| | `draft_order_create` | Create an unpaid draft for a chosen SKU. |
| | `checkout_next_step` | What must the customer do before this can be paid? |
| **payment** | `payment_authorize` | Authorize a **simulated** payment. |
| | `payment_capture` | Capture it and mark the order paid. |
| | `refund_status` | What has been refunded? |

> Payments are simulated. The Payment Agent writes rows to the local SQLite
> database and contacts no payment processor. `sim_auth_*` references are local.

---

## 4. Intent routing

A caller sends plain text, not a capability name. The router classifies it and
wakes only the agents that intent needs — a status question must not wake the
whole ecosystem.

| Intent | Example | Agent path |
| --- | --- | --- |
| `order_status` | "What is my order status?" | order |
| `shipping_estimate` | "When will my order arrive?" | shipping → order |
| `browse_catalog` | "List me the available products." | shopping → pricing → inventory → order |
| `product_advice` | "Find me earbuds under $120." | shopping → pricing → inventory → fulfillment → order |
| `purchase_intent` | "I want to buy AM-EAR-1002." | inventory → fulfillment → order |
| `checkout_payment` | "Checkout and pay for my order." | order → payment |

The path is a pipeline: each hop reads the previous one's output. See
"The arrows are load-bearing" in `README.md`.

Routing is rule-based (`classify_intent`), so runs are reproducible. It strips
prohibitions before matching, because a remote agent states its guardrails inline
— "do not capture payment" once routed straight to the Payment Agent.

---

## 5. The envelope layer

Inside the graph every hop appends an envelope to `a2a_log`:

```json
{
  "task_id": "uuid",
  "correlation_id": "uuid",     // identical across every hop of one request
  "sender": "hermes_myshopper",
  "recipient": "pricing_agent",
  "intent": "price_check",
  "payload": {...},
  "state": "accepted",
  "protocol": "agentmart.a2a.v1",
  "created_at": "ISO-8601"
}
```

Lifecycle: `proposed → accepted → in_progress → completed | failed`. The opening
hop is `proposed`; each agent emits `accepted` on entry and `completed` on exit.

This log is returned in the CLI's JSON dump and asserted by `test_scenarios.py`
(one correlation id across all hops, valid lifecycle states, `agentmart.a2a.v1`
throughout).

---

## 6. Calling it from Hermes

With the `a2a` toolset enabled, Hermes has five client tools:

| Tool | Purpose |
| --- | --- |
| `a2a_discover(url)` | Fetch and summarize a peer's Agent Card. Takes a **URL**, not a peer name. |
| `a2a_call(agent, message, context_id?)` | Send a task. Takes a **configured peer name** or a URL. |
| `a2a_list()` | Configured peers, persisted conversations, metrics. |
| `a2a_history(context_id)` | Replay a stored conversation. |
| `a2a_orchestrate(capability, message, mode?)` | Fan out to every peer advertising a capability. |

The peer is registered in `~/.hermes/config.yaml`:

```yaml
a2a_agents:
  agentmart:
    url: "http://127.0.0.1:9901"
    timeout: 900
    capabilities: [product_search, price_check, stock_check, ...]
```

Hermes' own exchanges are audited to `~/.hermes/a2a_audit.jsonl`, one line per
call. That file is the reliable evidence that a call actually happened — a reply
that reads convincingly but cites unknown brands means the model answered from
memory and never called the peer.

---

## 7. Worked examples

```bash
# Discovery
curl -s http://127.0.0.1:9901/.well-known/agent-card.json | python3 -m json.tool

# A task
curl -s -X POST http://127.0.0.1:9901/ -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":"t1","method":"SendMessage",
       "params":{"message":{"role":"ROLE_USER",
                 "parts":[{"text":"what is my order status"}]}}}' \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['result']['task']['artifacts'][0]['parts'][0]['text'])"

# Multi-turn: reuse contextId
#   ...,"message":{"role":"ROLE_USER","contextId":"ctx-demo-1","parts":[...]}

# With a bearer token
AGENTMART_A2A_TOKEN=secret ./.venv/bin/python a2a_server.py
curl -s -X POST http://127.0.0.1:9901/ -H 'Authorization: Bearer secret' ...
```

Interop: the card and wire format follow A2A v1.0, so any compliant client —
another Hermes, LangChain, CrewAI, Google ADK, the official `a2a-sdk` — can
discover and call this ecosystem without knowing anything in this file.
