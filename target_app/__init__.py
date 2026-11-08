"""Local demo API used as the default perfload target."""

from target_app.app import app, reset_state, resolve_bind

__all__ = ["app", "reset_state", "resolve_bind"]
