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


def test_gh_release_pin_missing_extra_key_raises_at_load(tmp_path: Path):
    p = tmp_path / "bad.toml"
    # Missing env_var (and others) for a gh-release-pin custom scope.
    p.write_text(
        "[[custom]]\n"
        'name = "libkrun"\n'
        'kind = "gh-release-pin"\n'
        'upstream_repo = "a/b"\n'
        'target_file = ".github/workflows/x.yml"\n'
        'target_kind = "yaml-env-var"\n'
    )
    with pytest.raises(ConfigError, match="env_var"):
        load_config(p)


def test_gh_release_pin_complete_extra_loads(tmp_path: Path):
    p = tmp_path / "ok.toml"
    p.write_text(
        "[[custom]]\n"
        'name = "libkrun"\n'
        'kind = "gh-release-pin"\n'
        'upstream_repo = "a/b"\n'
        'target_file = ".github/workflows/x.yml"\n'
        'target_kind = "yaml-env-var"\n'
        'env_var = "LIBKRUN_VERSION"\n'
    )
    cfg = load_config(p)
    assert cfg.custom[0].extra["env_var"] == "LIBKRUN_VERSION"


def test_min_severity_loads_global_and_scope(tmp_path: Path):
    from scripts.config import effective_min_severity

    p = tmp_path / "ok.toml"
    p.write_text('[defaults]\nmin_severity = "medium"\n\n[scopes.rust]\nmin_severity = "high"\n')
    cfg = load_config(p)
    assert cfg.defaults.min_severity == "medium"
    assert cfg.scopes["rust"].min_severity == "high"
    assert effective_min_severity(cfg, "rust") == "high"  # scope override wins
    assert effective_min_severity(cfg, "go") == "medium"  # falls back to global
    assert effective_min_severity(load_config(None), "rust") is None  # unset = no gating


def test_invalid_min_severity_raises(tmp_path: Path):
    p = tmp_path / "bad.toml"
    p.write_text('[defaults]\nmin_severity = "urgent"\n')
    with pytest.raises(ConfigError, match="min_severity"):
        load_config(p)


def test_update_runtime_defaults_off(tmp_path: Path):
    cfg_path = tmp_path / "sentinel.toml"
    cfg_path.write_text("[scopes.python]\nenabled = true\n")
    cfg = load_config(cfg_path)
    from scripts.config import update_runtime_enabled

    assert update_runtime_enabled(cfg, "python") is False  # opt-in
    assert update_runtime_enabled(cfg, "go") is False  # no override -> off


def test_update_runtime_opt_in(tmp_path: Path):
    cfg_path = tmp_path / "sentinel.toml"
    cfg_path.write_text("[scopes.python]\nupdate_runtime = true\n")
    cfg = load_config(cfg_path)
    from scripts.config import update_runtime_enabled

    assert update_runtime_enabled(cfg, "python") is True


def test_lead_days_default_and_override(tmp_path: Path):
    from scripts.config import effective_runtime_eol_lead_days

    cfg_path = tmp_path / "sentinel.toml"
    cfg_path.write_text(
        "[defaults]\nruntime_eol_lead_days = 14\n[scopes.python]\nruntime_eol_lead_days = 7\n"
    )
    cfg = load_config(cfg_path)
    assert effective_runtime_eol_lead_days(cfg, "python") == 7  # scope override
    assert effective_runtime_eol_lead_days(cfg, "go") == 14  # defaults


def test_lead_days_default_is_30(tmp_path: Path):
    from scripts.config import effective_runtime_eol_lead_days

    cfg = load_config(None)
    assert effective_runtime_eol_lead_days(cfg, "python") == 30


def test_lead_days_rejects_negative(tmp_path: Path):
    cfg_path = tmp_path / "sentinel.toml"
    cfg_path.write_text("[scopes.python]\nruntime_eol_lead_days = -1\n")
    with pytest.raises(ConfigError, match="runtime_eol_lead_days"):
        load_config(cfg_path)


def test_lead_days_rejects_fractional(tmp_path: Path):
    cfg_path = tmp_path / "sentinel.toml"
    cfg_path.write_text("[scopes.python]\nruntime_eol_lead_days = 1.5\n")
    with pytest.raises(ConfigError, match="runtime_eol_lead_days"):
        load_config(cfg_path)


def test_lead_days_rejects_bool(tmp_path: Path):
    cfg_path = tmp_path / "sentinel.toml"
    cfg_path.write_text("[defaults]\nruntime_eol_lead_days = true\n")
    with pytest.raises(ConfigError, match="runtime_eol_lead_days"):
        load_config(cfg_path)


def test_freshness_defaults_off(tmp_path):
    from scripts.config import (
        effective_freshness_group,
        effective_freshness_level,
        freshness_filters,
        load_config,
        update_freshness_enabled,
    )

    cfg = load_config(None)
    assert update_freshness_enabled(cfg, "javascript") is False
    assert effective_freshness_level(cfg, "javascript") == "range"
    assert effective_freshness_group(cfg, "javascript") == "scope"
    assert freshness_filters(cfg, "javascript") == ([], [])


def test_freshness_scope_override(tmp_path):
    from scripts.config import (
        effective_freshness_group,
        effective_freshness_level,
        freshness_filters,
        load_config,
        update_freshness_enabled,
    )

    p = tmp_path / "sentinel.toml"
    p.write_text(
        "[scopes.javascript]\n"
        "update_freshness = true\n"
        'freshness_level = "major"\n'
        'freshness_group = "dependency"\n'
        'freshness_include = ["lodash"]\n'
        'freshness_exclude = ["@types/*"]\n'
    )
    cfg = load_config(p)
    assert update_freshness_enabled(cfg, "javascript") is True
    assert effective_freshness_level(cfg, "javascript") == "major"
    assert effective_freshness_group(cfg, "javascript") == "dependency"
    assert freshness_filters(cfg, "javascript") == (["lodash"], ["@types/*"])


def test_freshness_defaults_table(tmp_path):
    from scripts.config import effective_freshness_group, effective_freshness_level, load_config

    p = tmp_path / "sentinel.toml"
    p.write_text('[defaults]\nfreshness_level = "major"\nfreshness_group = "dependency"\n')
    cfg = load_config(p)
    assert effective_freshness_level(cfg, "anything") == "major"
    assert effective_freshness_group(cfg, "anything") == "dependency"


def test_freshness_level_invalid(tmp_path):
    from scripts.config import ConfigError, load_config

    p = tmp_path / "sentinel.toml"
    p.write_text('[scopes.javascript]\nfreshness_level = "wild"\n')
    import pytest

    with pytest.raises(ConfigError):
        load_config(p)


def test_freshness_group_invalid(tmp_path):
    from scripts.config import ConfigError, load_config

    p = tmp_path / "sentinel.toml"
    p.write_text('[scopes.javascript]\nfreshness_group = "weekly"\n')
    import pytest

    with pytest.raises(ConfigError):
        load_config(p)


def test_freshness_include_must_be_list(tmp_path):
    from scripts.config import ConfigError, load_config

    p = tmp_path / "sentinel.toml"
    p.write_text('[scopes.javascript]\nfreshness_include = "lodash"\n')
    import pytest

    with pytest.raises(ConfigError):
        load_config(p)


def test_gomod_path_absolute_rejected(tmp_path: Path):
    p = tmp_path / "bad.toml"
    p.write_text('[scopes.go]\ngomod_path = "/etc/passwd"\n')
    with pytest.raises(ConfigError, match="workspace"):
        load_config(p)


def test_gomod_path_traversal_rejected(tmp_path: Path):
    p = tmp_path / "bad.toml"
    p.write_text('[scopes.go]\ngomod_path = "../../etc/passwd"\n')
    with pytest.raises(ConfigError, match="workspace"):
        load_config(p)


def test_custom_target_file_traversal_rejected(tmp_path: Path):
    p = tmp_path / "bad.toml"
    p.write_text(
        '[[custom]]\nname = "x"\nkind = "gh-release-pin"\n'
        'upstream_repo = "o/r"\ntarget_file = "../../../etc/cron.d/x"\n'
        'target_kind = "yaml-env-var"\nenv_var = "V"\n'
    )
    with pytest.raises(ConfigError, match="workspace"):
        load_config(p)


def test_malformed_toml_raises_config_error(tmp_path: Path):
    p = tmp_path / "bad.toml"
    p.write_text("this is = not valid = toml\n")
    with pytest.raises(ConfigError):
        load_config(p)
