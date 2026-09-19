# AgentMart Agent Ecosystem

This workshop lab implements the Day 3 architecture from the root `README.md`:

```text
Customer -> Chat -> Hermes / MyShopper -> A2A -> AgentMart agent group
```

The sample uses LangGraph to model the agent workflow and the OpenAI Python SDK pointed at OpenRouter for model calls.

## Architecture

```mermaid
flowchart TD
    Customer[Customer]
    Channel[Telegram / WhatsApp / WebChat]
    Hermes[Hermes AI Agent<br/>MyShopper]
    Router{Intent router}

    subgraph AgentMart[AgentMart Agent Ecosystem]
        Shopping[Shopping Agent]
        Pricing[Pricing Agent]
        Inventory[Inventory Agent]
        Fulfillment[Fulfillment Agent]
        Order[Order Agent]
        Payment[Payment Agent<br/>simulated]
    end

    Customer --> Channel
    Channel --> Hermes
    Hermes -->|A2A envelope| Router
    Router -->|browse / advice| Shopping
    Router -->|purchase| Inventory
    Router -->|order status| Order
    Router -->|checkout| Order
    Shopping --> Pricing
    Pricing --> Inventory
    Inventory --> Fulfillment
    Fulfillment --> Order
    Order -->|checkout only| Payment
```

Hermes classifies the customer message, then only the agents that intent needs
are woken. A status question does not wake the whole ecosystem.

| Customer intent | Example message | Agent path |
| --- | --- | --- |
| `order_status` | "What is my order status?" | Order |
| `browse_catalog` | "List me the available products." | Shopping → Pricing → Inventory → Order |
| `product_advice` | "Find me wireless earbuds under $120." | Shopping → Pricing → Inventory → Fulfillment → Order |
| `purchase_intent` | "I want to buy this AM-EAR-1002." | Inventory → Fulfillment → Order |
| `checkout_payment` | "Checkout and pay for my order." | Order → Payment |

Routing is rule-based rather than model-driven, so a scenario run is
reproducible and the assertions in `test_scenarios.py` mean something. The
routing table lives in `INTENT_PATHS` (`agentmart_ecosystem.py`) and is mirrored
in `hermes_a2a_config.json` under `intent_routing`.

### The arrows are load-bearing

The path is a **pipeline, not a fan-out**. Each hop reads the previous one's
output:

| Agent | Reads |
| --- | --- |
| Shopping | the A2A task and the product listing |
| Pricing | `shopping_result` |
| Inventory | `shopping_result`, `pricing_result` |
| Fulfillment | `inventory_result` |
| Order | `shopping_result`, `pricing_result`, `inventory_result` |

Pricing, Inventory and Fulfillment look independent, and at one point this lab
ran them concurrently in a single LangGraph superstep. It was about 8s faster and
it was wrong: Inventory received `"(agent not on this path)"` where Pricing's
ranking belonged, and Fulfillment the same where Inventory's stock findings
belonged. Both reasoned without their input.

What makes this worth a section is how quietly it passed. The Order Agent still
received all three results at the join, so the customer-facing answer read
perfectly, no error was raised, and the whole scenario suite stayed green — the
checks asserted which agents ran and whether SKUs were real, never whether an
agent got what it asked for.

The fan-out has been reverted. `test_scenarios.py` now has a `pipeline-inputs`
check that reads the prompts themselves and fails if any hand-off is empty:

```bash
python test_scenarios.py -s pipeline-inputs
```

Against the concurrent version it reports 5/7, naming the two broken hand-offs.
If you ever reintroduce the fan-out — it is a reasonable exercise — make the
downstream agents genuinely standalone on `product_listing` first, and keep this
check honest by updating what each agent declares it reads.

## Files

| File | Purpose |
| --- | --- |
| `agentmart_ecosystem.py` | Entry point: the CLI, and a re-export of the `agentmart` package. |
| `agentmart/` | The implementation: state, client, intents, context, prompts, graph. |
| `agentmart/agents/` | One module per agent — workers, myshopper, shipping, order, payment, batched. |
| `hermes_a2a_config.json` | Hermes agent configuration for the A2A connection into AgentMart. |
| `seed_data.py` | Seeds the product listing from `data/products.json` into SQLite. |
| `catalog.py` | Query helpers the agents use to read the seeded listing. |
| `orders.py` | Read/write helpers over the order book: orders, payments, draft orders. |
| `test_scenarios.py` | End-to-end scenario suite for the Hermes + A2A flows. |
| `a2a_server.py` | Serves the ecosystem over A2A v1.0 so a real agent can call it. |
| `TESTING.md` | End-to-end test prompts for all three layers, plus A2A list/history. |
| `A2A_API.md` | A2A reference: discovery, JSON-RPC wire, the 19 capabilities, envelopes. |
| `WALKTHROUGH.md` | Guided read of the code: one request from Telegram to a grounded answer. |
| `SKILLS.md` | Creating a Hermes skill that routes a question to an A2A peer. |
| `shipping.py` | Deterministic dispatch/delivery dates: calendars, cut-off, holidays. |
| `console.html` | Web console: the graph, token flow, prompts and responses per hop. |
| `skills/agentmart/` | The shipping skill, ready to copy into `~/.hermes/skills/`. |
| `BENCHMARK.md` | Model comparison and the reasoning behind the chosen model/effort. |
| `SOUL.md` | Hermes persona plus the AgentMart routing rule; install to `~/.hermes/`. |
| `data/products.json` | Source product catalog: products, stock, warehouses, delivery options. |
| `data/orders.json` | Source order book: customers, orders, payment methods, payments. |
| `data/agentmart.db` | Generated SQLite database (git-ignored; created by `seed_data.py`). |
| `requirements.txt` | Python dependencies for the lab. |
| `.env.example` | Environment variable template for OpenRouter. |

## Setup

### macOS / Ubuntu

```bash
cd workshop
./setup.sh
cd agentmart_agent_ecosystem
source .venv/bin/activate
```

One script creates the virtual environment, installs dependencies, seeds the
product listing, and copies `.env.example` to `.env`. Useful flags:
`--force` (rebuild the venv), `--reset-db` (rebuild the seeded data),
`--no-seed` (skip seeding).

### Windows (PowerShell)

```powershell
cd D:\Projects\Building-Autonomous-AI-Agent\workshop\agentmart_agent_ecosystem
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python seed_data.py
```

Edit `.env` and set `OPENROUTER_API_KEY`.

## Installing Hermes

Hermes/MyShopper is **not a separate package** — there is nothing to `pip install`.
It is the personal buying agent built into this lab:

| Piece | Where it lives |
| --- | --- |
| Agent node | `hermes_myshopper_node()` in `agentmart_ecosystem.py` |
| Agent identity, channels, capabilities | `hermes_a2a_config.json` -> `hermes_agent` |
| A2A connection into AgentMart | `hermes_a2a_config.json` -> `a2a_connection` |
| Model client | `OpenRouterHermesClient` in `agentmart_ecosystem.py` |

So "installing Hermes" means installing the lab environment:

```bash
cd workshop
./setup.sh                  # venv + dependencies + seeded catalog + .env
cd agentmart_agent_ecosystem
source .venv/bin/activate
```

Confirm Hermes is wired up and can reach OpenRouter:

```bash
python agentmart_ecosystem.py --check-model
```

This prints the resolved model settings and makes one real call. Without a key it
reports `api_key : MISSING` and exits non-zero, so it is a safe first check.

## Configuring the Model (OpenRouter + Qwen3.7 Flash)

The lab defaults to **Qwen3.7 Flash** (`qwen/qwen3.7-flash`) through
OpenRouter's OpenAI-compatible API.

### 1. Get an API key

Create one at <https://openrouter.ai/keys> and put it in `.env`:

```bash
OPENROUTER_API_KEY=sk-or-v1-...
```

### 2. Set the model

`.env` already ships with these settings:

```text
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_MODEL=qwen/qwen3.7-flash
OPENROUTER_TEMPERATURE=0.2
OPENROUTER_MAX_TOKENS=6000
OPENROUTER_REASONING_EFFORT=medium
```

### 3. How settings resolve

Three layers, first match wins:

| Priority | Source | Use it for |
| --- | --- | --- |
| 1 | Environment / `.env` | Your key and per-machine overrides |
| 2 | `hermes_a2a_config.json` -> `hermes_agent.model` | The agent's declared default |
| 3 | Built-in defaults in `agentmart_ecosystem.py` | Last resort |

The config block declares the model as part of the agent's identity:

```json
"model": {
  "provider": "openrouter",
  "default_model": "qwen/qwen3.7-flash",
  "fallback_models": ["deepseek/deepseek-v4-flash-0731", "openai/gpt-oss-120b"],
  "temperature": 0.2,
  "max_tokens": 6000,
  "reasoning_effort": "medium"
}
```

`fallback_models` is passed to OpenRouter as its `models` array, so a request is
automatically retried down the list if the primary model is unavailable.

### 4. Choosing a model

Every model below was tested in **both** roles this lab needs, because passing one
does not imply passing the other:

- **Hermes tool loop** — does the agent actually *invoke* `a2a_call`, with 25 tool
  schemas and a large system prompt in context? Several models emit the call as
  plain text instead, which silently does nothing.
- **Lab grounding** — do the six agents answer only from the seeded catalog, with
  no empty replies and no invented SKUs?

| Slug | $/run | vs K3 | Hermes tools | Lab grounding |
| --- | --- | --- | --- | --- |
| `qwen/qwen3.7-flash` | $0.0014 | 105x cheaper | yes | yes — **lab default** |
| `deepseek/deepseek-v4-flash-0731` | $0.0019 | 77x cheaper | yes | yes — fallback, slower |
| `openai/gpt-oss-120b` | $0.0017 | 86x cheaper | yes | **invented `AM-EAR-1100`** |
| `qwen/qwen3-30b-a3b-instruct-2507` | $0.0021 | 70x cheaper | **no — printed JSON as text** | yes |
| `mistralai/mistral-nemo` | $0.0005 | 272x cheaper | **no — "tool not available"** | yes |
| `moonshotai/kimi-k3` | $0.1470 | — | yes | yes |

`$/run` is one six-agent `product_advice` request at this lab's measured token
profile (~19K prompt, ~6K completion).

Two lessons worth keeping:

- **A model that passes a one-shot tool probe can still fail a real agent loop.**
  `qwen3-30b-a3b-instruct` called the tool perfectly in isolation and emitted the
  same call as message text once Hermes' full prompt was in play.
- **Cheapest is not safe.** `mistral-nemo` is the cheapest tool-capable option and
  claimed the tool did not exist; `gpt-oss-120b` grounded fine in isolation and
  then invented a SKU in the full chain — the exact failure this lab teaches against.

Reasoning models (including the default) share `max_tokens` between reasoning and
the visible reply, so keep `OPENROUTER_MAX_TOKENS` generous and
`OPENROUTER_REASONING_EFFORT=medium` — otherwise agents return empty strings.
See `BENCHMARK.md` for the measurements behind both the model and the effort level.

### 5. Running the agents on OpenAI directly

Setting `OPENAI_API_KEY`, `OPENAI_BASE_URL` and `OPENAI_MODEL` points the six
AgentMart agents at OpenAI's own endpoint; they take precedence over the
`OPENROUTER_*` values. `gpt-5.6-luna` runs the six-agent chain in ~21s against
~76s on `qwen/qwen3.7-flash`, for roughly 8x the cost per run.

The client reshapes the request for that endpoint, because the gpt-5.6 family
rejects `max_tokens` (wants `max_completion_tokens`), rejects any temperature but
its default, and takes `reasoning_effort` as a top-level parameter rather than
OpenRouter's `reasoning` object. `--check-model` prints which endpoint is live.

**Hermes needs one extra step on this path.** Every Hermes turn carries tool
schemas, and `gpt-5.6-luna` rejects function tools together with
`reasoning_effort` — including when the parameter is omitted. It must be present
and set to `none`, a level Hermes' effort ladder will not emit on its own. A
`custom_providers` entry forces it onto the wire via `extra_body`, after which
Hermes runs against OpenAI directly with tools working. Section 8 of
`BENCHMARK.md` has the full parameter matrix and the exact config block.

Switch model for a single run without editing any file:

```bash
OPENROUTER_MODEL=moonshotai/kimi-k2.6 python agentmart_ecosystem.py --check-model
```

Because the client is OpenAI-compatible, any other OpenRouter slug
(`openai/...`, `anthropic/...`) works the same way.

## Hermes A2A Configuration

`hermes_a2a_config.json` makes the A2A handoff explicit:

- Hermes agent identity: `hermes_myshopper`
- Hermes role: represents the customer
- Supported channels: Telegram, WhatsApp, WebChat
- OpenRouter model settings: read from the `.env` variables
- A2A task endpoint: `agentmart://a2a/tasks`
- Heartbeat stream: `agentmart.a2a.heartbeats`
- Capability registry: `agentmart.a2a.capabilities`
- Target AgentMart agents: Shopping, Pricing, Inventory, Fulfillment, and Order

The LangGraph demo loads this file and embeds the connection metadata into the A2A envelope that Hermes sends to AgentMart.

## Seeded Product Listing

`seed_data.py` loads `data/products.json` into `data/agentmart.db` (SQLite,
standard library only) across four tables: `products`, `inventory`,
`warehouses`, and `fulfillment_options`.

```bash
python seed_data.py                # create/refresh the database
python seed_data.py --reset        # drop and rebuild every table
python seed_data.py --list         # print the seeded listing
python seed_data.py --list --category audio/earbuds --max-price 120
```

Seeding is idempotent: re-running rewrites every row from the JSON source, so
editing `data/products.json` and re-running is the intended way to change the
catalog.

The Shopping, Pricing, Inventory, and Fulfillment agents receive this listing in
their prompts, so they cite real SKUs, prices, stock levels, and delivery ETAs.
Narrow what the agents see with `--category` and `--max-price`:

```bash
python agentmart_ecosystem.py --dry-run --category audio/earbuds --max-price 120 \
  "Find me wireless earbuds under $120 with good battery life."
```

If the database has not been seeded, the run still completes and the agents are
told the catalog is unavailable.

## Run

Dry-run mode does not call the model. It is useful for checking the LangGraph/A2A flow:

```bash
python agentmart_ecosystem.py --dry-run "Find me wireless earbuds under $120 with good battery life."
```

Live mode calls OpenRouter:

```bash
python agentmart_ecosystem.py "Find me wireless earbuds under $120 with good battery life."
```

## Flow

1. Hermes/MyShopper receives the customer request from a chat channel.
2. Hermes classifies the intent and creates an A2A task envelope addressed to the
   AgentMart ecosystem. Every later hop reuses that envelope's `correlation_id`.
3. The router wakes only the agents that intent needs (see the table above),
   in order, each reading the previous hop's result.
4. Each agent hop appends its own envelope to `a2a_log`, moving through the
   `proposed -> accepted -> in_progress -> completed` lifecycle from Part 7.
5. The Order Agent answers from the order book, or creates a draft order.
6. On a checkout intent the Payment Agent settles it — simulated (see below).

## Running It From Telegram

A real session against the running system: Telegram -> Hermes/MyShopper
-> A2A over HTTP -> the AgentMart graph. The `a2a_call` badges under each reply are
Hermes invoking the peer. Every SKU, price and stock figure comes from the seeded
catalog, not from the model's own knowledge.

Prerequisites: `a2a_server.py` running, the peer registered in `~/.hermes/config.yaml`,
and the routing rule from `SOUL.md` installed. See `TESTING.md` for the full checklist.

### 1. Shortlist, then buy

![Telegram: AgentMart returns a shortlist of seeded earbuds, then processes a purchase](screenshot/01-telegram-shortlist-and-buy.png)

*"Ask agentmart to find me wireless earbuds under $120 with good battery life."*

Naming the peer is no longer required — with the routing rule from `SOUL.md`
installed, a bare *"Find me wireless earbuds under $120"* reaches AgentMart on its
own. Naming it is still the reliable choice for a live demo, because the rule is a
model instruction rather than a routing guarantee.
fires `a2a_list` then `a2a_call`, and AgentMart answers with seeded SKUs — Aurora
Buds Pro (`AM-EAR-1001`, $109, 32h battery) down to Tidal Mini Buds (`AM-EAR-1005`,
$39), each with real stock counts and delivery options.

This is the check that matters: a reply naming real-world brands means the A2A call
never happened and the model answered from memory.

### 2. Fulfillment catches a mismatch

![Telegram: Hermes notices the order contains a power bank and travel hub, not the earbuds](screenshot/02-telegram-fulfillment-mismatch.png)

Asked to proceed to fulfillment, Hermes reads back what the order book actually
contains — `AM-PWR-5001` Aurora PowerCell and `AM-PWR-5002` Kestrel Travel Hub —
notices that is **not** the `AM-EAR-1002` earbuds that were asked for, stops, and
asks whether to cancel or correct. It does not quietly proceed.

That behaviour is the `SOUL.md` rule working: relay what AgentMart returned, and
never paper over a discrepancy with something more plausible.

### 3. Order status

![Telegram: full order status showing payment, fulfillment, ETA and contents](screenshot/03-telegram-order-status.png)

`order_status` routes to the Order Agent alone — no shopping, pricing, inventory
or fulfillment agent is woken — and returns payment state, simulated auth ref,
locker pickup, ETA and line items straight from the order book.

### What capture 1 caught: prohibitions read as instructions

The purchase in capture 1 settled the customer's **pre-existing** order
`AM-ORD-20260915-0003` (power bank + travel hub, $93.00) instead of drafting a new
one for `AM-EAR-1002`. Captures 2 and 3 are the system noticing its own mistake.

The cause was in `classify_intent`, and it is worth understanding because it is a
general hazard when an LLM front-end drives a rule-based router.

Hermes asked correctly. What it sent was:

> The customer wants to buy SKU AM-EAR-1002 (Nimbus Air 2). Please create a draft
> order for quantity 1 ... **Do not charge or capture payment**; just confirm the
> draft order details and next **checkout** step.

Both guardrails — the phrase forbidding payment, and the words "checkout step" —
matched the `checkout_payment` rules. The router read a *prohibition* as a
*command*, routed to the Payment Agent, found no order id, fell back to
`find_payable_order()`, and settled whatever unpaid order the customer already had.

A remote agent states its safety constraints inline, and those constraints name the
exact capability they are forbidding. The lab's own test phrasings are short and
human ("I want to buy this AM-EAR-1002."), so nothing caught it. Across the real
session, **four of seven** requests routed to `checkout_payment`, including three
that said "Do not take any payment, refund, or fulfillment action."

Fixed in four parts:

1. `strip_prohibitions()` removes negated clauses (`do not ...`, `without ...`,
   `never ...`) up to their clause boundary before any rule runs.
2. An explicit `draft order` request outranks every payment word trailing it.
3. `checkout` followed by `step`/`process`/`flow`/`page` is a noun phrase, not an
   instruction to charge; `order summary` and `order_status_lookup` are status reads.
4. `buy` must be intentional — "wants to buy" is purchase intent, "where to buy" is
   advice. And a request naming an existing order id can never fall through to
   `product_advice`.

`test_scenarios.py` now asserts all 14 phrasings, human and agent-generated, so a
prohibition can never again be read as an instruction:

```bash
python test_scenarios.py -s intent-routing   # or just: python test_scenarios.py
```

## Batching the Worker Hops

`--batch-workers` runs every worker agent on the path in **one** model call
instead of one call each:

```bash
python agentmart_ecosystem.py --batch-workers --timing "Find me wireless earbuds under $120."
./.venv/bin/python a2a_server.py --batch-workers
```

| | Default | `--batch-workers` |
| --- | --- | --- |
| Hops | 6 | 3 |
| A2A envelopes | 11 | 5 |
| Worker segment | ~8.4s | ~3.3s |
| End to end | ~15s | ~9s |
| SKUs cited | identical | identical |

**Why this is safe where concurrency was not.** Running the workers in parallel
broke the chain: each branch read a stale snapshot, so Inventory never saw
Pricing's ranking. Batching has the opposite property — one model sees the whole
chain in a single context, so the hand-off is *stronger*, not weaker. The Order
Agent still receives all four results, parsed back out of the reply's sections;
`test_scenarios.py -s batched-workers` asserts exactly that.

**What it costs.** Four agents negotiating over A2A become one prompt wearing four
headings. The transcript records one hop, because fabricating four entries from a
single call would make the replay lie about what ran.

It is off by default for that reason. Turn it on to show the room the trade —
same answer, same SKUs, 40% less time, two thirds fewer envelopes — rather than to
hide it.

## Web Console

`a2a_server.py` serves a console at **http://127.0.0.1:9901/console** showing every
run that passed through it.

```bash
./.venv/bin/python a2a_server.py      # then open the URL
```

- **Flow strip** — the agent graph with the hops that actually ran lit up and timed,
  including the Shipping Agent.
- **Per-hop rows** — duration, model, and a token bar split four ways: prompt served
  from cache, fresh prompt, reasoning, visible completion. Cached prompt shows green,
  so a working prefix cache is visible at a glance.
- **Prompts and responses** — expand any hop for its system prompt, user prompt and
  reply, exactly as sent.
- **Run totals** — prompt, cached, completion and reasoning tokens.
- **↻ Update shipping date** — fires a `shipping_estimate` task and draws the
  `hermes_myshopper → shipping_agent → order_agent` path.
- **Order book** — every order as a card in a lifecycle column (awaiting payment →
  paid → packed → in transit → delivered, with cancelled at the end), showing total,
  amount paid, items, ETA and tracking. Read live on each poll, so a purchase or
  checkout moves a card while you watch, and the card flashes when its state changes.

It is responsive: the flow strip becomes a vertical stack on a phone rather than a
sideways scroll, type scales fluidly with the viewport, and `console.html` is read
per request — edit it and reload, no restart.

It reads a bounded in-memory buffer of the last 25 runs, so nothing is persisted and
restarting the server clears it. Dry runs are traced too, so the console can be
demonstrated without spending anything.

## Seeded Order Book

`data/orders.json` seeds three customers, five orders across every lifecycle
state, their payment methods, and their payment history. This is what makes
"what is my order status" and "checkout and pay" resolve against real rows.

```bash
python seed_data.py --list-orders    # print the seeded order book
```

| Customer | Channel | Orders |
| --- | --- | --- |
| `CUST-1001` Wei Ling Tan | Telegram | delivered, in_transit, **awaiting_payment** |
| `CUST-1002` Arun Prakash | WhatsApp | packed |
| `CUST-1003` Mei Chen | WebChat | cancelled (refunded) |

`CUST-1001` is the default customer, and its `awaiting_payment` order is what a
bare "checkout and pay" settles. Override with `--customer`.

### Payments are simulated

The Payment Agent writes `authorized` then `captured` rows into the local SQLite
database and generates a `sim_auth_...` reference. **No payment processor is ever
contacted, no card number is stored, and no money moves.** The agent is
instructed to say so in its reply.

## Scenario Suite

`test_scenarios.py` sends one customer message per scenario through the real
LangGraph workflow, then asserts on what actually happened: the intent chosen,
the agents woken, the A2A envelope chain, and the resulting rows in the order
book.

```bash
python test_scenarios.py                  # all scenarios, dry-run
python test_scenarios.py --list           # list scenario names
python test_scenarios.py -s buy-this      # run one
python test_scenarios.py --verbose        # show the A2A hops and agent replies
python test_scenarios.py --live           # call OpenRouter for real
```

| Scenario | Message | What it proves |
| --- | --- | --- |
| `order-status` | "What is my order status?" | Only the Order Agent wakes; the real order book is read |
| `order-status-specific` | "Where is my order AM-ORD-...?" | An order id scopes the lookup to that one order |
| `order-status-unknown` | "Where is my order AM-ORD-9999-9999?" | A missing order degrades gracefully, no crash |
| `list-products` | "List me the available products." | Browsing skips the Fulfillment Agent; real SKUs reach the prompts |
| `buy-this` | "I want to buy this AM-EAR-1002." | A real draft order is created and stops at `awaiting_payment` |
| `checkout-and-pay` | "Checkout and pay for my order." | The unpaid order is settled; a simulated receipt is written |
| `product-advice` | "Find me wireless earbuds under $120." | The original full recommendation pipeline still runs |
| `buy-then-checkout` | purchase, then settle that order | Two turns on one order id = two distinct A2A tasks |

Dry-run is the default, so the whole suite passes with **no OpenRouter key**:
everything asserted is the deterministic part of the system — routing, the A2A
envelope chain, and order/payment state. `--live` sends the same scenarios
through the model as well.

The suite re-seeds the order book before each scenario and again at the end, so
runs are isolated and the lab is left in its seeded state. Pass `--no-reseed` to
inspect what a run left behind.
