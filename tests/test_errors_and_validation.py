"""Error categories and catch_response checks."""

from perfload.errors import categorize
from perfload.validation import check_response


class FakeResponse:
    def __init__(self, status_code, payload=None, *, bad_json=False):
        self.status_code = status_code
        self._payload = payload
        self._bad_json = bad_json
        self.outcome = None
        self.message = None

    def json(self):
        if self._bad_json:
            raise ValueError("nope")
        return self._payload

    def failure(self, message):
        self.outcome = "failure"
        self.message = message

    def success(self):
        self.outcome = "success"


def test_categories():
    assert categorize(success=True, status_code=200, exception_type=None, error=None) == (
        "success",
        "success",
    )
    assert categorize(
        success=False,
        status_code=500,
        exception_type="CatchResponseError",
        error="status 500 not in [200]",
    ) == ("http_status", "500")
    assert categorize(
        success=False,
        status_code=None,
        exception_type="ConnectionError",
        error="timed out",
    ) == ("exception", "ConnectionError")
    assert categorize(
        success=False,
        status_code=200,
        exception_type="CatchResponseError",
        error="missing keys: id",
    ) == ("validation", "response_validation")
    assert categorize(
        success=False,
        status_code=200,
        exception_type="CatchResponseError",
        error="invalid json: nope",
    ) == ("validation", "response_validation")


def test_check_response_success_and_failures():
    ok = FakeResponse(200, {"items": [], "count": 0})
    check_response(ok, expected_status=200, required_keys=("items", "count"))
    assert ok.outcome == "success"

    missing = FakeResponse(200, {"items": []})
    check_response(missing, expected_status=200, required_keys=("items", "count"))
    assert missing.outcome == "failure"
    assert "missing keys" in missing.message

    status = FakeResponse(503, {"detail": "nope"})
    check_response(status, expected_status=200)
    assert status.outcome == "failure"
    assert "503" in status.message

    empty = FakeResponse(204)
    check_response(empty, expected_status=204, expect_json=False)
    assert empty.outcome == "success"

    broken = FakeResponse(200, bad_json=True)
    check_response(broken, expected_status=200)
    assert broken.outcome == "failure"
    assert "invalid json" in broken.message

    listing = FakeResponse(200, ["not", "an", "object"])
    check_response(listing, expected_status=200, required_keys=("items",))
    assert listing.outcome == "failure"
    assert "JSON object" in listing.message
