"""Headless Locust execution and post-run reporting."""

import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from perfload import __version__
from perfload.exceptions import RunError
from perfload.exporters import write_exports
from perfload.graphs import render_graphs
from perfload.metrics import summarize
from perfload.preflight import wait_for_health
from perfload.report import write_reports
from perfload.safeguards import RunPlan


def build_locust_command(plan: RunPlan, output_dir: Path) -> list[str]:
    """Command that runs the packaged locustfile headlessly.

    Virtual users are the concurrency level: Locust schedules one greenlet per user.
    """
    locustfile = Path(__file__).resolve().parent / "locustfile.py"
    load = plan.config.load
    return [
        sys.executable,
        "-m",
        "locust",
        "-f",
        str(locustfile),
        "--headless",
        "--only-summary",
        "--host",
        plan.config.target.base_url,
        "--users",
        str(load.users),
        "--spawn-rate",
        str(load.spawn_rate),
        "--run-time",
        f"{load.duration_seconds + 30}s",
        "--exit-code-on-error",
        "1",
        "--html",
        str(output_dir / "locust-report.html"),
        "--csv",
        str(output_dir / "locust"),
        "--csv-full-history",
        "--stop-timeout",
        "3",
    ]


def runtime_document(plan: RunPlan, output_dir: Path) -> dict:
    """JSON document the locustfile re-validates before sending traffic."""
    load = plan.config.load
    auth = plan.config.target.auth
    guards = plan.config.safeguards
    return {
        "base_url": plan.config.target.base_url,
        "username": auth.username,
        "password": auth.password,
        "login_path": auth.login_path,
        "me_path": auth.me_path,
        "wait_min_seconds": load.wait_min_seconds,
        "wait_max_seconds": load.wait_max_seconds,
        "stages": [stage.as_dict() for stage in plan.stages],
        "request_log": str(output_dir / "requests.jsonl"),
        "acknowledge_authorization": plan.acknowledge,
        "profile": load.profile,
        "users": load.users,
        "spawn_rate": load.spawn_rate,
        "duration_seconds": load.duration_seconds,
        "allowed_hosts": list(guards.allowed_hosts),
        "max_users": guards.max_users,
        "max_spawn_rate": guards.max_spawn_rate,
    }


def _fault_injection(environ: dict[str, str]) -> dict[str, str]:
    def _read(name: str, default: str) -> str:
        raw = environ.get(name, "").strip()
        return raw if raw else default

    return {
        "latency_ms": _read("TARGET_LATENCY_MS", "0"),
        "jitter_ms": _read("TARGET_LATENCY_JITTER_MS", "0"),
        "error_rate": _read("TARGET_ERROR_RATE", "0"),
        "note": (
            "Taken from the runner environment. These apply only if the target "
            "process was started with the same variables."
        ),
    }


def _load_jsonl(path: Path) -> list[dict]:
    records: list[dict] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                records.append(json.loads(text))
            except json.JSONDecodeError as exc:
                raise RunError(f"Corrupt request log {path}:{line_number}: {exc}") from exc
    return records


def _print_summary(summary, output_dir: Path) -> None:
    print()
    print("Performance summary")
    print(f"  Total requests:     {summary.total_requests}")
    print(f"  Successful:         {summary.successful}")
    print(f"  Failed:             {summary.failed}")
    print(f"  Error percentage:   {summary.error_percentage:.2f}%")
    print(f"  Average ms:         {summary.average_ms:.2f}")
    print(f"  Median ms:          {summary.median_ms:.2f}")
    print(
        "  P90 / P95 / P99 ms: "
        f"{summary.p90_ms:.2f} / {summary.p95_ms:.2f} / {summary.p99_ms:.2f}"
    )
    print(f"  Min / max ms:       {summary.min_ms:.2f} / {summary.max_ms:.2f}")
    print(f"  Requests/s:         {summary.requests_per_second:.3f}")
    print(f"  Throughput B/s:     {summary.throughput_bytes_per_second:.1f}")
    print(f"  Report:             {output_dir / 'report.md'}")


def execute(
    plan: RunPlan,
    output_dir: Path,
    *,
    wait_for_target: float,
    environ: dict[str, str] | None = None,
) -> dict:
    """Run Locust, then write metrics, charts, and reports. Returns the summary JSON."""
    env = dict(os.environ if environ is None else environ)
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    wait_for_health(plan.config.target.base_url, timeout_seconds=wait_for_target)
    document = runtime_document(plan, output_dir)
    runtime_path = output_dir / "runtime.json"
    runtime_path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    env["PERFLOAD_RUNTIME_JSON"] = str(runtime_path)
    env["PYTHONUNBUFFERED"] = "1"

    started_at = datetime.now(UTC)
    clock = time.perf_counter()
    completed = subprocess.run(
        build_locust_command(plan, output_dir),
        env=env,
        cwd=output_dir,
        check=False,
    )
    elapsed = time.perf_counter() - clock
    finished_at = datetime.now(UTC)
    log_path = output_dir / "requests.jsonl"
    if completed.returncode not in (0, 1):
        raise RunError(f"Locust exited with code {completed.returncode}.")
    if not log_path.is_file():
        raise RunError("Locust did not write a request log.")

    records = _load_jsonl(log_path)
    summary = summarize(records, elapsed_seconds=elapsed)
    try:
        locust_version = importlib.metadata.version("locust")
    except importlib.metadata.PackageNotFoundError:
        locust_version = "unknown"
    meta = {
        "framework": "perfload",
        "version": __version__,
        "profile": plan.config.load.profile,
        "base_url": plan.config.target.base_url,
        "host": plan.host,
        "users": plan.config.load.users,
        "spawn_rate": plan.config.load.spawn_rate,
        "duration_seconds": plan.config.load.duration_seconds,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "locust": locust_version,
        "concurrency_model": "locust gevent virtual users (one greenlet per user)",
        "stages": document["stages"],
        "target_fault_injection": _fault_injection(env),
    }
    write_exports(records, summary, meta, output_dir)
    render_graphs(records, summary, output_dir / "graphs")
    write_reports(meta, summary, output_dir)
    _print_summary(summary, output_dir)
    summary_path = output_dir / "summary.json"
    return json.loads(summary_path.read_text(encoding="utf-8"))
