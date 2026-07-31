"""단일 작성자 SQLite의 검증된 운영 백업."""

from __future__ import annotations

import hashlib
import os
import secrets
import shutil
import sqlite3
import tempfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path


class BackupNotQuiescent(RuntimeError):
    pass


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _require_quiescent(connection: sqlite3.Connection) -> None:
    if _table_exists(connection, "rounds") and connection.execute(
        "SELECT COUNT(*) FROM rounds WHERE status='open'"
    ).fetchone()[0]:
        raise BackupNotQuiescent("일반 행사 수집 회차가 열려 있어 백업할 수 없습니다")
    if _table_exists(connection, "aipol_experiments"):
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(aipol_experiments)")
        }
        if "registration_open" in columns and connection.execute(
            "SELECT COUNT(*) FROM aipol_experiments WHERE registration_open=1"
        ).fetchone()[0]:
            raise BackupNotQuiescent("AIPOL 참가자 등록이 열려 있어 백업할 수 없습니다")

    if _table_exists(connection, "jobs") and connection.execute(
        "SELECT COUNT(*) FROM jobs WHERE status='running'"
    ).fetchone()[0]:
        raise BackupNotQuiescent("AI 작업이 실행 중이어서 백업할 수 없습니다")


def create_verified_backup(source: Path | None = None) -> dict[str, str | int]:
    source = source or Path(os.environ.get("EVENT_DB_PATH", "/data/event.db"))
    backup_dir = source.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    destination = backup_dir / f"event-{stamp}-{secrets.token_hex(4)}.db"
    partial = destination.with_suffix(".db.partial")
    source_uri = str(source)
    source_kwargs: dict[str, object] = {}
    if os.environ.get("EVENT_SQLITE_NOLOCK", "false").lower() == "true":
        source_uri = f"file:{source}?mode=ro&nolock=1"
        source_kwargs = {"uri": True}

    try:
        with tempfile.TemporaryDirectory(prefix="aipol-backup-") as temp_dir:
            local_backup = Path(temp_dir) / destination.name
            with closing(sqlite3.connect(source_uri, **source_kwargs)) as source_db:
                _require_quiescent(source_db)
                with closing(sqlite3.connect(local_backup)) as backup_db:
                    source_db.backup(backup_db)
                    integrity = backup_db.execute("PRAGMA integrity_check").fetchone()[0]
                    if integrity != "ok":
                        raise RuntimeError(f"backup integrity check failed: {integrity}")
            shutil.copyfile(local_backup, partial)
            with partial.open("r+b") as copied:
                copied.flush()
                os.fsync(copied.fileno())
            partial.replace(destination)
    finally:
        partial.unlink(missing_ok=True)

    return {
        "path": str(destination),
        "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        "bytes": destination.stat().st_size,
    }
