"""Status and JSON body checks for Locust ``catch_response`` blocks."""

from collections.abc import Iterable


def check_response(
    response,
    *,
    expected_status: int | Iterable[int] = 200,
    required_keys: Iterable[str] | None = None,
    expect_json: bool = True,
) -> None:
    """Mark a caught Locust response as a success or a validation failure."""
    if isinstance(expected_status, int):
        expected = (expected_status,)
    else:
        expected = tuple(expected_status)
    status = getattr(response, "status_code", None)
    if status not in expected:
        response.failure(f"status {status} not in {list(expected)}")
        return
    if not expect_json:
        response.success()
        return
    try:
        payload = response.json()
    except ValueError as exc:
        response.failure(f"invalid json: {exc}")
        return
    if required_keys:
        if not isinstance(payload, dict):
            response.failure("expected a JSON object")
            return
        missing = [key for key in required_keys if key not in payload]
        if missing:
            response.failure("missing keys: " + ", ".join(missing))
            return
    response.success()
