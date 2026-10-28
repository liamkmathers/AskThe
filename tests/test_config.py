from pathlib import Path

import pytest

from askthe.config import (
    ConfigError,
    list_creator_slugs,
    load_app_config,
    load_creator,
    load_video_selection,
)

REPO = Path(__file__).resolve().parent.parent


def write_config(tmp_path: Path, body: str = "") -> Path:
    path = tmp_path / "askthe.toml"
    path.write_text(
        'data_dir = "data"\ncreators_dir = "creators"\n'
        '[adapters.store]\nuse = "memory"\npath = "x.db"\n' + body
    )
    (tmp_path / "creators").mkdir()
    return path


def test_repo_config_and_iron_snail_load():
    config = load_app_config(REPO / "askthe.toml")
    assert config.data_dir == REPO / "data"
    assert "iron-snail" in list_creator_slugs(config)

    creator = load_creator(config, "iron-snail")
    assert creator.instance_name == "Ask The Iron Snail"
    assert "t-shirts" in creator.categories
    uniqlo = next(g for g in creator.glossary if g.name == "Uniqlo")
    assert "Unilo" in uniqlo.heard_as

    selection = load_video_selection(config, creator)
    assert selection[:3] == ["VtBFkFZoaII", "ixCSNbzQNcI", "A6SkEwdjj-8"]


def test_paths_resolve_against_the_config_file(tmp_path):
    config = load_app_config(write_config(tmp_path))
    assert config.data_dir == tmp_path / "data"
    assert config.creators_dir == tmp_path / "creators"


def test_adapter_options_are_passed_through(tmp_path):
    config = load_app_config(write_config(tmp_path))
    assert config.adapters["store"].use == "memory"
    assert config.adapters["store"].options == {"path": "x.db"}


def test_missing_and_invalid_config_raise_config_error(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_app_config(tmp_path / "nope.toml")
    bad = tmp_path / "bad.toml"
    bad.write_text("data_dir = ")
    with pytest.raises(ConfigError):
        load_app_config(bad)


def test_creator_slug_must_match_file_name(tmp_path):
    config = load_app_config(write_config(tmp_path))
    (tmp_path / "creators" / "other.yaml").write_text(
        (REPO / "creators" / "iron-snail.yaml").read_text()
    )
    with pytest.raises(ConfigError, match="does not match"):
        load_creator(config, "other")


def test_video_selection_ignores_comments_blanks_and_duplicates(tmp_path):
    config = load_app_config(write_config(tmp_path))
    creator_yaml = (REPO / "creators" / "iron-snail.yaml").read_text()
    (tmp_path / "creators" / "iron-snail.yaml").write_text(creator_yaml)
    (tmp_path / "creators" / "iron-snail.videos.txt").write_text(
        "# header\n\nabc  # first\nabc\n  def\n"
    )
    creator = load_creator(config, "iron-snail")
    assert load_video_selection(config, creator) == ["abc", "def"]
