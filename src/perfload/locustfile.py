"""Locust user, response checks, and the active load-profile shape.

Start runs through ``perfload run`` so the safety checks execute first.
This module repeats those checks when Locust imports it.
"""

import json
import os
import sys
import threading
import time
import uuid

from locust import HttpUser, LoadTestShape, between, events, task

from perfload.errors import categorize
from perfload.exceptions import SafeguardError
from perfload.safeguards import enforce_runtime
from perfload.validation import check_response


def _bootstrap() -> dict:
    path = os.environ.get("PERFLOAD_RUNTIME_JSON", "").strip()
    if not path:
        sys.stderr.write(
            "perfload safeguard: PERFLOAD_RUNTIME_JSON is not set. "
            "Start the test with `perfload run` so host and load caps are enforced.\n"
        )
        raise SystemExit(2)
    try:
        with open(path, encoding="utf-8") as handle:
            runtime = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"perfload safeguard: could not read runtime file: {exc}\n")
        raise SystemExit(2) from exc
    try:
        enforce_runtime(runtime)
    except SafeguardError as exc:
        sys.stderr.write(f"perfload safeguard: {exc}\n")
        raise SystemExit(2) from exc
    return runtime


RUNTIME = _bootstrap()


class _JsonlLog:
    def __init__(self, path: str) -> None:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        self._handle = open(path, "w", encoding="utf-8")
        self._lock = threading.Lock()
        self._closed = False

    def write(self, record: dict) -> None:
        line = json.dumps(record, separators=(",", ":"))
        with self._lock:
            if self._closed:
                return
            self._handle.write(line + "\n")
            self._handle.flush()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._handle.close()
            self._closed = True


LOG = _JsonlLog(str(RUNTIME["request_log"]))


def _on_request(
    request_type,
    name,
    response_time,
    response_length,
    response,
    context,
    exception,
    **kwargs,
) -> None:
    del context, kwargs
    try:
        status = getattr(response, "status_code", None) if response is not None else None
        exception_type = type(exception).__name__ if exception is not None else None
        error = str(exception) if exception is not None else None
        success = exception is None
        category, key = categorize(
            success=success,
            status_code=status,
            exception_type=exception_type,
            error=error,
        )
        LOG.write(
            {
                "timestamp": time.time(),
                "method": request_type,
                "name": name,
                "response_time_ms": float(response_time),
                "status_code": status,
                "success": success,
                "exception_type": exception_type,
                "error": error,
                "bytes": int(response_length or 0),
                "category": category,
                "category_key": key,
            }
        )
    except Exception as exc:  # noqa: BLE001 - recorder must not break the test
        sys.stderr.write(f"perfload recorder: {exc}\n")


events.request.add_listener(_on_request)


@events.quitting.add_listener
def _close_log(environment, **kwargs) -> None:
    del environment, kwargs
    LOG.close()


class CatalogUser(HttpUser):
    """Concurrent virtual user. Locust runs one greenlet per spawned user.

    ``on_start`` logs in once and reuses the bearer token on later tasks.
    """

    host = str(RUNTIME["base_url"])
    wait_time = between(float(RUNTIME["wait_min_seconds"]), float(RUNTIME["wait_max_seconds"]))

    def on_start(self) -> None:
        self.token: str | None = None
        self.item_id: int | None = None
        self.client.timeout = 10
        self._login()

    def _login(self) -> None:
        for _ in range(3):
            with self.client.post(
                str(RUNTIME["login_path"]),
                json={
                    "username": RUNTIME["username"],
                    "password": RUNTIME["password"],
                },
                name="POST /api/v1/auth/login",
                catch_response=True,
            ) as response:
                if response.status_code != 200:
                    response.failure(f"login status {response.status_code}")
                    continue
                try:
                    payload = response.json()
                    token = payload["access_token"]
                except (ValueError, KeyError, TypeError) as exc:
                    response.failure(f"login body: {exc}")
                    continue
                if not token:
                    response.failure("empty token")
                    continue
                response.success()
                self.token = str(token)
                self.client.headers["Authorization"] = f"Bearer {self.token}"
                return

    def _body(self, quantity: int = 1) -> dict:
        suffix = uuid.uuid4().hex[:8]
        return {"name": f"item-{suffix}", "sku": f"SKU-{suffix}", "quantity": quantity}

    def _ensure_item(self) -> int | None:
        if self.item_id is not None:
            return self.item_id
        with self.client.post(
            "/api/v1/items",
            json=self._body(),
            name="POST /api/v1/items",
            catch_response=True,
        ) as response:
            check_response(
                response,
                expected_status=201,
                required_keys=("id", "name", "sku", "quantity"),
            )
            if response.status_code == 201:
                try:
                    self.item_id = int(response.json()["id"])
                except (ValueError, KeyError, TypeError):
                    return None
        return self.item_id

    @task(5)
    def list_items(self) -> None:
        with self.client.get(
            "/api/v1/items",
            name="GET /api/v1/items",
            catch_response=True,
        ) as response:
            check_response(response, expected_status=200, required_keys=("items", "count"))

    @task(3)
    def create_item(self) -> None:
        with self.client.post(
            "/api/v1/items",
            json=self._body(),
            name="POST /api/v1/items",
            catch_response=True,
        ) as response:
            check_response(
                response,
                expected_status=201,
                required_keys=("id", "name", "sku", "quantity"),
            )
            if response.status_code == 201:
                try:
                    self.item_id = int(response.json()["id"])
                except (ValueError, KeyError, TypeError):
                    return

    @task(3)
    def get_item(self) -> None:
        item_id = self._ensure_item()
        if item_id is None:
            return
        with self.client.get(
            f"/api/v1/items/{item_id}",
            name="GET /api/v1/items/:id",
            catch_response=True,
        ) as response:
            check_response(response, expected_status=200, required_keys=("id", "name"))

    @task(2)
    def replace_item(self) -> None:
        item_id = self._ensure_item()
        if item_id is None:
            return
        with self.client.put(
            f"/api/v1/items/{item_id}",
            json=self._body(quantity=2),
            name="PUT /api/v1/items/:id",
            catch_response=True,
        ) as response:
            check_response(response, expected_status=200, required_keys=("id", "quantity"))

    @task(2)
    def patch_item(self) -> None:
        item_id = self._ensure_item()
        if item_id is None:
            return
        with self.client.patch(
            f"/api/v1/items/{item_id}",
            json={"quantity": 4},
            name="PATCH /api/v1/items/:id",
            catch_response=True,
        ) as response:
            check_response(response, expected_status=200, required_keys=("id", "quantity"))

    @task(1)
    def delete_item(self) -> None:
        item_id = self._ensure_item()
        if item_id is None:
            return
        deleted = False
        with self.client.delete(
            f"/api/v1/items/{item_id}",
            name="DELETE /api/v1/items/:id",
            catch_response=True,
        ) as response:
            check_response(response, expected_status=204, expect_json=False)
            deleted = response.status_code == 204
        if deleted:
            self.item_id = None

    @task(1)
    def current_user(self) -> None:
        with self.client.get(
            str(RUNTIME["me_path"]),
            name="GET /api/v1/auth/me",
            catch_response=True,
        ) as response:
            check_response(response, expected_status=200, required_keys=("username",))


class ProfileShape(LoadTestShape):
    """Step function built from the runtime stage plan.

    ``use_common_options`` tells Locust that ``--users``, ``--spawn-rate``, and
    ``--run-time`` are intentional. The stage list is still what changes the
    user count. ``tick`` also stops the run if it drifts past the planned duration.
    """

    use_common_options = True

    def tick(self):
        run_time = self.get_run_time()
        if run_time >= float(RUNTIME["duration_seconds"]) + 5:
            return None
        for stage in RUNTIME["stages"]:
            if run_time < float(stage["end"]):
                return int(stage["users"]), float(stage["spawn_rate"])
        return None
