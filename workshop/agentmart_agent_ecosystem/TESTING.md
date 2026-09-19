# Testing the MyShopper → A2A → AgentMart System

End-to-end test prompts for the whole stack, from the LangGraph graph alone up to
the real Hermes agent calling it over the A2A protocol from Telegram.

Three layers, each testable on its own. Test them in order — a failure at layer 1
will look like a protocol bug at layer 3.

```
  Layer 3   Telegram / CLI → Hermes (gpt-5.6-luna, OpenAI direct) ──┐
                                                │ a2a_call
  Layer 2   A2A v1.0 JSON-RPC over HTTP :9901 ──┤
                                                │
  Layer 1   LangGraph AgentMart ecosystem ──────┘
```

---

## Preflight

```bash
cd workshop/agentmart_agent_ecosystem

# 1. Data seeded? (12 products, 5 orders, 3 customers)
./.venv/bin/python seed_data.py --list-orders | head -5

# 2. Model reachable?
./.venv/bin/python agentmart_ecosystem.py --check-model
#    -> "Connection OK."

# 3. A2A server up? (start it if not — it does NOT auto-start)
curl -s http://127.0.0.1:9901/health
#    -> {"status": "ok", "dry_run": false}
```

```bash
# 4. Routing rule installed? Without it Hermes answers shopping questions
#    from its own knowledge and never calls AgentMart at all.
grep -q "route to AgentMart" ~/.hermes/SOUL.md && echo "routing rule present" \
  || echo "MISSING -- install it (see below)"
```

Start the server in its own terminal and leave it running:

```bash
./.venv/bin/python a2a_server.py
```

### Installing the routing rule

`SOUL.md` in this folder is Hermes' persona plus the AgentMart routing rule. It
is what makes a bare shopping question reach the ecosystem instead of being
answered from the model's own training data.

```bash
cp ~/.hermes/SOUL.md ~/.hermes/SOUL.md.bak      # keep your existing persona
cp SOUL.md ~/.hermes/SOUL.md
hermes gateway restart                          # SOUL.md is read at session start
```

The rule is topic-triggered, not an identity override: it fires on product,
price, stock, delivery, order, checkout and payment questions, and leaves every
other kind of request alone.

---

## Finding the bottleneck

Every model call logs its own duration, so the slowest hop is greppable rather
than guessed at:

```bash
# Server: one PERF line per agent, then the task total
grep "PERF agent=" ~/.../a2a_live.log
#  PERF agent=pricing_agent 7.1s prompt_tok=2975 completion_tok=1003 reasoning_tok=341 ...
grep "task done" ~/.../a2a_live.log
#  A2A task done: 6 hop(s) in 22.3s

# CLI: same lines, without running the server
./.venv/bin/python agentmart_ecosystem.py --timing "Find me wireless earbuds under $120."
```

Read `completion_tok` next to the duration: these agents are almost always slow
because they are *writing* a lot, not because the prompt is large.

**Do not time the bottleneck with `httpx` log lines.** They are emitted when
response headers arrive, not when the body has been read, so a slow call looks
fast and the time appears to vanish somewhere after it. The `PERF` lines wrap the
whole call.

**Do not tune against `hermes -z` either.** The CLI pays ~3s of process startup
per invocation that the gateway never pays. The truth for a Telegram user is in
`~/.hermes/logs/gateway.log`:

```bash
grep "response ready" ~/.hermes/logs/gateway.log | tail
#  response ready: platform=telegram ... time=32.3s api_calls=2 response=552
```

`api_calls=2` is Hermes' own two calls per turn — one to decide to call the peer,
one to compose the reply from what came back.

---

## Layer 1 — the graph alone

No network, no Hermes. Proves routing, the order book and the agent prompts.

```bash
# Whole suite, dry-run, no API key needed, ~2s
./.venv/bin/python test_scenarios.py

# One scenario, with the A2A hops and agent replies printed
./.venv/bin/python test_scenarios.py -s product-advice --verbose

# Routing only: 14 phrasings, human and agent-generated. Catches the class of bug
# where a request saying "do not capture payment" routes to the Payment Agent.
./.venv/bin/python test_scenarios.py -s intent-routing

# Each agent still receives the upstream result it reads
./.venv/bin/python test_scenarios.py -s pipeline-inputs

# Batching collapses the worker hops without starving the Order Agent
./.venv/bin/python test_scenarios.py -s batched-workers

# WALKTHROUGH.md's line references still point at their symbols
./.venv/bin/python test_scenarios.py -s doc-refs

# The same suite against the real model
./.venv/bin/python test_scenarios.py --live
```

**Pass:** `12/12 scenarios passed`.

### Per-intent prompts

Each wakes a different set of agents — that is the routing teaching point.

| Prompt | Intent | Agents woken |
| --- | --- | --- |
| `What is my order status?` | `order_status` | order |
| `Where is my order AM-ORD-20260912-0002?` | `order_status` | order (scoped to one order) |
| `Where is my order AM-ORD-9999-9999?` | `order_status` | order (reports "not found", must not crash) |
| `List me the available products.` | `browse_catalog` | shopping → pricing → inventory → order |
| `Find me wireless earbuds under $120 with good battery life.` | `product_advice` | shopping → pricing → inventory → fulfillment → order |
| `I want to buy this AM-EAR-1002.` | `purchase_intent` | inventory → fulfillment → order |
| `Checkout and pay for my order.` | `checkout_payment` | order → payment |

The arrows are load-bearing: each hop reads the previous one's output. Inventory
reads Pricing's ranking, Fulfillment reads Inventory's stock findings, and the
Order Agent reads all three.

Running Pricing, Inventory and Fulfillment concurrently was tried and reverted. It
saved about 8s, but both downstream agents then received
`"(agent not on this path)"` where their upstream input belonged. The Order Agent
still saw all three at the join, so the final answer looked right and this suite
still passed — the checks assert routing and grounding, not that each agent got
its input. If you reintroduce the fan-out, assert on the agent prompts too.

```bash
./.venv/bin/python agentmart_ecosystem.py "Find me wireless earbuds under \$120 with good battery life."
```

Prints the full state as JSON: `transcript`, `a2a_log`, `intent`, `draft_order`.

**Watch for:** every transcript entry must have a non-empty `message`. Empty
replies mean the token budget is being eaten by reasoning — see Troubleshooting.

---

## Performance reference

Measured over the A2A wire, gpt-5.6-luna on OpenAI direct. Use these as the shape,
not as promises: per-hop latency swings run to run.

| Intent | Default | `--batch-workers` | Repeat |
| --- | ---: | ---: | ---: |
| `order_status` | 5.4s | 4.9s | 3.8-4.2s |
| `browse_catalog` | 10.3s | 6.6s | **0.00s** |
| `product_advice` | 13.3s | 8.4s | **0.00s** |
| `purchase_intent` | 8.9s | 5.6s | 6.0-8.5s |
| `checkout_payment` | 5.7s | 5.6s | 6.1-6.5s |

Three things to read off it:

- **Batching only helps where workers run.** `checkout_payment` is unchanged
  because no worker agent is on its path, and `order_status` barely moves because
  only the Order Agent runs. The three worker-heavy intents gain ~1.6x.
- **Only the two read-only intents repeat instantly.** `purchase_intent` and
  `checkout_payment` write to the order book and `order_status` goes stale the
  moment one does, so all three re-run every time by design.
- **The server itself is not in the picture.** Its own round trip is ~0.4ms
  against 5,000-13,000ms of model time.

---

## Layer 2 — the A2A wire

`A2A_API.md` is the reference for this layer: discovery, the JSON-RPC methods
and error codes, which agent owns which of the 16 capabilities, and the envelope
schema. What follows is how to exercise it.

Proves the protocol without involving Hermes. Useful when layer 1 passes but
layer 3 fails.

```bash
# Agent Card — 16 skills across the six agents
curl -s http://127.0.0.1:9901/.well-known/agent-card.json | python3 -m json.tool | head -30

# A task, in exactly the shape Hermes sends
curl -s -X POST http://127.0.0.1:9901/ \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":"t1","method":"SendMessage",
       "params":{"message":{"role":"ROLE_USER","contextId":"ctx-manual-01",
                 "parts":[{"text":"what is my order status"}]}}}' \
  | python3 -m json.tool
```

**Pass:** `status.state` is `TASK_STATE_COMPLETED`, and `artifacts[0].parts[0].text`
holds the answer plus the hop trailer.

Error cases worth checking:

```bash
# Unknown method -> -32601
curl -s -X POST http://127.0.0.1:9901/ -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"Nope","params":{}}'

# No text part -> -32602
curl -s -X POST http://127.0.0.1:9901/ -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"SendMessage","params":{"message":{"parts":[]}}}'
```

---

## Layer 3 — Hermes calling AgentMart

The real agent, from Telegram (**@MyShopperISSBot**) or a CLI chat.

### Discovery

> Discover the A2A agent at http://127.0.0.1:9901 and tell me what it can do.

**Pass:** Hermes reports "AgentMart Agent Ecosystem", JSONRPC v1.0, 16 skills.

### Does it route on its own?

With the routing rule installed, a bare request should reach AgentMart with no
mention of the peer:

> Find me wireless earbuds under $120 with good battery life.

**Pass:** the reply names seeded SKUs (`AM-EAR-1001`, `AM-EAR-1002`), and
`~/.hermes/a2a_audit.jsonl` gains a line.

**Fail:** the reply names real-world brands — EarFun, Anker, Jabra, Nothing —
and the audit log does not move. That is Hermes answering from training data,
which means the routing rule is missing or the gateway was not restarted after
installing it. Always check the audit log, not just the reply: a confident
answer about real products is exactly what this failure looks like.

### Delegated shopping (explicit)

Naming the peer works with or without the routing rule:

> Ask the agentmart agent to find me wireless earbuds under $120 with good battery life.

> Ask agentmart what my order status is.

> Ask agentmart to list the available products.

> Tell agentmart I want to buy AM-EAR-1002.

> Ask agentmart to checkout and pay for my order.

**Pass:** the reply cites real seeded data — SKUs like `AM-EAR-1001`, the $109.00
price, 32h battery, stock counts, delivery options — and ends with the trailer:

```
---
[intent: product_advice]
[A2A hops: hermes_myshopper -> shopping_agent -> pricing_agent -> ...]
```

Invented products or prices mean the catalog was not reached.

### Capability fan-out

> Use a2a_orchestrate to ask every agent advertising order_status_lookup for my order status.

Only `agentmart` advertises it, so exactly one peer should answer.

---

## A2A introspection — list and history

### From chat (Telegram or CLI)

> List my a2a peers.

**Pass:** `agentmart` at `http://127.0.0.1:9901`, auth none, 16 capabilities,
plus the persisted conversations and a metrics line.

> Show me the a2a history for ctx-dfc1682a50f3406a

Replace the id with one from the list. **Pass:** the original request and the
full AgentMart reply come back.

> What A2A conversations do you have saved?

### From the shell

```bash
# Peers, conversations, metrics
cd ~/.hermes/hermes-agent && ./venv/bin/python -c "
import sys; sys.path.insert(0,'.')
from plugins.platforms.a2a import tools
print(tools.a2a_list({}))"

# Replay one conversation
cd ~/.hermes/hermes-agent && ./venv/bin/python -c "
import sys; sys.path.insert(0,'.')
from plugins.platforms.a2a import tools
print(tools.a2a_history({'context_id':'ctx-dfc1682a50f3406a'}))"
```

> **Metrics read `0 in / 0 out`?** They are per-process counters, so a fresh
> process always shows zeros. The audit file below is the durable record.

### The logs on disk

```bash
# Audit trail — one line per exchange
cat ~/.hermes/a2a_audit.jsonl | python3 -c "
import sys, json, datetime
for line in sys.stdin:
    r = json.loads(line)
    ts = datetime.datetime.fromtimestamp(r['ts']).strftime('%H:%M:%S')
    print(f\"{ts}  {r['direction']:9s} {r['peer']:10s} {r['summary'][:60]}\")"

# Full conversation text, one file per context
ls -lt ~/.hermes/a2a_conversations/
cat ~/.hermes/a2a_conversations/<context-id>.jsonl | python3 -m json.tool

# Gateway side (Telegram connect, inbound A2A platform)
hermes logs gateway -n 40
hermes logs gateway -f          # follow live
```

There is **no** `hermes console` command for A2A — the console has no `a2a`
verbs. The files above and the agent tools are the whole surface.

> **Two different things are called "the A2A log".** Hermes' real protocol audit
> lives in `~/.hermes/`. The workshop's *simulated* envelope chain — correlation
> ids, `proposed → accepted → completed` lifecycle — lives in the graph state
> under `a2a_log`, visible in the CLI's JSON dump. They are separate records of
> the same conversation at different layers.

---

## Full-system smoke test

Ten minutes, top to bottom:

```bash
cd workshop/agentmart_agent_ecosystem
./.venv/bin/python seed_data.py --reset           # 1. clean data
./.venv/bin/python test_scenarios.py              # 2. graph: 8/8
./.venv/bin/python agentmart_ecosystem.py --check-model   # 3. model
./.venv/bin/python a2a_server.py &                # 4. serve
curl -s http://127.0.0.1:9901/health              # 5. wire
hermes gateway status                             # 6. telegram connected
```

Then, on Telegram: *"Ask agentmart to find me wireless earbuds under $120."*
Then: *"List my a2a peers."* Then: *"Show the a2a history for that conversation."*

Expect roughly 30–60s for a six-agent request. Model latency varies run to run.

---

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| Hermes: "unknown agent 'agentmart'" | Peer not registered | Check `a2a_agents` in `~/.hermes/config.yaml` |
| Hermes: "could not reach agentmart" | Server not running | `./.venv/bin/python a2a_server.py` |
| Hermes: "timed out" | Chain slower than the peer timeout | Raise `a2a_agents.agentmart.timeout` (currently 900s) |
| Agent replies are empty strings | Reasoning ate the token budget | `OPENROUTER_MAX_TOKENS=6000`, `OPENROUTER_REASONING_EFFORT=medium` |
| Reply invents products/prices | Catalog not seeded | `./.venv/bin/python seed_data.py --reset` |
| `CatalogNotSeededError` | No `data/agentmart.db` | `./.venv/bin/python seed_data.py` |
| Hermes has no `a2a_*` tools | Toolset off for that platform | `hermes tools enable a2a --platform telegram` then `hermes gateway restart` |
| Telegram silent | Gateway down or user not allowed | `hermes gateway status`; check `TELEGRAM_ALLOWED_USERS` in `~/.hermes/.env` |
| Six-agent run takes minutes | Reasoning effort unset | Confirm `OPENROUTER_REASONING_EFFORT=medium` in `.env` |
| Reply names real brands, not seeded SKUs | Routing rule missing | `cp SOUL.md ~/.hermes/SOUL.md && hermes gateway restart` |
| `HTTP 402: requires more credits` | OpenRouter key limit reached | Top up or raise the key cap at openrouter.ai/settings/credits |
