"""단일 작성자 SQLite의 검증된 운영 백업."""

from __future__ import annotations

import hashlib
import os
import secrets
import shutil
import sqlite3
import tempfile
import time
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


def _connect_read_only(source: Path) -> sqlite3.Connection:
    source_uri = f"file:{source}?mode=ro"
    if os.environ.get("EVENT_SQLITE_NOLOCK", "false").lower() == "true":
        source_uri += "&nolock=1"
    return sqlite3.connect(source_uri, uri=True)


def _restore_check(backup: Path, required_tables: frozenset[str]) -> None:
    with tempfile.TemporaryDirectory(prefix="aipol-restore-check-") as temp_dir:
        restored = Path(temp_dir) / backup.name
        shutil.copyfile(backup, restored)
        with closing(sqlite3.connect(restored)) as restored_db:
            integrity = restored_db.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise RuntimeError(f"restored backup integrity check failed: {integrity}")
            tables = {
                row[0] for row in restored_db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            missing = sorted(required_tables - tables)
            if missing:
                raise RuntimeError(f"restored backup is missing tables: {', '.join(missing)}")


def _validate_isolated_review_semantics(backup: Path) -> None:
    """Reject a review backup containing operational identifiers or data classes."""
    with closing(_connect_read_only(backup)) as connection:
        checks = (
            ("aipol_process_review_events", "cohort_type!='synthetic_review'"),
            ("aipol_experiments", "id NOT LIKE 'review-xp-%'"),
            ("aipol_participants", "id NOT LIKE 'review-ap-%'"),
            ("aipol_v4_issue_classification_runs", "id NOT LIKE 'review-vir-%'"),
            ("aipol_v4_council_generation_runs", "id NOT LIKE 'review-vcr-%'"),
            ("aipol_v4_council_steps", "id NOT LIKE 'review-vcs-%'"),
            ("aipol_v4_ai_council_runs", "id NOT LIKE 'review-vc-%'"),
        )
        for table, invalid_where in checks:
            invalid = connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {invalid_where}"
            ).fetchone()[0]
            if invalid:
                raise RuntimeError(
                    f"isolated review backup contains invalid rows in {table}"
                )
        if connection.execute(
            "SELECT COUNT(*) FROM aipol_process_review_events"
        ).fetchone()[0] < 1:
            raise RuntimeError("isolated review backup contains no review event")
        if connection.execute(
            "SELECT COUNT(*) FROM aipol_v4_ai_council_runs"
        ).fetchone()[0] < 1:
            raise RuntimeError("isolated review backup contains no AI council run evidence")


def _create_verified_backup(
    source: Path,
    *,
    backup_dir: Path,
    filename_prefix: str,
    require_quiescent: bool,
    required_tables: frozenset[str] = frozenset(),
) -> dict[str, str | int]:
    if not source.is_file():
        raise FileNotFoundError(source)
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    destination = backup_dir / f"{filename_prefix}-{stamp}-{secrets.token_hex(4)}.db"
    partial = destination.with_suffix(".db.partial")

    try:
        with tempfile.TemporaryDirectory(prefix="aipol-backup-") as temp_dir:
            local_backup = Path(temp_dir) / destination.name
            with closing(_connect_read_only(source)) as source_db:
                if require_quiescent:
                    _require_quiescent(source_db)
                with closing(sqlite3.connect(local_backup)) as backup_db:
                    source_db.backup(backup_db)
                    integrity = backup_db.execute("PRAGMA integrity_check").fetchone()[0]
                    if integrity != "ok":
                        raise RuntimeError(f"backup integrity check failed: {integrity}")
            _restore_check(local_backup, required_tables)
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


def create_verified_backup(source: Path | None = None) -> dict[str, str | int]:
    source = source or Path(os.environ.get("EVENT_DB_PATH", "/data/event.db"))
    return _create_verified_backup(
        source,
        backup_dir=source.parent / "backups",
        filename_prefix="event",
        require_quiescent=True,
    )


def create_verified_isolated_review_backup(
    source: Path,
    *,
    operational_source: Path,
    retention_days: int,
) -> dict[str, str | int]:
    """Back up only the isolated synthetic-review repository and verify a restore."""
    source = source.resolve()
    operational_source = operational_source.resolve()
    if source == operational_source:
        raise ValueError("process review database must be physically isolated")
    if retention_days < 1 or retention_days > 30:
        raise ValueError("process review backup retention must be between 1 and 30 days")
    backup_dir = source.parent / "process-review-backups"
    result = _create_verified_backup(
        source,
        backup_dir=backup_dir,
        filename_prefix="aipol-process-review",
        require_quiescent=False,
        required_tables=frozenset({
            "aipol_process_review_events",
            "aipol_process_review_inputs",
            "aipol_process_review_steps",
            "aipol_process_review_bindings",
            "aipol_experiments",
            "aipol_participants",
            "aipol_v4_issue_classification_runs",
            "aipol_v4_council_generation_runs",
            "aipol_v4_council_steps",
            "aipol_v4_ai_council_runs",
        }),
    )
    try:
        _validate_isolated_review_semantics(Path(str(result["path"])))
    except Exception:
        Path(str(result["path"])).unlink(missing_ok=True)
        raise
    cutoff = time.time() - retention_days * 86_400
    pruned = 0
    for candidate in backup_dir.glob("aipol-process-review-*.db"):
        if (
            candidate != Path(str(result["path"]))
            and candidate.is_file()
            and not candidate.is_symlink()
            and candidate.stat().st_mtime < cutoff
        ):
            candidate.unlink()
            pruned += 1
    return {
        **result,
        "restore_check": "ok",
        "retention_days": retention_days,
        "pruned_backups": pruned,
    }
