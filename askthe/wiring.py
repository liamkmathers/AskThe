"""The composition root: reads config and builds the adapters behind each interface.

This is the only module that constructs adapters. Adding an implementation means
writing the adapter and registering it below; nothing else in the engine changes.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from askthe.config import AppConfig, ConfigError
from askthe.core.interfaces import (
    CatalogSource,
    Embedder,
    KnowledgeStore,
    LLMClient,
    RawArchive,
    SearchIndex,
    TranscriptSource,
    VectorIndex,
)

# Each adapter factory takes (options from askthe.toml, the app config) and returns
# the adapter. Factories are named as "module:callable" and imported only when
# selected, so an adapter's dependencies are needed only if it's in use.
Factory = Callable[[dict[str, Any], AppConfig], Any]

PORTS: dict[str, type] = {
    "catalog": CatalogSource,
    "transcripts": TranscriptSource,
    "raw_archive": RawArchive,
    "store": KnowledgeStore,
    "search": SearchIndex,
    "embedder": Embedder,
    "vectors": VectorIndex,
    "llm": LLMClient,
}

REGISTRY: dict[str, dict[str, str]] = {
    "catalog": {
        "memory": "askthe.wiring:_memory_catalog",
        "yt-dlp": "askthe.wiring:_ytdlp_catalog",
    },
    "transcripts": {
        "memory": "askthe.wiring:_memory_transcripts",
        "youtube-transcript-api": "askthe.wiring:_transcript_api",
        "files": "askthe.wiring:_transcript_files",
    },
    "raw_archive": {
        "memory": "askthe.wiring:_memory_raw_archive",
        "files": "askthe.wiring:_file_raw_archive",
    },
    "store": {
        "memory": "askthe.wiring:_memory_store",
        "sqlite": "askthe.wiring:_sqlite_store",
    },
    "search": {
        "memory": "askthe.wiring:_memory_search",
        "sqlite": "askthe.wiring:_sqlite_search",
    },
    "embedder": {
        "memory": "askthe.wiring:_memory_embedder",
        "openai": "askthe.wiring:_openai_embedder",
    },
    "vectors": {
        "memory": "askthe.wiring:_memory_vectors",
        "sqlite": "askthe.wiring:_sqlite_vectors",
    },
    "llm": {
        "memory": "askthe.wiring:_memory_llm",
        "anthropic": "askthe.wiring:_anthropic_llm",
    },
}


@dataclass(frozen=True)
class Services:
    config: AppConfig
    catalog: CatalogSource
    transcripts: TranscriptSource
    raw_archive: RawArchive
    store: KnowledgeStore
    search: SearchIndex
    embedder: Embedder
    vectors: VectorIndex
    llm: LLMClient


def build_services(config: AppConfig) -> Services:
    unknown = set(config.adapters) - set(PORTS)
    if unknown:
        raise ConfigError(f"unknown adapter ports in config: {sorted(unknown)}")
    built = {port: build_adapter(config, port) for port in PORTS}
    return Services(config=config, **built)


def build_adapter(config: AppConfig, port: str) -> Any:
    choice = config.adapters.get(port)
    if choice is None:
        raise ConfigError(f"no adapter configured for {port!r} (add [adapters.{port}])")
    available = REGISTRY[port]
    if choice.use not in available:
        raise ConfigError(f"unknown {port} adapter {choice.use!r}; available: {sorted(available)}")
    factory = _load(available[choice.use])
    adapter = factory(choice.options, config)
    if not isinstance(adapter, PORTS[port]):
        raise ConfigError(
            f"{port} adapter {choice.use!r} does not implement {PORTS[port].__name__}"
        )
    return adapter


def _load(target: str) -> Factory:
    module_name, _, attr = target.partition(":")
    return getattr(importlib.import_module(module_name), attr)


# --- Factories ------------------------------------------------------------------


def _memory_catalog(options: dict[str, Any], config: AppConfig) -> Any:
    from askthe.adapters.memory import MemoryCatalogSource

    return MemoryCatalogSource()


def _memory_transcripts(options: dict[str, Any], config: AppConfig) -> Any:
    from askthe.adapters.memory import MemoryTranscriptSource

    return MemoryTranscriptSource()


def _memory_raw_archive(options: dict[str, Any], config: AppConfig) -> Any:
    from askthe.adapters.memory import MemoryRawArchive

    return MemoryRawArchive()


def _memory_store(options: dict[str, Any], config: AppConfig) -> Any:
    from askthe.adapters.memory import MemoryKnowledgeStore

    return MemoryKnowledgeStore()


def _memory_search(options: dict[str, Any], config: AppConfig) -> Any:
    from askthe.adapters.memory import MemorySearchIndex

    return MemorySearchIndex()


def _memory_llm(options: dict[str, Any], config: AppConfig) -> Any:
    from askthe.adapters.memory import MemoryLLMClient

    return MemoryLLMClient(models=config.models)


def _ytdlp_catalog(options: dict[str, Any], config: AppConfig) -> Any:
    from askthe.adapters.youtube import YtDlpCatalogSource

    return YtDlpCatalogSource()


def _transcript_api(options: dict[str, Any], config: AppConfig) -> Any:
    from askthe.adapters.youtube import TranscriptApiSource

    return TranscriptApiSource(languages=options.get("languages", ["en"]))


def _transcript_files(options: dict[str, Any], config: AppConfig) -> Any:
    from askthe.adapters.files import TranscriptFileSource
    from askthe.core.models import TranscriptKind

    return TranscriptFileSource(
        directory=config.data_dir / options.get("dir", "transcripts"),
        kind=TranscriptKind(options.get("kind", "manual")),
        language=options.get("language", "en"),
    )


def _file_raw_archive(options: dict[str, Any], config: AppConfig) -> Any:
    from askthe.adapters.files import FileRawArchive

    return FileRawArchive(root=config.data_dir)


def _sqlite_store(options: dict[str, Any], config: AppConfig) -> Any:
    from askthe.adapters.sqlite import SqliteKnowledgeStore

    return SqliteKnowledgeStore(config.data_dir / options.get("path", "askthe.db"))


def _sqlite_search(options: dict[str, Any], config: AppConfig) -> Any:
    from askthe.adapters.sqlite import SqliteSearchIndex

    return SqliteSearchIndex(config.data_dir / options.get("path", "askthe.db"))


def _anthropic_llm(options: dict[str, Any], config: AppConfig) -> Any:
    from askthe.adapters.anthropic_llm import AnthropicLLMClient

    return AnthropicLLMClient(
        models=config.models,
        effort=options.get("effort"),
        max_tokens=options.get("max_tokens", 16000),
        fallbacks=options.get("fallbacks", True),
        base_url=options.get("base_url", "https://api.anthropic.com"),
    )


def _memory_embedder(options: dict[str, Any], config: AppConfig) -> Any:
    from askthe.adapters.memory import MemoryEmbedder

    return MemoryEmbedder()


def _openai_embedder(options: dict[str, Any], config: AppConfig) -> Any:
    from askthe.adapters.openai_embedder import OpenAIEmbedder

    return OpenAIEmbedder(
        model=options.get("model", "text-embedding-3-small"),
        batch_size=options.get("batch_size", 256),
    )


def _memory_vectors(options: dict[str, Any], config: AppConfig) -> Any:
    from askthe.adapters.memory import MemoryVectorIndex

    return MemoryVectorIndex()


def _sqlite_vectors(options: dict[str, Any], config: AppConfig) -> Any:
    from askthe.adapters.sqlite import SqliteVectorIndex

    return SqliteVectorIndex(config.data_dir / options.get("path", "askthe.db"))
