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
```

The lab includes:

- a LangGraph workflow for the AgentMart agent group
- an OpenRouter-backed OpenAI-compatible model client
- a Hermes/MyShopper A2A sender node
- `hermes_a2a_config.json`, which defines the Hermes agent identity, A2A connection, heartbeat stream, capability registry, and target AgentMart agents
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

The lab is configured for **Kimi K3** (`moonshotai/kimi-k3`) via OpenRouter.
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

## Seeded Data

The lab ships a product catalog so the agents reason over real SKUs, prices,
stock levels, and delivery options instead of inventing them.

```bash
python seed_data.py                # create/refresh data/agentmart.db
python seed_data.py --reset        # drop and rebuild every table
python seed_data.py --list         # print the seeded product listing
python seed_data.py --list --category audio/earbuds --max-price 120
```

Edit `data/products.json` to change the catalog, then re-run `python seed_data.py`.
