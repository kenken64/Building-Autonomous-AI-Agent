"""The OpenAI-compatible model client, its per-endpoint request shaping, and the
per-hop PERF/trace instrumentation the console reads."""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable

from dotenv import load_dotenv

logger = logging.getLogger("agentmart")



# Optional trace sink. The console needs the prompt, the reply and the token counts
# for every hop; the log line carries only the numbers. Set to a callable to receive
# one dict per model call. Left None everywhere else so a CLI run costs nothing.
TRACE_SINK: Callable[[dict[str, Any]], None] | None = None




def set_trace_sink(sink: Callable[[dict[str, Any]], None] | None) -> None:
    """Install (or clear) the per-hop trace callback."""
    global TRACE_SINK
    TRACE_SINK = sink




DEFAULT_MODEL = "moonshotai/kimi-k3"




class OpenRouterHermesClient:
    """OpenAI-compatible client for OpenRouter, configured for Hermes/MyShopper.

    Settings resolve in this order, first match wins:
      1. environment variables / .env  (OPENROUTER_MODEL, ...)
      2. the model block in hermes_a2a_config.json
      3. the built-in defaults
    """

    def __init__(self, dry_run: bool = False, model_config: dict[str, Any] | None = None,
                 model_override: str | None = None) -> None:
        load_dotenv()
        config = model_config or {}
        self.dry_run = dry_run
        # OPENAI_* wins when set, so pointing the lab at OpenAI directly needs no rename.
        self.api_key = os.getenv("OPENAI_API_KEY") or os.getenv("OPENROUTER_API_KEY", "")
        self.base_url = (os.getenv("OPENAI_BASE_URL") or
                         os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"))
        self.model = (model_override
                      or os.getenv("OPENAI_MODEL") or os.getenv("OPENROUTER_MODEL")
                      or config.get("default_model") or DEFAULT_MODEL)
        # OpenAI's own endpoint and OpenRouter disagree on three parameters, so the
        # request has to be shaped per endpoint rather than sent one way and hoped for.
        self.openai_native = "api.openai.com" in self.base_url
        # OpenAI splits its own catalogue in two: the reasoning families take
        # reasoning_effort and reject any temperature but their default, while
        # gpt-4.x takes temperature and rejects reasoning_effort outright.
        # OpenRouter normalizes both, so this only matters on the direct endpoint.
        self.openai_reasoning_family = self.model.startswith(("gpt-5", "o1", "o3", "o4"))
        self.fallback_models = config.get("fallback_models", [])
        self.temperature = float(os.getenv("OPENROUTER_TEMPERATURE", config.get("temperature", 0.2)))
        self.max_tokens = int(os.getenv("OPENROUTER_MAX_TOKENS", config.get("max_tokens", 1200)))
        # Kimi K3 reasons before it answers, and reasoning is billed and timed like any
        # other completion token. Capping the effort is the single biggest latency win;
        # set OPENROUTER_REASONING_EFFORT=default to hand the model its full budget back.
        self.reasoning_effort = os.getenv(
            "OPENROUTER_REASONING_EFFORT", config.get("reasoning_effort", "medium")
        )
        self.http_referer = os.getenv("OPENROUTER_HTTP_REFERER", "http://localhost")
        self.app_title = os.getenv("OPENROUTER_APP_TITLE", "AgentMart Workshop")

    def complete(self, agent_name: str, system_prompt: str, user_prompt: str) -> str:
        if self.dry_run or not self.api_key:
            reply = self._dry_run_reply(agent_name, user_prompt)
            # Trace dry runs too, so the console can be demonstrated without spend.
            if TRACE_SINK is not None:
                TRACE_SINK({
                    "agent": agent_name, "model": "(dry-run)", "seconds": 0.0,
                    "system_prompt": system_prompt, "user_prompt": user_prompt,
                    "response": reply, "prompt_tokens": 0, "cached_tokens": 0,
                    "completion_tokens": 0, "reasoning_tokens": 0, "finish_reason": "dry_run",
                })
            return reply

        from openai import OpenAI

        client = OpenAI(base_url=self.base_url, api_key=self.api_key)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        kwargs: dict[str, Any] = {"model": self.model, "messages": messages}

        if self.openai_native:
            # The gpt-5.6 family rejects `max_tokens` (wants `max_completion_tokens`),
            # rejects any temperature but the default, and takes reasoning as a
            # top-level `reasoning_effort` rather than OpenRouter's `reasoning` object.
            # Model fallbacks and the attribution headers are OpenRouter features.
            kwargs["max_completion_tokens"] = self.max_tokens
            if self.openai_reasoning_family:
                if self.reasoning_effort and self.reasoning_effort != "default":
                    kwargs["reasoning_effort"] = self.reasoning_effort
            else:
                kwargs["temperature"] = self.temperature
        else:
            extra_body: dict[str, Any] = {}
            if self.fallback_models:
                # OpenRouter retries these in order if the primary model is unavailable.
                extra_body["models"] = [self.model, *self.fallback_models]
            if self.reasoning_effort and self.reasoning_effort != "default":
                extra_body["reasoning"] = {"effort": self.reasoning_effort}
            kwargs.update(
                extra_headers={"HTTP-Referer": self.http_referer, "X-Title": self.app_title},
                extra_body=extra_body,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )

        started = time.time()
        response = client.chat.completions.create(**kwargs)
        elapsed = time.time() - started
        content = response.choices[0].message.content or ""
        usage = getattr(response, "usage", None)
        details = getattr(usage, "completion_tokens_details", None) if usage else None
        prompt_details = getattr(usage, "prompt_tokens_details", None) if usage else None
        # cached_tok is the prefix-cache hit: it should cover the shared catalog on
        # every call after the first. A run of zeros means the prefix drifted.
        logger.info(
            "PERF agent=%s %.1fs model=%s prompt_tok=%s cached_tok=%s completion_tok=%s "
            "reasoning_tok=%s out_chars=%d finish=%s",
            agent_name, elapsed, self.model,
            getattr(usage, "prompt_tokens", "?"),
            getattr(prompt_details, "cached_tokens", 0) if prompt_details else "?",
            getattr(usage, "completion_tokens", "?"),
            getattr(details, "reasoning_tokens", "?") if details else "?",
            len(content), response.choices[0].finish_reason,
        )
        if TRACE_SINK is not None:
            TRACE_SINK({
                "agent": agent_name,
                "model": self.model,
                "seconds": round(elapsed, 2),
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "response": content,
                "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                "cached_tokens": (getattr(prompt_details, "cached_tokens", 0) or 0) if prompt_details else 0,
                "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
                "reasoning_tokens": (getattr(details, "reasoning_tokens", 0) or 0) if details else 0,
                "finish_reason": response.choices[0].finish_reason,
            })
        return content

    @staticmethod
    def _dry_run_reply(agent_name: str, user_prompt: str) -> str:
        compact_prompt = " ".join(user_prompt.split())
        return f"[dry-run:{agent_name}] {compact_prompt[:260]}"
