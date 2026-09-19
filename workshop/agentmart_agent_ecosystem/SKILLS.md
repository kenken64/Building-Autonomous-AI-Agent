# Creating a Hermes Skill that Routes Through A2A

How the shipping skill was built, and how to build another. The pattern is narrow on
purpose: **a skill here teaches Hermes where to ask, never what to answer.**

The lab ships one at `skills/agentmart/shipping/SKILL.md`.

---

## The rule that shapes everything

`SOUL.md` forbids Hermes inventing a product, price, stock figure or delivery date.
A skill that computed shipping dates in its own prose would contradict that rule and
hand the customer a fabricated commitment that reads exactly like a real one.

So the division is:

| | Owns |
| --- | --- |
| **Hermes skill** | recognising the question, calling the right peer, relaying the answer intact |
| **AgentMart agent** | the data, the arithmetic, the dates |

If you find yourself writing facts into a skill, the skill is the wrong place.

---

## Layout

Hermes reads skills from `~/.hermes/skills/<category>/<skill>/SKILL.md`, with a
category blurb beside it:

```
~/.hermes/skills/agentmart/
├── DESCRIPTION.md              category description
└── shipping/
    └── SKILL.md                the skill itself
```

`DESCRIPTION.md` is frontmatter only:

```markdown
---
description: Routing shipping, delivery-timing and order questions to the AgentMart agent ecosystem over A2A instead of answering them from memory.
---
```

`SKILL.md` carries its own frontmatter, then prose:

```markdown
---
name: agentmart-shipping
description: "Answer delivery-timing questions by asking AgentMart's Shipping Agent over A2A."
version: 1.0.0
author: AgentMart Workshop
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [A2A, Shipping, Delivery, AgentMart, Simulation]
    related_skills: []
---
```

Only `name` and `description` do real work: the description is what Hermes matches a
question against, so write it as the job, not the topic.

---

## What to put in the body

Four sections, in this order. The shipping skill is the worked example.

**1. What you do not know.** State the absence first.

> Delivery dates belong to AgentMart, not to you. **You have no shipping data of your
> own.** A plausible-sounding date is the failure mode this skill exists to prevent.

**2. When this applies — and when it does not.** The negative cases matter more.

> Not this skill: *where* an order is right now ("where is my order", "has it
> shipped") — that is a status lookup and AgentMart routes it to the Order Agent by
> itself.

Without that, the skill fires on every order question and the routing you already
built gets bypassed.

**3. The exact call.**

```
a2a_call(agent="agentmart", message="<the customer's timing question, with the order id if known>")
```

Say what to pass and why: the estimate is anchored to when the order was placed, so
the dates differ without the id.

**4. How to relay.** Constrain the rewrite.

> Quote the dates exactly. Do not convert, round, or re-derive them. "2-3 days" is
> not an acceptable rewrite of a delivery date. Say the estimate is simulated. If
> AgentMart returns no estimate, say so — do not fill the gap.

A closing "how to tell it worked" section helps too: the audit log grows, or the
answer was invented.

---

## Installing it

```bash
mkdir -p ~/.hermes/skills/agentmart/shipping
cp -r skills/agentmart/ ~/.hermes/skills/
hermes gateway restart
```

**The `skills` toolset must be enabled**, or Hermes never sees the skill — the index
is rendered into the system prompt from that toolset:

```bash
hermes tools enable skills --platform telegram
hermes tools enable skills --platform cli
```

This lab once ran with only the `a2a` toolset for speed; the skills index measured
**0 B** and no skill could fire. Check with:

```bash
hermes prompt-size | grep "skills index"     # should be non-zero
```

It costs roughly 10.6 KB of prompt — ~4.9 KB of tool schema plus the index.

---

## The other half: an agent to route to

A skill is only useful if the peer can answer. The shipping skill needed a matching
agent in AgentMart:

1. **A deterministic core** — `shipping.py` computes dispatch and delivery dates from
   warehouse calendars, a 15:00 cut-off and per-warehouse holidays. No model
   involved, so the same inputs give the same answer and a test can assert on it.
2. **An agent that only explains** — `shipping_agent_node` receives the calculated
   dates and is told: *"Never compute, adjust, or invent a date: quote the ones you
   are given."*
3. **An intent and a path** — `shipping_estimate` routes `shipping_agent → order_agent`.
   Its rule sits ahead of `order_status`, because "when will it arrive" and "where is
   my order" want different agents.
4. **A capability on the Agent Card** — added to `hermes_a2a_config.json`, so the
   skill's peer advertises `shipping_estimate` and a client can discover it.

Step 1 is the one people skip. Without it the agent has nothing to quote and invents
dates anyway, and the skill's careful wording achieves nothing.

---

## Checking it

```bash
# the chain, with real dates
python agentmart_ecosystem.py "When will my order AM-ORD-20260912-0002 arrive?"

# through Hermes: the audit log must grow
wc -l < ~/.hermes/a2a_audit.jsonl
hermes -z "When will my order AM-ORD-20260912-0002 arrive?"
wc -l < ~/.hermes/a2a_audit.jsonl
```

The tell is always the same. A date in the answer that is not in the calculated
estimates means it was invented, however reasonable it looks.
