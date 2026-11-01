"""Deterministic offline mode: block outbound network access in-process (NFR-002, SAFE-001).

This is the only module allowed to import ``socket`` - and only to disable it.
"""

from __future__ import annotations

import socket


class OfflineViolationError(RuntimeError):
    """Raised when code attempts network access while offline mode is enforced."""


def _blocked(*_args: object, **_kwargs: object) -> None:
    raise OfflineViolationError(
        "network access is disabled: llm-eval-regression-lab runs in deterministic offline mode"
    )


def enforce_offline() -> None:
    """Replace socket connection entry points with a function that raises. Idempotent."""
    socket.socket.connect = _blocked  # type: ignore[method-assign]
    socket.socket.connect_ex = _blocked  # type: ignore[method-assign]
    socket.create_connection = _blocked  # type: ignore[assignment]
    socket.getaddrinfo = _blocked  # type: ignore[assignment]


def is_offline_enforced() -> bool:
    return socket.create_connection is _blocked
