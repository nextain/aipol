from __future__ import annotations

import hashlib
import importlib
import io
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
EVENT_TOOL = ROOT / "event-tool"
MODULES = ("db", "aipol_audit_checkpoint", "aipol_admin_store")


@pytest.fixture()
def checkpoint(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(EVENT_TOOL))
    monkeypatch.setenv("EVENT_DB_PATH", str(tmp_path / "event.db"))
    monkeypatch.setenv("EVENT_SQLITE_NOLOCK", "false")
    monkeypatch.setenv(
        "AIPOL_AUDIT_CHECKPOINT_SECRETS_JSON",
        json.dumps({"checkpoint-key-2026-07": "k" * 48}),
    )
    monkeypatch.setenv("AIPOL_AUDIT_CHECKPOINT_ACTIVE_KEY_ID", "checkpoint-key-2026-07")
    for name in MODULES:
        sys.modules.pop(name, None)
    db = importlib.import_module("db")
    db.init()
    checkpoint_module = importlib.import_module("aipol_audit_checkpoint")
    admin = importlib.import_module("aipol_admin_store")
    admin.init()
    store = checkpoint_module.MemoryCheckpointStore({})
    checkpoint_module.configure(store)
    assert admin.reconcile_external_checkpoint(fail=True)["sequence"] == 0
    yield db, checkpoint_module, admin, store
    checkpoint_module.configure(None)
    for name in MODULES:
        sys.modules.pop(name, None)


def _append(admin, suffix: str) -> None:
    admin.append_external_audit(
        actor="security-reviewer",
        action=f"test.{suffix}",
        resource_type="test",
        resource_id=suffix,
        payload={"suffix": suffix},
    )


def test_checkpoint_is_keyed_monotonic_and_create_only(checkpoint):
    _, _, admin, store = checkpoint
    _append(admin, "one")
    _append(admin, "two")

    assert sorted(store.blobs) == [0, 1, 2]
    assert store.blobs[2]["previous_hash"] == store.blobs[1]["head_hash"]
    assert admin.reconcile_external_checkpoint(fail=True)["sequence"] == 2

    conflicting = dict(store.blobs[2], head_hash="f" * 64)
    with pytest.raises(Exception, match="create-only"):
        store.create(2, conflicting)


def test_sqlite_tail_deletion_is_detected(checkpoint):
    db, module, admin, _ = checkpoint
    _append(admin, "one")
    _append(admin, "two")
    with db._conn() as connection:
        connection.execute("DROP TRIGGER aipol_admin_audit_no_delete")
        connection.execute("DELETE FROM aipol_admin_audit WHERE sequence=2")

    with pytest.raises(module.CheckpointError, match="ahead"):
        admin.reconcile_external_checkpoint(fail=True)


def test_full_hash_recalculation_cannot_match_remote_checkpoint(checkpoint):
    db, module, admin, _ = checkpoint
    _append(admin, "one")
    _append(admin, "two")
    with db._conn() as connection:
        connection.execute("DROP TRIGGER aipol_admin_audit_no_update")
        rows = connection.execute("SELECT * FROM aipol_admin_audit ORDER BY sequence").fetchall()
        previous = admin.GENESIS_HASH
        for row in rows:
            payload = json.dumps({"rewritten": row["sequence"]}, separators=(",", ":"), sort_keys=True)
            body = {
                "sequence": row["sequence"], "event_id": row["event_id"],
                "timestamp": row["timestamp"], "actor_id": row["actor_id"],
                "action": row["action"], "resource_type": row["resource_type"],
                "resource_id": row["resource_id"], "payload_json": payload,
                "previous_hash": previous,
            }
            current = hashlib.sha256(admin._canonical(body).encode("utf-8")).hexdigest()
            connection.execute(
                "UPDATE aipol_admin_audit SET payload_json=?,previous_hash=?,event_hash=? WHERE sequence=?",
                (payload, previous, current, row["sequence"]),
            )
            previous = current

    assert admin.verify_audit_chain()
    with pytest.raises(module.CheckpointError, match="does not match"):
        admin.reconcile_external_checkpoint(fail=True)


def test_checkpoint_gap_signature_tamper_and_sqlite_rollback_fail_closed(checkpoint):
    db, module, admin, store = checkpoint
    _append(admin, "one")
    _append(admin, "two")

    saved = dict(store.blobs[1])
    del store.blobs[1]
    with pytest.raises(module.CheckpointError, match="gap or rollback"):
        admin.reconcile_external_checkpoint(fail=True)
    store.blobs[1] = saved

    saved_tail = dict(store.blobs[2])
    store.blobs[2]["signature"] = "0" * 64
    with pytest.raises(module.CheckpointError, match="signature"):
        admin.reconcile_external_checkpoint(fail=True)

    store.blobs[2] = saved_tail
    # A database snapshot rollback cannot erase the immutable remote head.
    with db._conn() as connection:
        connection.execute("DROP TRIGGER aipol_admin_audit_no_delete")
        connection.execute("DELETE FROM aipol_admin_audit WHERE sequence=2")
    with pytest.raises(module.CheckpointError):
        admin.reconcile_external_checkpoint(fail=True)


def test_hidden_remote_tail_cannot_be_recreated_over_existing_blob(checkpoint):
    _, module, admin, store = checkpoint
    _append(admin, "one")
    retained = dict(store.blobs[1])

    class RollbackViewStore(module.MemoryCheckpointStore):
        def list(self):
            values = super().list()
            return [value for value in values if value["sequence"] != 1]

    module.configure(RollbackViewStore({0: store.blobs[0], 1: retained}))
    with pytest.raises(module.CheckpointError, match="create-only"):
        admin.reconcile_external_checkpoint(fail=True)


def test_production_rejects_disabled_file_and_memory_modes(monkeypatch):
    monkeypatch.syspath_prepend(str(EVENT_TOOL))
    sys.modules.pop("aipol_audit_checkpoint", None)
    module = importlib.import_module("aipol_audit_checkpoint")
    for mode in ("disabled", "file", "memory"):
        monkeypatch.setenv("AIPOL_AUDIT_CHECKPOINT_MODE", mode)
        with pytest.raises(module.CheckpointError):
            module.store_from_environment(production=True)


def test_azure_adapter_reads_actual_locked_policy_before_blob_access(monkeypatch):
    monkeypatch.syspath_prepend(str(EVENT_TOOL))
    sys.modules.pop("aipol_audit_checkpoint", None)
    module = importlib.import_module("aipol_audit_checkpoint")

    class Credential:
        scopes = []

        def get_token(self, scope):
            self.scopes.append(scope)
            return type("Token", (), {"token": "managed-identity-token"})()

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_):
            self.close()

    class Opener:
        state = "Locked"

        def open(self, request, timeout):
            assert request.full_url.startswith("https://management.azure.com/subscriptions/")
            return Response(json.dumps({"properties": {"state": self.state}}).encode())

    policy_id = (
        "/subscriptions/sub/resourceGroups/rg-aipol-dev/providers/Microsoft.Storage/"
        "storageAccounts/staipol/blobServices/default/containers/aipol-audit-checkpoints/"
        "immutabilityPolicies/default"
    )
    credential, opener = Credential(), Opener()
    adapter = module.AzureBlobCheckpointStore(
        "https://staipol.blob.core.windows.net/aipol-audit-checkpoints",
        "client-id",
        policy_id,
        credential=credential,
        opener=opener,
    )
    adapter._assert_locked()
    assert credential.scopes == ["https://management.azure.com/.default"]

    opener.state = "Unlocked"
    with pytest.raises(module.CheckpointError, match="not Locked"):
        adapter._assert_locked()
