"""Aggregate a request log into the headline performance metrics."""

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass

import pandas as pd

from perfload.exceptions import RunError


@dataclass(frozen=True)
class EndpointSummary:
    name: str
    total: int
    successful: int
    failed: int
    error_percentage: float
    average_ms: float
    median_ms: float
    p95_ms: float
    min_ms: float
    max_ms: float
    requests_per_second: float


@dataclass(frozen=True)
class ErrorSummary:
    category: str
    key: str
    count: int
    percentage: float


@dataclass(frozen=True)
class MetricsSummary:
    total_requests: int
    successful: int
    failed: int
    average_ms: float
    median_ms: float
    p90_ms: float
    p95_ms: float
    p99_ms: float
    min_ms: float
    max_ms: float
    requests_per_second: float
    throughput_bytes_per_second: float
    error_percentage: float
    elapsed_seconds: float
    total_bytes: int
    endpoints: list[EndpointSummary]
    errors: list[ErrorSummary]

    def to_dict(self) -> dict:
        return asdict(self)


def _quantile(values: pd.Series, quantile: float) -> float:
    if values.empty:
        return 0.0
    return float(values.quantile(quantile, interpolation="linear"))


def _endpoint_row(name: str, frame: pd.DataFrame, elapsed_seconds: float) -> EndpointSummary:
    times = frame["response_time_ms"].astype(float)
    total = int(len(frame))
    failed = int((~frame["success"].astype(bool)).sum())
    successful = total - failed
    return EndpointSummary(
        name=name,
        total=total,
        successful=successful,
        failed=failed,
        error_percentage=(failed / total * 100.0) if total else 0.0,
        average_ms=float(times.mean()) if total else 0.0,
        median_ms=_quantile(times, 0.50),
        p95_ms=_quantile(times, 0.95),
        min_ms=float(times.min()) if total else 0.0,
        max_ms=float(times.max()) if total else 0.0,
        requests_per_second=total / elapsed_seconds,
    )


def summarize(records: Sequence[Mapping], elapsed_seconds: float) -> MetricsSummary:
    """Compute totals, percentiles, throughput, and error buckets.

    Percentiles use pandas' linear interpolation (``Series.quantile``).
    Latency stats include every completed request, successful or failed.
    Requests per second and throughput use the runner wall clock.
    """
    if elapsed_seconds <= 0:
        raise RunError("elapsed_seconds must be > 0.")
    if not records:
        raise RunError("No requests were recorded.")

    frame = pd.DataFrame(list(records))
    required = {"response_time_ms", "success", "name"}
    missing = required.difference(frame.columns)
    if missing:
        raise RunError(f"Request records are missing fields: {sorted(missing)}")
    frame["response_time_ms"] = pd.to_numeric(frame["response_time_ms"], errors="coerce")
    frame = frame.dropna(subset=["response_time_ms"])
    if frame.empty:
        raise RunError("No requests had a numeric response time.")
    frame["success"] = frame["success"].astype(bool)
    if "bytes" not in frame.columns:
        frame["bytes"] = 0
    frame["bytes"] = pd.to_numeric(frame["bytes"], errors="coerce").fillna(0).astype(int)
    if "category" not in frame.columns:
        frame["category"] = "unknown"
    if "category_key" not in frame.columns:
        frame["category_key"] = "unknown"

    times = frame["response_time_ms"].astype(float)
    total = int(len(frame))
    failed = int((~frame["success"]).sum())
    successful = total - failed
    total_bytes = int(frame["bytes"].sum())

    endpoints = [
        _endpoint_row(str(name), group, elapsed_seconds)
        for name, group in frame.groupby("name", sort=False)
    ]
    endpoints.sort(key=lambda item: (-item.total, item.name))

    failures = frame.loc[~frame["success"]]
    errors: list[ErrorSummary] = []
    if not failures.empty:
        grouped = (
            failures.groupby(["category", "category_key"], dropna=False)
            .size()
            .reset_index(name="n")
        )
        for row in grouped.itertuples(index=False):
            count = int(row.n)
            errors.append(
                ErrorSummary(
                    category=str(row.category),
                    key=str(row.category_key),
                    count=count,
                    percentage=count / total * 100.0,
                )
            )
        errors.sort(key=lambda item: (-item.count, item.category, item.key))

    return MetricsSummary(
        total_requests=total,
        successful=successful,
        failed=failed,
        average_ms=float(times.mean()),
        median_ms=_quantile(times, 0.50),
        p90_ms=_quantile(times, 0.90),
        p95_ms=_quantile(times, 0.95),
        p99_ms=_quantile(times, 0.99),
        min_ms=float(times.min()),
        max_ms=float(times.max()),
        requests_per_second=total / elapsed_seconds,
        throughput_bytes_per_second=total_bytes / elapsed_seconds,
        error_percentage=failed / total * 100.0,
        elapsed_seconds=float(elapsed_seconds),
        total_bytes=total_bytes,
        endpoints=endpoints,
        errors=errors,
    )
