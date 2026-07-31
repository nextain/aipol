import importlib
import base64
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


ROOT = Path(__file__).parents[1]
EVENT_TOOL = ROOT / "event-tool"
PASSWORD = "a-production-password-12345"
sys.path.insert(0, str(EVENT_TOOL))
import admin_auth  # noqa: E402

TOTP_SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"


def _encoded_json(value: object) -> str:
    return base64.b64encode(json.dumps(value).encode("utf-8")).decode("ascii")


@pytest.fixture()
def deployed_app(tmp_path, monkeypatch):
    monkeypatch.setenv("EVENT_ENV", "production")
    monkeypatch.setenv("EVENT_DEMO_ENABLED", "false")
    monkeypatch.setenv("EVENT_DB_PATH", str(tmp_path / "event.db"))
    monkeypatch.setenv("EVENT_ROSTER_PATH", str(tmp_path / "roster.json"))
    monkeypatch.setenv("EVENT_SQLITE_NOLOCK", "false")
    monkeypatch.setenv("EVENT_SESSION_SECRET", "s" * 48)
    monkeypatch.setenv("EVENT_ADMIN_USERS_JSON_B64", _encoded_json({"hong": admin_auth.hash_password(PASSWORD)}))
    monkeypatch.delenv("EVENT_ADMIN_USERS_JSON", raising=False)
    monkeypatch.setenv("EVENT_ADMIN_ROLES_JSON_B64", _encoded_json({"hong": ["admin"]}))
    monkeypatch.delenv("EVENT_ADMIN_ROLES_JSON", raising=False)
    monkeypatch.setenv("EVENT_ADMIN_TOTP_SECRETS_JSON_B64", _encoded_json({"hong": TOTP_SECRET}))
    monkeypatch.delenv("EVENT_ADMIN_TOTP_SECRETS_JSON", raising=False)
    monkeypatch.setenv("AIPOL_AUDIT_CHECKPOINT_SECRETS_JSON", json.dumps({"test-key": "k" * 48}))
    monkeypatch.setenv("AIPOL_AUDIT_CHECKPOINT_ACTIVE_KEY_ID", "test-key")
    monkeypatch.syspath_prepend(str(EVENT_TOOL))
    for name in ("server", "db", "aipol_store", "aipol_admin_store", "aipol_audit_checkpoint", "ai_config", "deliberate", "llm"):
        sys.modules.pop(name, None)
    checkpoint = importlib.import_module("aipol_audit_checkpoint")
    monkeypatch.setattr(
        checkpoint,
        "store_from_environment",
        lambda *, production: checkpoint.MemoryCheckpointStore({}),
    )
    server = importlib.import_module("server")
    yield server, TestClient(server.app), tmp_path / "event.db"
    for name in ("server", "db", "aipol_store", "aipol_admin_store", "aipol_audit_checkpoint", "ai_config", "deliberate", "llm"):
        sys.modules.pop(name, None)


def login(client):
    response = client.post("/api/admin/login", json={
        "username": "hong", "password": PASSWORD, "otp": admin_auth.totp(TOTP_SECRET)
    })
    assert response.status_code == 200
    return response.json()["token"]


def test_totp_replay_and_credential_rotation_revoke_sessions(deployed_app):
    server, client, _ = deployed_app
    otp = admin_auth.totp(TOTP_SECRET)
    first = client.post("/api/admin/login", json={
        "username": "hong", "password": PASSWORD, "otp": otp,
    })
    assert first.status_code == 200
    assert client.post("/api/admin/login", json={
        "username": "hong", "password": PASSWORD, "otp": otp,
    }).status_code == 401
    token = first.json()["token"]
    server.ADMIN_USERS["hong"] = admin_auth.hash_password("rotated-production-password-12345")
    assert client.get("/api/admin/events", headers={"X-Admin-Token": token}).status_code == 401


def test_totp_counter_survives_module_reload(deployed_app):
    server, _, _ = deployed_app
    assert server.db.claim_totp_counter("persistent-admin", 4242)
    reloaded_db = importlib.reload(server.db)
    assert not reloaded_db.claim_totp_counter("persistent-admin", 4242)
    assert reloaded_db.claim_totp_counter("persistent-admin", 4243)


def test_temporary_shared_admin_can_skip_totp_when_explicitly_allowlisted(deployed_app):
    server, client, _ = deployed_app
    username = "temporary-shared-admin"
    password = "temporary-shared-password-12345"
    server.ADMIN_USERS[username] = admin_auth.hash_password(password)
    server.ADMIN_ROLES[username] = frozenset({server.Role.ADMIN})
    server.ADMIN_TOTP_OPTIONAL_USERS = frozenset({username})

    response = client.post("/api/admin/login", json={
        "username": username,
        "password": password,
        "otp": "",
    })

    assert response.status_code == 200
    assert response.json()["username"] == username
    assert client.get(
        "/api/admin/events",
        headers={"X-Admin-Token": response.json()["token"]},
    ).status_code == 200


def test_production_requires_strong_personal_credentials(tmp_path):
    env = os.environ | {
        "PYTHONPATH": str(EVENT_TOOL),
        "EVENT_ENV": "production",
        "EVENT_DB_PATH": str(tmp_path / "bad.db"),
        "EVENT_ADMIN_USERS_JSON": '{"operator":"demo"}',
        "EVENT_ADMIN_ROLES_JSON": '{"operator":["operator"]}',
        "EVENT_SESSION_SECRET": "short",
    }
    result = subprocess.run(
        [sys.executable, "-c", "import server"],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert result.returncode != 0
    assert "EVENT_SESSION_SECRET" in result.stderr


def test_demo_closed_and_security_headers(deployed_app):
    _, client, _ = deployed_app
    response = client.get("/api/citizen/current")
    assert response.json() == {"open": False}
    assert response.headers["x-robots-tag"].startswith("noindex")
    assert response.headers["x-frame-options"] == "DENY"
    assert client.get("/docs").status_code == 404
    assert client.post("/api/citizen/submit", json={"answers": {}}).status_code == 409


def test_personal_session_and_hashed_participant_code(deployed_app):
    _, client, db_path = deployed_app
    token = login(client)
    headers = {"X-Admin-Token": token}
    assert client.get("/api/admin/events", headers=headers).status_code == 200
    assert client.get("/api/admin/events", headers={"X-Admin-Token": PASSWORD}).status_code == 401

    event = client.post("/api/admin/events", headers=headers, json={"title": "검증 행사"}).json()
    round_ = client.post(
        f"/api/admin/events/{event['id']}/rounds",
        headers=headers,
        json={
            "round_no": 1,
            "title": "1차",
            "intro": ["안내"],
            "attachments": [],
            "proposals": [{"id": "A", "title": "A안", "body": "설명"}],
            "profile_fields": [{"key": "age", "label": "연령대", "type": "select", "options": ["20대"]}],
        },
    ).json()
    client.post(f"/api/admin/rounds/{round_['id']}/status", headers=headers, json={"status": "open"})
    submitted = client.post(
        "/api/citizen/submit",
        json={"answers": {"A": {"stance": "accept", "text": "동의"}}, "profile": {"age": "20대"}},
    )
    assert submitted.status_code == 200
    raw_code = submitted.json()["code"]
    assert raw_code.startswith("C") and len(raw_code) == 33
    with sqlite3.connect(db_path) as conn:
        stored = conn.execute("SELECT code FROM participants").fetchone()[0]
    assert stored.startswith("sha256:")
    assert raw_code not in stored


def test_attachment_scheme_is_fail_closed(deployed_app):
    _, client, _ = deployed_app
    headers = {"X-Admin-Token": login(client)}
    event = client.post("/api/admin/events", headers=headers, json={"title": "링크 검증"}).json()
    response = client.post(
        f"/api/admin/events/{event['id']}/rounds",
        headers=headers,
        json={"round_no": 1, "title": "1차", "attachments": [{"name": "위험", "url": "javascript:alert(1)"}]},
    )
    assert response.status_code == 400


def test_production_backup_fails_closed_until_recovery_lineage_exists(deployed_app):
    _, client, _ = deployed_app
    unauthenticated = client.post("/api/admin/aipol/maintenance/backup")
    assert unauthenticated.status_code == 401

    response = client.post(
        "/api/admin/aipol/maintenance/backup",
        headers={"X-Admin-Token": login(client)},
    )
    assert response.status_code == 503
    assert "복구 계보" in response.json()["detail"]


def test_unknown_account_failures_do_not_lock_every_admin(deployed_app):
    _, client, _ = deployed_app
    for _ in range(10):
        assert client.post("/api/admin/login", json={
            "username": "unknown", "password": "wrong", "otp": "000000",
        }).status_code == 401
    assert client.post("/api/admin/login", json={
        "username": "hong", "password": PASSWORD, "otp": admin_auth.totp(TOTP_SECRET),
    }).status_code == 200


def test_malformed_token_and_login_burst_fail_closed(deployed_app):
    _, client, _ = deployed_app
    assert client.get("/api/admin/events", headers={"X-Admin-Token": "%%%not-base64"}).status_code == 401
    for _ in range(10):
        assert client.post("/api/admin/login", json={"username": "hong", "password": "wrong"}).status_code == 401
    assert client.post("/api/admin/login", json={"username": "hong", "password": "wrong"}).status_code == 429


def test_interrupted_jobs_are_marked_failed(deployed_app):
    server, _, _ = deployed_app
    event = server.db.create_event("재시작 검증")
    round_ = server.db.create_round(event["id"], round_no=1, title="1차")
    job = server.db.create_job(round_["id"])
    assert server.db.fail_interrupted_jobs() == 1
    assert server.db.get_job(job["id"])["status"] == "failed"
