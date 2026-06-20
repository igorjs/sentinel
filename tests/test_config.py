from pathlib import Path

import pytest

from scripts.config import ConfigError, load_config


def test_load_none_returns_default(fixtures_dir: Path):
    cfg = load_config(None)
    assert cfg.scopes == {}
    assert cfg.custom == []
    assert cfg.defaults.pr_labels == ["dependencies", "automated"]


def test_load_fixture(fixtures_dir: Path):
    cfg = load_config(fixtures_dir / "sentinel.toml")
    assert cfg.scopes["go"].gomod_path == "sdks/go/go.mod"
    assert cfg.scopes["go"].update_runtime is True
    assert cfg.scopes["python"].update_runtime is False
    assert cfg.scopes["javascript"].enabled is False
    assert len(cfg.custom) == 1
    assert cfg.custom[0].name == "libkrun-bottle"
    assert cfg.custom[0].extra["env_var"] == "LIBKRUN_BOTTLE_VERSION"


def test_unknown_top_level_key_raises(tmp_path: Path):
    p = tmp_path / "bad.toml"
    p.write_text("typo_field = 1\n")
    with pytest.raises(ConfigError, match="unknown key"):
        load_config(p)


def test_unknown_scope_override_key_raises(tmp_path: Path):
    p = tmp_path / "bad.toml"
    p.write_text('[scopes.rust]\ntypo = "x"\n')
    with pytest.raises(ConfigError, match="unknown key"):
        load_config(p)


def test_custom_missing_required_kind_raises(tmp_path: Path):
    p = tmp_path / "bad.toml"
    p.write_text('[[custom]]\nname = "x"\n')
    with pytest.raises(ConfigError, match=r"missing.*kind"):
        load_config(p)
