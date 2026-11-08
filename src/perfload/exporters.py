"""CSV and JSON exports of a completed run."""

import json
from pathlib import Path

import pandas as pd

from perfload.metrics import MetricsSummary

_REQUEST_COLUMNS = [
    "timestamp",
    "method",
    "name",
    "response_time_ms",
    "status_code",
    "success",
    "exception_type",
    "error",
    "bytes",
    "category",
    "category_key",
]


def write_exports(
    records: list[dict],
    summary: MetricsSummary,
    meta: dict,
    output_dir: Path,
) -> None:
    """Write summary.json plus request, endpoint, error, and one-row summary CSVs."""
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": meta,
        "metrics": {
            key: value
            for key, value in summary.to_dict().items()
            if key not in {"endpoints", "errors"}
        },
        "endpoints": _plain(summary.endpoints),
        "errors": _plain(summary.errors),
        "stages": meta.get("stages", []),
    }
    (output_dir / "summary.json").write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )

    frame = pd.DataFrame(records)
    for column in _REQUEST_COLUMNS:
        if column not in frame.columns:
            frame[column] = pd.NA
    frame[_REQUEST_COLUMNS].to_csv(output_dir / "requests.csv", index=False)

    pd.DataFrame([payload["metrics"]]).to_csv(output_dir / "summary.csv", index=False)
    endpoints = payload["endpoints"] or [{"name": "", "total": 0}]
    pd.DataFrame(endpoints).to_csv(output_dir / "endpoints.csv", index=False)
    errors = payload["errors"] or [{"category": "", "key": "", "count": 0, "percentage": 0.0}]
    pd.DataFrame(errors).to_csv(output_dir / "errors.csv", index=False)


def _plain(items: list) -> list[dict]:
    from dataclasses import asdict, is_dataclass

    plain: list[dict] = []
    for item in items:
        if is_dataclass(item) and not isinstance(item, type):
            plain.append(asdict(item))
        else:
            plain.append(dict(item))
    return plain
