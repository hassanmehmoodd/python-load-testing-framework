"""Check that a run directory contains the expected report files."""

import json
from pathlib import Path

REQUIRED_RELATIVE_PATHS = (
    "summary.json",
    "summary.csv",
    "requests.csv",
    "endpoints.csv",
    "errors.csv",
    "report.md",
    "report.html",
    "locust-report.html",
    "graphs/response_time_over_time.png",
    "graphs/percentiles.png",
    "graphs/rps_over_time.png",
    "graphs/error_rate_over_time.png",
)


def validate_output_dir(directory: Path, *, strict_success: bool = False) -> dict:
    """Raise if artifacts are missing or the summary recorded no traffic."""
    missing = [rel for rel in REQUIRED_RELATIVE_PATHS if not (directory / rel).is_file()]
    if missing:
        joined = ", ".join(missing)
        raise FileNotFoundError(f"Missing report artifacts in {directory}: {joined}")
    summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    metrics = summary.get("metrics") or {}
    total = int(metrics.get("total_requests") or 0)
    if total <= 0:
        raise ValueError(f"{directory / 'summary.json'} recorded no requests.")
    failed = int(metrics.get("failed") or 0)
    if strict_success and failed != 0:
        raise ValueError(f"{directory} recorded {failed} failed requests.")
    return summary
