"""Matplotlib charts for a completed run."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg", force=True)
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from perfload.metrics import MetricsSummary  # noqa: E402

_BLUE = "#1f4e79"
_TEAL = "#0f766e"
_RED = "#b42318"
_AMBER = "#b54708"
_INK = "#24292f"


def _apply_style() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.edgecolor": "#d0d7de",
            "axes.labelcolor": _INK,
            "xtick.color": _INK,
            "ytick.color": _INK,
            "axes.titleweight": "bold",
            "axes.grid": True,
            "grid.color": "#eaeef2",
            "grid.linewidth": 0.8,
            "font.size": 11,
            "axes.titlesize": 13,
        }
    )


def _bucket(frame: pd.DataFrame) -> pd.DataFrame:
    working = frame.copy()
    start = float(working["timestamp"].min())
    working["elapsed_s"] = working["timestamp"].astype(float) - start
    working["bucket"] = working["elapsed_s"].floordiv(1).astype(int)
    return working


def render_graphs(records: list[dict], summary: MetricsSummary, output_dir: Path) -> list[Path]:
    """Write the four standard charts and return their paths."""
    _apply_style()
    output_dir.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(records)
    paths = [
        _response_time(frame, output_dir / "response_time_over_time.png"),
        _percentiles(summary, output_dir / "percentiles.png"),
        _rps(frame, output_dir / "rps_over_time.png"),
        _error_rate(frame, output_dir / "error_rate_over_time.png"),
    ]
    plt.close("all")
    return paths


def _response_time(frame: pd.DataFrame, path: Path) -> Path:
    figure, axis = plt.subplots(figsize=(10, 4.5))
    if frame.empty or "timestamp" not in frame.columns:
        axis.set_title("Response time over time")
        figure.savefig(path, dpi=120, bbox_inches="tight")
        plt.close(figure)
        return path
    bucketed = _bucket(frame)
    grouped = bucketed.groupby("bucket")["response_time_ms"]
    mean = grouped.mean()
    p95 = grouped.quantile(0.95, interpolation="linear")
    axis.plot(mean.index, mean.values, color=_BLUE, linewidth=2, label="Mean")
    axis.plot(p95.index, p95.values, color=_AMBER, linewidth=2, label="P95")
    axis.set_title("Response time over time")
    axis.set_xlabel("Elapsed seconds")
    axis.set_ylabel("Response time (ms)")
    axis.legend(frameon=False)
    figure.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(figure)
    return path


def _percentiles(summary: MetricsSummary, path: Path) -> Path:
    labels = ["Min", "Median", "Average", "P90", "P95", "P99", "Max"]
    values = [
        summary.min_ms,
        summary.median_ms,
        summary.average_ms,
        summary.p90_ms,
        summary.p95_ms,
        summary.p99_ms,
        summary.max_ms,
    ]
    figure, axis = plt.subplots(figsize=(10, 4.5))
    colors = [_TEAL, _BLUE, _BLUE, _BLUE, _AMBER, _AMBER, _RED]
    bars = axis.bar(labels, values, color=colors)
    axis.bar_label(bars, fmt="%.1f", padding=3, fontsize=9)
    axis.set_title("Response time percentiles")
    axis.set_ylabel("Milliseconds")
    figure.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(figure)
    return path


def _rps(frame: pd.DataFrame, path: Path) -> Path:
    figure, axis = plt.subplots(figsize=(10, 4.5))
    if frame.empty or "timestamp" not in frame.columns:
        axis.set_title("Requests per second")
        figure.savefig(path, dpi=120, bbox_inches="tight")
        plt.close(figure)
        return path
    counts = _bucket(frame).groupby("bucket").size()
    axis.plot(counts.index, counts.values, color=_TEAL, linewidth=2, marker="o", markersize=3)
    axis.fill_between(counts.index, counts.values, color=_TEAL, alpha=0.12)
    axis.set_title("Requests per second")
    axis.set_xlabel("Elapsed seconds")
    axis.set_ylabel("Completed requests in the 1s bucket")
    figure.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(figure)
    return path


def _error_rate(frame: pd.DataFrame, path: Path) -> Path:
    figure, axis = plt.subplots(figsize=(10, 4.5))
    axis.set_ylim(0, 100)
    if frame.empty or "timestamp" not in frame.columns or "success" not in frame.columns:
        axis.set_title("Error rate over time")
        figure.savefig(path, dpi=120, bbox_inches="tight")
        plt.close(figure)
        return path
    bucketed = _bucket(frame)
    grouped = bucketed.groupby("bucket")["success"]
    rate = (1 - grouped.mean().astype(float)) * 100.0
    axis.plot(rate.index, rate.values, color=_RED, linewidth=2)
    axis.fill_between(rate.index, rate.values, color=_RED, alpha=0.12)
    axis.set_title("Error rate over time")
    axis.set_xlabel("Elapsed seconds")
    axis.set_ylabel("Failed requests (%)")
    figure.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(figure)
    return path
