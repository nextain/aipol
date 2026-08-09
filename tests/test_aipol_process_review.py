"""Contract tests for the isolated, read-only pension process review."""
from __future__ import annotations

import importlib
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


EVENT_TOOL = Path(__file__).parents[1] / "event-tool"
MODULES = (
    "server", "db", "aipol_store", "aipol_process_review", "aipol_admin_store",
    "aipol_audit_checkpoint", "aipol_chat", "aipol_batch", "aipol_receipt",
    "ai_config", "deliberate", "llm",
)


def test_process_review_snapshot_is_flagged_isolated_and_append_only(tmp_path, monkeypatch):
    event_db_path = tmp_path / "event.db"
    review_db_path = tmp_path / "isolated-process-review.db"
    monkeypatch.setenv("EVENT_ENV", "development")
    monkeypatch.setenv("EVENT_DB_PATH", str(event_db_path))
    # Exercise the Azure Files-compatible connection contract used by DEV.
    monkeypatch.setenv("EVENT_SQLITE_NOLOCK", "true")
    monkeypatch.setenv("EVENT_SESSION_SECRET", "s" * 48)
    monkeypatch.setenv("AIPOL_PROCESS_REVIEW_DB_PATH", str(review_db_path))
    monkeypatch.delenv("AIPOL_PROCESS_REVIEW_ENABLED", raising=False)
    monkeypatch.syspath_prepend(str(EVENT_TOOL))
    for name in MODULES:
        sys.modules.pop(name, None)
    server = importlib.import_module("server")
    route = "/api/aipol/process-reviews/pension-v4-20260808-r1"

    try:
        with TestClient(server.app) as client:
            assert client.get(route).status_code == 404
            assert not review_db_path.exists()

            monkeypatch.setenv("AIPOL_PROCESS_REVIEW_ENABLED", "true")
            server.aipol_process_review.init()
            response = client.get(route)
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-store"
            snapshot = response.json()
            assert snapshot["fixture"] == {
                "kind": "mock", "read_only": True, "participant_count": 40,
            }
            assert [step["number"] for step in snapshot["steps"]] == list(range(1, 11))
            assert len(snapshot["steps"][3]["issues"]) == 5
            assert set(snapshot["input_hashes"]) == {
                "m1", "deliberation_1", "m2", "deliberation_2",
            }
            assert len(snapshot["steps"][6]["council"]) == 3
            assert snapshot["steps"][8]["d_acceptability"]["response_count"] == 40
            assert "개인 연금 계산" in snapshot["forbidden_stages"]
            assert len(snapshot["content_hash"]) == 64
            assert client.post(route).status_code == 405

        with sqlite3.connect(event_db_path) as connection:
            tables = {
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            assert "aipol_process_review_snapshots" not in tables

        with sqlite3.connect(review_db_path) as connection:
            row = connection.execute(
                "SELECT fixture_kind, content_hash FROM aipol_process_review_snapshots WHERE id=?",
                (snapshot["review_id"],),
            ).fetchone()
            assert row == ("mock", snapshot["content_hash"])
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                connection.execute(
                    "UPDATE aipol_process_review_snapshots SET contract_version='drift' WHERE id=?",
                    (snapshot["review_id"],),
                )
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                connection.execute(
                    "DELETE FROM aipol_process_review_snapshots WHERE id=?",
                    (snapshot["review_id"],),
                )
    finally:
        for name in MODULES:
            sys.modules.pop(name, None)
