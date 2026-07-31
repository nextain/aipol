from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "azure" / "event-tool-dev" / "backup_sqlite.py"
sys.path.insert(0, str(ROOT / "event-tool"))
import sqlite_backup  # noqa: E402


def test_backup_is_complete_and_integrity_checked_before_publish(tmp_path: Path) -> None:
    source = tmp_path / "event.db"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE evidence(id TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO evidence VALUES('row-1', 'preserved')")
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        env=os.environ | {"EVENT_DB_PATH": str(source), "EVENT_SQLITE_NOLOCK": "false"},
        capture_output=True, text=True, check=True,
    )
    report = json.loads(result.stdout)
    backup = Path(report["path"])
    assert backup.exists() and backup.stat().st_size == report["bytes"] > 0
    assert not list(backup.parent.glob("*.partial"))
    with sqlite3.connect(backup) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT value FROM evidence WHERE id='row-1'").fetchone()[0] == "preserved"


def test_packaged_backup_cli_runs_from_flat_container_directory(tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    shutil.copyfile(SCRIPT, app_dir / "backup_sqlite.py")
    shutil.copyfile(ROOT / "event-tool" / "sqlite_backup.py", app_dir / "sqlite_backup.py")
    source = tmp_path / "event.db"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE marker(value TEXT)")
        connection.execute("INSERT INTO marker VALUES('container-layout')")
    result = subprocess.run(
        [sys.executable, str(app_dir / "backup_sqlite.py")],
        env=os.environ | {"EVENT_DB_PATH": str(source), "EVENT_SQLITE_NOLOCK": "false"},
        capture_output=True, text=True, check=True,
    )
    report = json.loads(result.stdout)
    assert Path(report["path"]).is_file()


def test_packaged_backup_cli_refuses_live_writer_lease(tmp_path: Path) -> None:
    app_dir = tmp_path / "app-live"
    app_dir.mkdir()
    shutil.copyfile(SCRIPT, app_dir / "backup_sqlite.py")
    shutil.copyfile(ROOT / "event-tool" / "sqlite_backup.py", app_dir / "sqlite_backup.py")
    source = tmp_path / "event.db"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE marker(value TEXT)")
    lease = tmp_path / "event-tool.writer-lease"
    lease.mkdir()
    result = subprocess.run(
        [sys.executable, str(app_dir / "backup_sqlite.py")],
        env=os.environ | {"EVENT_DB_PATH": str(source), "EVENT_SQLITE_NOLOCK": "false"},
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "writer lease exists" in result.stderr
    assert not list((tmp_path / "backups").glob("*.db"))


def test_backup_fails_closed_while_collection_is_open(tmp_path: Path) -> None:
    source = tmp_path / "event.db"
    with sqlite3.connect(source) as connection:
        connection.execute(
            "CREATE TABLE aipol_experiments("
            "id TEXT, registration_open INTEGER, freeze_manifest TEXT)"
        )
        connection.execute(
            "INSERT INTO aipol_experiments VALUES(?,?,?)",
            ("xp-1", 1, json.dumps({"collection_enabled": True})),
        )
    with pytest.raises(sqlite_backup.BackupNotQuiescent) as error:
        sqlite_backup.create_verified_backup(source)
    assert str(error.value)
    assert not list((tmp_path / "backups").glob("*.db"))


def test_backup_allows_closed_anchored_collection_manifest(tmp_path: Path) -> None:
    source = tmp_path / "event.db"
    with sqlite3.connect(source) as connection:
        connection.execute(
            "CREATE TABLE aipol_experiments("
            "id TEXT, registration_open INTEGER, freeze_manifest TEXT)"
        )
        connection.execute(
            "CREATE TABLE aipol_freeze_manifest_anchors(manifest_envelope TEXT)"
        )
        connection.execute("INSERT INTO aipol_experiments VALUES('xp-1', 0, NULL)")
        connection.execute(
            "INSERT INTO aipol_freeze_manifest_anchors VALUES(?)",
            (json.dumps({"collection_enabled": True}),),
        )
    report = sqlite_backup.create_verified_backup(source)
    assert Path(report["path"]).is_file()
