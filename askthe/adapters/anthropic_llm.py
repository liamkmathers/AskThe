"""LLM adapter for the Anthropic API (Claude), using structured outputs.

Model names and effort levels come from askthe.toml, per task. The system prompt and
the shared context (a whole transcript) are marked for prompt caching, so the many
calls made for one video pay full price for them once.

Reads the API key from ASKTHE_ANTHROPIC_API_KEY, falling back to ANTHROPIC_API_KEY.
The app has its own variable because hosted Claude Code environments reserve
ANTHROPIC_API_KEY for Claude Code itself.
"""

from __future__ import annotations

import os
from typing import Any

import anthropic

from askthe.core.interfaces import Generated, LLMError, LLMTask, T

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicLLMClient:
    def __init__(
        self,
        models: dict[str, str],
        effort: dict[str, str] | None = None,
        max_tokens: int = 16000,
        fallbacks: bool = True,
        base_url: str = "https://api.anthropic.com",
        api_key_env: tuple[str, ...] = ("ASKTHE_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
        client: anthropic.Anthropic | None = None,
    ) -> None:
        missing = [t.value for t in LLMTask if t.value not in models]
        if missing:
            raise ValueError(f"no model configured for tasks {missing}; set [models] in config")
        self._models = models
        self._effort = effort or {}
        self._max_tokens = max_tokens
        self._fallbacks = fallbacks
        self._base_url = base_url
        self._api_key_env = api_key_env
        self._client = client  # created on first use, so commands that don't call the
        # model work without an API key

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:
            api_key = next((os.environ[v] for v in self._api_key_env if os.environ.get(v)), None)
            if not api_key:
                raise LLMError(f"no API key: set {' or '.join(self._api_key_env)}")
            # base_url is explicit so an ANTHROPIC_BASE_URL meant for other tools is ignored.
            self._client = anthropic.Anthropic(
                api_key=api_key, base_url=self._base_url, max_retries=4
            )
        return self._client

    def model_for(self, task: LLMTask) -> str:
        return self._models[task.value]

    def generate_structured(
        self,
        task: LLMTask,
        system: str,
        prompt: str,
        output_type: type[T],
        context: str | None = None,
    ) -> Generated[T]:
        content: list[dict[str, Any]] = []
        if context:
            content.append(
                {"type": "text", "text": context, "cache_control": {"type": "ephemeral"}}
            )
        content.append({"type": "text", "text": prompt})

        params: dict[str, Any] = {}
        if task.value in self._effort:
            params["output_config"] = {"effort": self._effort[task.value]}
        if self._fallbacks:
            # On a policy refusal, the API re-runs the request on a fallback model.
            params["betas"] = [FALLBACK_BETA]
            params["fallbacks"] = "default"
        try:
            response = self.client.beta.messages.parse(
                model=self.model_for(task),
                max_tokens=self._max_tokens,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": content}],
                output_format=output_type,
                **params,
            )
        except (anthropic.BadRequestError, anthropic.NotFoundError) as e:
            raise LLMError(f"request rejected: {e.message}") from e
        except anthropic.AuthenticationError as e:
            raise LLMError("the API key was rejected") from e
        except anthropic.RateLimitError as e:
            raise LLMError("rate limited by the API, even after retries") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise LLMError(f"could not reach the API: {e}") from e
        except anthropic.AnthropicError as e:
            raise LLMError(str(e)) from e

        if response.stop_reason == "refusal":
            category = response.stop_details.category if response.stop_details else None
            raise LLMError(f"model declined the request (category: {category})")
        if response.stop_reason == "max_tokens":
            raise LLMError(f"output hit max_tokens ({self._max_tokens}); use a smaller window")
        if response.parsed_output is None:
            raise LLMError("model returned no parseable output")

        usage = response.usage
        return Generated(
            value=response.parsed_output,
            model=response.model,
            usage={
                "input": usage.input_tokens,
                "output": usage.output_tokens,
                "cache_read": usage.cache_read_input_tokens or 0,
                "cache_write": usage.cache_creation_input_tokens or 0,
            },
        )
