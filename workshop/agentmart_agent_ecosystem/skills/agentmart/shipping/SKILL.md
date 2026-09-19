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

# AgentMart Shipping — timing questions over A2A

Delivery dates belong to AgentMart, not to you. Its Shipping Agent calculates
dispatch and delivery dates from warehouse calendars, cut-off times and per-warehouse
holidays; you relay them.

**You have no shipping data of your own.** A plausible-sounding date is the failure
mode this skill exists to prevent: it reads as a real commitment to the customer and
is wrong.

## When this applies

Any question about *when* something ships, arrives, or can arrive:

- "When will my order arrive?"
- "How long is delivery to Johor?"
- "Can I have it by Friday?"
- "What's the ETA on AM-ORD-20260912-0002?"
- "Which delivery option is fastest?"

Not this skill: *where* an order is right now ("where is my order", "has it
shipped") — that is a status lookup and AgentMart routes it to the Order Agent by
itself.

## How to answer

Call the peer and relay what comes back:

```
a2a_call(agent="agentmart", message="<the customer's timing question, with the order id if known>")
```

Pass the order id when the customer gave one — the estimate is anchored to when that
order was placed, so the dates differ without it.

Then:

- **Quote the dates exactly.** Do not convert, round, or re-derive them. "2-3 days"
  is not an acceptable rewrite of a delivery date.
- **Say the estimate is simulated.** It is a workshop simulator; no carrier is
  contacted.
- **Keep every option AgentMart returned**, with its cost and whether it is tracked.
  The cheapest and the fastest are rarely the same line.
- **If AgentMart returns no estimate, say so.** Do not fill the gap.

## What drives the dates

Useful for explaining an answer, not for computing one:

| Input | Effect |
| --- | --- |
| Order placed after 15:00 | dispatch moves to the next working day |
| Warehouse calendar | SG-CENTRAL closes Sunday; MY-JB and US-WEST close Saturday and Sunday |
| Per-warehouse holidays | skipped when counting working days |
| Method `eta_days` | working days added after dispatch |
| `locker_pickup`, `same_day_courier` | no tracking number |

## Checking it worked

`~/.hermes/a2a_audit.jsonl` gains a line per call. If it did not grow, the answer
came from memory and the dates are fabricated regardless of how reasonable they look.
