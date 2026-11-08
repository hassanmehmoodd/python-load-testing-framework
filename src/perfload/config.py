"""YAML, environment, and CLI configuration."""

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from perfload.constants import PROFILES
from perfload.exceptions import ConfigError

_ENV_PATHS: dict[str, tuple[str, ...]] = {
    "PERFLOAD_BASE_URL": ("target", "base_url"),
    "PERFLOAD_USERNAME": ("target", "auth", "username"),
    "PERFLOAD_PASSWORD": ("target", "auth", "password"),
    "PERFLOAD_USERS": ("load", "users"),
    "PERFLOAD_SPAWN_RATE": ("load", "spawn_rate"),
    "PERFLOAD_DURATION": ("load", "duration_seconds"),
    "PERFLOAD_PROFILE": ("load", "profile"),
    "PERFLOAD_OUTPUT_DIR": ("output", "directory"),
}


class AuthConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    login_path: str = "/api/v1/auth/login"
    me_path: str = "/api/v1/auth/me"
    username: str = "demo"
    password: str = "demo-pass"


class TargetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str = "http://127.0.0.1:8000"
    auth: AuthConfig = Field(default_factory=AuthConfig)


class SafeguardConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_users: int = 25
    max_spawn_rate: float = 10
    allowed_hosts: list[str] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1", "::1"]
    )


class LoadConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: str = "ramp"
    users: int = 10
    spawn_rate: float = 2
    duration_seconds: int = 40
    wait_min_seconds: float = 0.05
    wait_max_seconds: float = 0.2

    @model_validator(mode="after")
    def check_profile_and_waits(self) -> "LoadConfig":
        if self.profile not in PROFILES:
            known = ", ".join(PROFILES)
            raise ValueError(f"profile must be one of: {known}.")
        if self.wait_min_seconds < 0 or self.wait_max_seconds < 0:
            raise ValueError("wait times must be >= 0.")
        if self.wait_min_seconds > self.wait_max_seconds:
            raise ValueError("wait_min_seconds cannot exceed wait_max_seconds.")
        return self


class OutputConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    directory: str = "reports/latest"


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: TargetConfig = Field(default_factory=TargetConfig)
    safeguards: SafeguardConfig = Field(default_factory=SafeguardConfig)
    load: LoadConfig = Field(default_factory=LoadConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)


def deep_merge(base: Mapping[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    """Merge nested dictionaries. Overlay values replace base values."""
    merged = dict(base)
    for key, value in overlay.items():
        current = merged.get(key)
        if isinstance(value, dict) and isinstance(current, dict):
            merged[key] = deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def _set_path(payload: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    cursor = payload
    for key in path[:-1]:
        child = cursor.get(key)
        if not isinstance(child, dict):
            child = {}
            cursor[key] = child
        cursor = child
    cursor[path[-1]] = value


def apply_environment(payload: dict[str, Any], environ: Mapping[str, str]) -> dict[str, Any]:
    """Copy ``payload`` and apply known PERFLOAD_* variables."""
    updated = deep_merge(payload, {})
    casters = {
        "PERFLOAD_USERS": int,
        "PERFLOAD_SPAWN_RATE": float,
        "PERFLOAD_DURATION": int,
    }
    for name, path in _ENV_PATHS.items():
        if name not in environ:
            continue
        raw = environ[name].strip()
        if raw == "":
            continue
        caster = casters.get(name, str)
        try:
            value = caster(raw)
        except ValueError as exc:
            raise ConfigError(f"{name}={raw!r} is not a valid {caster.__name__}.") from exc
        _set_path(updated, path, value)
    return updated


def load_config(
    path: Path,
    *,
    overrides: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
) -> AppConfig:
    """Load YAML, then environment variables, then explicit overrides."""
    if not path.is_file():
        raise ConfigError(f"Config file not found: {path}")
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"Could not parse {path}: {exc}") from exc
    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict):
        raise ConfigError(f"Config root in {path} must be a mapping.")
    merged = apply_environment(loaded, os.environ if environ is None else environ)
    if overrides:
        merged = deep_merge(merged, overrides)
    try:
        return AppConfig.model_validate(merged)
    except ValidationError as exc:
        raise ConfigError(f"Invalid configuration in {path}: {exc}") from exc
