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

```powershell
cd D:\Projects\Building-Autonomous-AI-Agent\workshop\agentmart_agent_ecosystem
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Set `OPENROUTER_API_KEY` in `.env`, then run:

```powershell
python agentmart_ecosystem.py "Find me wireless earbuds under $120 with good battery life."
```

To verify the workflow without calling OpenRouter:

```powershell
python agentmart_ecosystem.py --dry-run "Find me wireless earbuds under $120 with good battery life."
```
