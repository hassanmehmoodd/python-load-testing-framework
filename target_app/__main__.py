"""Run the demo target on localhost."""

import os

import uvicorn

from target_app.app import resolve_bind


def main() -> None:
    try:
        host = resolve_bind()
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    port = int(os.environ.get("TARGET_PORT", "8000"))
    uvicorn.run("target_app.app:app", host=host, port=port)


if __name__ == "__main__":
    main()
