# Workshop

This folder contains hands-on labs for the **Building Autonomous AI Agents** workshop.

## Labs

| Lab | Focus | Entry point |
| --- | --- | --- |
| AgentMart Agent Ecosystem | Build the Day 3 MyShopper -> A2A -> AgentMart workflow with LangGraph and OpenRouter. | `agentmart_agent_ecosystem/README.md` |

## AgentMart Agent Ecosystem

The AgentMart lab implements the architecture from the root `README.md`:

```text
Customer
   |
Telegram / WhatsApp / WebChat
   |
   v
Hermes / MyShopper
   |
   | A2A
   v
AgentMart Agent Ecosystem
   |
   +-- Shopping Agent
   +-- Pricing Agent
   +-- Inventory Agent
   +-- Fulfillment Agent
   +-- Order Agent
   +-- Payment Agent (simulated)
```

The lab includes:

- a LangGraph workflow for the AgentMart agent group
- an OpenRouter-backed OpenAI-compatible model client
- a Hermes/MyShopper A2A sender node, with a correlated envelope per agent hop
- intent routing, so a status question does not wake the whole ecosystem
- a seeded order book and a simulated Payment Agent
- `hermes_a2a_config.json`, which defines the Hermes agent identity, A2A connection, heartbeat stream, capability registry, intent routing, and target AgentMart agents
- a scenario suite covering the end-to-end customer flows
- dry-run mode for testing the workflow without an API key

## Quick Start

### macOS / Ubuntu

```bash
cd workshop
./setup.sh
cd agentmart_agent_ecosystem
source .venv/bin/activate
```

`setup.sh` finds a Python 3.10+ interpreter, creates the lab virtual environment,
installs `requirements.txt`, seeds the product listing into SQLite, and copies
`.env.example` to `.env`.

| Flag | Effect |
| --- | --- |
| `--force` | Recreate the virtual environment from scratch |
| `--reset-db` | Drop and rebuild the seeded product listing |
| `--no-seed` | Skip data seeding |
| `--help` | Show usage |

### Windows (PowerShell)

```powershell
cd D:\Projects\Building-Autonomous-AI-Agent\workshop\agentmart_agent_ecosystem
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python seed_data.py
```

## Hermes and the Model

Hermes/MyShopper is the personal buying agent built into the lab — there is no
separate package to install. `setup.sh` installs it along with the lab.

The lab is configured for **Qwen3.7 Flash** (`qwen/qwen3.7-flash`) via OpenRouter,
chosen because it runs the whole six-agent chain for about 1/100th the cost of
Kimi K3 with the same grounded answers.
Set your key in `.env` (`OPENROUTER_API_KEY`), then verify the connection:

```bash
python agentmart_ecosystem.py --check-model
```

Model settings resolve from `.env` first, then `hermes_a2a_config.json`, then
built-in defaults. See the lab README for the full breakdown and the list of
Kimi slugs.

## Run

Set `OPENROUTER_API_KEY` in `.env`, then run:

```bash
python agentmart_ecosystem.py "Find me wireless earbuds under $120 with good battery life."
```

To verify the workflow without calling OpenRouter:

```bash
python agentmart_ecosystem.py --dry-run "Find me wireless earbuds under $120 with good battery life."
```

## Scenario Suite

`test_scenarios.py` drives the customer flows end to end and asserts on the
intent chosen, the agents woken, the A2A envelope chain, and the order book:

```bash
python test_scenarios.py              # all scenarios, dry-run, no API key needed
python test_scenarios.py --list       # list scenario names
python test_scenarios.py --verbose    # show the A2A hops and agent replies
python test_scenarios.py --live       # call OpenRouter for real
```

Covers: "what is my order status", "list me the available products",
"I want to buy this AM-EAR-1002", "checkout and pay", the original
recommendation pipeline, and a chained buy-then-checkout.

Payments are simulated: the Payment Agent writes rows to the local SQLite
database and contacts no payment processor.

## Seeded Data

The lab ships a product catalog so the agents reason over real SKUs, prices,
stock levels, and delivery options instead of inventing them.

```bash
python seed_data.py                # create/refresh data/agentmart.db
python seed_data.py --reset        # drop and rebuild every table
python seed_data.py --list         # print the seeded product listing
python seed_data.py --list --category audio/earbuds --max-price 120
```

`seed_data.py` also seeds the order book from `data/orders.json`: three
customers, five orders across every lifecycle state, and their payment history.

```bash
python seed_data.py --list-orders  # print the seeded order book
```

Edit `data/products.json` or `data/orders.json` to change the seeded data, then
re-run `python seed_data.py`.
