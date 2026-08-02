"""AIPOL 3차 측정 FastAPI/SQLite 운영 경계 테스트."""
from __future__ import annotations

import base64
import ipaddress
import importlib
import json
import sqlite3
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from policy_lab.domains.pension.experiment import MeasurementSpec, content_hash


ROOT = Path(__file__).parents[1]
EVENT_TOOL = ROOT / "event-tool"
PASSWORD = "a-production-password-12345"
EDITOR_PASSWORD = "an-editor-password-12345"
ADMISSION_CODE = "KAPS-2026-AIPOL!"
RECEIPT_CONTRACT = {
    "contract_id": "calculator-completion-v1",
    "version": "1.0.0",
    "mode": "signed_one_time_completion",
    "issuer": "https://example.test",
    "audience": "aipol-event-tool",
    "public_key_id": "fixture-key-1",
    "receipt_format": "flattened_jws_json",
    "signature_algorithm": "EdDSA",
}
INTEGRATION_VERSION = "aipol-calculator-return-v2"
INTEGRATION_TEST_HASH = "9" * 64
MODULES = ("server", "db", "aipol_store", "aipol_admin_store", "aipol_audit_checkpoint", "aipol_chat", "aipol_receipt", "ai_config", "deliberate", "llm")
CATEGORIES = (
    "policy_options", "calculation", "measurement", "privacy", "research_ethics",
    "source_license", "procedure",
)
ADMISSION_CREDENTIALS: dict[str, list[str]] = {}


@pytest.fixture()
def aipol_app(tmp_path, monkeypatch):
    monkeypatch.setenv("EVENT_ENV", "development")
    monkeypatch.setenv("EVENT_DEMO_ENABLED", "false")
    monkeypatch.setenv("EVENT_DB_PATH", str(tmp_path / "event.db"))
    monkeypatch.setenv("EVENT_ROSTER_PATH", str(tmp_path / "roster.json"))
    monkeypatch.setenv("EVENT_SQLITE_NOLOCK", "false")
    monkeypatch.setenv("EVENT_SESSION_SECRET", "s" * 48)
    monkeypatch.setenv(
        "EVENT_ADMIN_USERS_JSON",
        json.dumps({"hong": PASSWORD, "editor": EDITOR_PASSWORD}),
    )
    monkeypatch.setenv(
        "EVENT_ADMIN_ROLES_JSON",
        json.dumps({
            "hong": ["approver", "operator", "admin", "auditor"],
            "editor": ["editor"],
        }),
    )
    monkeypatch.syspath_prepend(str(EVENT_TOOL))
    for name in MODULES:
        sys.modules.pop(name, None)
    server = importlib.import_module("server")
    class FixtureReceiptVerifier:
        verifier_id = "test-only-fixture-verifier"

        def verify(self, receipt, contract, context):
            assert contract == RECEIPT_CONTRACT
            if receipt.get("contract_hash") != content_hash(contract):
                raise server.aipol_store.ExperimentError("invalid fixture receipt contract")
            return str(receipt.get("receipt_id") or "")

    server.aipol_store.configure_completion_receipt_verifier(FixtureReceiptVerifier())
    with TestClient(server.app) as client:
        yield server, client, tmp_path / "event.db"
    for name in MODULES:
        sys.modules.pop(name, None)


def _admin_headers(client: TestClient, username: str = "hong") -> dict:
    password = PASSWORD if username == "hong" else EDITOR_PASSWORD
    response = client.post("/api/admin/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return {"X-Admin-Token": response.json()["token"]}


def _create(
    client: TestClient,
    headers: dict,
    *,
    capacity: int = 20,
    suffix: str = "",
    procedure_version: str = "v1",
) -> dict:
    editor_headers = _admin_headers(client, "editor")
    response = client.post(
        "/api/admin/aipol/experiments",
        headers=editor_headers,
        json={
            "title": "AIPOL 연금개혁 정책실험",
            "experiment_version": f"2026-08-12.1{suffix}",
            "session_id": f"session-a{suffix}",
            "consent_version": "consent-v1",
            "consent_text": "연구 절차와 응답 저장에 동의합니다.",
            "question_id": "main-choice",
            "question_text": "세 정책안 중 현재 가장 선호하는 안을 선택해 주세요.",
            "option_set_version": "approved-options-v1",
            "capacity": capacity,
            "procedure_version": procedure_version,
            "policy_options": [
                {"policy_option_id": "A", "label": "검증용 A안", "policy_version": "approved-options-v1",
                 "source": "test-fixture", "approved_by": "test-reviewer", "lever_values": {"fixture": "A"}},
                {"policy_option_id": "B", "label": "검증용 B안", "policy_version": "approved-options-v1",
                 "source": "test-fixture", "approved_by": "test-reviewer", "lever_values": {"fixture": "B"}},
                {"policy_option_id": "C", "label": "검증용 C안", "policy_version": "approved-options-v1",
                 "source": "test-fixture", "approved_by": "test-reviewer", "lever_values": {"fixture": "C"}},
            ],
        },
    )
    assert response.status_code == 200, response.text
    created = response.json()
    ADMISSION_CREDENTIALS[created["id"]] = list(created["admission_credentials"])
    assert len(ADMISSION_CREDENTIALS[created["id"]]) == capacity
    assert len(set(ADMISSION_CREDENTIALS[created["id"]])) == capacity
    return created


def test_legacy_hash_only_admission_is_collection_closed_until_admin_one_time_rotation(
    aipol_app, monkeypatch,
) -> None:
    server, client, db_path = aipol_app
    admin_headers = _admin_headers(client)
    editor_headers = _admin_headers(client, "editor")
    legacy = _create(client, admin_headers, capacity=2, suffix="-legacy")
    modern = _create(client, admin_headers, capacity=1, suffix="-modern")

    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP TRIGGER aipol_admission_seats_no_delete")
        connection.execute(
            "DELETE FROM aipol_admission_seats WHERE experiment_id=?", (legacy["id"],)
        )
        connection.execute(
            "UPDATE aipol_experiments SET admission_code_hash=? WHERE id=?",
            ("legacy-one-way-hash", legacy["id"]),
        )
        connection.execute(
            "CREATE TRIGGER aipol_admission_seats_no_delete BEFORE DELETE ON "
            "aipol_admission_seats BEGIN SELECT RAISE(ABORT, 'append-only'); END"
        )

    readiness = client.get("/readyz").json()
    assert readiness["collection_ready"] is False
    assert readiness["admission_inventory_ready"] is False
    assert readiness["legacy_admission_rotation_required_ids"] == [legacy["id"]]
    rows = client.get("/api/admin/aipol/experiments", headers=admin_headers).json()
    legacy_read = next(row for row in rows if row["id"] == legacy["id"])
    modern_read = next(row for row in rows if row["id"] == modern["id"])
    assert legacy_read["admission_state"] == "legacy_rotation_required"
    assert legacy_read["registration_open"] is False
    assert "admission_code_hash" not in legacy_read
    assert modern_read["admission_state"] == "ready"
    assert modern_read["admission_seat_count"] == 1

    blocked = client.post(
        f"/api/aipol/experiments/{legacy['id']}/participants",
        json={
            "admission_code": ADMISSION_CODE,
            "registration_nonce": "n" * 16, "idempotency_key": "legacy-blocked",
        },
    )
    assert blocked.status_code == 423

    monkeypatch.setenv(
        "EVENT_CREDENTIAL_SECRETS_JSON",
        json.dumps({"legacy-event-session": "s" * 48, "rotated-active": "r" * 48}),
    )
    monkeypatch.setenv("EVENT_CREDENTIAL_ACTIVE_KEY_ID", "rotated-active")

    denied = client.post(
        f"/api/admin/aipol/experiments/{legacy['id']}/admission-seats/rotate",
        headers=editor_headers,
        json={"reason": "legacy migration fixture"},
    )
    assert denied.status_code == 403
    rotated = client.post(
        f"/api/admin/aipol/experiments/{legacy['id']}/admission-seats/rotate",
        headers=admin_headers,
        json={
            "reason": "legacy migration fixture", "new_capacity": 2,
            "confirmation": f"ROTATE {legacy['id']} TO 2",
        },
    )
    assert rotated.status_code == 200
    assert rotated.headers["cache-control"] == "no-store"
    issued = rotated.json()["admission_credentials"]
    assert len(issued) == len(set(issued)) == 2
    assert rotated.json()["admission_state"] == "ready"
    with sqlite3.connect(db_path) as connection:
        retained_key_id = connection.execute(
            "SELECT credential_key_id FROM aipol_experiments WHERE id=?", (legacy["id"],)
        ).fetchone()[0]
    assert retained_key_id == "legacy-event-session"

    replay = client.post(
        f"/api/admin/aipol/experiments/{legacy['id']}/admission-seats/rotate",
        headers=admin_headers,
        json={
            "reason": "second issue must fail closed", "new_capacity": 2,
            "confirmation": f"ROTATE {legacy['id']} TO 2",
        },
    )
    assert replay.status_code == 409
    serialized_reads = json.dumps(
        client.get("/api/admin/aipol/experiments", headers=admin_headers).json()
    )
    assert all(credential not in serialized_reads for credential in issued)
    audit = client.get("/api/admin/aipol/audit", headers=admin_headers).json()
    rotation = next(
        event for event in audit["events"]
        if event["action"] == "experiment.admission_seats.rotated"
        and event["resource_id"] == legacy["id"]
    )
    assert json.loads(rotation["payload_json"]) == {
        "existing_participant_count": 0,
        "issued_count": 2,
        "new_capacity": 2,
        "old_capacity": 2,
        "reason": "legacy migration fixture",
    }
    assert all(credential not in json.dumps(rotation) for credential in issued)
    assert client.get("/readyz").json()["admission_inventory_ready"] is True


def test_legacy_rotation_rejects_zero_capacity_and_preserves_hash(aipol_app):
    _, client, db_path = aipol_app
    headers = _admin_headers(client)
    experiment = _create(client, headers, capacity=1, suffix="-legacy-zero")
    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP TRIGGER aipol_admission_seats_no_delete")
        connection.execute(
            "DELETE FROM aipol_admission_seats WHERE experiment_id=?", (experiment["id"],)
        )
        connection.execute(
            "UPDATE aipol_experiments SET capacity=0,admission_code_hash=? WHERE id=?",
            ("legacy-zero-hash", experiment["id"]),
        )
        connection.execute(
            "CREATE TRIGGER aipol_admission_seats_no_delete BEFORE DELETE ON "
            "aipol_admission_seats BEGIN SELECT RAISE(ABORT, 'append-only'); END"
        )
        connection.commit()
    response = client.post(
        f"/api/admin/aipol/experiments/{experiment['id']}/admission-seats/rotate",
        headers=headers,
        json={
            "reason": "zero capacity must fail closed", "new_capacity": 0,
            "confirmation": f"ROTATE {experiment['id']} TO 0",
        },
    )
    assert response.status_code == 400
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT capacity,admission_code_hash FROM aipol_experiments WHERE id=?",
            (experiment["id"],),
        ).fetchone()
        assert row == (0, "legacy-zero-hash")
        assert connection.execute(
            "SELECT COUNT(*) FROM aipol_admission_seats WHERE experiment_id=?",
            (experiment["id"],),
        ).fetchone()[0] == 0


def test_legacy_rotation_reserves_existing_participants_and_issues_only_remaining_seats(
    aipol_app,
):
    server, client, db_path = aipol_app
    headers = _admin_headers(client)
    experiment = _create(client, headers, capacity=2, suffix="-legacy-existing")
    _artifact(client, headers, experiment["id"], "personal_comparison", "personal-existing")
    assert _freeze(client, headers, experiment).status_code == 200
    existing = _register(client, experiment["id"])
    assert existing.status_code == 200
    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP TRIGGER aipol_admission_claims_no_delete")
        connection.execute("DROP TRIGGER aipol_admission_seats_no_delete")
        connection.execute(
            "DELETE FROM aipol_admission_claims WHERE experiment_id=?", (experiment["id"],)
        )
        connection.execute(
            "DELETE FROM aipol_admission_seats WHERE experiment_id=?", (experiment["id"],)
        )
        connection.execute(
            "UPDATE aipol_experiments SET admission_code_hash=? WHERE id=?",
            ("legacy-existing-hash", experiment["id"]),
        )
        connection.commit()
    server.aipol_store.init()
    rotated = client.post(
        f"/api/admin/aipol/experiments/{experiment['id']}/admission-seats/rotate",
        headers=headers,
        json={
            "reason": "reconcile existing legacy participant",
            "new_capacity": 2,
            "confirmation": f"ROTATE {experiment['id']} TO 2",
        },
    )
    assert rotated.status_code == 200
    issued = rotated.json()["admission_credentials"]
    assert len(issued) == 1
    assert rotated.json()["capacity"] == 2
    assert rotated.json()["admission_seat_count"] == 2
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM aipol_admission_claims WHERE experiment_id=?",
            (experiment["id"],),
        ).fetchone()[0] == 1
    for index, credential in enumerate(issued):
        assert _register(
            client, experiment["id"], code=credential,
            nonce=f"legacy-remaining-nonce-{index:04d}",
            key=f"legacy-remaining-key-{index:04d}",
        ).status_code == 200


def _canonical_documents(client: TestClient, headers: dict, experiment_id: str) -> dict[str, str]:
    existing = client.get(
        f"/api/admin/aipol/experiments/{experiment_id}/canonical-documents", headers=headers
    ).json()
    if existing:
        return {item["category"]: item["content_hash"] for item in existing}
    calculation_evidence = {
        "source_repository": "https://github.com/example/approved-calculator",
        "source_commit": "a" * 40,
        "source_tree_hash": "b" * 64,
        "build_hash": "c" * 64,
        "license_spdx": "Apache-2.0",
        "license_evidence_hash": "d" * 64,
        "approved_origin": "https://example.test",
        "csp": "default-src 'self'; script-src 'self'; connect-src 'none'; form-action 'none'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
        "network_test_hash": "e" * 64,
        "policy_values_status": "approved",
        "integration_status": "approved",
        "integration_contract_version": INTEGRATION_VERSION,
        "integration_test_hash": INTEGRATION_TEST_HASH,
        "receipt_contract": RECEIPT_CONTRACT,
        "receipt_contract_hash": content_hash(RECEIPT_CONTRACT),
        "raw_input_egress": False,
    }
    hashes = {}
    editor_headers = _admin_headers(client, "editor")
    for category in CATEGORIES:
        request_body = {
            "category": category,
            "document_id": f"doc-{category}",
            "document_version": "v1",
            "body": f"사람이 승인한 {category} 정본 fixture",
            "evidence": calculation_evidence if category == "calculation" else {"fixture": True},
        }
        preview = client.post(
            f"/api/admin/aipol/experiments/{experiment_id}/canonical-documents/preview",
            headers=headers,
            json=request_body,
        )
        assert preview.status_code == 200, preview.text
        digest = preview.json()["content_hash"]
        drafted = client.post(
            f"/api/admin/aipol/experiments/{experiment_id}/canonical-drafts",
            headers=editor_headers,
            json={**request_body, "declared_content_hash": digest},
        )
        assert drafted.status_code == 200, drafted.text
        saved = client.post(
            f"/api/admin/aipol/experiments/{experiment_id}/canonical-documents",
            headers=headers,
            json={
                **request_body,
                "declared_content_hash": digest,
                "approval_id": f"approval-{experiment_id}-{category}",
                "approved_by": "hong",
            },
        )
        assert saved.status_code == 200, saved.text
        hashes[category] = digest
    return hashes


def _freeze_body(client: TestClient, headers: dict, experiment: dict, *, mismatch=False) -> dict:
    spec = MeasurementSpec(**experiment["measurement_spec"])
    documents = client.get(
        f"/api/admin/aipol/experiments/{experiment['id']}/canonical-documents", headers=headers
    ).json()
    by_category = {document["category"]: document for document in documents}
    assert set(by_category) == set(CATEGORIES)
    body = {
        "manifest_id": "freeze-a",
        "experiment_version": experiment["experiment_version"],
        "option_set_version": experiment["measurement_spec"]["option_set_version"],
        "measurement_spec_hash": "f" * 64 if mismatch else spec.spec_hash,
        "status": "frozen",
        "collection_enabled": True,
        "approvals": [
            {
                "category": category,
                "approval_id": by_category[category]["approval_id"],
                "approved_by": by_category[category]["approved_by"],
                "approved_at": by_category[category]["approved_at"],
                "content_hash": by_category[category]["content_hash"],
            }
            for category in CATEGORIES
        ],
    }
    return body


def _freeze(client: TestClient, headers: dict, experiment: dict, *, mismatch=False) -> dict:
    body = _freeze_body(client, headers, experiment, mismatch=mismatch)
    _artifact(client, headers, experiment["id"], "expert_explanation", "expert")
    _artifact(client, headers, experiment["id"], "ai_opinion", "ai-fallback", fallback=True)
    return client.put(
        f"/api/admin/aipol/experiments/{experiment['id']}/freeze", headers=headers, json=body
    )


def _artifact(client, headers, experiment_id, kind, marker, *, fallback=False):
    if kind == "ai_opinion":
        response = client.post(
            f"/api/admin/aipol/experiments/{experiment_id}/ai-candidates",
            headers=headers,
            json={
                "candidate_role": "fallback" if fallback else "primary",
                "artifact_id": marker,
                "artifact_version": "v1",
                "content": {"title": marker, "body": "운영 승인된 AI 자료"},
                "model": "fixture-model",
                "deployment": "fixture-deployment",
                "prompt_version": "fixture-prompt-v1",
                "generated_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
                "evidence_refs": ["fixture-evidence-1"],
                "m2_aggregate_hash": None if fallback else "f" * 64,
                "approval_id": f"approval-{experiment_id}-{marker}",
                "approved_by": "hong",
            },
        )
        assert response.status_code == 200, response.text
        return response.json()
    content = {"title": marker, "body": "운영 승인된 자료"}
    if kind == "personal_comparison":
        documents = _canonical_documents(client, headers, experiment_id)
        content = {
            "title": "승인된 개인 조건 비교",
            "launch_url": "https://example.test/approved-calculator",
            "launch_origin": "https://example.test",
            "calculation_version": "fixture-v1",
            "limitations": "검증용 fixture이며 실제 연금액이 아닙니다.",
            "canonical_document_hash": documents["calculation"],
            "build_hash": "c" * 64,
            "receipt_contract_hash": content_hash(RECEIPT_CONTRACT),
            "integration_contract_version": INTEGRATION_VERSION,
            "integration_test_hash": INTEGRATION_TEST_HASH,
        }
    response = client.post(
        f"/api/admin/aipol/experiments/{experiment_id}/artifacts",
        headers=headers,
        json={
            "kind": kind,
            "artifact_id": marker,
            "artifact_version": "v1",
            "content": content,
            "approval_id": f"approval-{experiment_id}-{marker}",
            "approved_by": "hong",
            "fallback_used": fallback,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _participant_headers(token: str) -> dict:
    return {"X-Participant-Token": token}


def _register(client, experiment_id, *, code=None, nonce=None, key=None):
    nonce = nonce or f"nonce-{uuid.uuid4()}"
    key = key or f"register-{uuid.uuid4()}"
    automatic = code is None
    credentials = ADMISSION_CREDENTIALS.get(experiment_id, [])
    selected_code = code if code is not None else (credentials[0] if credentials else ADMISSION_CODE)
    response = client.post(
        f"/api/aipol/experiments/{experiment_id}/participants",
        json={"admission_code": selected_code, "registration_nonce": nonce, "idempotency_key": key},
    )
    if automatic and response.status_code == 200 and credentials and credentials[0] == selected_code:
        credentials.pop(0)
    return response


def _post(client, path, token, revision, key, **extra):
    if "/exposures/" in path and not path.endswith("/open") and extra.get("read_ack") is True:
        opened = client.post(
            f"{path}/open",
            headers=_participant_headers(token),
            json={"expected_revision": revision, "idempotency_key": f"{key}-open"},
        )
        if opened.status_code != 200:
            return opened
    if path.endswith("/exposures/E1a") and "completion_receipt" not in extra:
        extra["completion_receipt"] = {
            "receipt_id": f"fixture-{uuid.uuid4()}",
            "contract_hash": content_hash(RECEIPT_CONTRACT),
            "signature": "test-only-not-a-production-signature",
        }
    return client.post(
        path,
        headers=_participant_headers(token),
        json={"expected_revision": revision, "idempotency_key": key, **extra},
    )


def _full_flow(client, experiment_id, token, *, choices=("A", "B", "C"), release=True):
    base = f"/api/aipol/experiments/{experiment_id}"
    assert _post(client, f"{base}/consent", token, 0, "consent", consent_version="consent-v1", affirmed=True).status_code == 200
    assert _post(client, f"{base}/exposures/E1a", token, 1, "e1a", read_ack=True).status_code == 200
    assert _post(client, f"{base}/measurements/M1", token, 2, "m1", choice=choices[0], reason="", confidence=3).status_code == 200
    assert _post(client, f"{base}/exposures/E1b", token, 3, "e1b", read_ack=True).status_code == 200
    assert _post(client, f"{base}/measurements/M2", token, 4, "m2", choice=choices[1], reason="", confidence=3).status_code == 200
    if release:
        admin_headers = _admin_headers(client)
        assert client.post(
            f"/api/admin/aipol/experiments/{experiment_id}/close-registration", headers=admin_headers
        ).status_code == 200
        assert client.post(
            f"/api/admin/aipol/experiments/{experiment_id}/release-e2",
            headers=admin_headers,
            json={"candidate_role": "fallback", "selection_reason": "fixture 장애 대체본 선택"},
        ).status_code == 200
    assert _post(client, f"{base}/exposures/E2", token, 5, "e2", read_ack=True).status_code == 200
    response = _post(
        client, f"{base}/measurements/M3", token, 6, "m3", choice=choices[2], reason="",
        confidence=3,
        secondary_evaluation={"artifact_id": "ai-fallback", "acceptance": 4, "reason": "별도 평가"},
    )
    assert response.status_code == 200, response.text
    return response


def _advance_to_m2(client, experiment_id, token, *, choice="B"):
    base = f"/api/aipol/experiments/{experiment_id}"
    assert _post(client, f"{base}/consent", token, 0, "c", consent_version="consent-v1", affirmed=True).status_code == 200
    assert _post(client, f"{base}/exposures/E1a", token, 1, "e1a", read_ack=True).status_code == 200
    assert _post(client, f"{base}/measurements/M1", token, 2, "m1", choice="A", reason="", confidence=3).status_code == 200
    assert _post(client, f"{base}/exposures/E1b", token, 3, "e1b", read_ack=True).status_code == 200
    assert _post(client, f"{base}/measurements/M2", token, 4, "m2", choice=choice, reason="", confidence=3).status_code == 200


def test_collection_is_closed_until_matching_freeze_manifest(aipol_app):
    _, client, _ = aipol_app
    headers = _admin_headers(client)
    experiment = _create(client, headers)
    register = _register(client, experiment["id"])
    assert register.status_code == 423
    _artifact(client, headers, experiment["id"], "personal_comparison", "personal-tool")
    mismatch = _freeze(client, headers, experiment, mismatch=True)
    assert mismatch.status_code == 423
    assert _register(client, experiment["id"]).status_code == 423


def test_registration_code_nonce_idempotency_capacity_and_concurrency(aipol_app):
    server, client, db_path = aipol_app
    headers = _admin_headers(client)
    experiment = _create(client, headers, capacity=1)
    _artifact(client, headers, experiment["id"], "personal_comparison", "personal-tool")
    assert _freeze(client, headers, experiment).status_code == 200
    assert _register(client, experiment["id"], code="Wrong-Code-2026!").status_code == 401

    nonce = "nonce-concurrent-00000001"
    key = "register-concurrent-0001"
    seat_code = experiment["admission_credentials"][0]
    def register_once(_):
        with TestClient(server.app) as concurrent_client:
            return _register(
                concurrent_client, experiment["id"], code=seat_code, nonce=nonce, key=key
            )
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(register_once, range(2)))
    assert [response.status_code for response in responses] == [200, 200]
    assert len({response.json()["participant_token"] for response in responses}) == 1
    assert _register(client, experiment["id"], code="Wrong-Code-2027!").status_code == 401
    remote_key = (experiment["id"], "testclient")
    assert remote_key in server.REGISTRATION_FAILURES
    assert _register(
        client, experiment["id"], code=seat_code, nonce=nonce, key=key
    ).status_code == 200
    assert remote_key in server.REGISTRATION_FAILURES
    assert _register(client, experiment["id"], nonce=nonce, key="different-key-0001").status_code == 409
    assert _register(client, experiment["id"], code=seat_code).status_code == 401
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM aipol_registration_nonces").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM aipol_admission_claims").fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM aipol_participants WHERE participant_type='real'"
        ).fetchone()[0] == 1
        assert seat_code not in "\n".join(connection.iterdump())
    fetched = next(
        item for item in client.get("/api/admin/aipol/experiments", headers=headers).json()
        if item["id"] == experiment["id"]
    )
    assert "admission_credentials" not in fetched


def test_one_time_recovery_rotates_token_without_plaintext_and_blocks_replay_race_mismatch(
    aipol_app,
):
    server, client, db_path = aipol_app
    headers = _admin_headers(client)
    experiment = _create(client, headers, capacity=1, suffix="-recovery")
    other = _create(client, headers, capacity=1, suffix="-recovery-other")
    _artifact(client, headers, experiment["id"], "personal_comparison", "personal-recovery")
    assert _freeze(client, headers, experiment).status_code == 200
    registered = _register(
        client, experiment["id"], nonce="recovery-nonce-00000001", key="recovery-register-0001"
    )
    assert registered.status_code == 200
    assert registered.headers["cache-control"] == "no-store"
    original_token = registered.json()["participant_token"]
    original_code = registered.json()["recovery_code"]
    assert original_code.startswith("AIPOL-RC-") and len(original_code) >= 40

    mismatch = client.post(
        f"/api/aipol/experiments/{other['id']}/participants/recover",
        json={"recovery_code": original_code},
    )
    assert mismatch.status_code == 401
    recovered = client.post(
        f"/api/aipol/experiments/{experiment['id']}/participants/recover",
        json={"recovery_code": original_code},
    )
    assert recovered.status_code == 200
    assert recovered.headers["cache-control"] == "no-store"
    replacement_token = recovered.json()["participant_token"]
    replacement_code = recovered.json()["recovery_code"]
    assert replacement_token != original_token and replacement_code != original_code
    base = f"/api/aipol/experiments/{experiment['id']}"
    assert client.get(f"{base}/current", headers=_participant_headers(original_token)).status_code == 401
    restored = client.get(f"{base}/current", headers=_participant_headers(replacement_token))
    assert restored.status_code == 200
    assert restored.json()["stage"] == "consent" and restored.json()["state_revision"] == 0
    assert client.post(
        f"{base}/participants/recover", json={"recovery_code": original_code}
    ).status_code == 401

    def redeem_once(_):
        with TestClient(server.app) as concurrent_client:
            return concurrent_client.post(
                f"{base}/participants/recover", json={"recovery_code": replacement_code}
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        raced = list(pool.map(redeem_once, range(2)))
    assert sorted(response.status_code for response in raced) == [200, 401]

    with sqlite3.connect(db_path) as connection:
        dump = "\n".join(connection.iterdump())
        assert original_code not in dump and replacement_code not in dump
        assert original_token not in dump and replacement_token not in dump
        assert "recovery-nonce-00000001" not in dump
        assert connection.execute(
            "SELECT COUNT(*) FROM aipol_participant_recoveries"
        ).fetchone()[0] == 2
        assert connection.execute(
            "SELECT COUNT(*) FROM aipol_participant_recovery_codes"
        ).fetchone()[0] == 3
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("DELETE FROM aipol_participant_recoveries")


def test_server_generated_registration_codes_failure_budgets_and_success_volume(aipol_app, monkeypatch):
    server, client, _ = aipol_app
    headers = _admin_headers(client)
    weak = client.post(
        "/api/admin/aipol/experiments", headers=_admin_headers(client, "editor"),
        json={
            "title": "weak", "experiment_version": "weak-v1", "session_id": "weak-session",
            "consent_version": "v1", "consent_text": "consent", "question_id": "q",
            "question_text": "question", "option_set_version": "v1", "admission_code": "Operator-Code-123!",
            "capacity": 1, "policy_options": [
                {"policy_option_id": key, "label": key, "policy_version": "v1"}
                for key in ("A", "B", "C")
            ],
        },
    )
    assert weak.status_code == 400
    assert "unexpected=['admission_code']" in weak.text
    with pytest.raises(server.aipol_store.ExperimentError, match="3종 이상"):
        server.aipol_store._validate_admission_code("aaaaaaaaaaaaaaaa")

    experiment = _create(client, headers, capacity=20, suffix="-rate")
    assert all(code.startswith("Aipol-7-") for code in experiment["admission_credentials"])
    assert "Operator-Code-123!" not in experiment["admission_credentials"]
    _artifact(client, headers, experiment["id"], "personal_comparison", "personal-tool-rate")
    assert _freeze(client, headers, experiment).status_code == 200
    monkeypatch.setattr(server, "AIPOL_REGISTRATION_FAILURES_PER_REMOTE", 3)
    for attempt in range(3):
        assert _register(client, experiment["id"], code=f"wrong-code-{attempt:04d}!").status_code == 401
    limited = _register(client, experiment["id"], code="wrong-code-final!")
    assert limited.status_code == 429 and "Retry-After" in limited.headers

    server.REGISTRATION_FAILURES.clear()
    server.REGISTRATION_GLOBAL_FAILURES.clear()
    volume = _create(client, headers, capacity=100, suffix="-success-volume")
    _artifact(client, headers, volume["id"], "personal_comparison", "personal-tool-volume")
    assert _freeze(client, headers, volume).status_code == 200
    def shared_nat_registration(code):
        return _register(client, volume["id"], code=code).status_code

    with ThreadPoolExecutor(max_workers=32) as pool:
        statuses = list(pool.map(shared_nat_registration, volume["admission_credentials"]))
    assert statuses == [200] * 100
    assert server.REGISTRATION_FAILURES == {}
    assert server.REGISTRATION_GLOBAL_FAILURES == []

    monkeypatch.setattr(server, "AIPOL_REGISTRATION_RATE_MAX_KEYS", 100)
    monkeypatch.setattr(server, "AIPOL_REGISTRATION_GLOBAL_FAILURE_BUDGET", 10_000)
    for index in range(150):
        server._record_registration_failure(f"experiment-{index}", f"remote-{index}")
    assert len(server.REGISTRATION_FAILURES) <= 100
    monkeypatch.setattr(server, "AIPOL_REGISTRATION_GLOBAL_FAILURE_BUDGET", 10)
    with pytest.raises(server.HTTPException) as blocked:
        server._check_registration_failure_budget("new-experiment", "new-remote")
    assert blocked.value.status_code == 429


def test_untrusted_forwarded_headers_cannot_bypass_login_or_registration_limits(
    aipol_app, monkeypatch
):
    server, client, _ = aipol_app
    assert server.TRUSTED_PROXY_NETWORKS == ()

    server.LOGIN_FAILURES.clear()
    for attempt in range(10):
        response = client.post(
            "/api/admin/login",
            headers={"X-Forwarded-For": f"198.51.100.{attempt + 1}"},
            json={"username": "hong", "password": "wrong"},
        )
        assert response.status_code == 401
    assert client.post(
        "/api/admin/login",
        headers={"X-Forwarded-For": "203.0.113.250"},
        json={"username": "hong", "password": "wrong"},
    ).status_code == 429
    assert set(server.LOGIN_FAILURES) == {"testclient|hong"}

    server.LOGIN_FAILURES.clear()
    headers = _admin_headers(client)
    experiment = _create(client, headers, capacity=4, suffix="-xff-limit")
    _artifact(client, headers, experiment["id"], "personal_comparison", "personal-tool-xff")
    assert _freeze(client, headers, experiment).status_code == 200
    monkeypatch.setattr(server, "AIPOL_REGISTRATION_FAILURES_PER_REMOTE", 3)
    monkeypatch.setattr(server, "AIPOL_REGISTRATION_GLOBAL_FAILURE_BUDGET", 4)
    server.REGISTRATION_FAILURES.clear()
    server.REGISTRATION_GLOBAL_FAILURES.clear()
    for attempt in range(3):
        response = client.post(
            f"/api/aipol/experiments/{experiment['id']}/participants",
            headers={"X-Forwarded-For": f"198.51.100.{attempt + 1}"},
            json={
                "admission_code": "Wrong-Code-2026!",
                "registration_nonce": f"nonce-xff-{attempt:08d}",
                "idempotency_key": f"register-xff-{attempt:08d}",
            },
        )
        assert response.status_code == 401
    blocked = client.post(
        f"/api/aipol/experiments/{experiment['id']}/participants",
        headers={"X-Forwarded-For": "203.0.113.250"},
        json={
            "admission_code": "Wrong-Code-2026!",
            "registration_nonce": "nonce-xff-final-0001",
            "idempotency_key": "register-xff-final-0001",
        },
    )
    assert blocked.status_code == 429
    assert len(server.REGISTRATION_FAILURES) == 1
    assert len(server.REGISTRATION_GLOBAL_FAILURES) == 3


def test_trusted_proxy_chain_uses_rightmost_untrusted_address(aipol_app, monkeypatch):
    server, _, _ = aipol_app
    monkeypatch.setattr(
        server,
        "TRUSTED_PROXY_NETWORKS",
        (ipaddress.ip_network("10.0.0.0/8"),),
    )
    request = server.Request({
        "type": "http",
        "client": ("10.1.2.3", 1234),
        "headers": [(b"x-forwarded-for", b"203.0.113.77, 198.51.100.8, 10.2.3.4")],
    })
    assert server._remote_address(request) == "198.51.100.8"

    malformed = server.Request({
        "type": "http",
        "client": ("10.1.2.3", 1234),
        "headers": [(b"x-forwarded-for", b"not-an-ip")],
    })
    assert server._remote_address(malformed) == "10.1.2.3"


def test_experiment_mutation_audit_outbox_survives_delivery_failure_and_restart(aipol_app, monkeypatch):
    server, client, db_path = aipol_app
    original = server.aipol_admin_store.drain_experiment_audit_outbox

    def unavailable(*_args, **_kwargs):
        raise sqlite3.OperationalError("simulated audit sink outage")

    monkeypatch.setattr(server.aipol_admin_store, "drain_experiment_audit_outbox", unavailable)
    created = _create(client, _admin_headers(client), suffix="-outbox-restart")
    with sqlite3.connect(db_path) as connection:
        pending = connection.execute(
            "SELECT COUNT(*) FROM aipol_experiment_audit_outbox WHERE delivered_at IS NULL"
        ).fetchone()[0]
        assert pending >= 1
        assert connection.execute(
            "SELECT COUNT(*) FROM aipol_experiments WHERE id=?", (created["id"],)
        ).fetchone()[0] == 1

    monkeypatch.setattr(server.aipol_admin_store, "drain_experiment_audit_outbox", original)
    for name in MODULES:
        sys.modules.pop(name, None)
    restarted = importlib.import_module("server")
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM aipol_experiment_audit_outbox WHERE delivered_at IS NULL"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM aipol_admin_audit WHERE resource_id=? AND action='experiment.created'",
            (created["id"],),
        ).fetchone()[0] == 1
        sequences = [row[0] for row in connection.execute(
            "SELECT sequence FROM aipol_admin_audit ORDER BY sequence"
        )]
        assert sequences == list(range(1, len(sequences) + 1))
    assert restarted.aipol_admin_store.verify_audit_chain()


def test_freeze_rejects_arbitrary_hashes_and_unlicensed_calculator(aipol_app):
    _, client, _ = aipol_app
    headers = _admin_headers(client)
    experiment = _create(client, headers)
    _artifact(client, headers, experiment["id"], "personal_comparison", "personal-tool")
    documents = client.get(
        f"/api/admin/aipol/experiments/{experiment['id']}/canonical-documents", headers=headers
    ).json()
    hashes = {item["category"]: item["content_hash"] for item in documents}
    body = {
        "manifest_id": "tampered-freeze",
        "experiment_version": experiment["experiment_version"],
        "option_set_version": experiment["measurement_spec"]["option_set_version"],
        "measurement_spec_hash": experiment["measurement_spec_hash"],
        "status": "frozen",
        "collection_enabled": True,
        "approvals": [
            {
                "category": category,
                "approval_id": f"tampered-{category}",
                "approved_by": "research-owner",
                "approved_at": "2026-08-01T09:00:00+09:00",
                "content_hash": "0" * 64 if category == "privacy" else hashes[category],
            }
            for category in CATEGORIES
        ],
    }
    rejected = client.put(
        f"/api/admin/aipol/experiments/{experiment['id']}/freeze", headers=headers, json=body
    )
    assert rejected.status_code == 423
    assert _register(client, experiment["id"]).status_code == 423

    other = _create(client, headers, suffix="-unlicensed")
    evidence = {
        "source_repository": "https://github.com/armybonita/repo",
        "source_commit": "a" * 40,
        "source_tree_hash": "b" * 64,
        "build_hash": "c" * 64,
        "license_spdx": "NOASSERTION",
        "license_evidence_hash": "d" * 64,
        "approved_origin": "https://personal-pension-simulator-v2.army78.chatgpt.site",
        "csp": "default-src 'self'; script-src 'self'; connect-src 'none'; form-action 'none'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
        "network_test_hash": "e" * 64,
        "policy_values_status": "placeholder",
        "raw_input_egress": False,
    }
    preview = client.post(
        f"/api/admin/aipol/experiments/{other['id']}/canonical-documents/preview",
        headers=headers,
        json={
            "category": "calculation", "document_id": "pr1", "document_version": "fcbae3c",
            "body": "PR #1 감사본", "evidence": evidence,
        },
    )
    assert preview.status_code == 400
    evidence["license_spdx"] = "Apache-2.0"
    assert client.post(
        f"/api/admin/aipol/experiments/{other['id']}/canonical-documents/preview",
        headers=headers,
        json={
            "category": "calculation", "document_id": "pr1", "document_version": "fcbae3c",
            "body": "PR #1 policy values review", "evidence": evidence,
        },
    ).status_code == 400
    evidence["policy_values_status"] = "approved"
    evidence["integration_status"] = "approved"
    evidence["receipt_contract"] = RECEIPT_CONTRACT
    evidence["receipt_contract_hash"] = content_hash(RECEIPT_CONTRACT)
    assert client.post(
        f"/api/admin/aipol/experiments/{other['id']}/canonical-documents/preview",
        headers=headers,
        json={
            "category": "calculation", "document_id": "pr1", "document_version": "fcbae3c",
            "body": "PR #1 has no fragment/postMessage integration evidence", "evidence": evidence,
        },
    ).status_code == 400
    assert other["collection_enabled"] is False and other["registration_open"] is False


def test_primary_ai_requires_frozen_m2_hash_and_manual_selection(aipol_app):
    _, client, db_path = aipol_app
    headers = _admin_headers(client)
    experiment = _create(client, headers)
    _artifact(client, headers, experiment["id"], "personal_comparison", "personal-tool")
    assert _freeze(client, headers, experiment).status_code == 200
    token = _register(client, experiment["id"]).json()["participant_token"]
    _advance_to_m2(client, experiment["id"], token)
    client.post(
        f"/api/admin/aipol/experiments/{experiment['id']}/close-registration", headers=headers
    )
    aggregate = client.get(
        f"/api/admin/aipol/experiments/{experiment['id']}/m2-aggregate", headers=headers
    ).json()
    future_generated_at = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    invalid_primary = client.post(
        f"/api/admin/aipol/experiments/{experiment['id']}/ai-candidates",
        headers=headers,
        json={
            "candidate_role": "primary", "artifact_id": "invalid-primary", "artifact_version": "v1",
            "content": {"title": "invalid", "body": "invalid aggregate hash"},
            "model": "approved-model", "deployment": "approved-deployment",
            "prompt_version": "prompt-v1", "generated_at": future_generated_at,
            "evidence_refs": ["m2-aggregate"], "m2_aggregate_hash": aggregate["aggregate_hash"],
            "approval_id": "approval-invalid", "approved_by": "hong",
        },
    )
    assert invalid_primary.status_code == 400
    before_cutoff = (
        datetime.fromisoformat(aggregate["cutoff_at"].replace("Z", "+00:00"))
        - timedelta(seconds=1)
    ).isoformat()
    reversed_primary = client.post(
        f"/api/admin/aipol/experiments/{experiment['id']}/ai-candidates",
        headers=headers,
        json={
            "candidate_role": "primary", "artifact_id": "reversed-primary", "artifact_version": "v1",
            "content": {"title": "reversed", "body": "pre-M2 generation"},
            "model": "approved-model", "deployment": "approved-deployment",
            "prompt_version": "prompt-v1", "generated_at": before_cutoff,
            "evidence_refs": ["m2-aggregate"], "m2_aggregate_hash": aggregate["aggregate_hash"],
            "approval_id": "approval-reversed", "approved_by": "hong",
        },
    )
    assert reversed_primary.status_code == 400
    generated_after_m2 = datetime.now(timezone.utc).isoformat()
    primary = client.post(
        f"/api/admin/aipol/experiments/{experiment['id']}/ai-candidates",
        headers=headers,
        json={
            "candidate_role": "primary", "artifact_id": "ai-primary", "artifact_version": "v1",
            "content": {"title": "M2 기반 AI 의견", "body": "승인 본문"},
            "model": "approved-model", "deployment": "approved-deployment",
            "prompt_version": "prompt-v1", "generated_at": generated_after_m2,
            "evidence_refs": ["m2-aggregate", "policy-options-v1"],
            "m2_aggregate_hash": aggregate["aggregate_hash"],
            "approval_id": "approval-primary", "approved_by": "hong",
        },
    )
    assert primary.status_code == 200, primary.text
    assert client.post(
        f"/api/admin/aipol/experiments/{experiment['id']}/release-e2",
        headers=headers,
        json={"candidate_role": "primary", "selection_reason": ""},
    ).status_code == 400
    released = client.post(
        f"/api/admin/aipol/experiments/{experiment['id']}/release-e2",
        headers=headers,
        json={"candidate_role": "primary", "selection_reason": "M2 기반 승인본 선택"},
    )
    assert released.status_code == 200, released.text
    current = client.get(
        f"/api/aipol/experiments/{experiment['id']}/current",
        headers=_participant_headers(token),
    ).json()
    assert current["artifact"]["artifact_id"] == "ai-primary"
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT candidate_role,selection_reason,selected_by,m2_aggregate_hash FROM aipol_e2_selections"
        ).fetchone() == (
            "primary", "M2 기반 승인본 선택", "hong", aggregate["aggregate_hash"],
        )


def test_ai_candidate_public_schema_matches_exact_response_and_provenance_hash(aipol_app):
    from jsonschema import Draft202012Validator, FormatChecker
    from jsonschema.exceptions import ValidationError

    _, client, _ = aipol_app
    headers = _admin_headers(client)
    experiment = _create(client, headers, suffix="-ai-schema")
    approved = _artifact(
        client, headers, experiment["id"], "ai_opinion", "ai-schema-fallback",
        fallback=True,
    )
    schema = json.loads(
        (ROOT / "contracts" / "aipol-ai-candidate-approved-public.schema.json").read_text("utf-8")
    )
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    validator.validate(approved)
    assert approved["content_hash"] != content_hash(approved["content"])
    with pytest.raises(ValidationError):
        validator.validate({**approved, "unexpected": True})
    missing = dict(approved)
    missing.pop("approved_at")
    with pytest.raises(ValidationError):
        validator.validate(missing)


def test_release_rejects_ai_candidate_provenance_tampering_even_if_content_is_unchanged(
    aipol_app,
):
    _, client, db_path = aipol_app
    headers = _admin_headers(client)
    experiment = _create(client, headers, suffix="-ai-tamper")
    _artifact(client, headers, experiment["id"], "personal_comparison", "personal-ai-tamper")
    assert _freeze(client, headers, experiment).status_code == 200
    token = _register(client, experiment["id"]).json()["participant_token"]
    _advance_to_m2(client, experiment["id"], token)
    assert client.post(
        f"/api/admin/aipol/experiments/{experiment['id']}/close-registration", headers=headers
    ).status_code == 200
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        row = dict(connection.execute(
            "SELECT * FROM aipol_ai_candidates WHERE experiment_id=? AND candidate_role='fallback'",
            (experiment["id"],),
        ).fetchone())
        tampered_content = {"title": "tampered", "body": "unapproved body"}
        tampered_envelope = {
            "candidate_role": row["candidate_role"],
            "artifact_id": row["artifact_id"],
            "artifact_version": row["artifact_version"],
            "content": tampered_content,
            "model": "tampered-model",
            "deployment": row["deployment"],
            "prompt_version": row["prompt_version"],
            "generated_at": row["generated_at"],
            "evidence_refs": json.loads(row["evidence_refs"]),
            "m2_aggregate_hash": row["m2_aggregate_hash"],
        }
        connection.execute("DROP TRIGGER aipol_ai_candidates_no_update")
        connection.execute(
            "UPDATE aipol_ai_candidates SET model='tampered-model',content=?,content_hash=? "
            "WHERE experiment_id=? AND candidate_role='fallback'",
            (
                json.dumps(tampered_content, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                content_hash(tampered_envelope), experiment["id"],
            ),
        )
        connection.commit()
    rejected = client.post(
        f"/api/admin/aipol/experiments/{experiment['id']}/release-e2",
        headers=headers,
        json={"candidate_role": "fallback", "selection_reason": "must fail"},
    )
    assert rejected.status_code == 409
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM aipol_e2_selections WHERE experiment_id=?",
            (experiment["id"],),
        ).fetchone()[0] == 0


def test_release_requires_exactly_one_independent_ai_approval_event(aipol_app):
    _, client, db_path = aipol_app
    headers = _admin_headers(client)
    experiment = _create(client, headers, suffix="-ai-approval-anchor")
    _artifact(client, headers, experiment["id"], "personal_comparison", "personal-anchor")
    assert _freeze(client, headers, experiment).status_code == 200
    token = _register(client, experiment["id"]).json()["participant_token"]
    _advance_to_m2(client, experiment["id"], token)
    assert client.post(
        f"/api/admin/aipol/experiments/{experiment['id']}/close-registration", headers=headers
    ).status_code == 200
    with sqlite3.connect(db_path) as connection:
        approval = connection.execute(
            "SELECT * FROM aipol_approval_events WHERE experiment_id=? "
            "AND object_type='ai_candidate' AND object_id='fallback'",
            (experiment["id"],),
        ).fetchone()
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO aipol_approval_events VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    "duplicate-approval", experiment["id"], "ai_candidate", "fallback",
                    approval[4], "different-approval-id", approval[6], approval[7],
                    approval[8], time.time(),
                ),
            )
        connection.rollback()
        connection.execute("DROP TRIGGER aipol_approval_events_no_delete")
        connection.execute(
            "DELETE FROM aipol_approval_events WHERE experiment_id=? "
            "AND object_type='ai_candidate' AND object_id='fallback'",
            (experiment["id"],),
        )
        connection.commit()
    rejected = client.post(
        f"/api/admin/aipol/experiments/{experiment['id']}/release-e2",
        headers=headers,
        json={"candidate_role": "fallback", "selection_reason": "missing approval must fail"},
    )
    assert rejected.status_code == 409


def test_released_e2_candidate_is_rehashed_and_checked_against_release_binding(aipol_app):
    _, client, db_path = aipol_app
    headers = _admin_headers(client)
    experiment = _create(client, headers, suffix="-released-ai-tamper")
    _artifact(client, headers, experiment["id"], "personal_comparison", "personal-released-ai")
    assert _freeze(client, headers, experiment).status_code == 200
    token = _register(client, experiment["id"]).json()["participant_token"]
    _advance_to_m2(client, experiment["id"], token)
    assert client.post(
        f"/api/admin/aipol/experiments/{experiment['id']}/close-registration", headers=headers
    ).status_code == 200
    assert client.post(
        f"/api/admin/aipol/experiments/{experiment['id']}/release-e2", headers=headers,
        json={"candidate_role": "fallback", "selection_reason": "approved fallback"},
    ).status_code == 200
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        row = dict(connection.execute(
            "SELECT * FROM aipol_ai_candidates WHERE experiment_id=? AND candidate_role='fallback'",
            (experiment["id"],),
        ).fetchone())
        changed = {**json.loads(row["content"]), "body": "unapproved released replacement"}
        changed_digest = content_hash({
            "candidate_role": row["candidate_role"], "artifact_id": row["artifact_id"],
            "artifact_version": row["artifact_version"], "content": changed,
            "model": row["model"], "deployment": row["deployment"],
            "prompt_version": row["prompt_version"], "generated_at": row["generated_at"],
            "evidence_refs": json.loads(row["evidence_refs"]),
            "m2_aggregate_hash": row["m2_aggregate_hash"],
        })
        connection.execute("DROP TRIGGER aipol_ai_candidates_no_update")
        connection.execute(
            "UPDATE aipol_ai_candidates SET content=?,content_hash=? WHERE id=?",
            (
                json.dumps(changed, sort_keys=True, separators=(",", ":")),
                changed_digest, row["id"],
            ),
        )
        connection.commit()
    current = client.get(
        f"/api/aipol/experiments/{experiment['id']}/current",
        headers=_participant_headers(token),
    )
    assert current.status_code == 409
    assert "unapproved released replacement" not in current.text


def test_e2_waits_for_registration_close_m2_barrier_and_audited_attrition(aipol_app):
    _, client, db_path = aipol_app
    headers = _admin_headers(client)
    experiment = _create(client, headers)
    _artifact(client, headers, experiment["id"], "personal_comparison", "personal-tool")
    assert _freeze(client, headers, experiment).status_code == 200
    first = _register(client, experiment["id"]).json()
    _register(client, experiment["id"])
    token = first["participant_token"]
    base = f"/api/aipol/experiments/{experiment['id']}"
    _post(client, f"{base}/consent", token, 0, "c", consent_version="consent-v1", affirmed=True)
    _post(client, f"{base}/exposures/E1a", token, 1, "e1a", read_ack=True)
    _post(client, f"{base}/measurements/M1", token, 2, "m1", choice="A", reason="", confidence=3)
    _post(client, f"{base}/exposures/E1b", token, 3, "e1b", read_ack=True)
    _post(client, f"{base}/measurements/M2", token, 4, "m2", choice="B", reason="", confidence=3)

    waiting = client.get(f"{base}/current", headers=_participant_headers(token)).json()
    assert waiting["waiting_for_e2_release"] is True
    assert "artifact" not in waiting
    assert client.post(
        f"/api/admin/aipol/experiments/{experiment['id']}/close-registration", headers=headers
    ).status_code == 200
    assert client.post(
        f"/api/admin/aipol/experiments/{experiment['id']}/release-e2", headers=headers,
        json={"candidate_role": "fallback", "selection_reason": "barrier 검증"},
    ).status_code == 400
    attrited = client.post(
        f"/api/admin/aipol/experiments/{experiment['id']}/mark-pending-attrition",
        headers=headers,
        json={"actor": "spoofed-user", "reason": "사전 등록된 M2 마감 규칙"},
    )
    assert attrited.status_code == 200 and attrited.json()["attrited"] == 1
    assert client.post(
        f"/api/admin/aipol/experiments/{experiment['id']}/release-e2", headers=headers,
        json={"candidate_role": "fallback", "selection_reason": "미완료자 처리 후 공개"},
    ).status_code == 200
    released = client.get(f"{base}/current", headers=_participant_headers(token)).json()
    assert released["artifact"]["artifact_id"] == "ai-fallback"
    assert _register(client, experiment["id"]).status_code == 423
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT actor,reason,cutoff_at FROM aipol_withdrawals"
        ).fetchone() == ("hong", "사전 등록된 M2 마감 규칙", attrited.json()["cutoff_at"])


def test_m2_cohort_finalization_is_atomic_once_and_primary_must_be_generated_after_it(aipol_app):
    server, client, db_path = aipol_app
    headers = _admin_headers(client)
    experiment = _create(client, headers, suffix="-m2-finalization")
    _artifact(client, headers, experiment["id"], "personal_comparison", "personal-finalization")
    assert _freeze(client, headers, experiment).status_code == 200
    first = _register(client, experiment["id"]).json()["participant_token"]
    _register(client, experiment["id"])
    _advance_to_m2(client, experiment["id"], first)
    assert client.post(
        f"/api/admin/aipol/experiments/{experiment['id']}/close-registration", headers=headers
    ).status_code == 200
    generated_before_finalization = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM aipol_m2_finalizations WHERE experiment_id=?",
            (experiment["id"],),
        ).fetchone()[0] == 0

    def finalize(_: int):
        return server.aipol_store.mark_pending_attrition(
            experiment["id"], actor="hong", reason="pre-registered M2 cutoff rule"
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(finalize, (1, 2)))
    assert sorted(item["attrited"] for item in results) == [0, 1]
    aggregate = client.get(
        f"/api/admin/aipol/experiments/{experiment['id']}/m2-aggregate", headers=headers
    ).json()
    assert aggregate["cohort_finalized_at"] > generated_before_finalization
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM aipol_m2_finalizations WHERE experiment_id=?",
            (experiment["id"],),
        ).fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE aipol_m2_finalizations SET aggregate_hash=? WHERE experiment_id=?",
                ("0" * 64, experiment["id"]),
            )

    endpoint = f"/api/admin/aipol/experiments/{experiment['id']}/ai-candidates"
    base_candidate = {
        "candidate_role": "primary", "artifact_id": "ai-primary-finalized",
        "artifact_version": "v1", "content": {"title": "M2 기반", "body": "승인 본문"},
        "model": "approved-model", "deployment": "approved-deployment",
        "prompt_version": "prompt-v1", "evidence_refs": ["m2-finalized-aggregate"],
        "m2_aggregate_hash": aggregate["aggregate_hash"],
        "approval_id": "approval-primary-finalized", "approved_by": "hong",
    }
    rejected = client.post(
        endpoint, headers=headers,
        json={**base_candidate, "generated_at": generated_before_finalization},
    )
    assert rejected.status_code == 400
    accepted = client.post(
        endpoint, headers=headers,
        json={**base_candidate, "generated_at": datetime.now(timezone.utc).isoformat()},
    )
    assert accepted.status_code == 200, accepted.text


def test_m2_barrier_rejects_time_and_hash_simultaneous_tamper(aipol_app):
    server, client, db_path = aipol_app
    headers = _admin_headers(client)
    experiment = _create(client, headers, suffix="-m2-barrier-tamper", capacity=1)
    _artifact(client, headers, experiment["id"], "personal_comparison", "personal-m2-tamper")
    assert _freeze(client, headers, experiment).status_code == 200
    token = _register(client, experiment["id"]).json()["participant_token"]
    _advance_to_m2(client, experiment["id"], token)
    assert client.post(
        f"/api/admin/aipol/experiments/{experiment['id']}/close-registration", headers=headers
    ).status_code == 200
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        row = dict(connection.execute(
            "SELECT * FROM aipol_m2_finalizations WHERE experiment_id=?", (experiment["id"],)
        ).fetchone())
        changed_at = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        envelope = {
            "id": row["id"], "experiment_id": experiment["id"],
            "aggregate_hash": row["aggregate_hash"], "finalized_at": changed_at,
            "finalized_by": row["finalized_by"],
            "cohort_registered_count": row["cohort_registered_count"],
            "cohort_m2_count": row["cohort_m2_count"],
            "cohort_attrited_count": row["cohort_attrited_count"],
        }
        connection.execute("DROP TRIGGER aipol_m2_finalizations_no_update")
        connection.execute(
            "UPDATE aipol_m2_finalizations SET finalized_at=?,barrier_hash=? WHERE id=?",
            (changed_at, content_hash(envelope), row["id"]),
        )
        connection.commit()
    rejected = client.get(
        f"/api/admin/aipol/experiments/{experiment['id']}/m2-aggregate", headers=headers
    )
    assert rejected.status_code == 409
    assert "approval event" in rejected.text


def test_three_measurement_api_and_sqlite_ledger_are_append_only(aipol_app):
    _, client, db_path = aipol_app
    headers = _admin_headers(client)
    experiment = _create(client, headers)
    _artifact(client, headers, experiment["id"], "personal_comparison", "personal-tool")
    assert _freeze(client, headers, experiment).status_code == 200
    registered = _register(client, experiment["id"])
    assert registered.status_code == 200
    token = registered.json()["participant_token"]

    base = f"/api/aipol/experiments/{experiment['id']}"
    current = client.get(f"{base}/current", headers=_participant_headers(token)).json()
    assert current["stage"] == "consent"
    assert "artifact" not in current and "policy_options" not in current
    _full_flow(client, experiment["id"], token)
    done = client.get(f"{base}/current", headers=_participant_headers(token)).json()
    assert done["stage"] == "complete"

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM aipol_measurements").fetchone()[0] == 3
        assert connection.execute("SELECT COUNT(*) FROM aipol_exposures").fetchone()[0] == 3
        assert connection.execute("SELECT COUNT(*) FROM aipol_exposure_opens").fetchone()[0] == 3
        assert connection.execute(
            "SELECT COUNT(*) FROM aipol_exposures WHERE opened_at < completed_at"
        ).fetchone()[0] == 3
        assert connection.execute("SELECT COUNT(*) FROM aipol_secondary_evaluations").fetchone()[0] == 1
        rows = connection.execute(
            "SELECT measurement_id,choice,option_order FROM aipol_measurements ORDER BY state_revision"
        ).fetchall()
        assert [(row[0], row[1]) for row in rows] == [("M1", "A"), ("M2", "B"), ("M3", "C")]
        assert len({row[2] for row in rows}) == 1
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("UPDATE aipol_measurements SET choice='B' WHERE measurement_id='M1'")

    for module_name in MODULES:
        sys.modules.pop(module_name, None)
    restarted = importlib.import_module("server")
    with TestClient(restarted.app) as restarted_client:
        restored = restarted_client.get(
            f"{base}/current", headers=_participant_headers(token)
        )
        assert restored.status_code == 200
        assert restored.json()["stage"] == "complete"


def test_v2_starts_with_m1_then_personal_comparison_and_structures_m2(aipol_app):
    _, client, db_path = aipol_app
    headers = _admin_headers(client)
    experiment = _create(client, headers, suffix="-v2-order", procedure_version="v2")
    _artifact(client, headers, experiment["id"], "personal_comparison", "personal-v2-order")
    assert _freeze(client, headers, experiment).status_code == 200
    token = _register(client, experiment["id"]).json()["participant_token"]
    base = f"/api/aipol/experiments/{experiment['id']}"

    consented = _post(
        client, f"{base}/consent", token, 0, "v2-consent",
        consent_version="consent-v1", affirmed=True,
    )
    assert consented.status_code == 200 and consented.json()["stage"] == "M1"
    first = client.get(f"{base}/current", headers=_participant_headers(token)).json()
    assert first["stage"] == "M1" and len(first["policy_options"]) == 3

    m1 = _post(
        client, f"{base}/measurements/M1", token, 1, "v2-m1",
        choice="A", reason="최초 선택", confidence=3,
    )
    assert m1.status_code == 200 and m1.json()["stage"] == "E1a"
    assert _post(
        client, f"{base}/exposures/E1a", token, 2, "v2-e1a", read_ack=True,
    ).json()["stage"] == "M2"

    missing = _post(
        client, f"{base}/measurements/M2", token, 3, "v2-m2-missing",
        choice="B", reason="", confidence=3,
    )
    assert missing.status_code == 400
    conditional_without_reason = _post(
        client, f"{base}/measurements/M2", token, 3, "v2-m2-empty",
        choice="B", stance="conditional", reason="", confidence=3,
    )
    assert conditional_without_reason.status_code == 400
    accepted = _post(
        client, f"{base}/measurements/M2", token, 3, "v2-m2",
        choice="B", stance="conditional", reason="재정 조건 확인 필요", confidence=3,
    )
    assert accepted.status_code == 200 and accepted.json()["stage"] == "E2"
    assert client.post(
        f"/api/admin/aipol/experiments/{experiment['id']}/close-registration",
        headers=headers,
    ).status_code == 200
    aggregate = client.get(
        f"/api/admin/aipol/experiments/{experiment['id']}/m2-aggregate",
        headers=headers,
    ).json()
    assert aggregate["stance_counts"] == {"accept": 0, "conditional": 1, "reject": 0}
    assert "재정 조건 확인 필요" not in json.dumps(aggregate, ensure_ascii=False)

    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT measurement_id,stance,preceding_exposure_hash "
            "FROM aipol_measurements ORDER BY state_revision"
        ).fetchall()
    assert rows[0][0] == "M1" and rows[0][1] is None and len(rows[0][2]) == 64
    assert rows[1][:2] == ("M2", "conditional")


def test_v2_uses_facilitator_selected_public_input_and_distinct_d_prime_through_restart(aipol_app):
    _, client, db_path = aipol_app
    headers = _admin_headers(client)
    experiment = _create(client, headers, suffix="-v2-complete", procedure_version="v2")
    _artifact(client, headers, experiment["id"], "personal_comparison", "personal-v2-complete")
    assert _freeze(client, headers, experiment).status_code == 200
    token = _register(client, experiment["id"]).json()["participant_token"]
    base = f"/api/aipol/experiments/{experiment['id']}"

    assert _post(
        client, f"{base}/consent", token, 0, "v2c-consent",
        consent_version="consent-v1", affirmed=True,
    ).json()["stage"] == "M1"
    assert _post(
        client, f"{base}/measurements/M1", token, 1, "v2c-m1",
        choice="A", reason="", confidence=3,
    ).json()["stage"] == "E1a"
    assert _post(
        client, f"{base}/exposures/E1a", token, 2, "v2c-e1a", read_ack=True,
    ).json()["stage"] == "M2"
    assert _post(
        client, f"{base}/measurements/M2", token, 3, "v2c-m2",
        choice="B", stance="conditional", reason="조건을 확인해야 함", confidence=4,
    ).json()["stage"] == "E2"
    assert client.post(
        f"/api/admin/aipol/experiments/{experiment['id']}/close-registration",
        headers=headers,
    ).status_code == 200
    release = client.post(
        f"/api/admin/aipol/experiments/{experiment['id']}/release-e2",
        headers=headers,
        json={"candidate_role": "fallback", "selection_reason": "v2 검토용 D 선택"},
    )
    assert release.status_code == 200
    released = release.json()
    too_early_public_input = client.post(
        f"/api/admin/aipol/experiments/{experiment['id']}/public-audience-inputs",
        headers=headers,
        json={
            "sequence": 1,
            "statement": "아직 공개 청중 의견 절차 전입니다",
            "idempotency_key": "v2c-too-early-public-input",
        },
    )
    assert too_early_public_input.status_code == 409
    assert _post(
        client, f"{base}/exposures/E2", token, 4, "v2c-e2", read_ack=True,
    ).json()["stage"] == "E1b"
    assert _post(
        client, f"{base}/exposures/E1b", token, 5, "v2c-e1b", read_ack=True,
    ).json()["stage"] == "A1"
    a1_current = client.get(f"{base}/current", headers=_participant_headers(token)).json()
    assert a1_current["public_audience_discussion"] == {
        "participant_text_collection": False,
        "facilitator_selected_input": True,
        "acknowledgement_required": True,
    }
    empty_public_inputs = client.get(
        f"/api/admin/aipol/experiments/{experiment['id']}/public-audience-inputs",
        headers=headers,
    ).json()
    assert empty_public_inputs["input_count"] == 0
    assert empty_public_inputs["pending_count"] == 1
    with sqlite3.connect(db_path) as connection:
        expert_hash = connection.execute(
            "SELECT content_hash FROM aipol_artifacts WHERE experiment_id=? AND kind='expert_explanation'",
            (experiment["id"],),
        ).fetchone()[0]
    premature_d_prime = client.post(
        f"/api/admin/aipol/experiments/{experiment['id']}/artifacts",
        headers=headers,
        json={
            "kind": "final_ai_opinion",
            "artifact_id": "premature-d-prime-v2",
            "artifact_version": "v1",
            "content": {
                "title": "조기 D′",
                "body": "공개 청중 의견 절차 완료 전에는 차단되어야 합니다.",
                "m2_aggregate_hash": released["e2_m2_aggregate_hash"],
                "expert_artifact_hash": expert_hash,
                "public_audience_input_hash": empty_public_inputs["aggregate_hash"],
                "model": "fixture-revision-model",
                "deployment": "fixture-revision-deployment",
                "prompt_version": "fixture-d-prime-v1",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "evidence_refs": ["premature"],
            },
            "approval_id": f"approval-{experiment['id']}-premature-d-prime",
            "approved_by": "hong",
            "fallback_used": False,
        },
    )
    assert premature_d_prime.status_code == 400
    assert client.post(
        f"{base}/audience-discussion-ack",
        headers=_participant_headers(token),
        json={
            "response": "참가자 개인 텍스트는 받으면 안 됨",
            "expected_revision": 6,
            "idempotency_key": "v2c-invalid-private-text",
        },
    ).status_code == 400
    removed_private_endpoint = client.post(
        f"{base}/audience-feedback",
        headers=_participant_headers(token),
        json={
            "response": "예전 비공개 입력 경로",
            "abstained": False,
            "expected_revision": 6,
            "idempotency_key": "v2c-removed-private-endpoint",
        },
    )
    assert removed_private_endpoint.status_code in {404, 405}

    public_statement = "재정 조건을 더 명확히 밝혀야 합니다"
    selected = client.post(
        f"/api/admin/aipol/experiments/{experiment['id']}/public-audience-inputs",
        headers=headers,
        json={
            "sequence": 1,
            "statement": public_statement,
            "idempotency_key": "v2c-public-input-1",
        },
    )
    assert selected.status_code == 200, selected.text
    discussion_ack = _post(
        client, f"{base}/audience-discussion-ack", token, 6, "v2c-discussion-ack",
    )
    assert discussion_ack.status_code == 200 and discussion_ack.json()["stage"] == "E3"
    current = client.get(f"{base}/current", headers=_participant_headers(token)).json()
    assert current["waiting_for_e3_release"] is True
    assert public_statement not in json.dumps(current, ensure_ascii=False)

    aggregate_response = client.get(
        f"/api/admin/aipol/experiments/{experiment['id']}/public-audience-inputs",
        headers=headers,
    )
    assert aggregate_response.status_code == 200
    aggregate = aggregate_response.json()
    assert aggregate["input_count"] == 1
    assert aggregate["inputs"][0]["statement"] == public_statement
    final = client.post(
        f"/api/admin/aipol/experiments/{experiment['id']}/artifacts",
        headers=headers,
        json={
            "kind": "final_ai_opinion",
            "artifact_id": "d-prime-v2",
            "artifact_version": "v1",
            "content": {
                "title": "수정 의견 D′",
                "body": "M2, 전문가 논평, 청중 의견을 반영한 수정 의견입니다.",
                "m2_aggregate_hash": released["e2_m2_aggregate_hash"],
                "expert_artifact_hash": expert_hash,
                "public_audience_input_hash": aggregate["aggregate_hash"],
                "model": "fixture-revision-model",
                "deployment": "fixture-revision-deployment",
                "prompt_version": "fixture-d-prime-v1",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "evidence_refs": ["m2-finalization", "expert-approved", "audience-finalized"],
            },
            "approval_id": f"approval-{experiment['id']}-d-prime-v2",
            "approved_by": "hong",
            "fallback_used": False,
        },
    )
    assert final.status_code == 200, final.text
    assert final.json()["artifact_id"] == "d-prime-v2"
    assert final.json()["content_hash"] != released["e2_selected_candidate_id"]

    e3 = _post(
        client, f"{base}/exposures/E3", token, 7, "v2c-e3", read_ack=True,
    )
    assert e3.status_code == 200, e3.text
    assert e3.json()["stage"] == "M3"
    completed = _post(
        client, f"{base}/measurements/M3", token, 8, "v2c-m3",
        choice="C", reason="최종 선택", confidence=4,
        secondary_evaluation={
            "artifact_id": "d-prime-v2", "acceptance": 4, "reason": "최종 별도 평가",
        },
    )
    assert completed.status_code == 200 and completed.json()["stage"] == "complete"

    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM aipol_audience_discussion_acks"
        ).fetchone()[0] == 1


        assert connection.execute(
            "SELECT statement FROM aipol_public_audience_inputs"
        ).fetchone()[0] == public_statement
        assert connection.execute("SELECT COUNT(*) FROM aipol_v2_exposures").fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(DISTINCT artifact_id) FROM aipol_artifacts "
            "WHERE experiment_id=? AND kind='final_ai_opinion'",
            (experiment["id"],),
        ).fetchone()[0] == 1
        d_id = connection.execute(
            "SELECT c.artifact_id FROM aipol_ai_candidates c JOIN aipol_experiments e "
            "ON e.e2_selected_candidate_id=c.id WHERE e.id=?", (experiment["id"],),
        ).fetchone()[0]
        d_prime_id = connection.execute(
            "SELECT artifact_id FROM aipol_artifacts WHERE experiment_id=? "
            "AND kind='final_ai_opinion'", (experiment["id"],),
        ).fetchone()[0]
        assert d_id != d_prime_id

    for module_name in MODULES:
        sys.modules.pop(module_name, None)
    restarted = importlib.import_module("server")
    with TestClient(restarted.app) as restarted_client:
        restored = restarted_client.get(
            f"{base}/current", headers=_participant_headers(token)
        )
        assert restored.status_code == 200
        assert restored.json()["stage"] == "complete"


def test_v2_synthetic_review_uses_explicit_synthetic_d_prime_without_real_aggregates(aipol_app):
    _, client, _ = aipol_app
    headers = _admin_headers(client)
    experiment = _create(client, headers, suffix="-v2-synthetic", procedure_version="v2")
    _artifact(client, headers, experiment["id"], "personal_comparison", "personal-v2-synthetic")
    expert = _artifact(client, headers, experiment["id"], "expert_explanation", "expert-v2-synthetic")
    _artifact(client, headers, experiment["id"], "ai_opinion", "ai-v2-synthetic", fallback=True)
    frozen = client.put(
        f"/api/admin/aipol/experiments/{experiment['id']}/freeze", headers=headers,
        json={
            "manifest_id": "freeze-v2-synthetic",
            "experiment_version": experiment["experiment_version"],
            "option_set_version": experiment["measurement_spec"]["option_set_version"],
            "measurement_spec_hash": experiment["measurement_spec_hash"],
            "status": "frozen", "collection_enabled": False, "approvals": [],
        },
    )
    assert frozen.status_code == 200, frozen.text
    created = client.post(
        f"/api/admin/aipol/experiments/{experiment['id']}/synthetic-participants",
        headers=headers,
    )
    assert created.status_code == 200, created.text
    token = created.json()["participant_token"]
    base = f"/api/aipol/experiments/{experiment['id']}"
    assert _post(client, f"{base}/consent", token, 0, "sv2-consent", consent_version="consent-v1", affirmed=True).json()["stage"] == "M1"
    assert _post(client, f"{base}/measurements/M1", token, 1, "sv2-m1", choice="A", reason="", confidence=3).json()["stage"] == "E1a"
    assert client.post(
        f"{base}/exposures/E1a/open", headers=_participant_headers(token),
        json={"expected_revision": 2, "idempotency_key": "sv2-e1a-open"},
    ).status_code == 200
    e1a = client.post(
        f"{base}/exposures/E1a", headers=_participant_headers(token),
        json={"expected_revision": 2, "idempotency_key": "sv2-e1a", "read_ack": True},
    )
    assert e1a.status_code == 200 and e1a.json()["stage"] == "M2"
    assert _post(client, f"{base}/measurements/M2", token, 3, "sv2-m2", choice="B", stance="accept", reason="", confidence=3).json()["stage"] == "E2"
    assert _post(client, f"{base}/exposures/E2", token, 4, "sv2-e2", read_ack=True).json()["stage"] == "E1b"
    assert _post(client, f"{base}/exposures/E1b", token, 5, "sv2-e1b", read_ack=True).json()["stage"] == "A1"
    assert _post(client, f"{base}/audience-discussion-ack", token, 6, "sv2-a1").json()["stage"] == "E3"
    final = client.post(
        f"/api/admin/aipol/experiments/{experiment['id']}/artifacts", headers=headers,
        json={
            "kind": "final_ai_opinion", "artifact_id": "d-prime-v2-synthetic",
            "artifact_version": "v1", "approval_id": f"approval-{experiment['id']}-d-prime-synthetic",
            "approved_by": "hong", "fallback_used": False,
            "content": {
                "title": "합성 검토용 수정 의견 D′",
                "body": "실제 참가자 집계와 분리된 화면 흐름 검토용 자료입니다.",
                "synthetic_review": True, "m2_aggregate_hash": None,
                "public_audience_input_hash": None,
                "expert_artifact_hash": expert["content_hash"],
                "model": "synthetic-review-fixture", "deployment": "test-only",
                "prompt_version": "synthetic-review-v1",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "evidence_refs": ["synthetic-review-only"],
            },
        },
    )
    assert final.status_code == 200, final.text
    current = client.get(f"{base}/current", headers=_participant_headers(token)).json()
    assert current["artifact"]["artifact_id"] == "d-prime-v2-synthetic"
    assert current["artifact"]["content"]["synthetic_review"] is True
    assert _post(client, f"{base}/exposures/E3", token, 7, "sv2-e3", read_ack=True).json()["stage"] == "M3"


def test_no_skip_idempotency_conflict_and_stale_revision(aipol_app):
    _, client, _ = aipol_app
    headers = _admin_headers(client)
    experiment = _create(client, headers)
    _artifact(client, headers, experiment["id"], "personal_comparison", "personal-tool")
    assert _freeze(client, headers, experiment).status_code == 200
    token = _register(client, experiment["id"]).json()["participant_token"]
    base = f"/api/aipol/experiments/{experiment['id']}"

    skipped = _post(client, f"{base}/measurements/M1", token, 0, "skip", choice="A", reason="", confidence=3)
    assert skipped.status_code == 409
    not_affirmed = _post(
        client, f"{base}/consent", token, 0, "not-affirmed",
        consent_version="consent-v1", affirmed=False,
    )
    assert not_affirmed.status_code == 400
    first = _post(client, f"{base}/consent", token, 0, "same", consent_version="consent-v1", affirmed=True)
    retry = _post(client, f"{base}/consent", token, 0, "same", consent_version="consent-v1", affirmed=True)
    assert first.status_code == retry.status_code == 200
    assert first.json() == retry.json()
    conflict = _post(client, f"{base}/consent", token, 0, "same", consent_version="changed", affirmed=True)
    assert conflict.status_code == 409
    stale = _post(client, f"{base}/exposures/E1a", token, 0, "stale", read_ack=True)
    assert stale.status_code == 409


def test_session_wide_fallback_and_real_synthetic_summary_separation(aipol_app):
    _, client, _ = aipol_app
    headers = _admin_headers(client)
    experiment = _create(client, headers)
    _artifact(client, headers, experiment["id"], "personal_comparison", "personal-tool")
    assert _freeze(client, headers, experiment).status_code == 200
    real = _register(client, experiment["id"]).json()
    synthetic = client.post(
        f"/api/admin/aipol/experiments/{experiment['id']}/synthetic-participants", headers=headers
    ).json()
    _full_flow(client, experiment["id"], real["participant_token"], choices=("A", "B", "C"))
    _full_flow(
        client, experiment["id"], synthetic["participant_token"],
        choices=("C", "C", "C"), release=False,
    )

    real_summary = client.get(
        f"/api/admin/aipol/experiments/{experiment['id']}/summary", headers=headers
    ).json()
    synthetic_summary = client.get(
        f"/api/admin/aipol/experiments/{experiment['id']}/summary?participant_type=synthetic",
        headers=headers,
    ).json()
    assert real_summary["measurement_counts"] == {"M1": 1, "M2": 1, "M3": 1}
    assert real_summary["transitions"]["M1_M2"] == {"A->B": 1}
    assert synthetic_summary["transitions"]["M1_M2"] == {"C->C": 1}
    assert real_summary["participant_results_public"] is False


def test_noncollection_synthetic_review_completes_without_real_collection_or_receipt(
    aipol_app,
):
    server, client, db_path = aipol_app
    headers = _admin_headers(client)
    experiment = _create(client, headers, suffix="-synthetic-review")
    assert client.post(
        f"/api/admin/aipol/experiments/{experiment['id']}/synthetic-participants",
        headers=headers,
    ).status_code == 423
    _artifact(client, headers, experiment["id"], "personal_comparison", "review-personal")
    _artifact(client, headers, experiment["id"], "expert_explanation", "review-expert")
    _artifact(client, headers, experiment["id"], "ai_opinion", "review-ai", fallback=True)
    spec = MeasurementSpec(**experiment["measurement_spec"])
    frozen = client.put(
        f"/api/admin/aipol/experiments/{experiment['id']}/freeze",
        headers=headers,
        json={
            "manifest_id": "synthetic-review-v1",
            "experiment_version": experiment["experiment_version"],
            "option_set_version": experiment["measurement_spec"]["option_set_version"],
            "measurement_spec_hash": spec.spec_hash,
            "status": "frozen",
            "collection_enabled": False,
            "approvals": [],
        },
    )
    assert frozen.status_code == 200, frozen.text
    assert frozen.json()["collection_enabled"] is False
    assert _register(client, experiment["id"]).status_code == 423

    created = client.post(
        f"/api/admin/aipol/experiments/{experiment['id']}/synthetic-participants",
        headers=headers,
    )
    assert created.status_code == 200, created.text
    created_review = created.json()
    token = created_review["participant_token"]
    assert created_review["review_id"].startswith("ap-")
    assert created_review["expires_at"]
    base = f"/api/aipol/experiments/{experiment['id']}"
    server.aipol_store.configure_completion_receipt_verifier(None)

    current = client.get(f"{base}/current", headers=_participant_headers(token)).json()
    assert current["synthetic_review"] is True
    assert current["stage"] == "consent"
    assert _post(
        client, f"{base}/consent", token, 0, "review-consent",
        consent_version="consent-v1", affirmed=True,
    ).status_code == 200
    e1a_current = client.get(f"{base}/current", headers=_participant_headers(token)).json()
    assert e1a_current["artifact"]["artifact_id"] == "review-personal"
    assert "receipt_context" not in e1a_current
    assert client.post(
        f"{base}/exposures/E1a/open",
        headers=_participant_headers(token),
        json={"expected_revision": 1, "idempotency_key": "review-e1a-open"},
    ).status_code == 200
    assert client.post(
        f"{base}/exposures/E1a",
        headers=_participant_headers(token),
        json={
            "expected_revision": 1,
            "idempotency_key": "review-e1a",
            "read_ack": True,
        },
    ).status_code == 200
    assert _post(
        client, f"{base}/measurements/M1", token, 2, "review-m1",
        choice="A", reason="", confidence=3,
    ).status_code == 200
    assert _post(
        client, f"{base}/exposures/E1b", token, 3, "review-e1b", read_ack=True,
    ).status_code == 200
    assert _post(
        client, f"{base}/measurements/M2", token, 4, "review-m2",
        choice="B", reason="", confidence=3,
    ).status_code == 200
    e2_current = client.get(f"{base}/current", headers=_participant_headers(token)).json()
    assert e2_current["artifact"]["artifact_id"] == "review-ai"
    assert e2_current.get("waiting_for_e2_release") is not True
    assert _post(
        client, f"{base}/exposures/E2", token, 5, "review-e2", read_ack=True,
    ).status_code == 200
    complete = _post(
        client, f"{base}/measurements/M3", token, 6, "review-m3",
        choice="C", reason="", confidence=3,
        secondary_evaluation={
            "artifact_id": "review-ai", "acceptance": 4, "reason": "합성 검토",
        },
    )
    assert complete.status_code == 200, complete.text
    assert complete.json()["stage"] == "complete"
    summary = client.get(
        f"/api/admin/aipol/experiments/{experiment['id']}/summary?participant_type=synthetic",
        headers=headers,
    ).json()
    assert summary["funnel"]["complete"] == 1
    assert summary["measurement_counts"] == {"M1": 1, "M2": 1, "M3": 1}

    revoked = client.post(
        f"/api/admin/aipol/experiments/{experiment['id']}/synthetic-participants/"
        f"{created_review['review_id']}/revoke",
        headers=headers,
        json={"reason": "검토 링크 교체"},
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["revoked"] is True
    assert client.get(f"{base}/current", headers=_participant_headers(token)).status_code == 401

    expiring = client.post(
        f"/api/admin/aipol/experiments/{experiment['id']}/synthetic-participants",
        headers=headers,
    ).json()
    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP TRIGGER aipol_synthetic_review_grants_no_update")
        connection.execute(
            "UPDATE aipol_synthetic_review_grants SET expires_at=? WHERE participant_id=?",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), expiring["review_id"]),
        )
    assert client.get(
        f"{base}/current", headers=_participant_headers(expiring["participant_token"])
    ).status_code == 401


def test_simultaneous_measurements_only_one_commits(aipol_app):
    _, client, _ = aipol_app
    headers = _admin_headers(client)
    experiment = _create(client, headers)
    _artifact(client, headers, experiment["id"], "personal_comparison", "personal-tool")
    assert _freeze(client, headers, experiment).status_code == 200
    token = _register(client, experiment["id"]).json()["participant_token"]
    base = f"/api/aipol/experiments/{experiment['id']}"
    _post(client, f"{base}/consent", token, 0, "c", consent_version="consent-v1", affirmed=True)
    _post(client, f"{base}/exposures/E1a", token, 1, "e", read_ack=True)

    def submit(key, choice):
        with TestClient(client.app) as concurrent_client:
            return _post(
                concurrent_client, f"{base}/measurements/M1", token, 2, key,
                choice=choice, reason="", confidence=3,
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(pool.map(lambda pair: submit(*pair), (("m-a", "A"), ("m-b", "B"))))
    assert statuses == [200, 409]


def test_manifest_tamper_fails_closed_and_withdrawal_is_append_only(aipol_app):
    _, client, db_path = aipol_app
    headers = _admin_headers(client)
    experiment = _create(client, headers)
    _artifact(client, headers, experiment["id"], "personal_comparison", "personal-tool")
    assert _freeze(client, headers, experiment).status_code == 200
    token = _register(client, experiment["id"]).json()["participant_token"]
    base = f"/api/aipol/experiments/{experiment['id']}"
    consent = _post(client, f"{base}/consent", token, 0, "c", consent_version="consent-v1", affirmed=True)
    assert consent.status_code == 200
    withdrawn = _post(client, f"{base}/withdraw", token, 1, "w", reason="participant-request")
    assert withdrawn.status_code == 200
    assert client.get(f"{base}/current", headers=_participant_headers(token)).json()["stage"] == "withdrawn"
    assert _post(client, f"{base}/exposures/E1a", token, 2, "late", read_ack=True).status_code == 409
    with sqlite3.connect(db_path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("DELETE FROM aipol_withdrawals")

    # 별도 새 참가자 등록 뒤 동결표가 외부에서 훼손되어도 후속 읽기·제출은 닫힌다.
    second = _register(client, experiment["id"]).json()["participant_token"]
    with sqlite3.connect(db_path) as connection:
        manifest = json.loads(connection.execute(
            "SELECT manifest_envelope FROM aipol_freeze_manifest_anchors WHERE experiment_id=?",
            (experiment["id"],),
        ).fetchone()[0])
        manifest["measurement_spec_hash"] = "0" * 64
        connection.execute(
            "UPDATE aipol_experiments SET freeze_manifest=? WHERE id=?",
            (json.dumps(manifest), experiment["id"]),
        )
        connection.commit()
    assert client.get(f"{base}/current", headers=_participant_headers(second)).status_code == 409


def test_full_freeze_manifest_anchor_rejects_metadata_and_coherent_hash_tamper(aipol_app):
    _, client, db_path = aipol_app
    headers = _admin_headers(client)
    experiment = _create(client, headers, capacity=1, suffix="-manifest-anchor")
    _artifact(client, headers, experiment["id"], "personal_comparison", "personal-anchor")
    frozen = _freeze(client, headers, experiment)
    assert frozen.status_code == 200
    original = frozen.json()["freeze_manifest"]
    mutations = (
        {"manifest_id": "forged-manifest"},
        {"frozen_by": "forged-approver", "frozen_at": "2099-01-01T00:00:00+00:00"},
        {"approval_id": "forged-approval", "approved_by": "forged-approver",
         "approved_at": "2099-01-01T00:00:00+00:00"},
    )
    for mutation in mutations:
        forged = json.loads(json.dumps(original))
        if "approval_id" in mutation:
            forged["approvals"][0].update(mutation)
        else:
            forged.update(mutation)
        with sqlite3.connect(db_path) as connection:
            connection.execute(
                "UPDATE aipol_experiments SET freeze_manifest=? WHERE id=?",
                (json.dumps(forged), experiment["id"]),
            )
            connection.commit()
        assert _register(client, experiment["id"]).status_code == 409
        with sqlite3.connect(db_path) as connection:
            connection.execute(
                "UPDATE aipol_experiments SET freeze_manifest=NULL WHERE id=?",
                (experiment["id"],),
            )
            connection.commit()

    forged = json.loads(json.dumps(original))
    forged["manifest_id"] = "coherent-forged-manifest"
    forged["manifest_approval"]["approval_id"] = "coherent-forged-approval"
    with sqlite3.connect(db_path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE aipol_freeze_manifest_anchors SET manifest_envelope=? "
                "WHERE experiment_id=?", (json.dumps(forged), experiment["id"])
            )
        connection.execute("DROP TRIGGER aipol_freeze_manifest_anchors_no_update")
        connection.execute(
            "UPDATE aipol_freeze_manifest_anchors SET manifest_envelope=?,manifest_hash=? "
            "WHERE experiment_id=?",
            (json.dumps(forged), content_hash(forged), experiment["id"]),
        )
        connection.commit()
    assert _register(client, experiment["id"]).status_code == 409


def test_existing_freeze_manifest_is_backfilled_to_append_only_anchor(aipol_app):
    server, client, db_path = aipol_app
    headers = _admin_headers(client)
    experiment = _create(client, headers, capacity=1, suffix="-manifest-migration")
    _artifact(client, headers, experiment["id"], "personal_comparison", "personal-migration")
    frozen = _freeze(client, headers, experiment)
    assert frozen.status_code == 200
    legacy_envelope = frozen.json()["freeze_manifest"]
    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP TRIGGER aipol_freeze_manifest_anchors_no_delete")
        connection.execute("DROP TRIGGER aipol_approval_events_no_delete")
        connection.execute(
            "DELETE FROM aipol_approval_events WHERE experiment_id=? AND object_type='freeze_manifest'",
            (experiment["id"],),
        )
        connection.execute(
            "DELETE FROM aipol_freeze_manifest_anchors WHERE experiment_id=?", (experiment["id"],)
        )
        connection.execute(
            "UPDATE aipol_experiments SET freeze_manifest=?,freeze_manifest_anchor_id=NULL WHERE id=?",
            (json.dumps(legacy_envelope), experiment["id"]),
        )
        connection.commit()
    server.aipol_store.init()
    migrated = server.aipol_store.get_experiment(experiment["id"])
    assert migrated["freeze_manifest"]["manifest_id"] == legacy_envelope["manifest_id"]
    assert migrated["freeze_manifest_anchor_id"].startswith("fma-legacy-")
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT freeze_manifest,freeze_manifest_anchor_id FROM aipol_experiments WHERE id=?",
            (experiment["id"],),
        ).fetchone()
        assert row[0] is None and row[1] == migrated["freeze_manifest_anchor_id"]
        assert connection.execute(
            "SELECT COUNT(*) FROM aipol_freeze_manifest_anchors WHERE experiment_id=?",
            (experiment["id"],),
        ).fetchone()[0] == 1
    assert _register(client, experiment["id"]).status_code == 200


def test_signed_approver_server_time_editor_separation_and_hash_chain_audit(aipol_app):
    _, client, db_path = aipol_app
    headers = _admin_headers(client)
    experiment = _create(client, headers, suffix="-approval")
    request_body = {
        "category": "policy_options",
        "document_id": "approval-test",
        "document_version": "v1",
        "body": "signed approval test",
        "evidence": {"fixture": True},
    }
    preview = client.post(
        f"/api/admin/aipol/experiments/{experiment['id']}/canonical-documents/preview",
        headers=headers,
        json=request_body,
    ).json()
    editor_headers = _admin_headers(client, "editor")
    assert client.post(
        f"/api/admin/aipol/experiments/{experiment['id']}/canonical-drafts",
        headers=headers,
        json={**request_body, "declared_content_hash": preview["content_hash"]},
    ).status_code == 403
    drafted = client.post(
        f"/api/admin/aipol/experiments/{experiment['id']}/canonical-drafts",
        headers=editor_headers,
        json={**request_body, "declared_content_hash": preview["content_hash"]},
    )
    assert drafted.status_code == 200, drafted.text
    server_drafts = client.get(
        f"/api/admin/aipol/experiments/{experiment['id']}/canonical-drafts", headers=headers
    ).json()
    assert server_drafts == [drafted.json()]
    endpoint = f"/api/admin/aipol/experiments/{experiment['id']}/canonical-documents"
    assert client.post(endpoint, headers=editor_headers, json={
        **request_body, "declared_content_hash": preview["content_hash"],
        "approval_id": "editor-cannot-approve", "approved_by": "editor",
    }).status_code == 403
    assert client.post(endpoint, headers=headers, json={
        **request_body, "body": "approver changed the editor draft",
        "declared_content_hash": preview["content_hash"],
        "approval_id": "approval-tampered", "approved_by": "hong",
    }).status_code == 400
    assert client.post(endpoint, headers=headers, json={
        **request_body, "declared_content_hash": preview["content_hash"],
        "approval_id": "approval-mismatch", "approved_by": "editor",
        "approved_at": "1900-01-01T00:00:00Z",
    }).status_code == 400
    saved = client.post(endpoint, headers=headers, json={
        **request_body, "declared_content_hash": preview["content_hash"],
        "approval_id": "approval-signed", "approved_by": "hong",
        "approved_at": "1900-01-01T00:00:00Z",
    })
    assert saved.status_code == 200, saved.text
    assert saved.json()["approved_at"] != "1900-01-01T00:00:00Z"
    assert saved.json()["approved_at"].endswith("+00:00")
    audit = client.get("/api/admin/aipol/audit", headers=headers).json()
    assert audit["valid"] is True
    assert {item["action"] for item in audit["events"]} >= {
        "experiment.created", "experiment.canonical.drafted", "experiment.canonical.approved",
    }
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT editor_by,approver_by,approved_at FROM aipol_approval_events "
            "WHERE approval_id='approval-signed'"
        ).fetchone() == ("editor", "hong", saved.json()["approved_at"])
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE aipol_canonical_drafts SET body='tampered' WHERE experiment_id=?",
                (experiment["id"],),
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "DELETE FROM aipol_canonical_drafts WHERE experiment_id=?",
                (experiment["id"],),
            )


def test_freeze_requires_preapproved_expert_fallback_and_binds_hashes(aipol_app):
    _, client, _ = aipol_app
    headers = _admin_headers(client)
    experiment = _create(client, headers, suffix="-prerequisites")
    _artifact(client, headers, experiment["id"], "personal_comparison", "personal-tool")
    body = _freeze_body(client, headers, experiment)
    endpoint = f"/api/admin/aipol/experiments/{experiment['id']}/freeze"
    assert client.put(endpoint, headers=headers, json=body).status_code == 423
    _artifact(client, headers, experiment["id"], "expert_explanation", "expert")
    assert client.put(endpoint, headers=headers, json=body).status_code == 423
    _artifact(client, headers, experiment["id"], "ai_opinion", "ai-fallback", fallback=True)
    frozen = client.put(endpoint, headers=headers, json=body)
    assert frozen.status_code == 200, frozen.text
    bindings = frozen.json()["freeze_manifest"]["artifact_bindings"]
    assert set(bindings) == {
        "E1a", "E1b", "E2_fallback", "receipt_contract", "calculator_integration",
    }
    assert bindings["calculator_integration"] == INTEGRATION_TEST_HASH
    assert all(len(value) == 64 for value in bindings.values())
    assert client.post(
        f"/api/admin/aipol/experiments/{experiment['id']}/canonical-documents",
        headers=headers,
        json={
            "category": "privacy", "document_id": "late", "document_version": "v2",
            "body": "late", "evidence": {}, "declared_content_hash": "0" * 64,
            "approval_id": "late-canonical", "approved_by": "hong",
        },
    ).status_code == 400
    assert client.post(
        f"/api/admin/aipol/experiments/{experiment['id']}/artifacts",
        headers=headers,
        json={
            "kind": "expert_explanation", "artifact_id": "late-expert",
            "artifact_version": "v2", "content": {"title": "late", "body": "late"},
            "approval_id": "late-expert-approval", "approved_by": "hong",
        },
    ).status_code == 400


def test_frozen_calculator_and_canonical_payload_rehash_blocks_origin_and_hash_tamper(aipol_app):
    _, client, db_path = aipol_app
    headers = _admin_headers(client)
    experiment = _create(client, headers, suffix="-frozen-calculator-tamper")
    _artifact(client, headers, experiment["id"], "personal_comparison", "personal-frozen")
    assert _freeze(client, headers, experiment).status_code == 200
    token = _register(client, experiment["id"]).json()["participant_token"]
    base = f"/api/aipol/experiments/{experiment['id']}"
    assert _post(
        client, f"{base}/consent", token, 0, "consent",
        consent_version="consent-v1", affirmed=True,
    ).status_code == 200

    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        canonical = dict(connection.execute(
            "SELECT * FROM aipol_canonical_documents WHERE experiment_id=? AND category='calculation'",
            (experiment["id"],),
        ).fetchone())
        evidence = json.loads(canonical["evidence"])
        evidence["approved_origin"] = "https://evil.example"
        canonical_envelope = {
            "category": canonical["category"], "document_id": canonical["document_id"],
            "document_version": canonical["document_version"], "body": canonical["body"],
            "bound_settings_hash": canonical["bound_settings_hash"], "evidence": evidence,
        }
        canonical_digest = content_hash(canonical_envelope)
        artifact = dict(connection.execute(
            "SELECT * FROM aipol_artifacts WHERE experiment_id=? AND kind='personal_comparison'",
            (experiment["id"],),
        ).fetchone())
        artifact_content = json.loads(artifact["content"])
        artifact_content["launch_url"] = "https://evil.example/collect-income"
        artifact_content["canonical_document_hash"] = canonical_digest
        artifact_digest = content_hash(artifact_content)
        connection.execute("DROP TRIGGER aipol_canonical_documents_no_update")
        connection.execute("DROP TRIGGER aipol_artifacts_no_update")
        connection.execute(
            "UPDATE aipol_canonical_documents SET evidence=?,content_hash=? WHERE id=?",
            (json.dumps(evidence, sort_keys=True, separators=(",", ":")), canonical_digest, canonical["id"]),
        )
        connection.execute(
            "UPDATE aipol_artifacts SET content=?,content_hash=? WHERE id=?",
            (
                json.dumps(artifact_content, sort_keys=True, separators=(",", ":")),
                artifact_digest, artifact["id"],
            ),
        )
        connection.commit()

    current = client.get(f"{base}/current", headers=_participant_headers(token))
    assert current.status_code == 409
    assert "evil.example" not in current.text
    canonical_read = client.get(
        f"/api/admin/aipol/experiments/{experiment['id']}/canonical-documents",
        headers=headers,
    )
    assert canonical_read.status_code == 409


def test_frozen_expert_payload_is_rehashed_before_public_read(aipol_app):
    _, client, db_path = aipol_app
    headers = _admin_headers(client)
    experiment = _create(client, headers, suffix="-expert-tamper")
    _artifact(client, headers, experiment["id"], "personal_comparison", "personal-expert")
    assert _freeze(client, headers, experiment).status_code == 200
    token = _register(client, experiment["id"]).json()["participant_token"]
    base = f"/api/aipol/experiments/{experiment['id']}"
    _post(client, f"{base}/consent", token, 0, "c", consent_version="consent-v1", affirmed=True)
    _post(client, f"{base}/exposures/E1a", token, 1, "e1a", read_ack=True)
    _post(client, f"{base}/measurements/M1", token, 2, "m1", choice="A", reason="", confidence=3)
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT id,content FROM aipol_artifacts WHERE experiment_id=? AND kind='expert_explanation'",
            (experiment["id"],),
        ).fetchone()
        changed = {**json.loads(row[1]), "body": "unapproved expert replacement"}
        connection.execute("DROP TRIGGER aipol_artifacts_no_update")
        connection.execute(
            "UPDATE aipol_artifacts SET content=?,content_hash=? WHERE id=?",
            (json.dumps(changed, sort_keys=True, separators=(",", ":")), content_hash(changed), row[0]),
        )
        connection.commit()
    assert client.get(f"{base}/current", headers=_participant_headers(token)).status_code == 409


@pytest.mark.parametrize("column,value", [
    ("consent_text", "tampered consent"),
    ("procedure_config", '{"stages":["consent","M3"]}'),
])
def test_consent_and_exact_procedure_tamper_keep_collection_off(aipol_app, column, value):
    _, client, db_path = aipol_app
    headers = _admin_headers(client)
    experiment = _create(client, headers, suffix=f"-{column}")
    _artifact(client, headers, experiment["id"], "personal_comparison", "personal-tool")
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            f"UPDATE aipol_experiments SET {column}=? WHERE id=?", (value, experiment["id"])
        )
        connection.commit()
    rejected = _freeze(client, headers, experiment)
    assert rejected.status_code == 423
    assert _register(client, experiment["id"]).status_code == 423


def test_frozen_live_settings_and_stored_binding_simultaneous_tamper_is_anchored(aipol_app):
    server, client, db_path = aipol_app
    headers = _admin_headers(client)
    experiment = _create(client, headers, suffix="-settings-anchor", capacity=1)
    _artifact(client, headers, experiment["id"], "personal_comparison", "personal-settings")
    assert _freeze(client, headers, experiment).status_code == 200
    token = _register(client, experiment["id"]).json()["participant_token"]
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        raw = dict(connection.execute(
            "SELECT * FROM aipol_experiments WHERE id=?", (experiment["id"],)
        ).fetchone())
        raw["measurement_spec"] = json.loads(raw["measurement_spec"])
        raw["policy_options"] = json.loads(raw["policy_options"])
        raw["procedure_config"] = json.loads(raw["procedure_config"])
        raw["freeze_manifest"] = json.loads(connection.execute(
            "SELECT manifest_envelope FROM aipol_freeze_manifest_anchors WHERE experiment_id=?",
            (experiment["id"],),
        ).fetchone()[0])
        raw["question_text"] = "TAMPERED QUESTION"
        raw["policy_options"][0]["label"] = "TAMPERED OPTION"
        envelope = server.aipol_store._live_settings_envelope(raw)
        changed_hash = content_hash(envelope)
        raw["freeze_manifest"]["settings_binding"]["settings_hash"] = changed_hash
        connection.execute("DROP TRIGGER aipol_freeze_settings_anchors_no_update")
        connection.execute(
            "UPDATE aipol_freeze_settings_anchors SET settings_envelope=?,settings_hash=? "
            "WHERE experiment_id=?",
            (json.dumps(envelope, sort_keys=True, separators=(",", ":")), changed_hash, experiment["id"]),
        )
        changed_manifest_hash = content_hash(raw["freeze_manifest"])
        connection.execute("DROP TRIGGER aipol_freeze_manifest_anchors_no_update")
        connection.execute(
            "UPDATE aipol_freeze_manifest_anchors SET manifest_envelope=?,manifest_hash=? "
            "WHERE experiment_id=?",
            (
                json.dumps(raw["freeze_manifest"], sort_keys=True, separators=(",", ":")),
                changed_manifest_hash,
                experiment["id"],
            ),
        )
        connection.execute(
            "UPDATE aipol_experiments SET question_text=?,policy_options=? WHERE id=?",
            (
                raw["question_text"],
                json.dumps(raw["policy_options"], sort_keys=True, separators=(",", ":")),
                experiment["id"],
            ),
        )
        connection.commit()
    rejected = client.get(
        f"/api/aipol/experiments/{experiment['id']}/current",
        headers=_participant_headers(token),
    )
    assert rejected.status_code == 409
    assert "approval event" in rejected.text


def test_versioned_credential_rotation_retains_old_active_key_and_new_events_use_new_key(
    aipol_app, monkeypatch
):
    server, client, db_path = aipol_app
    v1, v2 = "v1-secret-" + "a" * 40, "v2-secret-" + "b" * 40
    monkeypatch.setenv("EVENT_CREDENTIAL_SECRETS_JSON", json.dumps({"v1": v1, "v2": v2}))
    monkeypatch.setenv("EVENT_CREDENTIAL_ACTIVE_KEY_ID", "v1")
    headers = _admin_headers(client)
    old = _create(client, headers, suffix="-credential-v1", capacity=2)
    _artifact(client, headers, old["id"], "personal_comparison", "personal-credential-v1")
    assert _freeze(client, headers, old).status_code == 200
    dormant = _create(client, headers, suffix="-credential-v1-dormant", capacity=1)
    _artifact(client, headers, dormant["id"], "personal_comparison", "personal-v1-dormant")

    monkeypatch.setenv("EVENT_CREDENTIAL_ACTIVE_KEY_ID", "v2")
    assert server.aipol_store.credential_readiness()["ready"] is True
    assert _register(client, old["id"]).status_code == 200
    new = _create(client, headers, suffix="-credential-v2", capacity=1)
    with sqlite3.connect(db_path) as connection:
        rows = dict(connection.execute(
            "SELECT id,credential_key_id FROM aipol_experiments WHERE id IN (?,?)",
            (old["id"], new["id"]),
        ).fetchall())
    assert rows == {old["id"]: "v1", new["id"]: "v2"}

    monkeypatch.setenv("EVENT_CREDENTIAL_SECRETS_JSON", json.dumps({"v2": v2}))
    readiness = client.get("/readyz")
    assert readiness.status_code == 200
    assert readiness.json()["credential_keys_ready"] is False
    assert readiness.json()["missing_credential_key_ids"] == ["v1"]
    with pytest.raises(RuntimeError, match="unavailable credential keys"):
        server.aipol_store.credential_readiness(fail=True)
    assert _register(client, old["id"]).status_code == 423
    assert _freeze(client, headers, dormant).status_code == 423


def test_legacy_experiment_schema_migrates_to_explicit_credential_key_id(
    aipol_app, monkeypatch, tmp_path
):
    server, _, _ = aipol_app
    legacy_db = tmp_path / "legacy-event.db"
    with sqlite3.connect(legacy_db) as connection:
        connection.execute(
            "CREATE TABLE aipol_experiments("
            "id TEXT PRIMARY KEY,title TEXT NOT NULL,experiment_version TEXT NOT NULL,"
            "session_id TEXT NOT NULL,measurement_spec TEXT NOT NULL,policy_options TEXT NOT NULL,"
            "freeze_manifest TEXT,consent_version TEXT NOT NULL,admission_code_hash TEXT,"
            "created_at REAL NOT NULL)"
        )
        connection.execute(
            "INSERT INTO aipol_experiments VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                "xp-legacy", "legacy", "v0", "s0", "{}", "[]", None,
                "consent-v0", None, time.time(),
            ),
        )
        connection.commit()
    monkeypatch.setenv("EVENT_DB_PATH", str(legacy_db))
    monkeypatch.setattr(server.db, "DB_PATH", legacy_db)
    server.aipol_store.init()
    with sqlite3.connect(legacy_db) as connection:
        key_id = connection.execute(
            "SELECT credential_key_id FROM aipol_experiments WHERE id='xp-legacy'"
        ).fetchone()[0]
    assert key_id == server.aipol_store.LEGACY_CREDENTIAL_KEY_ID


def test_e1a_receipt_is_required_verified_once_and_not_stored_raw(aipol_app):
    _, client, db_path = aipol_app
    headers = _admin_headers(client)
    experiment = _create(client, headers, suffix="-receipt")
    _artifact(client, headers, experiment["id"], "personal_comparison", "personal-tool")
    assert _freeze(client, headers, experiment).status_code == 200
    first = _register(client, experiment["id"]).json()["participant_token"]
    second = _register(client, experiment["id"]).json()["participant_token"]
    base = f"/api/aipol/experiments/{experiment['id']}"
    receipt = {
        "receipt_id": "external-one-time-receipt",
        "contract_hash": content_hash(RECEIPT_CONTRACT),
        "signature": "opaque-external-signature",
    }
    for token, key in ((first, "first"), (second, "second")):
        assert _post(
            client, f"{base}/consent", token, 0, f"{key}-consent",
            consent_version="consent-v1", affirmed=True,
        ).status_code == 200
        current = client.get(f"{base}/current", headers=_participant_headers(token)).json()
        assert current["receipt_context"]["contract_hash"] == content_hash(RECEIPT_CONTRACT)
        assert current["receipt_context"]["participant_pseudonym"].startswith("participant-")
        assert set(current["receipt_context"]) == {
            "experiment_id", "experiment_version", "session_id", "participant_pseudonym",
            "artifact_id", "artifact_hash", "contract_hash",
        }
        assert current["calculator_integration"] == {
            "contract_version": INTEGRATION_VERSION,
            "allowed_origin": "https://example.test",
            "launch_url": "https://example.test/approved-calculator",
            "launch_origin": "https://example.test",
            "context_fragment_key": "aipol_context",
            "max_context_bytes": 2048,
        }
        serialized = json.dumps(current, ensure_ascii=False).lower()
        assert "participant_token" not in serialized and "admission_code" not in serialized
        assert client.post(
            f"{base}/exposures/E1a/open", headers=_participant_headers(token),
            json={"expected_revision": 1, "idempotency_key": f"{key}-open"},
        ).status_code == 200
    assert client.post(
        f"{base}/exposures/E1a", headers=_participant_headers(first),
        json={"expected_revision": 1, "idempotency_key": "missing", "read_ack": True},
    ).status_code == 400
    invalid = {**receipt, "contract_hash": "0" * 64, "receipt_id": "invalid"}
    assert client.post(
        f"{base}/exposures/E1a", headers=_participant_headers(first),
        json={
            "expected_revision": 1, "idempotency_key": "invalid", "read_ack": True,
            "completion_receipt": invalid,
        },
    ).status_code == 400
    assert client.post(
        f"{base}/exposures/E1a", headers=_participant_headers(first),
        json={
            "expected_revision": 1, "idempotency_key": "valid", "read_ack": True,
            "completion_receipt": receipt,
        },
    ).status_code == 200
    assert client.post(
        f"{base}/exposures/E1a", headers=_participant_headers(second),
        json={
            "expected_revision": 1, "idempotency_key": "reused", "read_ack": True,
            "completion_receipt": receipt,
        },
    ).status_code == 409
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT receipt_id,verifier_id,receipt_hash FROM aipol_calculator_receipts"
        ).fetchone()
    assert row[0] == "external-one-time-receipt"
    assert row[1] == "test-only-fixture-verifier"
    assert len(row[2]) == 64 and "opaque-external-signature" not in "|".join(row)


def test_participant_ui_parses_flattened_jws_and_production_verifier_accepts_it(aipol_app):
    server, client, db_path = aipol_app
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    headers = _admin_headers(client)
    experiment = _create(client, headers, suffix="-real-jws")
    _artifact(client, headers, experiment["id"], "personal_comparison", "personal-real-jws")
    assert _freeze(client, headers, experiment).status_code == 200
    token = _register(client, experiment["id"]).json()["participant_token"]
    base = f"/api/aipol/experiments/{experiment['id']}"
    assert _post(
        client, f"{base}/consent", token, 0, "consent-real-jws",
        consent_version="consent-v1", affirmed=True,
    ).status_code == 200
    current = client.get(f"{base}/current", headers=_participant_headers(token)).json()

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    def encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

    server.aipol_store.configure_completion_receipt_verifier(
        server.aipol_receipt.Ed25519JwsReceiptVerifier(encode(public_key), "fixture-key-1")
    )
    protected = encode(json.dumps(
        {"alg": "EdDSA", "typ": "JWT", "kid": "fixture-key-1"},
        separators=(",", ":"),
    ).encode())
    issued_at = int(time.time())
    payload = encode(json.dumps({
        **current["receipt_context"],
        "iss": RECEIPT_CONTRACT["issuer"],
        "aud": RECEIPT_CONTRACT["audience"],
        "iat": issued_at,
        "exp": issued_at + 300,
        "jti": "ui-production-jws-1",
    }, separators=(",", ":"), sort_keys=True).encode())
    flattened = {
        "protected": protected,
        "payload": payload,
        "signature": encode(private_key.sign(f"{protected}.{payload}".encode("ascii"))),
    }
    parser = EVENT_TOOL / "web" / "aipol-receipt.js"

    def parse_in_participant_ui(value: str) -> dict:
        result = subprocess.run(
            [
                "node", "-e",
                "const p=require(process.argv[1]);process.stdout.write(JSON.stringify(p.parse(process.argv[2])));",
                str(parser), value,
            ],
            check=True, capture_output=True, text=True,
        )
        return json.loads(result.stdout)

    ui_receipt = parse_in_participant_ui(json.dumps(flattened))
    assert ui_receipt == flattened
    assert client.post(
        f"{base}/exposures/E1a/open", headers=_participant_headers(token),
        json={"expected_revision": 1, "idempotency_key": "real-jws-open"},
    ).status_code == 200
    accepted = client.post(
        f"{base}/exposures/E1a", headers=_participant_headers(token),
        json={
            "read_ack": True, "completion_receipt": ui_receipt,
            "expected_revision": 1, "idempotency_key": "real-jws-complete",
        },
    )
    assert accepted.status_code == 200, accepted.text
    assert _post(
        client, f"{base}/measurements/M1", token, 2, "real-jws-m1",
        choice="A", reason="", confidence=3,
    ).status_code == 200
    assert _post(
        client, f"{base}/exposures/E1b", token, 3, "real-jws-e1b", read_ack=True,
    ).status_code == 200
    assert _post(
        client, f"{base}/measurements/M2", token, 4, "real-jws-m2",
        choice="B", reason="", confidence=3,
    ).status_code == 200
    assert client.post(
        f"/api/admin/aipol/experiments/{experiment['id']}/close-registration", headers=headers
    ).status_code == 200
    assert client.post(
        f"/api/admin/aipol/experiments/{experiment['id']}/release-e2",
        headers=headers,
        json={"candidate_role": "fallback", "selection_reason": "signed receipt rehearsal"},
    ).status_code == 200
    assert _post(
        client, f"{base}/exposures/E2", token, 5, "real-jws-e2", read_ack=True,
    ).status_code == 200
    completed = _post(
        client, f"{base}/measurements/M3", token, 6, "real-jws-m3",
        choice="C", reason="", confidence=3,
        secondary_evaluation={
            "artifact_id": "ai-fallback", "acceptance": 4, "reason": "rehearsal",
        },
    )
    assert completed.status_code == 200, completed.text
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT receipt_id,verifier_id FROM aipol_calculator_receipts"
        ).fetchone() == ("ui-production-jws-1", "ed25519-jws:fixture-key-1")

    for malformed in (
        '{"token":"legacy-wrapper"}',
        json.dumps({**flattened, "extra": "not-allowed"}),
        "x" * 25001,
    ):
        result = subprocess.run(
            [
                "node", "-e",
                "const p=require(process.argv[1]);try{p.parse(process.argv[2]);process.exit(0)}catch(e){process.exit(7)}",
                str(parser), malformed,
            ],
            check=False,
        )
        assert result.returncode == 7
