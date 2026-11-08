"""Host policy and hard caps."""

import pytest

from perfload.config import load_config
from perfload.constants import ABSOLUTE_MAX_USERS
from perfload.exceptions import SafeguardError
from perfload.safeguards import enforce_runtime, host_of, prepare_run
from tests.conftest import BASE_CONFIG, write_config


def _plan(tmp_path, body: str, *, acknowledge: bool = False):
    path = tmp_path / "config.yaml"
    write_config(path, body)
    return prepare_run(load_config(path, environ={}), acknowledge=acknowledge)


def test_localhost_is_allowed(tmp_path):
    plan = _plan(tmp_path, BASE_CONFIG)
    assert plan.host == "127.0.0.1"
    assert plan.stages[-1].users == 5
    assert plan.warnings == ()


def test_ipv6_localhost_is_allowed(tmp_path):
    body = BASE_CONFIG.replace("http://127.0.0.1:8000", "http://[::1]:8000")
    plan = _plan(tmp_path, body)
    assert plan.host == "::1"


def test_public_host_is_blocked_even_with_acknowledgement(tmp_path):
    body = BASE_CONFIG.replace("http://127.0.0.1:8000", "https://api.github.com")
    with pytest.raises(SafeguardError, match="denylist"):
        _plan(tmp_path, body, acknowledge=True)


def test_non_allowlisted_host_requires_acknowledgement(tmp_path):
    body = BASE_CONFIG.replace("http://127.0.0.1:8000", "http://example.com:8080")
    with pytest.raises(SafeguardError, match="allowlist"):
        _plan(tmp_path, body)
    plan = _plan(tmp_path, body, acknowledge=True)
    assert plan.host == "example.com"
    assert plan.warnings
    assert "authorized" in plan.warnings[0].lower() or "Authorization" in plan.warnings[0]


def test_users_above_configured_cap_are_rejected(tmp_path):
    body = BASE_CONFIG.replace("users: 5", "users: 26")
    with pytest.raises(SafeguardError, match="hard cap"):
        _plan(tmp_path, body)


def test_spawn_rate_above_configured_cap_is_rejected(tmp_path):
    body = BASE_CONFIG.replace("spawn_rate: 1\n", "spawn_rate: 11\n")
    with pytest.raises(SafeguardError, match="spawn rate"):
        _plan(tmp_path, body)


def test_config_cannot_raise_the_absolute_user_cap(tmp_path):
    body = BASE_CONFIG.replace("max_users: 25", f"max_users: {ABSOLUTE_MAX_USERS + 10}")
    body = body.replace("users: 5", "users: 5")
    with pytest.raises(SafeguardError, match="absolute cap"):
        _plan(tmp_path, body)


def test_duration_bounds(tmp_path):
    with pytest.raises(SafeguardError, match="Duration"):
        _plan(tmp_path, BASE_CONFIG.replace("duration_seconds: 25", "duration_seconds: 4"))
    with pytest.raises(SafeguardError, match="Duration"):
        _plan(tmp_path, BASE_CONFIG.replace("duration_seconds: 25", "duration_seconds: 601"))


def test_origin_must_not_include_a_path_or_credentials():
    with pytest.raises(SafeguardError, match="path"):
        host_of("http://127.0.0.1:8000/api")
    with pytest.raises(SafeguardError, match="credentials"):
        host_of("http://user:pass@127.0.0.1:8000")
    with pytest.raises(SafeguardError, match="http"):
        host_of("ftp://127.0.0.1")


def test_runtime_document_repeats_the_host_check():
    with pytest.raises(SafeguardError, match="denylist"):
        enforce_runtime(
            {
                "base_url": "https://github.com",
                "allowed_hosts": ["localhost"],
                "acknowledge_authorization": True,
                "stages": [{"end": 25, "users": 5, "spawn_rate": 1}],
                "users": 5,
                "spawn_rate": 1,
                "duration_seconds": 25,
                "max_users": 25,
                "max_spawn_rate": 10,
            }
        )
