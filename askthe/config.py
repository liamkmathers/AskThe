"""Loading the application config (askthe.toml) and creator configs (creators/*.yaml)."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from askthe.core.evaluation import Price, TestQuestion
from askthe.core.models import ChannelInfo, Creator

DEFAULT_CONFIG_PATH = Path("askthe.toml")


class ConfigError(Exception):
    pass


class AdapterChoice(BaseModel):
    """Which adapter implements a port. Keys other than `use` are adapter options."""

    model_config = ConfigDict(extra="allow")

    use: str

    @property
    def options(self) -> dict[str, Any]:
        return dict(self.model_extra or {})


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root: Path = Field(exclude=True)
    data_dir: Path
    creators_dir: Path
    eval_dir: Path = Path("eval")
    adapters: dict[str, AdapterChoice]
    models: dict[str, str] = Field(default_factory=dict)
    retrieval: dict[str, Any] = Field(default_factory=dict)
    prices: dict[str, Price] = Field(default_factory=dict)  # per model, $ per MTok

    @model_validator(mode="after")
    def _resolve_paths(self) -> AppConfig:
        self.data_dir = (self.root / self.data_dir).resolve()
        self.creators_dir = (self.root / self.creators_dir).resolve()
        self.eval_dir = (self.root / self.eval_dir).resolve()
        return self


def load_env_file(path: Path) -> list[str]:
    """Set environment variables from a `.env` file: `NAME=value` lines, with
    optional `export ` and quotes; blank lines and `#` comments are skipped.

    Variables already set in the environment win, so a key exported in the shell
    overrides the file. Returns the names it set. `.env` is git-ignored: secrets
    never go in the repository.
    """
    try:
        lines = path.read_text().splitlines()
    except (FileNotFoundError, IsADirectoryError):
        return []
    loaded = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.removeprefix("export ").partition("=")
        name, value = name.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()  # trailing comment
        if name and name not in os.environ:
            os.environ[name] = value
            loaded.append(name)
    return loaded


def load_app_config(path: Path = DEFAULT_CONFIG_PATH) -> AppConfig:
    """Load askthe.toml. Relative paths inside it resolve against its own folder.

    A `.env` file beside it, if there is one, is loaded into the environment first
    (see load_env_file), so API keys can live there instead of in the shell.
    """
    path = Path(path)
    load_env_file(path.resolve().parent / ".env")
    try:
        raw = tomllib.loads(path.read_text())
    except FileNotFoundError:
        raise ConfigError(f"config file not found: {path}") from None
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from None
    try:
        return AppConfig(root=path.resolve().parent, **raw)
    except ValidationError as e:
        raise ConfigError(f"{path}: {e}") from None


def creator_path(config: AppConfig, slug: str) -> Path:
    return config.creators_dir / f"{slug}.yaml"


def load_creator(config: AppConfig, slug: str) -> Creator:
    path = creator_path(config, slug)
    try:
        raw = yaml.safe_load(path.read_text())
    except FileNotFoundError:
        raise ConfigError(f"no creator config at {path}") from None
    except yaml.YAMLError as e:
        raise ConfigError(f"{path}: {e}") from None
    try:
        creator = Creator(**raw)
    except (TypeError, ValidationError) as e:
        raise ConfigError(f"{path}: {e}") from None
    if creator.slug != slug:
        raise ConfigError(f"{path}: slug {creator.slug!r} does not match file name {slug!r}")
    channel = config.data_dir / slug / "raw" / "channel.json"
    if channel.exists() and creator.channel is None:
        try:
            creator.channel = ChannelInfo.model_validate_json(channel.read_text())
        except ValidationError as e:
            raise ConfigError(f"{channel}: {e}") from None
    return creator


def list_creator_slugs(config: AppConfig) -> list[str]:
    return sorted(p.stem for p in config.creators_dir.glob("*.yaml"))


def load_video_selection(config: AppConfig, creator: Creator) -> list[str]:
    """The creator's chosen video IDs: one per line, `#` starts a comment."""
    if creator.video_selection is None:
        return []
    path = config.creators_dir / creator.video_selection
    try:
        lines = path.read_text().splitlines()
    except FileNotFoundError:
        raise ConfigError(f"video selection file not found: {path}") from None
    ids: list[str] = []
    for line in lines:
        video = line.split("#", 1)[0].strip()
        if video and video not in ids:
            ids.append(video)
    return ids


def load_questions(path: Path) -> list[TestQuestion]:
    """A test set: a YAML list of questions in the format of docs/EVALUATION.md."""
    try:
        raw = yaml.safe_load(Path(path).read_text()) or []
    except FileNotFoundError:
        raise ConfigError(f"no test set at {path}") from None
    except yaml.YAMLError as e:
        raise ConfigError(f"{path}: {e}") from None
    try:
        questions = [TestQuestion(**item) for item in raw]
    except (TypeError, ValidationError) as e:
        raise ConfigError(f"{path}: {e}") from None
    ids = [q.id for q in questions]
    if len(ids) != len(set(ids)):
        raise ConfigError(f"{path}: question ids repeat")
    return questions
