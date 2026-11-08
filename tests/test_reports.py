"""Exports, charts, and report files."""

import json

import pandas as pd

from perfload.artifacts import validate_output_dir
from perfload.exporters import write_exports
from perfload.graphs import render_graphs
from perfload.metrics import summarize
from perfload.report import write_reports
from tests.test_metrics import RECORDS


def _materialize(tmp_path):
    summary = summarize(RECORDS, elapsed_seconds=10)
    meta = {
        "version": "1.0.0",
        "profile": "ramp",
        "base_url": "http://127.0.0.1:8000",
        "users": 5,
        "spawn_rate": 1,
        "duration_seconds": 25,
        "started_at": "2026-01-01T00:00:00+00:00",
        "finished_at": "2026-01-01T00:00:10+00:00",
        "python": "3.12.3",
        "platform": "test-platform",
        "locust": "2.47.0",
        "concurrency_model": "locust gevent virtual users (one greenlet per user)",
        "stages": [{"end": 25, "users": 5, "spawn_rate": 1}],
        "target_fault_injection": {"latency_ms": "0", "jitter_ms": "0", "error_rate": "0"},
    }
    write_exports(RECORDS, summary, meta, tmp_path)
    render_graphs(RECORDS, summary, tmp_path / "graphs")
    write_reports(meta, summary, tmp_path)
    (tmp_path / "locust-report.html").write_text("<html>locust</html>", encoding="utf-8")
    return summary


def test_exports_and_reports_round_trip(tmp_path):
    summary = _materialize(tmp_path)
    loaded = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert loaded["metrics"]["total_requests"] == 5
    assert loaded["metrics"]["p95_ms"] == pytest_approx(summary.p95_ms)
    requests = pd.read_csv(tmp_path / "requests.csv")
    assert len(requests) == 5
    markdown = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "Total requests | 5" in markdown
    assert "P95 (ms) | 48.00" in markdown
    assert "Requests per second | 0.500" in markdown
    assert "Throughput (response bytes/s) | 35.0" in markdown
    document = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert "48.00" in document
    assert "data:image/png;base64," in document
    for name in (
        "response_time_over_time.png",
        "percentiles.png",
        "rps_over_time.png",
        "error_rate_over_time.png",
    ):
        image = tmp_path / "graphs" / name
        assert image.is_file()
        assert image.stat().st_size > 1000


def test_validate_output_dir(tmp_path):
    _materialize(tmp_path)
    summary = validate_output_dir(tmp_path)
    assert summary["metrics"]["total_requests"] == 5
    try:
        validate_output_dir(tmp_path, strict_success=True)
    except ValueError as exc:
        assert "failed" in str(exc)
    else:
        raise AssertionError("strict validation should reject failures")


def test_validate_missing_artifact(tmp_path):
    _materialize(tmp_path)
    (tmp_path / "report.md").unlink()
    try:
        validate_output_dir(tmp_path)
    except FileNotFoundError as exc:
        assert "report.md" in str(exc)
    else:
        raise AssertionError("expected FileNotFoundError")


def pytest_approx(value):
    import pytest

    return pytest.approx(value)
