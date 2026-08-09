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
    "server", "db", "aipol_store", "aipol_v4_ai", "aipol_process_review", "aipol_admin_store",
    "aipol_audit_checkpoint", "aipol_chat", "aipol_batch", "aipol_receipt",
    "ai_config", "deliberate", "llm",
)


def test_process_review_event_is_stored_isolated_and_append_only(tmp_path, monkeypatch):
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
            canonical_page = client.get("/cases/pension/experiment/", follow_redirects=False)
            assert canonical_page.status_code == 200
            assert "연금개혁-AI 숙의민주주의 정책실험" in canonical_page.text

            slash_redirect = client.get(
                "/cases/pension/experiment?x=a%2Fb&x=%E2%9C%93&blank=",
                follow_redirects=False,
            )
            assert slash_redirect.status_code in {307, 308}
            assert slash_redirect.headers["location"] == (
                "/cases/pension/experiment/?x=a%2Fb&x=%E2%9C%93&blank="
            )

            legacy_page = client.get(
                "/aipol.html?review=process&dataset=pension-v4-20260808-r1",
                follow_redirects=False,
            )
            assert legacy_page.status_code in {307, 308}
            assert legacy_page.headers["location"] == (
                "/cases/pension/experiment/"
                "?review=process&dataset=pension-v4-20260808-r1"
            )

            assert client.get(route).status_code == 404
            assert not review_db_path.exists()

            monkeypatch.setenv("AIPOL_PROCESS_REVIEW_ENABLED", "true")
            server.aipol_process_review.init()
            response = client.get(route)
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-store"
            snapshot = response.json()
            assert snapshot["cohort"] == {
                "kind": "synthetic_review", "read_only": True, "participant_count": 40,
            }
            assert [step["number"] for step in snapshot["steps"]] == list(range(1, 11))
            assert len(snapshot["steps"][3]["issues"]) == 5
            assert set(snapshot["input_hashes"]) == {
                "source_bundle", "constraints", "m1", "deliberation_1",
                "five_issues", "m2", "deliberation_2",
            }
            assert len(snapshot["steps"][6]["council"]) == 3
            assert snapshot["steps"][6]["cohort"] == {
                "participant_type": "synthetic_review", "participant_count": 40,
            }
            assert len(snapshot["steps"][6]["constraint_verdicts"]) == 2
            assert len(snapshot["steps"][7]["expert_review"]["field_diff"]) == 3
            assert snapshot["steps"][7]["expert_review"]["approved_by"] != snapshot["steps"][7]["expert_review"]["editor_by"]
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
            assert not tables.intersection({
                "aipol_process_review_events", "aipol_process_review_inputs",
                "aipol_process_review_steps",
            })

        with sqlite3.connect(review_db_path) as connection:
            row = connection.execute(
                "SELECT cohort_type, content_hash FROM aipol_process_review_events WHERE id=?",
                (snapshot["review_id"],),
            ).fetchone()
            assert row == ("synthetic_review", snapshot["content_hash"])
            assert connection.execute(
                "SELECT COUNT(*) FROM aipol_process_review_inputs WHERE review_id=?",
                (snapshot["review_id"],),
            ).fetchone()[0] == 7
            assert connection.execute(
                "SELECT COUNT(*) FROM aipol_process_review_steps WHERE review_id=?",
                (snapshot["review_id"],),
            ).fetchone()[0] == 10
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                connection.execute(
                    "UPDATE aipol_process_review_events SET contract_version='drift' WHERE id=?",
                    (snapshot["review_id"],),
                )
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                connection.execute(
                    "DELETE FROM aipol_process_review_steps WHERE review_id=?",
                    (snapshot["review_id"],),
                )
    finally:
        for name in MODULES:
            sys.modules.pop(name, None)
