"""Bounded collector, durable Blob store and Azure scheduled-job contracts."""

from __future__ import annotations

import ast
import json
import sys
import types
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BOT = ROOT / "bots" / "policy_news"
sys.path.insert(0, str(BOT))

import scheduled_job  # noqa: E402
from adapters import AzureFoundryDraftAdapter, MockDraftAdapter, MockReviewAdapter  # noqa: E402
from azure_blob_store import ActiveRunError, AzureBlobRunStore  # noqa: E402
from collector import CollectionError, collect, visible_text  # noqa: E402
from config import RuntimeConfig  # noqa: E402
from contracts import ApprovalState, SourcePacket  # noqa: E402
from orchestrator import PolicyNewsOrchestrator  # noqa: E402


ATOM = b'''<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry><title>Artificial intelligence policy consultation one</title><summary>Public sector evaluation</summary><updated>2026-07-20T00:00:00Z</updated><link rel="alternate" href="https://official.example/item-1" /></entry>
  <entry><title>Artificial intelligence policy consultation two</title><summary>Public sector evidence</summary><updated>2026-07-19T00:00:00Z</updated><link rel="alternate" href="https://official.example/item-2" /></entry>
  <entry><title>Artificial intelligence policy consultation three</title><summary>Public sector regulation</summary><updated>2026-07-18T00:00:00Z</updated><link rel="alternate" href="https://official.example/item-3" /></entry>
  <entry><title>Artificial intelligence policy consultation four</title><summary>Public sector evaluation</summary><updated>2026-07-17T00:00:00Z</updated><link rel="alternate" href="https://official.example/item-4" /></entry>
</feed>'''


def collector_config(tmp_path: Path) -> Path:
    path = tmp_path / "sources.json"
    path.write_text(json.dumps({
        "feeds": [{"name": "Official Agency", "country": "Testland", "url": "https://official.example/feed.atom", "allowed_hosts": ["official.example"]}],
        "ai_terms": ["artificial intelligence"],
        "relevance_terms": ["policy", "public sector", "evaluation"],
    }), encoding="utf-8")
    return path


def test_collector_is_bounded_allowlisted_and_provenance_complete(tmp_path: Path) -> None:
    def fetch(url: str, *, allowed_hosts: set[str], max_bytes: int, timeout: int):
        assert allowed_hosts == {"official.example"}
        assert timeout == 7
        if url.endswith("feed.atom"):
            return ATOM, url, "application/atom+xml"
        number = url.rsplit("-", 1)[-1]
        body = f"<html><nav>menu</nav><main>Official policy source {number}. Human review remains required.</main><script>ignore()</script></html>".encode()
        return body, url, "text/html"

    packets = collect(
        max_items=3,
        timeout=7,
        fetcher=fetch,
        clock=lambda: datetime(2026, 7, 28, tzinfo=timezone.utc),
        config_path=collector_config(tmp_path),
    )
    assert len(packets) == 3
    assert [packet.source_url for packet in packets] == [f"https://official.example/item-{n}" for n in range(1, 4)]
    assert all(packet.fetched_at == "2026-07-28T00:00:00+00:00" for packet in packets)
    assert all(len(packet.content_sha256) == 64 for packet in packets)
    assert all("ignore" not in packet.source_text and "menu" not in packet.source_text for packet in packets)


def test_collector_rejects_unbounded_or_untrusted_inputs(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="between 1 and 3"):
        collect(max_items=4, config_path=collector_config(tmp_path))
    assert "hidden" not in visible_text(b"<html><style>hidden</style><main>visible</main></html>", "text/html")
    with pytest.raises(CollectionError, match="HTTPS"):
        from collector import bounded_fetch
        bounded_fetch("http://official.example/feed", allowed_hosts={"official.example"}, max_bytes=10)


class FakeStorageError(Exception):
    def __init__(self, status_code: int):
        self.status_code = status_code


class FakeDownload:
    def __init__(self, value: bytes):
        self.value = value

    def readall(self) -> bytes:
        return self.value


class FakeBlob:
    def __init__(self) -> None:
        self.value: bytes | None = None
        self.metadata: dict | None = None
        self.leased = False

    def upload_blob(self, value: bytes, *, overwrite: bool, metadata=None, content_settings=None) -> None:
        if self.value is not None and not overwrite:
            raise FakeStorageError(409)
        self.value = value
        self.metadata = metadata

    def download_blob(self) -> FakeDownload:
        if self.value is None:
            raise FakeStorageError(404)
        return FakeDownload(self.value)


class FakeContainer:
    def __init__(self) -> None:
        self.blobs: dict[str, FakeBlob] = {}

    def get_blob_client(self, name: str) -> FakeBlob:
        return self.blobs.setdefault(name, FakeBlob())


class FakeBlobService:
    def __init__(self) -> None:
        self.containers: dict[str, FakeContainer] = {}

    def get_container_client(self, name: str) -> FakeContainer:
        return self.containers.setdefault(name, FakeContainer())


class FakeLease:
    def __init__(self, blob: FakeBlob) -> None:
        self.blob = blob

    def acquire(self, lease_duration: int) -> None:
        assert lease_duration == 60
        if self.blob.leased:
            raise FakeStorageError(409)
        self.blob.leased = True

    def renew(self) -> None:
        if not self.blob.leased:
            raise FakeStorageError(409)

    def release(self) -> None:
        self.blob.leased = False


def test_blob_store_is_durable_private_boundary_and_idempotent() -> None:
    service = FakeBlobService()
    store = AzureBlobRunStore("https://staipoltest.blob.core.windows.net", service_client=service, lease_factory=FakeLease)
    config = RuntimeConfig(enabled=True, dry_run=True, review_provider="mock")
    draft = MockDraftAdapter()
    review = MockReviewAdapter()
    pipeline = PolicyNewsOrchestrator(
        config=config,
        draft_port=draft,
        review_port=review,
        store=store,
        allowed_hosts={"official.example"},
    )
    raw = {
        "source_name": "Official Agency", "source_url": "https://official.example/item",
        "published": "2026-07-20", "country": "Testland", "title": "AI policy",
        "source_text": "Official source body.", "fetched_at": "2026-07-28T00:00:00+00:00",
    }
    first = pipeline.run(raw)
    second = pipeline.run(raw)
    assert first.run_id == second.run_id
    assert first.state == ApprovalState.REVIEW_PASSED
    assert (draft.calls, review.calls) == (1, 1)
    runs = service.containers["policy-news-runs"].blobs
    sources = service.containers["policy-news-sources"].blobs
    assert f"idempotency/{first.idempotency_key}.txt" in runs
    assert f"records/{first.run_id}.json" in runs
    source_blob = next(iter(sources.values()))
    assert source_blob.metadata and source_blob.metadata["sha256"]
    with store.claim_source("a" * 64):
        with pytest.raises(ActiveRunError):
            with store.claim_source("a" * 64):
                pass
    with store.claim_source("a" * 64):
        pass


class FakeToken:
    token = "managed-identity-token"


class FakeTokenCredential:
    def __init__(self) -> None:
        self.scopes: list[str] = []

    def get_token(self, scope: str) -> FakeToken:
        self.scopes.append(scope)
        return FakeToken()


def test_foundry_managed_identity_header_is_short_lived_token(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(url: str, payload: dict, headers: dict, timeout: int):
        captured["headers"] = headers
        editorial = {"title_ko": "제목", "summary_ko": "요약", "policy_use": "활용", "human_review": "검토", "relevance": "관련", "caveat": "한계"}
        return {"id": "r", "choices": [{"message": {"content": json.dumps(editorial)}}]}, ""

    import adapters
    monkeypatch.setattr(adapters, "_post_json", fake_post)
    token_credential = FakeTokenCredential()
    config = RuntimeConfig(
        enabled=True, dry_run=False, foundry_region="eastus2",
        foundry_endpoint="https://aipol-ai.services.ai.azure.com", foundry_deployment="draft",
        foundry_auth_mode="managed_identity", foundry_managed_identity_client_id="uami-client-id",
    )
    source = SourcePacket.from_dict({
        "source_name": "Official", "source_url": "https://official.example/item", "published": "2026-07-20",
        "country": "Test", "title": "AI policy", "source_text": "Official source", "fetched_at": "2026-07-28T00:00:00+00:00",
    })
    AzureFoundryDraftAdapter(config, token_credential=token_credential).draft(source)
    assert captured["headers"] == {"Authorization": "Bearer managed-identity-token"}
    assert token_credential.scopes == ["https://ai.azure.com/.default"]


def test_scheduled_entrypoint_default_kill_switch_makes_no_cloud_call(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("POLICY_NEWS_ENABLED", "false")
    monkeypatch.delenv("AZURE_STORAGE_BLOB_URL", raising=False)
    assert scheduled_job.main() == 0
    assert '"status": "stopped"' in capsys.readouterr().out


def test_scheduled_entrypoint_requires_and_builds_real_kb_compiler(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    class Credential:
        def __init__(self, *, client_id: str):
            captured["client_id"] = client_id

    azure = types.ModuleType("azure")
    identity = types.ModuleType("azure.identity")
    identity.ManagedIdentityCredential = Credential
    azure.identity = identity
    monkeypatch.setitem(sys.modules, "azure", azure)
    monkeypatch.setitem(sys.modules, "azure.identity", identity)
    deployment_id = "sha256:" + "a" * 64
    app_client_id = "11111111-1111-4111-8111-111111111111"
    import adapters
    monkeypatch.setattr(adapters, "_get_json", lambda url, timeout, max_bytes: {
        "schemaVersion": "aipol-kb-receiver-contract-v1",
        "tenantId": "tenant-id",
        "audience": f"api://{app_client_id}",
        "scope": f"api://{app_client_id}/.default",
        "receiverAppClientId": app_client_id,
        "allowedUamiClientId": "uami-client-id",
        "allowedUamiPrincipalId": "uami-principal-id",
        "requiredAppRole": "Aipol.PolicyNews.Compile",
        "issuer": "https://login.microsoftonline.com/tenant-id/v2.0",
        "jwksUri": "https://login.microsoftonline.com/tenant-id/discovery/v2.0/keys",
        "validationMode": "entra-jwt-v2-strict",
        "receiverVersion": "1.2.3",
        "deploymentId": deployment_id,
        "compilePath": "/compile",
    })
    config = RuntimeConfig(
        enabled=True,
        dry_run=False,
        kb_compiler_mode="http",
        kb_compiler_endpoint="https://kb.aipol.example",
        kb_compiler_allowed_origins=("https://kb.aipol.example",),
        kb_compiler_scope=f"api://{app_client_id}/.default",
        kb_compiler_app_client_id=app_client_id,
        foundry_managed_identity_client_id="uami-client-id",
        kb_compiler_tenant_id="tenant-id",
        kb_compiler_uami_principal_id="uami-principal-id",
        kb_compiler_required_app_role="Aipol.PolicyNews.Compile",
        kb_compiler_receiver_version="1.2.3",
        kb_compiler_receiver_deployment_id=deployment_id,
    )
    config.validate()
    compiler = scheduled_job.build_knowledge_compiler(config, scheduled_job.Budget(config))
    assert compiler.name == "naia-kb-compiler-http"
    assert compiler.endpoint == "https://kb.aipol.example"
    assert captured["client_id"] == "uami-client-id"

    monkeypatch.setenv("POLICY_NEWS_ENABLED", "true")
    monkeypatch.setenv("POLICY_NEWS_DRY_RUN", "false")
    monkeypatch.setenv("POLICY_NEWS_KB_COMPILER_MODE", "disabled")
    with pytest.raises(ValueError, match="requires a configured KB compiler"):
        scheduled_job.main()


def test_container_job_iac_defaults_are_manual_disabled_private_and_minimal() -> None:
    bicep = (ROOT / "deploy" / "azure" / "policy-news-job.bicep").read_text(encoding="utf-8")
    assert "param deployInfrastructure bool = false" in bicep
    assert "contains(containerImage, '@sha256:')" in bicep
    assert "image: containerImageValidated" in bicep
    assert "param enableSchedule bool = false" in bicep
    assert "param policyNewsEnabled bool = false" in bicep
    assert "param foundryEndpoint string = 'https://${foundryAccountName}.services.ai.azure.com'" in bicep
    assert "{ name: 'AZURE_AI_FOUNDRY_ENDPOINT', value: foundryEndpoint }" in bicep
    assert ".openai.azure.com" not in bicep
    assert "effectiveSchedule = enableSchedule && policyNewsEnabledValidated && !policyNewsDryRun && compilerConfigured && secretConfiguredValidated" in bicep
    assert "allowBlobPublicAccess: false" in bicep
    assert "allowSharedKeyAccess: false" in bicep
    assert bicep.count("publicAccess: 'None'") == 2
    assert "Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30" in bicep
    assert "type: 'UserAssigned'" in bicep
    assert "identity: jobIdentity!.id" in bicep
    assert "{ name: 'AZURE_CLIENT_ID', value: jobIdentity!.properties.clientId }" in bicep
    assert "dependsOn:" in bicep and "acrPullRole" in bicep
    assert "principalId: jobIdentity!.properties.principalId" in bicep
    assert "principalId: job!.identity.principalId" not in bicep
    assert "workloadProfileName: 'Consumption'" in bicep
    assert "cpu: json('0.25')" in bicep and "memory: '0.5Gi'" in bicep
    assert "parallelism: 1" in bicep
    assert "CognitiveServices/accounts@2025-06-01" in bicep
    assert "OPENROUTER_API_KEY', secretRef" in bicep
    assert "{ name: 'POLICY_NEWS_KB_COMPILER_MODE', value: kbCompilerMode }" in bicep
    assert "{ name: 'NAIA_KB_COMPILER_ENDPOINT', value: kbCompilerEndpointValidated }" in bicep
    assert "{ name: 'NAIA_KB_COMPILER_ALLOWED_ORIGINS', value: kbCompilerAllowedOriginValidated }" in bicep
    assert "{ name: 'NAIA_KB_COMPILER_SCOPE', value: kbCompilerScopeValidated }" in bicep
    assert "{ name: 'NAIA_KB_COMPILER_APP_CLIENT_ID', value: kbCompilerAppClientIdValidated }" in bicep
    assert "{ name: 'NAIA_KB_COMPILER_UAMI_PRINCIPAL_ID', value: jobIdentity!.properties.principalId }" in bicep
    assert "{ name: 'NAIA_KB_COMPILER_RECEIVER_DEPLOYMENT_ID', value: receiverDeploymentValidated }" in bicep
    assert "empty(receiverDigestRemainder)" in bicep
    assert "kbCompilerScope == expectedKbCompilerScope" in bicep
    assert "resourceGroupNameValidated" in bicep and "rg-aipol-dev" in bicep
    assert "policyNewsEnabled requires an attested HTTP receiver contract or local command KB compiler configuration" in bicep
    assert "scope: openRouterSecret" in bicep
    assert "scope: keyVault" not in bicep
    assert "openRouterSecretName" in bicep
    dockerfile = (BOT / "Dockerfile").read_text(encoding="utf-8")
    assert "POLICY_NEWS_ENABLED=false" in dockerfile
    assert 'USER 10001' in dockerfile
    assert 'ENTRYPOINT ["python", "scheduled_job.py"]' in dockerfile
    entrypoint = (BOT / "scheduled_job.py").read_text(encoding="utf-8")
    assert ".human_approve(" not in entrypoint
    assert ".mark_published(" not in entrypoint
    assert "knowledge_compiler=compiler" in entrypoint
    parameters = json.loads(
        (ROOT / "deploy" / "azure" / "policy-news-job.parameters.dev.example.json").read_text(encoding="utf-8")
    )
    assert parameters["parameters"]["foundryEndpoint"]["value"] == (
        "https://aipol-ai-mxajhqb4i5p4o.services.ai.azure.com"
    )
    runbook = (ROOT / "deploy" / "azure" / "POLICY-NEWS-JOB-RUNBOOK.md").read_text(encoding="utf-8")
    assert "https://aipol-ai-mxajhqb4i5p4o.services.ai.azure.com" in runbook
    assert "/openai/v1/chat/completions" in runbook
    assert "https://ai.azure.com/.default" in runbook
    verifier = (ROOT / "scripts" / "verify_azure_bicep.py").read_text(encoding="utf-8")
    assert "ARM_NEGATIVE_GUARD_RECEIPT" in verifier
    assert '"z" * 64' in verifier


def test_disabled_entrypoint_has_no_eager_cloud_or_provider_imports() -> None:
    tree = ast.parse((BOT / "scheduled_job.py").read_text(encoding="utf-8"))
    top_level_imports: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            top_level_imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            top_level_imports.add(node.module)
    assert not top_level_imports.intersection(
        {"adapters", "azure_blob_store", "collector", "nemotron_review", "orchestrator"}
    )
