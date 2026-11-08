"""Shared fixtures for perfload tests."""

import pytest

_PERFLOAD_ENV = (
    "PERFLOAD_BASE_URL",
    "PERFLOAD_USERNAME",
    "PERFLOAD_PASSWORD",
    "PERFLOAD_USERS",
    "PERFLOAD_SPAWN_RATE",
    "PERFLOAD_DURATION",
    "PERFLOAD_PROFILE",
    "PERFLOAD_OUTPUT_DIR",
    "PERFLOAD_ACKNOWLEDGE_AUTHORIZATION",
    "PERFLOAD_RUNTIME_JSON",
    "TARGET_LATENCY_MS",
    "TARGET_LATENCY_JITTER_MS",
    "TARGET_ERROR_RATE",
    "TARGET_HOST",
    "TARGET_ALLOW_REMOTE_BIND",
)


@pytest.fixture(autouse=True)
def _clear_perfload_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _PERFLOAD_ENV:
        monkeypatch.delenv(name, raising=False)


def write_config(path, body: str) -> None:
    path.write_text(body.strip() + "\n", encoding="utf-8")


BASE_CONFIG = """
target:
  base_url: "http://127.0.0.1:8000"
  auth:
    username: "demo"
    password: "demo-pass"
safeguards:
  max_users: 25
  max_spawn_rate: 10
  allowed_hosts:
    - localhost
    - 127.0.0.1
    - "::1"
load:
  profile: constant
  users: 5
  spawn_rate: 1
  duration_seconds: 25
  wait_min_seconds: 0.05
  wait_max_seconds: 0.2
output:
  directory: reports/test
"""
