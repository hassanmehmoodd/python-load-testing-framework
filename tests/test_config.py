"""Configuration parsing, overrides, and validation."""

from perfload.config import apply_environment, load_config
from perfload.exceptions import ConfigError
from tests.conftest import BASE_CONFIG, write_config


def test_load_default_shape(tmp_path):
    path = tmp_path / "config.yaml"
    write_config(path, BASE_CONFIG)
    config = load_config(path, environ={})
    assert config.target.base_url == "http://127.0.0.1:8000"
    assert config.load.profile == "constant"
    assert config.load.users == 5
    assert config.load.spawn_rate == 1
    assert config.safeguards.max_users == 25
    assert "localhost" in config.safeguards.allowed_hosts


def test_environment_overrides_file_and_cli_wins(tmp_path):
    path = tmp_path / "config.yaml"
    write_config(path, BASE_CONFIG)
    config = load_config(
        path,
        overrides={"load": {"users": 5}},
        environ={"PERFLOAD_USERS": "9", "PERFLOAD_PROFILE": "spike"},
    )
    assert config.load.users == 5
    assert config.load.profile == "spike"


def test_apply_environment_ignores_blank_values():
    updated = apply_environment({"load": {"users": 4}}, {"PERFLOAD_USERS": "  "})
    assert updated["load"]["users"] == 4


def test_invalid_environment_number(tmp_path):
    path = tmp_path / "config.yaml"
    write_config(path, BASE_CONFIG)
    try:
        load_config(path, environ={"PERFLOAD_USERS": "many"})
    except ConfigError as exc:
        assert "PERFLOAD_USERS" in str(exc)
    else:
        raise AssertionError("expected ConfigError")


def test_unknown_key_is_rejected(tmp_path):
    path = tmp_path / "config.yaml"
    write_config(path, BASE_CONFIG + "\nextra: true\n")
    try:
        load_config(path, environ={})
    except ConfigError as exc:
        assert "Invalid configuration" in str(exc)
    else:
        raise AssertionError("expected ConfigError")


def test_unknown_profile_is_rejected(tmp_path):
    path = tmp_path / "config.yaml"
    write_config(path, BASE_CONFIG.replace("profile: constant", "profile: tsunami"))
    try:
        load_config(path, environ={})
    except ConfigError as exc:
        assert "profile" in str(exc)
    else:
        raise AssertionError("expected ConfigError")


def test_missing_file(tmp_path):
    try:
        load_config(tmp_path / "missing.yaml", environ={})
    except ConfigError as exc:
        assert "not found" in str(exc)
    else:
        raise AssertionError("expected ConfigError")


def test_shipped_profiles_parse():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "config"
    for path in [root / "default.yaml", root / "smoke.yaml", * (root / "profiles").glob("*.yaml")]:
        config = load_config(path, environ={})
        assert config.target.base_url.startswith("http://127.0.0.1")
        assert config.load.users <= config.safeguards.max_users
