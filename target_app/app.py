"""In-memory catalog API with token auth and fault injection.

This process is the default load-test target. It binds to localhost unless
``TARGET_ALLOW_REMOTE_BIND=yes``. Latency and errors are optional and are
read on each request so tests can change them without a restart.
"""

import asyncio
import os
import random
import secrets
import threading
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

LOCAL_BIND_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
MAX_INJECTED_LATENCY_MS = 5000
RANDOM_ERROR_SKIP = frozenset({"/health", "/api/v1/auth/login"})
DEMO_USERS = {"demo": "demo-pass"}
SEED_ITEMS = (
    ("Gauze pad", "SKU-GAUZE", 25),
    ("Saline", "SKU-SALINE", 40),
    ("Tape", "SKU-TAPE", 15),
)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=80)


class ItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    sku: str = Field(min_length=1, max_length=40)
    quantity: int = Field(ge=0, le=1_000_000)
    notes: str | None = Field(default=None, max_length=200)


class ItemPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    sku: str | None = Field(default=None, min_length=1, max_length=40)
    quantity: int | None = Field(default=None, ge=0, le=1_000_000)
    notes: str | None = Field(default=None, max_length=200)


class ItemOut(BaseModel):
    id: int
    name: str
    sku: str
    quantity: int
    notes: str | None
    updated_at: str


@dataclass
class Item:
    id: int
    name: str
    sku: str
    quantity: int
    notes: str | None
    updated_at: str

    def to_out(self) -> ItemOut:
        return ItemOut(
            id=self.id,
            name=self.name,
            sku=self.sku,
            quantity=self.quantity,
            notes=self.notes,
            updated_at=self.updated_at,
        )


class Store:
    """Thread-safe in-memory state. Sync FastAPI endpoints run in a threadpool."""

    def __init__(self) -> None:
        self.items: dict[int, Item] = {}
        self.tokens: dict[str, str] = {}
        self.next_id = 1
        self.lock = threading.Lock()

    def reset(self) -> None:
        with self.lock:
            self.items.clear()
            self.tokens.clear()
            self.next_id = 1
            for name, sku, quantity in SEED_ITEMS:
                self._insert(name=name, sku=sku, quantity=quantity, notes=None)

    def _insert(self, *, name: str, sku: str, quantity: int, notes: str | None) -> Item:
        item = Item(
            id=self.next_id,
            name=name,
            sku=sku,
            quantity=quantity,
            notes=notes,
            updated_at=_now(),
        )
        self.items[item.id] = item
        self.next_id += 1
        return item


STORE = Store()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def reset_state() -> None:
    """Replace tokens and items with the seeded catalog."""
    STORE.reset()


def resolve_bind(host: str | None = None, allow_remote: str | None = None) -> str:
    """Return a bind host, refusing non-local binds unless explicitly allowed."""
    chosen = host if host is not None else os.environ.get("TARGET_HOST", "127.0.0.1")
    if allow_remote is None:
        flag = os.environ.get("TARGET_ALLOW_REMOTE_BIND", "")
    else:
        flag = allow_remote
    if chosen not in LOCAL_BIND_HOSTS and flag != "yes":
        raise ValueError(
            f"Refusing to bind {chosen}. The demo target listens on localhost. "
            "Set TARGET_ALLOW_REMOTE_BIND=yes only when you intend to expose it."
        )
    return chosen


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _latency_seconds(request: Request) -> float:
    if request.url.path == "/health":
        return 0.0
    base = max(0, _env_int("TARGET_LATENCY_MS", 0))
    jitter = max(0, _env_int("TARGET_LATENCY_JITTER_MS", 0))
    extra = 0
    header = request.headers.get("x-inject-latency-ms", "")
    if header.isdigit():
        extra = int(header)
    total_ms = base + (random.randint(0, jitter) if jitter else 0) + extra
    return min(total_ms, MAX_INJECTED_LATENCY_MS) / 1000.0


def _injected_response(request: Request) -> JSONResponse | None:
    if request.url.path == "/health":
        return None
    header = request.headers.get("x-inject-status", "")
    if header.isdigit():
        code = int(header)
        if 400 <= code <= 599:
            return JSONResponse(status_code=code, content={"detail": "injected status"})
    if request.url.path in RANDOM_ERROR_SKIP:
        return None
    rate = min(1.0, max(0.0, _env_float("TARGET_ERROR_RATE", 0.0)))
    if rate > 0 and random.random() < rate:
        return JSONResponse(status_code=500, content={"detail": "injected error"})
    return None


@asynccontextmanager
async def _lifespan(_: FastAPI):
    reset_state()
    yield


app = FastAPI(
    title="PerfLoad Demo Target",
    version="1.0.0",
    summary="Local-only catalog API used as the default load-test target.",
    description=(
        "In-memory items, bearer tokens, and optional latency or error injection. "
        "Do not point this at production data. Do not expose it beyond localhost "
        "unless you set TARGET_ALLOW_REMOTE_BIND=yes on purpose."
    ),
    lifespan=_lifespan,
)


@app.middleware("http")
async def fault_injection(request: Request, call_next):
    delay = _latency_seconds(request)
    if delay > 0:
        await asyncio.sleep(delay)
    injected = _injected_response(request)
    if injected is not None:
        return injected
    return await call_next(request)


def require_user(authorization: Annotated[str | None, Header()] = None) -> str:
    if authorization is None or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    with STORE.lock:
        username = STORE.tokens.get(token)
    if username is None:
        raise HTTPException(status_code=401, detail="Invalid token")
    return username


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/auth/login")
def login(body: LoginRequest) -> dict[str, str]:
    if DEMO_USERS.get(body.username) != body.password:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = secrets.token_urlsafe(32)
    with STORE.lock:
        STORE.tokens[token] = body.username
    return {"access_token": token, "token_type": "bearer"}


@app.get("/api/v1/auth/me")
def me(username: str = Depends(require_user)) -> dict[str, str]:
    return {"username": username}


@app.get("/api/v1/items")
def list_items(_: str = Depends(require_user)) -> dict[str, object]:
    with STORE.lock:
        items = [item.to_out().model_dump() for item in STORE.items.values()]
    items.sort(key=lambda item: int(item["id"]))
    return {"items": items, "count": len(items)}


@app.post("/api/v1/items", status_code=201)
def create_item(body: ItemIn, _: str = Depends(require_user)) -> ItemOut:
    with STORE.lock:
        item = STORE._insert(
            name=body.name,
            sku=body.sku,
            quantity=body.quantity,
            notes=body.notes,
        )
        return item.to_out()


@app.get("/api/v1/items/{item_id}")
def get_item(item_id: int, _: str = Depends(require_user)) -> ItemOut:
    with STORE.lock:
        item = STORE.items.get(item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Item not found")
        return item.to_out()


@app.put("/api/v1/items/{item_id}")
def replace_item(item_id: int, body: ItemIn, _: str = Depends(require_user)) -> ItemOut:
    with STORE.lock:
        current = STORE.items.get(item_id)
        if current is None:
            raise HTTPException(status_code=404, detail="Item not found")
        replacement = Item(
            id=item_id,
            name=body.name,
            sku=body.sku,
            quantity=body.quantity,
            notes=body.notes,
            updated_at=_now(),
        )
        STORE.items[item_id] = replacement
        return replacement.to_out()


@app.patch("/api/v1/items/{item_id}")
def patch_item(item_id: int, body: ItemPatch, _: str = Depends(require_user)) -> ItemOut:
    changes = body.model_dump(exclude_unset=True)
    with STORE.lock:
        current = STORE.items.get(item_id)
        if current is None:
            raise HTTPException(status_code=404, detail="Item not found")
        updated = Item(
            id=current.id,
            name=changes.get("name", current.name),
            sku=changes.get("sku", current.sku),
            quantity=changes.get("quantity", current.quantity),
            notes=changes.get("notes", current.notes),
            updated_at=_now(),
        )
        STORE.items[item_id] = updated
        return updated.to_out()


@app.delete("/api/v1/items/{item_id}", status_code=204)
def delete_item(item_id: int, _: str = Depends(require_user)) -> Response:
    with STORE.lock:
        if item_id not in STORE.items:
            raise HTTPException(status_code=404, detail="Item not found")
        del STORE.items[item_id]
    return Response(status_code=204)
