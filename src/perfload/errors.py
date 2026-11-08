"""Group failed requests by HTTP status or exception type."""

CATCH_RESPONSE_TYPES = frozenset({"CatchResponseError"})
_VALIDATION_TOKENS = (
    "missing key",
    "invalid json",
    "empty token",
    "login body",
    "expected a json object",
)


def categorize(
    *,
    success: bool,
    status_code: int | None,
    exception_type: str | None,
    error: str | None,
) -> tuple[str, str]:
    """Return ``(category, key)`` for one completed request.

    Categories are ``success``, ``http_status``, ``validation``, ``exception``,
    and ``unknown``.
    """
    if success:
        return "success", "success"
    if exception_type and exception_type not in CATCH_RESPONSE_TYPES:
        return "exception", exception_type
    text = (error or "").lower()
    if any(token in text for token in _VALIDATION_TOKENS):
        return "validation", "response_validation"
    if status_code is not None and status_code >= 400:
        return "http_status", str(status_code)
    if status_code is not None and "status " in text:
        return "http_status", str(status_code)
    if exception_type:
        return "exception", exception_type
    return "unknown", "unknown"
