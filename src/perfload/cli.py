"""Command line entry point."""

import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path

from perfload.artifacts import validate_output_dir
from perfload.config import load_config
from perfload.exceptions import ConfigError, PreflightError, RunError, SafeguardError
from perfload.preflight import wait_for_health
from perfload.runner import execute
from perfload.safeguards import acknowledgement_enabled, prepare_run


def build_parser():
    import argparse

    parser = argparse.ArgumentParser(
        prog="perfload",
        description=(
            "Safety-first load tests. The default target is the local demo API. "
            "Non-allowlisted hosts are refused unless you explicitly acknowledge "
            "that you are authorized to test them. Public third-party hosts are "
            "always refused."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run a headless load test and write a report")
    _add_load_args(run)
    run.add_argument(
        "--wait-for-target",
        type=float,
        default=0,
        help="Seconds to wait for GET /health (0 tries once).",
    )

    check = sub.add_parser("check-target", help="Check that GET /health returns 200")
    _add_load_args(check)
    check.add_argument("--wait-for-target", type=float, default=5)

    validate = sub.add_parser("validate", help="Check that a report directory is complete")
    validate.add_argument("--output", required=True, help="Directory written by perfload run")
    validate.add_argument(
        "--strict-success",
        action="store_true",
        help="Also fail when the summary contains any failed request.",
    )
    return parser


def _add_load_args(parser) -> None:
    parser.add_argument("--config", default="config/default.yaml", help="YAML config path")
    parser.add_argument("--profile", choices=["constant", "ramp", "stress", "spike", "endurance"])
    parser.add_argument("--users", type=int)
    parser.add_argument("--spawn-rate", type=float)
    parser.add_argument("--duration", type=int, help="Duration in seconds")
    parser.add_argument("--base-url")
    parser.add_argument("--output", help="Directory for reports, CSV, JSON, and graphs")
    parser.add_argument(
        "--acknowledge-authorization",
        action="store_true",
        help=(
            "Confirm you own or are authorized to test a host that is not on the "
            "allowlist. Does not permit public third-party services."
        ),
    )


def overrides_from_args(args) -> dict:
    """Nested overrides for flags that were actually passed."""
    overlay: dict = {}
    load: dict = {}
    if getattr(args, "profile", None):
        load["profile"] = args.profile
    if getattr(args, "users", None) is not None:
        load["users"] = args.users
    if getattr(args, "spawn_rate", None) is not None:
        load["spawn_rate"] = args.spawn_rate
    if getattr(args, "duration", None) is not None:
        load["duration_seconds"] = args.duration
    if load:
        overlay["load"] = load
    if getattr(args, "base_url", None):
        overlay["target"] = {"base_url": args.base_url}
    if getattr(args, "output", None):
        overlay["output"] = {"directory": args.output}
    return overlay


def load_plan(args, environ: Mapping[str, str]):
    try:
        config = load_config(
            Path(args.config),
            overrides=overrides_from_args(args),
            environ=environ,
        )
        acknowledge = acknowledgement_enabled(
            bool(getattr(args, "acknowledge_authorization", False)),
            environ,
        )
        return prepare_run(config, acknowledge=acknowledge)
    except (ConfigError, SafeguardError) as exc:
        print(f"perfload: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


def _print_warnings(plan) -> None:
    for warning in plan.warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    print(
        f"Safeguards passed for {plan.config.target.base_url} "
        f"(host {plan.host}, profile {plan.config.load.profile}, "
        f"users {plan.config.load.users}, spawn rate {plan.config.load.spawn_rate}).",
        file=sys.stderr,
    )


def run_command(args, environ: Mapping[str, str] | None = None) -> None:
    env = os.environ if environ is None else environ
    plan = load_plan(args, env)
    _print_warnings(plan)
    output = Path(plan.config.output.directory)
    try:
        execute(plan, output, wait_for_target=args.wait_for_target, environ=dict(env))
    except PreflightError as exc:
        print(f"perfload: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc
    except RunError as exc:
        print(f"perfload: {exc}", file=sys.stderr)
        raise SystemExit(4) from exc


def check_command(args, environ: Mapping[str, str] | None = None) -> None:
    env = os.environ if environ is None else environ
    plan = load_plan(args, env)
    _print_warnings(plan)
    try:
        wait_for_health(plan.config.target.base_url, timeout_seconds=args.wait_for_target)
    except PreflightError as exc:
        print(f"perfload: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc
    print(f"Target healthy: {plan.config.target.base_url}/health")


def validate_command(args) -> None:
    try:
        summary = validate_output_dir(Path(args.output), strict_success=args.strict_success)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"perfload: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    total = summary["metrics"]["total_requests"]
    print(f"Report OK: {total} requests in {args.output}")


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        run_command(args)
    elif args.command == "check-target":
        check_command(args)
    elif args.command == "validate":
        validate_command(args)
    else:
        parser.print_help()
        raise SystemExit(2)


if __name__ == "__main__":
    main()
