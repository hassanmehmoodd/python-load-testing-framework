"""Metric calculations against a known request set."""

import pytest

from perfload.exceptions import RunError
from perfload.metrics import summarize

RECORDS = [
    {
        "timestamp": 0,
        "name": "GET /a",
        "response_time_ms": 10,
        "success": True,
        "bytes": 100,
        "category": "success",
        "category_key": "success",
        "status_code": 200,
    },
    {
        "timestamp": 1,
        "name": "GET /a",
        "response_time_ms": 20,
        "success": True,
        "bytes": 100,
        "category": "success",
        "category_key": "success",
        "status_code": 200,
    },
    {
        "timestamp": 2,
        "name": "POST /a",
        "response_time_ms": 30,
        "success": True,
        "bytes": 100,
        "category": "success",
        "category_key": "success",
        "status_code": 201,
    },
    {
        "timestamp": 3,
        "name": "POST /a",
        "response_time_ms": 40,
        "success": False,
        "bytes": 50,
        "category": "http_status",
        "category_key": "500",
        "status_code": 500,
    },
    {
        "timestamp": 4,
        "name": "GET /a",
        "response_time_ms": 50,
        "success": False,
        "bytes": 0,
        "category": "exception",
        "category_key": "ConnectionError",
        "status_code": None,
    },
]


def test_headline_metrics_match_linear_percentiles():
    summary = summarize(RECORDS, elapsed_seconds=10)
    assert summary.total_requests == 5
    assert summary.successful == 3
    assert summary.failed == 2
    assert summary.error_percentage == pytest.approx(40.0)
    assert summary.average_ms == pytest.approx(30.0)
    assert summary.median_ms == pytest.approx(30.0)
    assert summary.p90_ms == pytest.approx(46.0)
    assert summary.p95_ms == pytest.approx(48.0)
    assert summary.p99_ms == pytest.approx(49.6)
    assert summary.min_ms == pytest.approx(10.0)
    assert summary.max_ms == pytest.approx(50.0)
    assert summary.requests_per_second == pytest.approx(0.5)
    assert summary.total_bytes == 350
    assert summary.throughput_bytes_per_second == pytest.approx(35.0)


def test_endpoint_and_error_breakdown():
    summary = summarize(RECORDS, elapsed_seconds=10)
    by_name = {item.name: item for item in summary.endpoints}
    assert by_name["GET /a"].total == 3
    assert by_name["GET /a"].failed == 1
    assert by_name["GET /a"].requests_per_second == pytest.approx(0.3)
    assert by_name["POST /a"].total == 2
    keys = {(item.category, item.key, item.count) for item in summary.errors}
    assert ("http_status", "500", 1) in keys
    assert ("exception", "ConnectionError", 1) in keys


def test_single_sample_percentiles_equal_that_sample():
    summary = summarize(
        [
            {
                "name": "GET /only",
                "response_time_ms": 12.5,
                "success": True,
                "bytes": 8,
                "category": "success",
                "category_key": "success",
            }
        ],
        elapsed_seconds=2,
    )
    assert summary.median_ms == pytest.approx(12.5)
    assert summary.p99_ms == pytest.approx(12.5)
    assert summary.failed == 0
    assert summary.errors == []


def test_empty_and_zero_elapsed_are_rejected():
    with pytest.raises(RunError):
        summarize([], elapsed_seconds=10)
    with pytest.raises(RunError):
        summarize(RECORDS, elapsed_seconds=0)
