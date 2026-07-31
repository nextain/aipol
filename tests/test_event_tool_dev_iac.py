from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import re
import sqlite3
import subprocess
import sys
import types
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
UNIT = ROOT / "deploy" / "azure" / "event-tool-dev"
BICEP = UNIT / "main.bicep"
DOCKERFILE = UNIT / "Dockerfile"
PARAMETERS = UNIT / "main.parameters.dev.json"
RUNBOOK = UNIT / "README.md"
PROD_BICEP = ROOT / "deploy" / "azure" / "event-tool-prod" / "main.bicep"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_prod_key_vault_secret_urls_include_path_separator() -> None:
    bicep = _text(PROD_BICEP)
    assert "${az.environment().suffixes.keyvaultDns}/'" in bicep
    assert "${vaultUri}secrets/event-session-secret/" in bicep


def test_dev_deployment_is_opt_in_and_feature_switches_default_off() -> None:
    bicep = _text(BICEP)
    parameters = json.loads(_text(PARAMETERS))["parameters"]

    for name in (
        "deployInfrastructure",
        "deployApp",
        "enableExternalIngress",
        "collectionEnabled",
        "chatbotEnabled",
        "receiptVerifierEnabled",
        "auditImmutabilityPolicyLocked",
    ):
        assert re.search(rf"param {name} bool = false\b", bicep)
        assert parameters[name]["value"] is False

    assert re.search(r"param batchEnabled bool = false\b", bicep)
    assert parameters["batchEnabled"]["value"] is False

    assert "var provisionApp = provisionInfrastructure && deployApp" in bicep
    assert "if (provisionApp)" in bicep
    assert "external: enableExternalIngress" in bicep
    assert "{ name: 'AIPOL_CHATBOT_PUBLIC_ENABLED', value: string(chatbotEnabled) }" in bicep
    assert "AIPOL_CHATBOT_ENABLED" not in bicep
    assert "AIPOL_COLLECTION_ENABLED" not in bicep
    assert "{ name: 'AIPOL_BATCH_AZURE_ENABLED', value: string(batchEnabled) }" in bicep
    assert "AIPOL_BATCH_AZURE_JOB_RESOURCE_ID" in bicep
    assert "POLICY_NEWS_ENABLED" not in bicep
    assert "{ name: 'EVENT_ENV', value: 'development' }" in bicep
    assert "{ name: 'EVENT_DEMO_ENABLED', value: 'false' }" in bicep


def test_stateful_sqlite_contract_is_single_replica_and_persistent() -> None:
    bicep = _text(BICEP)
    dockerfile = _text(DOCKERFILE)

    assert "Microsoft.Storage/storageAccounts/fileServices/shares" in bicep
    assert "Microsoft.App/managedEnvironments/storages" in bicep
    assert "storageType: 'AzureFile'" in bicep
    assert "mountPath: '/data'" in bicep
    assert "{ name: 'EVENT_DB_PATH', value: '/data/event.db' }" in bicep
    assert "{ name: 'EVENT_ROSTER_PATH', value: '/data/roster.json' }" in bicep
    assert "{ name: 'EVENT_SQLITE_NOLOCK', value: 'true' }" in bicep
    assert re.search(r"minReplicas:\s*1\b", bicep)
    assert re.search(r"maxReplicas:\s*1\b", bicep)
    assert '"--workers", "1"' in dockerfile
    assert '"--no-proxy-headers"' in dockerfile
    assert '"--forwarded-allow-ips"' not in dockerfile
    production_dockerfile = _text(ROOT / "event-tool" / "Dockerfile")
    assert '"--no-proxy-headers"' in production_dockerfile
    assert '"--forwarded-allow-ips"' not in production_dockerfile
    assert "param trustedProxyCidrs string = ''" in bicep
    assert "{ name: 'AIPOL_TRUSTED_PROXY_CIDRS', value: trustedProxyCidrs }" in bicep
    assert '"serialized_app:app"' in dockerfile
    assert "useradd --uid 10001 --gid 10001" in dockerfile
    assert "install -d -o 10001 -g 10001 -m 0750 /data" in dockerfile
    assert "USER 10001:10001" in dockerfile

    serialized_app = _text(UNIT / "serialized_app.py")
    assert "asyncio.Lock()" in serialized_app
    assert "async with self._http_lock" in serialized_app
    assert "WRITER_LEASE_PATH.mkdir()" in serialized_app
    assert "assert_data_directory_writable()" in serialized_app
    assert "acquire_writer_lease()" in serialized_app


def test_identity_is_used_for_acr_and_key_vault_without_literal_secrets() -> None:
    bicep = _text(BICEP)

    assert "Microsoft.ManagedIdentity/userAssignedIdentities" in bicep
    assert "adminUserEnabled: false" in bicep
    assert "7f951dda-4ed3-4680-a7ca-43fe172d538d" in bicep  # AcrPull
    assert "4633458b-17de-408a-b874-0445c86b69e6" in bicep  # Key Vault Secrets User
    assert "keyVaultUrl:" in bicep
    assert "secretRef: 'event-session-secret'" in bicep
    assert "secretRef: 'event-admin-users-json'" in bicep
    assert "secretRef: 'event-admin-roles-json'" in bicep
    assert "secretRef: 'event-credential-secrets-json'" in bicep
    assert "secretRef: 'event-audit-checkpoint-secrets-json'" in bicep
    assert "secretRef: 'aipol-receipt-ed25519-public-key'" in bicep
    assert "EVENT_SESSION_SECRET', value:" not in bicep
    assert "EVENT_ADMIN_USERS_JSON', value:" not in bicep
    assert "EVENT_ADMIN_ROLES_JSON', value:" not in bicep
    assert "EVENT_CREDENTIAL_SECRETS_JSON', value:" not in bicep
    assert "AIPOL_AUDIT_CHECKPOINT_SECRETS_JSON', value:" not in bicep
    assert "AIPOL_RECEIPT_ED25519_PUBLIC_KEY_B64', value:" not in bicep
    assert not re.search(r"(?:value|secretRef):\s*['\"]demo['\"]", bicep, re.IGNORECASE)
    assert "scope: keyVault" not in bicep
    assert "scope: eventSessionSecret" in bicep
    assert "scope: eventAdminUsersSecret" in bicep
    assert "scope: eventAdminRolesSecret" in bicep
    assert "scope: eventCredentialSecrets" in bicep
    assert "scope: eventAuditCheckpointSecrets" in bicep
    assert "scope: receiptPublicKeySecret" in bicep
    assert "five-named-secrets-only" in bicep
    assert "six-named-secrets-only" in bicep
    assert "output vaultWideKeyVaultSecretsUserAllowed bool = false" in bicep


def test_deployment_unit_has_no_vm_public_ip_or_production_target() -> None:
    bicep = _text(BICEP)
    runbook = _text(RUNBOOK)

    forbidden_resource_types = (
        "Microsoft.Compute/virtualMachines",
        "Microsoft.Network/publicIPAddresses",
        "Microsoft.Cdn/profiles",
    )
    assert not any(resource_type in bicep for resource_type in forbidden_resource_types)
    assert "output expectedResourceGroup string = 'rg-aipol-dev'" in bicep
    assert "var resourceGroupGuardPassed = resourceGroup().name == 'rg-aipol-dev'" in bicep
    assert "var provisionInfrastructure = deployInfrastructure && resourceGroupGuardPassed" in bicep
    assert "var featureGuardPassed = !enableExternalIngress && !collectionEnabled && !chatbotEnabled" in bicep
    assert "var provisionApp = provisionInfrastructure && deployApp && appInputGuardPassed && featureGuardPassed" in bicep
    assert "@allowed([false])\nparam enableExternalIngress bool = false" in bicep
    assert "contains(containerImage, '@sha256:')" in bicep
    assert "eventSessionSecretVersion" in bicep
    assert "eventAdminUsersSecretVersion" in bicep
    assert "eventAdminRolesSecretVersion" in bicep
    assert "eventCredentialKeysetVersion" in bicep
    assert "eventAuditCheckpointKeysetVersion" in bicep
    assert "receiptPublicKeySecretVersion" in bicep
    assert "--resource-group rg-aipol-dev" in runbook
    assert "Do not substitute `rg-aipol-prod`" in runbook


def test_batch_job_control_is_default_off_managed_identity_and_job_scoped() -> None:
    bicep = _text(BICEP)
    parameters = json.loads(_text(PARAMETERS))["parameters"]

    assert parameters["batchEnabled"]["value"] is False
    assert "Microsoft.App/jobs@2025-01-01' existing" in bicep
    assert "b9a307c4-5aa3-4b52-ba60-2b17c136cd7b" in bicep  # Container Apps Jobs Operator
    assert "scope: policyNewsJob" in bicep
    assert "scope: resourceGroup()" not in bicep
    assert "AIPOL_BATCH_AZURE_JOB_RESOURCE_ID" in bicep
    assert "AZURE_CLIENT_ID" in bicep


def test_receipt_verifier_is_optional_version_pinned_and_readiness_visible() -> None:
    bicep = _text(BICEP)
    server = _text(ROOT / "event-tool" / "server.py")
    runbook = _text(RUNBOOK)

    assert "param receiptVerifierEnabled bool = false" in bicep
    assert "AIPOL_RECEIPT_VERIFIER_MODE" in bicep
    assert "AIPOL_RECEIPT_KEY_ID" in bicep
    assert "AIPOL_RECEIPT_EXPECTED_ISSUER" in bicep
    assert "AIPOL_RECEIPT_EXPECTED_AUDIENCE" in bicep
    assert "AIPOL_RECEIPT_MAX_TTL_SECONDS" in bicep
    assert "receiptPublicKeySecretVersion" in bicep
    assert '"collection_ready"' in server
    assert "receipt_verifier" in server
    assert "full E1a" in runbook


def test_audit_checkpoint_is_immutable_keyed_and_delete_free() -> None:
    bicep = _text(BICEP)
    server = _text(ROOT / "event-tool" / "server.py")

    assert "immutableStorageWithVersioning" in bicep
    assert "immutabilityPolicies@2025-01-01" in bicep
    assert "auditImmutabilityPolicyLocked" in bicep
    assert "auditImmutabilityLockEvidenceId" in bicep
    assert "AIPOL_AUDIT_CHECKPOINT_MODE', value: 'azure_blob'" in bicep
    assert "AIPOL_AUDIT_IMMUTABILITY_POLICY_RESOURCE_ID" in bicep
    assert "containers/immutabilityPolicies/read" in bicep
    assert "event-audit-checkpoint-secrets-json/${eventAuditCheckpointKeysetVersion}" in bicep
    assert "AIPOL Audit Checkpoint Create-only Writer" in bicep
    assert "containers/blobs/read" in bicep and "containers/blobs/write" in bicep
    assert "containers/blobs/delete'" in bicep
    assert "output blobDataContributorAllowed bool = false" in bicep
    assert "output auditCheckpointDeleteAllowed bool = false" in bicep
    assert '"audit_checkpoint_ready"' in server
    assert "status_code=503" in server


def test_container_build_uses_root_context_and_pinned_base_image() -> None:
    dockerfile = _text(DOCKERFILE)
    dockerignore = _text(UNIT / "Dockerfile.dockerignore")

    assert re.search(r"^FROM python:3\.12-slim-bookworm@sha256:[0-9a-f]{64}$", dockerfile, re.MULTILINE)
    assert "COPY event-tool/*.py ./" in dockerfile
    assert "COPY policy_lab ./policy_lab" in dockerfile
    assert "COPY deploy/azure/event-tool-dev/serialized_app.py ./serialized_app.py" in dockerfile
    assert "COPY deploy/azure/event-tool-dev/backup_sqlite.py ./backup_sqlite.py" in dockerfile
    assert "COPY . ." not in dockerfile
    assert "!event-tool/web/**" in dockerignore
    assert "!policy_lab/**" in dockerignore
    assert "!deploy/azure/event-tool-dev/serialized_app.py" in dockerignore
    assert "!deploy/azure/event-tool-dev/backup_sqlite.py" in dockerignore


def test_runbook_states_sqlite_and_feature_flag_limitations() -> None:
    runbook = _text(RUNBOOK)

    assert "does not invent or" in runbook
    assert "ineffective collection variable" in runbook
    assert "AIPOL_BATCH_AZURE_ENABLED=false" in runbook
    assert "one replica, one process worker, and the serialized HTTP" in runbook
    assert "sqlite3.Connection.backup()" in runbook
    assert "Nothing in this directory has been deployed" in runbook
    assert "synthetic data" in runbook
    assert "session.policylab.nextain.io" in runbook
    assert "not the AIPOL source of truth" in runbook
    assert "Managed-identity RBAC drift gate" in runbook
    assert "az role assignment delete" in runbook


def test_deployment_wrapper_serializes_http_requests_and_blocks_second_writer(
    monkeypatch, tmp_path: Path
) -> None:
    active = 0
    max_active = 0

    async def inner(scope, receive, send) -> None:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1

    monkeypatch.setitem(sys.modules, "server", types.SimpleNamespace(app=inner))
    monkeypatch.setenv("EVENT_WRITER_LEASE_PATH", str(tmp_path / "writer-lease"))
    spec = importlib.util.spec_from_file_location(
        "event_tool_dev_serialized_app", UNIT / "serialized_app.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    second_spec = importlib.util.spec_from_file_location(
        "event_tool_dev_serialized_app_second", UNIT / "serialized_app.py"
    )
    assert second_spec and second_spec.loader
    second_module = importlib.util.module_from_spec(second_spec)
    with pytest.raises(RuntimeError, match="writer lease already exists"):
        second_spec.loader.exec_module(second_module)

    async def exercise() -> None:
        await asyncio.gather(
            *(
                module.app({"type": "http"}, None, None)
                for _ in range(5)
            )
        )

    asyncio.run(exercise())
    assert max_active == 1
    module.release_writer_lease()


def test_deployment_wrapper_fails_closed_when_data_mount_is_not_writable(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setitem(sys.modules, "server", types.SimpleNamespace(app=object()))
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("occupied", encoding="utf-8")
    monkeypatch.setenv("EVENT_DB_PATH", str(blocked / "event.db"))
    monkeypatch.setenv("EVENT_WRITER_LEASE_PATH", str(blocked / "writer-lease"))
    spec = importlib.util.spec_from_file_location(
        "event_tool_dev_serialized_app_blocked", UNIT / "serialized_app.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    with pytest.raises((RuntimeError, FileExistsError, NotADirectoryError)):
        spec.loader.exec_module(module)


def test_backup_helper_creates_readable_checksummed_copy(tmp_path: Path) -> None:
    source = tmp_path / "event.db"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE marker (value TEXT NOT NULL)")
        connection.execute("INSERT INTO marker VALUES ('persisted')")

    env = {**os.environ, "EVENT_DB_PATH": str(source)}
    completed = subprocess.run(
        [sys.executable, str(UNIT / "backup_sqlite.py")],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    receipt = json.loads(completed.stdout)
    backup = Path(receipt["path"])

    assert backup.is_file()
    assert receipt["bytes"] == backup.stat().st_size
    assert re.fullmatch(r"[0-9a-f]{64}", receipt["sha256"])
    with sqlite3.connect(backup) as connection:
        assert connection.execute("SELECT value FROM marker").fetchone() == ("persisted",)
