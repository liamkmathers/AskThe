from pathlib import Path

import pytest

from askthe.adapters.memory import MemoryKnowledgeStore
from askthe.config import ConfigError, load_app_config
from askthe.core.interfaces import KnowledgeStore
from askthe.wiring import PORTS, build_services

REPO = Path(__file__).resolve().parent.parent


def config_with(tmp_path: Path, adapters: dict[str, str]):
    body = "".join(f'[adapters.{port}]\nuse = "{use}"\n' for port, use in adapters.items())
    path = tmp_path / "askthe.toml"
    path.write_text('data_dir = "data"\ncreators_dir = "creators"\n' + body)
    return load_app_config(path)


def test_repo_config_builds_every_port():
    services = build_services(load_app_config(REPO / "askthe.toml"))
    for port, interface in PORTS.items():
        assert isinstance(getattr(services, port), interface)
    assert isinstance(services.store, MemoryKnowledgeStore)
    assert isinstance(services.store, KnowledgeStore)


def test_unknown_adapter_name_is_a_config_error(tmp_path):
    adapters = dict.fromkeys(PORTS, "memory") | {"store": "oracle"}
    with pytest.raises(ConfigError, match="unknown store adapter 'oracle'"):
        build_services(config_with(tmp_path, adapters))


def test_missing_port_is_a_config_error(tmp_path):
    adapters = dict.fromkeys(PORTS, "memory")
    del adapters["search"]
    with pytest.raises(ConfigError, match="no adapter configured for 'search'"):
        build_services(config_with(tmp_path, adapters))


def test_unknown_port_is_a_config_error(tmp_path):
    adapters = dict.fromkeys(PORTS, "memory") | {"teleporter": "memory"}
    with pytest.raises(ConfigError, match="unknown adapter ports"):
        build_services(config_with(tmp_path, adapters))
