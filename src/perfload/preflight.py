"""HTTPX health check before a load test starts."""

import time

import httpx

from perfload.exceptions import PreflightError


def wait_for_health(base_url: str, timeout_seconds: float) -> None:
    """GET ``/health`` until it returns 200 or the timeout elapses.

    A timeout of 0 tries once.
    """
    url = base_url.rstrip("/") + "/health"
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    last_error = "no response"
    while True:
        try:
            with httpx.Client(timeout=2.0) as client:
                response = client.get(url)
            if response.status_code == 200:
                return
            last_error = f"HTTP {response.status_code}"
        except httpx.HTTPError as exc:
            last_error = str(exc)
        if time.monotonic() >= deadline:
            raise PreflightError(
                f"GET {url} failed: {last_error}. Start the demo target with: "
                "python -m uvicorn target_app.app:app --host 127.0.0.1 --port 8000"
            )
        time.sleep(0.4)
