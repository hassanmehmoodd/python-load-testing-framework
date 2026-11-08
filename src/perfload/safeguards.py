"""Host allowlists, public-host denylist, and hard caps on load."""

from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlparse

from perfload.config import AppConfig
from perfload.constants import (
    ABSOLUTE_MAX_DURATION_SECONDS,
    ABSOLUTE_MAX_SPAWN_RATE,
    ABSOLUTE_MAX_USERS,
    ACK_TRUTHY,
    MIN_DURATION_SECONDS,
    PUBLIC_DENYLIST_SUFFIXES,
)
from perfload.exceptions import SafeguardError
from perfload.profiles import Stage, build_stages


@dataclass(frozen=True)
class RunPlan:
    """A configuration that has passed the safety checks."""

    config: AppConfig
    stages: list[Stage]
    acknowledge: bool
    host: str
    warnings: tuple[str, ...]


def acknowledgement_enabled(cli_flag: bool, environ: Mapping[str, str]) -> bool:
    """True when the CLI flag or the acknowledgement env var is set."""
    if cli_flag:
        return True
    raw = environ.get("PERFLOAD_ACKNOWLEDGE_AUTHORIZATION", "").strip().lower()
    return raw in ACK_TRUTHY


def host_of(base_url: str) -> str:
    """Return the hostname of an http(s) origin."""
    parsed = urlparse(base_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SafeguardError(f"base_url must be an http(s) origin, got {base_url!r}.")
    if parsed.username or parsed.password:
        raise SafeguardError("base_url must not include credentials.")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise SafeguardError("base_url must be an origin without a path, query, or fragment.")
    return parsed.hostname.lower().rstrip(".")


def denied_suffix(host: str) -> str | None:
    """Return the denylist suffix that matches ``host``, if any."""
    normalized = host.lower().rstrip(".")
    for suffix in PUBLIC_DENYLIST_SUFFIXES:
        if normalized == suffix or normalized.endswith("." + suffix):
            return suffix
    return None


def host_is_allowlisted(host: str, allowed_hosts: list[str]) -> bool:
    allowed = {item.lower().rstrip(".") for item in allowed_hosts}
    return host.lower().rstrip(".") in allowed


def enforce_host(
    *,
    host: str,
    base_url: str,
    allowed_hosts: list[str],
    acknowledge: bool,
) -> str | None:
    """Refuse public and non-allowlisted hosts. Returns a warning when ack is used."""
    suffix = denied_suffix(host)
    if suffix is not None:
        raise SafeguardError(
            f"Refusing to load test {base_url}. Host {host!r} matches the public-host "
            f"denylist ({suffix}). Acknowledgement does not override this. perfload will "
            "not target well-known third-party services."
        )
    if host_is_allowlisted(host, allowed_hosts):
        return None
    if not acknowledge:
        allowed = ", ".join(allowed_hosts) or "(empty)"
        raise SafeguardError(
            f"Refusing to load test {base_url}. Host {host!r} is not in the allowlist "
            f"({allowed}). The default target is the local demo API. To test a system you "
            "own, add its host to safeguards.allowed_hosts, or set "
            "PERFLOAD_ACKNOWLEDGE_AUTHORIZATION=yes (or pass --acknowledge-authorization). "
            "That acknowledgement does not permit public third-party services."
        )
    return (
        "Authorization acknowledgement is set. You confirmed this process may test "
        f"{base_url}. Load test only systems you own or are explicitly permitted to test."
    )


def enforce_limits(
    *,
    users: int,
    spawn_rate: float,
    duration_seconds: int,
    max_users: int,
    max_spawn_rate: float,
    stages: list[Mapping[str, object]] | list[Stage],
) -> None:
    """Reject loads above the configured cap or the absolute cap."""
    if max_users < 1 or max_users > ABSOLUTE_MAX_USERS:
        raise SafeguardError(
            f"safeguards.max_users is {max_users}, which is outside 1..{ABSOLUTE_MAX_USERS}. "
            "The absolute cap lives in code so a config file cannot raise it."
        )
    if max_spawn_rate <= 0 or max_spawn_rate > ABSOLUTE_MAX_SPAWN_RATE:
        raise SafeguardError(
            f"safeguards.max_spawn_rate is {max_spawn_rate}, which is outside "
            f"0..{ABSOLUTE_MAX_SPAWN_RATE}. The absolute cap lives in code."
        )
    if users < 1 or users > max_users:
        raise SafeguardError(
            f"Requested users {users} exceeds the configured hard cap of {max_users} "
            f"(absolute cap {ABSOLUTE_MAX_USERS})."
        )
    if spawn_rate <= 0 or spawn_rate > max_spawn_rate:
        raise SafeguardError(
            f"Requested spawn rate {spawn_rate} exceeds the configured hard cap of "
            f"{max_spawn_rate} users/second (absolute cap {ABSOLUTE_MAX_SPAWN_RATE})."
        )
    if duration_seconds < MIN_DURATION_SECONDS or duration_seconds > ABSOLUTE_MAX_DURATION_SECONDS:
        raise SafeguardError(
            f"Duration {duration_seconds}s is outside "
            f"{MIN_DURATION_SECONDS}..{ABSOLUTE_MAX_DURATION_SECONDS}s."
        )
    for stage in stages:
        if isinstance(stage, Stage):
            stage_users = stage.users
            stage_spawn = stage.spawn_rate
        else:
            stage_users = int(stage["users"])
            stage_spawn = float(stage["spawn_rate"])
        if stage_users > max_users or stage_spawn > max_spawn_rate:
            raise SafeguardError(
                f"Profile stage users={stage_users}, spawn_rate={stage_spawn} exceeds "
                f"the cap of {max_users} users and {max_spawn_rate} users/second."
            )


def prepare_run(config: AppConfig, *, acknowledge: bool) -> RunPlan:
    """Validate a loaded config and return the stage plan Locust will follow."""
    host = host_of(config.target.base_url)
    warning = enforce_host(
        host=host,
        base_url=config.target.base_url,
        allowed_hosts=list(config.safeguards.allowed_hosts),
        acknowledge=acknowledge,
    )
    stages = build_stages(
        config.load.profile,
        users=config.load.users,
        spawn_rate=config.load.spawn_rate,
        duration_seconds=config.load.duration_seconds,
    )
    enforce_limits(
        users=config.load.users,
        spawn_rate=config.load.spawn_rate,
        duration_seconds=config.load.duration_seconds,
        max_users=config.safeguards.max_users,
        max_spawn_rate=config.safeguards.max_spawn_rate,
        stages=stages,
    )
    warnings: list[str] = []
    if warning:
        warnings.append(warning)
    if config.load.duration_seconds > 180:
        warnings.append(
            "Duration is above 180s. Shipped endurance profiles use a short demo duration "
            "on purpose. Confirm this target is yours before running longer."
        )
    return RunPlan(
        config=config,
        stages=stages,
        acknowledge=acknowledge,
        host=host,
        warnings=tuple(warnings),
    )


def enforce_runtime(runtime: Mapping[str, object]) -> None:
    """Re-check the runtime document the Locust process is about to execute."""
    base_url = str(runtime["base_url"])
    host = host_of(base_url)
    allowed = [str(item) for item in runtime["allowed_hosts"]]  # type: ignore[union-attr]
    enforce_host(
        host=host,
        base_url=base_url,
        allowed_hosts=allowed,
        acknowledge=bool(runtime["acknowledge_authorization"]),
    )
    stages = runtime["stages"]
    if not isinstance(stages, list):
        raise SafeguardError("runtime stages must be a list.")
    enforce_limits(
        users=int(runtime["users"]),  # type: ignore[arg-type]
        spawn_rate=float(runtime["spawn_rate"]),  # type: ignore[arg-type]
        duration_seconds=int(runtime["duration_seconds"]),  # type: ignore[arg-type]
        max_users=int(runtime["max_users"]),  # type: ignore[arg-type]
        max_spawn_rate=float(runtime["max_spawn_rate"]),  # type: ignore[arg-type]
        stages=stages,
    )
