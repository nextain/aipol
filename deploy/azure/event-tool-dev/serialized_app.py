"""Deployment-only ASGI wrapper that serializes HTTP requests for SQLite safety.

The event-tool uses synchronous FastAPI handlers, which otherwise run in a
thread pool even with one Uvicorn worker. Azure Files is mounted with SQLite's
``nolock`` URI option, so this development image must not execute overlapping
requests that can write through separate SQLite connections.
"""

from __future__ import annotations

import atexit
import asyncio
import os
import secrets
from pathlib import Path
from typing import Any


_db_path = Path(os.environ.get("EVENT_DB_PATH", "/data/event.db"))
WRITER_LEASE_PATH = Path(
    os.environ.get("EVENT_WRITER_LEASE_PATH", str(_db_path.parent / "event-tool.writer-lease"))
)
_lease_owner = secrets.token_hex(16)


def assert_data_directory_writable() -> None:
    """Fail startup unless the runtime UID can write the persistent mount."""

    data_dir = _db_path.parent
    data_dir.mkdir(parents=True, exist_ok=True)
    probe = data_dir / f".aipol-write-probe-{_lease_owner}"
    try:
        probe.write_text(_lease_owner, encoding="utf-8")
        if probe.read_text(encoding="utf-8") != _lease_owner:
            raise RuntimeError(f"persistent data write verification failed: {data_dir}")
    except OSError as exc:
        raise RuntimeError(
            f"persistent data directory is not writable by the container user: {data_dir}"
        ) from exc
    finally:
        try:
            probe.unlink()
        except FileNotFoundError:
            pass


def acquire_writer_lease() -> None:
    """Acquire the cross-process writer lease before importing the DB app.

    Directory creation is atomic on the mounted SMB share. A stale directory
    deliberately blocks startup after an unclean exit; an operator must first
    prove that no revision is active before removing it.
    """

    WRITER_LEASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        WRITER_LEASE_PATH.mkdir()
    except FileExistsError as exc:
        raise RuntimeError(
            f"event-tool writer lease already exists: {WRITER_LEASE_PATH}"
        ) from exc
    (WRITER_LEASE_PATH / "owner").write_text(_lease_owner, encoding="utf-8")


def release_writer_lease() -> None:
    owner_path = WRITER_LEASE_PATH / "owner"
    try:
        if owner_path.read_text(encoding="utf-8") != _lease_owner:
            return
        owner_path.unlink()
        WRITER_LEASE_PATH.rmdir()
    except FileNotFoundError:
        return


assert_data_directory_writable()
acquire_writer_lease()
atexit.register(release_writer_lease)

try:
    from server import app as event_tool_app
except BaseException:
    release_writer_lease()
    raise


class SerializedHttpApp:
    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self._http_lock = asyncio.Lock()

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self._inner(scope, receive, send)
            return
        async with self._http_lock:
            await self._inner(scope, receive, send)


app = SerializedHttpApp(event_tool_app)
