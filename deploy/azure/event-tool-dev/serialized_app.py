"""Deployment-only ASGI wrapper that serializes HTTP requests for SQLite safety.

The event-tool uses synchronous FastAPI handlers, which otherwise run in a
thread pool even with one Uvicorn worker. Azure Files is mounted with SQLite's
``nolock`` URI option, so this development image must not execute overlapping
requests that can write through separate SQLite connections.
"""

from __future__ import annotations

import atexit
import asyncio
import json
import os
import secrets
from pathlib import Path
from typing import Any


_db_path = Path(os.environ.get("EVENT_DB_PATH", "/data/event.db"))
WRITER_LEASE_PATH = Path(
    os.environ.get("EVENT_WRITER_LEASE_PATH", str(_db_path.parent / "event-tool.writer-lease"))
)
_lease_owner = secrets.token_hex(16)


def _writer_identity() -> str:
    """Return the Container Apps replica identity, not the revision identity."""

    return os.environ.get("HOSTNAME", "local")


def _process_marker(pid: int | None = None) -> str:
    """Bind a lease to one Linux process incarnation, including PID reuse."""

    process_id = pid or os.getpid()
    try:
        fields = Path(f"/proc/{process_id}/stat").read_text(encoding="utf-8").rsplit(")", 1)[1].split()
        start_ticks = fields[19]
    except (OSError, IndexError) as exc:
        raise RuntimeError("cannot establish the event-tool writer process marker") from exc
    return f"linux:{process_id}:{start_ticks}"


_lease_identity = _writer_identity()
_lease_process_marker = _process_marker()


def _lease_record() -> dict[str, str | int]:
    return {
        "version": 1,
        "identity": _lease_identity,
        "process_marker": _lease_process_marker,
        "token": _lease_owner,
    }


def _read_lease_record(path: Path) -> dict:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"event-tool writer lease owner is unreadable: {path}") from exc
    if not isinstance(record, dict) or record.get("version") != 1:
        raise RuntimeError(f"event-tool writer lease owner has an unsupported format: {path}")
    return record


def _process_marker_is_live(marker: object) -> bool:
    if not isinstance(marker, str):
        return True
    parts = marker.split(":")
    if len(parts) != 3 or parts[0] != "linux" or not parts[1].isdigit():
        return True
    try:
        return secrets.compare_digest(_process_marker(int(parts[1])), marker)
    except RuntimeError:
        return False


def _retire_stale_same_replica_lease(owner_path: Path, record: dict) -> None:
    """Atomically retire a dead process lease from the same replica only."""

    if record.get("identity") != _lease_identity or _process_marker_is_live(
        record.get("process_marker")
    ):
        raise RuntimeError(f"event-tool writer lease already exists: {WRITER_LEASE_PATH}")
    if {item.name for item in WRITER_LEASE_PATH.iterdir()} != {owner_path.name}:
        raise RuntimeError(
            f"event-tool writer lease contains unexpected files: {WRITER_LEASE_PATH}"
        )
    stale_path = WRITER_LEASE_PATH.with_name(
        f".{WRITER_LEASE_PATH.name}.stale-{_lease_owner}"
    )
    WRITER_LEASE_PATH.rename(stale_path)
    try:
        WRITER_LEASE_PATH.mkdir()
    except BaseException:
        stale_path.rename(WRITER_LEASE_PATH)
        raise
    (stale_path / owner_path.name).unlink()
    stale_path.rmdir()


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

    Directory creation is atomic on the mounted SMB share. A dead process from
    the same Container Apps replica may reclaim its own lease after a restart.
    A different replica or revision still fails closed and requires the
    zero-active-revision operator procedure.
    """

    WRITER_LEASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        WRITER_LEASE_PATH.mkdir()
    except FileExistsError:
        owner_path = WRITER_LEASE_PATH / "owner"
        _retire_stale_same_replica_lease(owner_path, _read_lease_record(owner_path))
    (WRITER_LEASE_PATH / "owner").write_text(
        json.dumps(_lease_record(), sort_keys=True), encoding="utf-8"
    )


def release_writer_lease() -> None:
    owner_path = WRITER_LEASE_PATH / "owner"
    try:
        if _read_lease_record(owner_path).get("token") != _lease_owner:
            return
        owner_path.unlink()
        WRITER_LEASE_PATH.rmdir()
    except (FileNotFoundError, RuntimeError):
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
