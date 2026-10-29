"""Embeddings from the OpenAI API.

Reads the API key from ASKTHE_OPENAI_API_KEY, falling back to OPENAI_API_KEY. The model
is set in askthe.toml; changing it changes the embedder's name, so every document is
re-embedded rather than mixing vectors from different models.
"""

from __future__ import annotations

import os
from collections.abc import Sequence

import openai

from askthe.core.interfaces import EmbeddingError


class OpenAIEmbedder:
    def __init__(
        self,
        model: str,
        batch_size: int = 256,
        base_url: str = "https://api.openai.com/v1",
        api_key_env: tuple[str, ...] = ("ASKTHE_OPENAI_API_KEY", "OPENAI_API_KEY"),
        client: openai.OpenAI | None = None,
    ) -> None:
        self._model = model
        self._batch_size = batch_size
        self._base_url = base_url
        self._api_key_env = api_key_env
        self._client = client  # created on first use, so other commands need no key

    @property
    def name(self) -> str:
        return f"openai:{self._model}"

    @property
    def client(self) -> openai.OpenAI:
        if self._client is None:
            api_key = next((os.environ[v] for v in self._api_key_env if os.environ.get(v)), None)
            if not api_key:
                raise EmbeddingError(f"no API key: set {' or '.join(self._api_key_env)}")
            # base_url is explicit so an OPENAI_BASE_URL meant for other tools is ignored.
            self._client = openai.OpenAI(api_key=api_key, base_url=self._base_url, max_retries=4)
        return self._client

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            batch = list(texts[start : start + self._batch_size])
            try:
                response = self.client.embeddings.create(model=self._model, input=batch)
            except openai.AuthenticationError as e:
                raise EmbeddingError("the OpenAI API key was rejected") from e
            except openai.RateLimitError as e:
                raise EmbeddingError("rate limited by the OpenAI API, even after retries") from e
            except openai.APIStatusError as e:
                raise EmbeddingError(f"OpenAI API error {e.status_code}: {e.message}") from e
            except openai.APIConnectionError as e:
                raise EmbeddingError(f"could not reach the OpenAI API: {e}") from e
            vectors += [d.embedding for d in sorted(response.data, key=lambda d: d.index)]
        return vectors
