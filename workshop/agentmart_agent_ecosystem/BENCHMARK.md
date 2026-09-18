# Model Benchmark and Decision

Why this lab runs on `qwen/qwen3.7-flash` at `reasoning_effort: medium`, for both
Hermes/MyShopper and the AgentMart agents.

Measured 2026-09-18 against OpenRouter, on this lab's real prompts and the live
Hermes agent loop. Pricing from the OpenRouter `/models` API the same day.

---

## Decision

| | |
| --- | --- |
| **Model** | `qwen/qwen3.7-flash` |
| **Reasoning effort** | `medium` |
| **Applies to** | Hermes/MyShopper **and** all six AgentMart agents |
| **Fallbacks** | `deepseek/deepseek-v4-flash-0731`, then `openai/gpt-oss-120b` |
| **Replaces** | `moonshotai/kimi-k3` |
| **Cost change** | ~$0.147 -> ~$0.0014 per six-agent run (**~105x cheaper**) |

Config lives in three places, resolving env first: `.env`
(`OPENROUTER_MODEL`, `OPENROUTER_REASONING_EFFORT`), then
`hermes_a2a_config.json` -> `hermes_agent.model`, then the built-in defaults.
Hermes itself reads `~/.hermes/config.yaml` (`model.default`,
`agent.reasoning_effort`).

---

## 1. Why Kimi K3 had to go

K3 is $3.00/M input and $15.00/M output. This lab's `product_advice` request is
roughly 19K prompt and 6K completion tokens across six agents:

```
19,000 x $3.00/M  +  6,000 x $15.00/M  =  $0.147 per run
```

At that rate $2 of credit buys about **thirteen** runs. For a workshop where every
attendee runs the chain repeatedly, that is the wrong economics — and it is exactly
how the original $2 limit was exhausted mid-session.

## 2. Cost model

Same 19K/6K profile, tool-capable models with >=100K context:

| Model | in $/M | out $/M | Context | $/run | vs K3 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `mistralai/mistral-nemo` | 0.019 | 0.030 | 131K | 0.0005 | 272x |
| `qwen/qwen3.7-flash` | 0.030 | 0.130 | 1M | **0.0014** | **105x** |
| `openai/gpt-oss-120b` | 0.037 | 0.170 | 131K | 0.0017 | 86x |
| `deepseek/deepseek-v4-flash-0731` | 0.060 | 0.120 | 1.31M | 0.0019 | 77x |
| `qwen/qwen3-30b-a3b-instruct-2507` | 0.048 | 0.193 | 262K | 0.0021 | 70x |
| `moonshotai/kimi-k3` | 3.000 | 15.000 | 1M | 0.1470 | — |

Cost alone would have picked `mistral-nemo`. It was rejected — see below.

## 3. The two tests that actually decide it

A model must pass **both**. Passing one says nothing about the other.

**Hermes tool loop** — with 25 tool schemas and a large system prompt in context,
does the agent genuinely *invoke* `a2a_call`? Verified by watching
`~/.hermes/a2a_audit.jsonl` grow, not by reading the reply, because a model that
prints the call as text produces a confident-looking answer and does nothing.

**Lab grounding** — do the six agents answer only from the seeded catalog, with no
empty replies and no invented SKUs?

| Model | Hermes tool loop | Lab grounding | Verdict |
| --- | --- | --- | --- |
| `qwen/qwen3.7-flash` | pass | pass | **chosen** |
| `deepseek/deepseek-v4-flash-0731` | pass | pass | fallback 1 (slower) |
| `openai/gpt-oss-120b` | pass | **invented `AM-EAR-1100`** | fallback 2 |
| `qwen/qwen3-30b-a3b-instruct-2507` | **printed the call as text** | pass | rejected |
| `mistralai/mistral-nemo` | **"the tool is not available"** | pass | rejected |
| `moonshotai/kimi-k3` | pass | pass | too expensive |

Three findings worth carrying into other projects:

- **A one-shot tool probe does not predict a real agent loop.**
  `qwen3-30b-a3b-instruct` emitted a flawless `a2a_call` in isolation, then
  produced the same JSON as *message content* inside Hermes. The audit log never
  moved. Nothing errored.
- **Cheapest is not safe.** `mistral-nemo`, the cheapest tool-capable option,
  replied that `a2a_call` "is not available" and offered to help manually.
- **Grounding in isolation does not survive the full chain.** `gpt-oss-120b` cited
  3/3 real SKUs on a single prompt, then invented `AM-EAR-1100` as its final
  recommendation across six agents — the failure this lab exists to teach against.

## 4. Reasoning effort

Identical pricing-agent prompt, `max_tokens=6000`, one sample each:

| Model | Effort | Wall | Completion tok | Reasoning tok | Content chars | Cost |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `qwen3.7-flash` | high | 39.7s | 3,895 | 2,785 | 4,074 | $0.00054 |
| `qwen3.7-flash` | **medium** | **32.3s** | 3,001 | 2,120 | 3,157 | **$0.00043** |
| `qwen3.7-flash` | low | 35.6s | 3,300 | 2,185 | 4,014 | $0.00047 |
| `kimi-k3` | low | 668.2s | 1,992 | 1,036 | 3,271 | $0.03336 |

`medium` was both the fastest and the cheapest, so it is the default. The three
levels sit within ~7s of each other, which is inside run-to-run noise — the real
reason to prefer `medium` is the ~20% fewer reasoning tokens versus `high`, not the
clock.

## 5. Six-agent end-to-end runs

Same request each time: *"Find me wireless earbuds under $120 with good battery
life."* One sample per row.

| Model | Wall | Empty replies | Invented SKUs |
| --- | ---: | ---: | --- |
| `kimi-k3` | 29.5s / 58.3s | 0 | none |
| `qwen3-30b-a3b-instruct` | 50.7s | 0 | none |
| `qwen3.7-flash` @ medium | 76s | 0 | none |
| `qwen3.7-flash` @ low | 85s | 0 | none |
| `gpt-oss-120b` | 102.9s | 0 | **`AM-EAR-1100`** |
| `deepseek-v4-flash-0731` | 150s | 0 | none |

**On speed, honestly: the switch did not make the lab faster.** K3 ran the chain in
29.5-58.3s; qwen3.7-flash takes ~76s. The win here is cost, not latency. The one
measurement where K3 looked catastrophic — 668s for a single call in section 4 —
contradicts its own six-call run finishing in 29.5s, so treat it as provider
routing variance rather than evidence. Cost figures come from published per-token
pricing and are reliable; every latency figure here is a single sample and is not.

## 6. Why `OPENROUTER_MAX_TOKENS` must stay generous

Reasoning models spend this budget *before* emitting a visible token. The lab
originally shipped `max_tokens=1200`, which silently broke half the ecosystem:

| Agent | finish_reason | Reasoning tok | Content chars |
| --- | --- | ---: | ---: |
| hermes_myshopper | stop | 188 | 1,276 |
| shopping_agent | stop | 479 | 1,023 |
| pricing_agent | **length** | 1,166 / 1,200 | 141 |
| inventory_agent | **length** | **1,200 / 1,200** | **0** |
| fulfillment_agent | **length** | **1,200 / 1,200** | **0** |
| order_agent | **length** | 824 | 1,307 (truncated) |

Two agents returned empty strings and nothing raised. At 4,000 every agent
finished with `stop` and full content. The lab now ships 6,000.

## 7. Reproducing

```bash
# Cost table — pricing straight from OpenRouter
curl -s https://openrouter.ai/api/v1/models | python3 -c "..."   # see git history

# Lab grounding, any model, without editing a file
OPENROUTER_MODEL=<slug> python agentmart_ecosystem.py "Find me wireless earbuds under \$120 with good battery life."

# Hermes tool loop — the number must increase
wc -l < ~/.hermes/a2a_audit.jsonl
hermes -m <slug> --provider openrouter -z "Ask agentmart to find me wireless earbuds under \$120."
wc -l < ~/.hermes/a2a_audit.jsonl

# Routing and scenarios
python test_scenarios.py
```

## 8. gpt-5.6-luna, and why it runs on two different endpoints

Added after the original comparison. `gpt-5.6-luna` is **3.6x faster** than
qwen3.7-flash on the six-agent chain — 21s against 76s — and ~8x dearer:
~$0.0110 per run against ~$0.0014 ($0.200/M in, $1.200/M out).

It also has the most restrictive parameter surface of anything tested. On OpenAI's
own `/v1/chat/completions`:

| Parameter | Result |
| --- | --- |
| `max_tokens` | rejected — needs `max_completion_tokens` |
| `temperature: 0.2` | rejected — only the model default is allowed |
| `reasoning: {"effort": ...}` (OpenRouter shape) | rejected — unknown parameter |
| `reasoning_effort`, **no** tools | works — 6.0s, 3/3 SKUs |
| `reasoning_effort` **with** tools | **rejected** |
| `reasoning_effort: "none"` with tools | works — 1.5s, tool call fires |
| tools, `reasoning_effort` omitted | **rejected** |

That last pair is the trap: with function tools the parameter must be present *and*
set to `none`. Omitting it fails just as hard as setting it to `medium`.

**Consequence — the lab and Hermes take different routes to the same model:**

| | Endpoint | Why |
| --- | --- | --- |
| AgentMart's six agents | OpenAI direct | They never call tools, so the restriction never bites. Full `reasoning_effort` available. |
| Hermes/MyShopper | via OpenRouter | Every Hermes turn carries tool schemas. Hermes cannot emit `reasoning_effort: "none"` on this wire and has no `/v1/responses` mode for the provider, so OpenAI rejects every call. OpenRouter normalizes the combination and tools + reasoning work. |

Hermes direct-to-OpenAI was attempted and abandoned: `provider: openai-api` with
`agent.reasoning_effort: none`, and an explicit `hermes --reasoning none`, both
still returned

```
HTTP 400: Function tools with reasoning_effort are not supported for
gpt-5.6-luna in /v1/chat/completions. To use function tools, use
/v1/responses or set reasoning_effort to 'none'.
```

This is a Hermes limitation, not an OpenAI one — the wire level never reaches the
API as `none`.

The lab client therefore shapes each request by endpoint (`openai_native`, set from
the base URL), so the same code works against either. `OPENAI_*` environment
variables take precedence over `OPENROUTER_*` when present.

## Caveats

- **n = 1 per cell.** No repeats, no confidence intervals. Latency especially
  should be treated as indicative only.
- Prices are OpenRouter list prices on 2026-09-18 and will drift.
- Grounding was judged by SKU extraction plus reading the final answer, not by a
  rubric. `gpt-oss-120b` renders SKUs with a non-breaking hyphen (`AM‑EAR‑1001`),
  which defeated a naive substring check until the matcher normalised it — worth
  knowing before trusting any automated grounding metric.
- Only `product_advice` was exercised end to end per model. The other four intents
  were covered by the dry-run scenario suite, which does not call the model.
